#!/usr/bin/env python3

import yaml
import getopt
import os
import re
import sensors  # https://github.com/bastienleonard/pysensors.git
import subprocess
import sys
import time
import signal

def get_amd_temperatures() -> list[int]:
    """
    Fetch AMD GPU temperatures using sensors library.
    Returns a list of temperatures (or empty list if no AMD GPUs detected or errors occur).
    Errors are printed to stderr.
    """
    amd_temps = []
    try:
        for sensor in sensors.get_detected_chips():
            # Use 'amdgpu' only (k10temp is for AMD CPUs, not GPUs)
            if sensor.prefix == 'amdgpu':
                for feature in sensor.get_features():
                    # FIXED: Use sensor.get_all_subfeatures() instead of core.get_all_subfeatures()
                    for subfeature in sensor.get_all_subfeatures(feature):
                        # Only process temperature inputs (temp*_input), not voltage/fan/frequency readings
                        if subfeature.name.startswith('temp') and subfeature.name.endswith("_input"):
                            try:
                                temp = sensor.get_value(subfeature.number)
                                # Use the original range 0-125°C as specified in the plan
                                # This handles edge cases and cold GPUs properly
                                if 0 <= temp <= 125:  # Validate plausible range
                                    amd_temps.append(temp)
                                else:
                                    print(f"Warning: Invalid AMD GPU temperature {temp}°C (ignored)", file=sys.stderr)
                            except Exception as e:
                                print(f"Warning: Error reading AMD GPU temperature: {str(e)}", file=sys.stderr)
    except Exception as e:
        print(f"Error in get_amd_temperatures(): {str(e)}", file=sys.stderr)
    
    return amd_temps

def get_nvidia_temperatures() -> list[int]:
    """
    Fetch NVIDIA GPU temperatures using nvidia-smi with safety checks.
    Returns a list of temperatures (or empty list if errors occur).
    Errors are printed to stderr.
    """
    try:
        # Run nvidia-smi with a 5-second timeout
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3,  # Prevent hanging
            check=True,
        )
        
        # Split and validate output
        temps_raw = result.stdout.strip().split('\n')
        temperatures = []
        
        for temp_str in temps_raw:
            try:
                temp = int(temp_str)
                if 0 <= temp <= 125:  # Validate plausible range
                    temperatures.append(temp)
                else:
                    print(f"Warning: Invalid NVIDIA GPU temperature '{temp_str}' (ignored)", file=sys.stderr)
            except ValueError:
                print(f"Warning: Non-numeric NVIDIA GPU temperature '{temp_str}' (ignored)", file=sys.stderr)
        
        return temperatures
    except KeyboardInterrupt:
        raise  # Re-raise to allow main loop to handle
    except subprocess.TimeoutExpired:
        print("Error: nvidia-smi timed out (driver hung?).", file=sys.stderr)
        return []
    except subprocess.CalledProcessError as e:
        print(f"Error: nvidia-smi failed (exit={e.returncode}): {e.stderr.strip()}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Error: Unexpected error in get_nvidia_temperatures(): {str(e)}", file=sys.stderr)
        return []

def get_gpu_temperatures() -> list[int]:
    """
    Get temperatures from all available GPUs (both AMD and NVIDIA).
    Returns combined list of all GPU temperatures.
    
    Improved version with proper error handling and validation.
    """
    temperatures = []
    
    try:
        # Get AMD GPU temperatures using sensors library
        if config.get('gpu_monitoring', {}).get('monitor_amd_gpus', True):
            amd_temps = get_amd_temperatures()
            if amd_temps:
                temperatures.extend(amd_temps)
                if config['general']['debug']:
                    print(f"AMD GPU temperatures detected: {amd_temps}")
            else:
                if config['general']['debug']:
                    print("Warning: No AMD GPU temperatures detected", file=sys.stderr)
        
        # Get NVIDIA GPU temperatures using nvidia-smi
        if config.get('gpu_monitoring', {}).get('monitor_nvidia_gpus', True):
            nvidia_temps = get_nvidia_temperatures()
            if nvidia_temps:
                temperatures.extend(nvidia_temps)
                if config['general']['debug']:
                    print(f"NVIDIA GPU temperatures detected: {nvidia_temps}")
            else:
                if config['general']['debug']:
                    print("Warning: No NVIDIA GPU temperatures detected", file=sys.stderr)
    except KeyboardInterrupt:
        raise  # Re-raise to allow main loop to handle
    except Exception as e:
        print(f"Error in get_gpu_temperatures(): {str(e)}", file=sys.stderr)
        return [0]
    
    # Return combined temperatures or fallback
    return temperatures if temperatures else [0]
        

config = {
    'config_paths': ['fan_control.yaml', '/opt/fan_control/fan_control.yaml'],
    'general': {
        'debug': False,
        'interval': 60
    },
    'host': {}
}
state = {}


class ConfigError(Exception):
    pass

def ipmitool(args):
    global state
    host = config['host']
    cmd = ["ipmitool"]
    cmd += (args.split(' '))
    if config['general']['debug']:
        print(re.sub(r'-([UP]) (\S+)', r'-\1 ___', ' '.join(cmd)))  # Do not log IPMI credentials
        return True
    try:
        subprocess.check_output(cmd, timeout=15)
    except subprocess.CalledProcessError:
        print("\"{}\" command has returned a non-0 exit code".format(cmd), file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("\"{}\" command has timed out".format(cmd), file=sys.stderr)
        return False
    return True


def set_fan_control(wanted_mode):
    global state
    host = config['host']
    if wanted_mode == "manual" and state['fan_control_mode'] == "automatic":
        ipmitool("raw 0x30 0x30 0x01 0x00")
    elif wanted_mode == "automatic" and state['fan_control_mode'] == "manual":
        ipmitool("raw 0x30 0x30 0x01 0x01")
        state['fan_speed'] = 0
    state['fan_control_mode'] = wanted_mode

def set_fan_speed(threshold_n):
    global state
    host = config['host']
    wanted_percentage = host['speeds'][threshold_n]
    if config['general']['debug']:
        print(f"\tWanted percentage: {wanted_percentage}%")
    if wanted_percentage == state['fan_speed']:
        return
    if 5 <= wanted_percentage <= 100:
        wanted_percentage_hex = "{0:#0{1}x}".format(wanted_percentage, 4)
        if state['fan_control_mode'] != "manual":
            set_fan_control("manual")
            time.sleep(1)
        if not config['general']['debug']:
            print("[{}] Setting fans speed to {}%".format(host['name'], wanted_percentage))
        ipmitool(f"raw 0x30 0x30 0x02 0xff {wanted_percentage_hex}")
        state['fan_speed'] = wanted_percentage

def parse_config():
    global config, state
    config_path = next((p for p in config['config_paths'] if os.path.isfile(p)), None)
    if not config_path:
        raise RuntimeError("Missing or unspecified configuration file.")
    with open(config_path, 'r') as yaml_conf:
        config.update(yaml.safe_load(yaml_conf))
    
    # Validate GPU monitoring configuration
    if 'gpu_monitoring' not in config:
        config['gpu_monitoring'] = {}
    gpu_config = config['gpu_monitoring']
    if 'monitor_amd_gpus' not in gpu_config:
        gpu_config['monitor_amd_gpus'] = True
    if 'monitor_nvidia_gpus' not in gpu_config:
        gpu_config['monitor_nvidia_gpus'] = True
    
    host = config['host']
    if 'hysteresis' not in list(host.keys()):
        host['hysteresis'] = 0
    if len(host['temperatures']) < 2:
        raise ConfigError('Host "{}" has less than 2 ({}) temperature thresholds.'.format(host['name'], len(host['temperatures'])))
    if len(host['speeds']) != len(host['temperatures']):
        raise ConfigError('Host "{}" has {} fan speeds instead of {}.'.format(host['name'], len(host['speeds'], len(host['temperatures']))))
    # TODO: check presence/validity of values instead of keys presence only
    state.update({
        'fan_control_mode': 'automatic',
        'fan_speed': 0
    })
    if config['general']['debug']:
        print("\nInitial state:")
        print(state)
        print("\nInitial config:")
        print(config)
        print('')

def parse_opts():
    global config
    help_str = "fan_control.py [-d] [-c <path_to_config>] [-i <interval>]"

    try:
        opts, _ = getopt.getopt(sys.argv[1:], "hdc:i:", ["help", "debug", "config=", "interval="])
    except getopt.GetoptError as e:
        print("Unrecognized option. Usage:\n{}".format(help_str))
        raise getopt.GetoptError(e)

    for opt, arg in opts:
        if opt in ('-h', '--help'):
            print(help_str)
            raise InterruptedError
        elif opt in ('-d', '--debug'):
            config['general']['debug'] = True
        elif opt in ('-c', '--config'):
            config['config_paths'] = [arg]
        elif opt in ('-i', '--interval'):
            config['general']['interval'] = arg

def checkHysteresis(temperature, threshold_n):
    global state
    host = config['host']
    if not host['hysteresis']:
        return True
    if (state['fan_speed'] > host['speeds'][threshold_n] or
        state['fan_control_mode'] == 'automatic'):
        return temperature <= host['temperatures'][threshold_n] - host['hysteresis']
    return True

def calculate_effective_temperature(cpu_temp_avg, gpu_temps):
    """
    Calculate effective temperature using improved algorithm with:
    - Separate CPU/GPU curves
    - Max overpower detection
    - Configurable weighting
    
    Returns: (effective_temp, use_gpu_curve, debug_info)
    """
    # Get temperature control configuration with backward compatibility
    temp_control = config.get('temperature_control', {})
    
    # Default values (maintain backward compatibility)
    max_overpower_threshold = temp_control.get('max_overpower_threshold', 15)
    cpu_weight = temp_control.get('cpu_weight', 0.5)
    gpu_weight = temp_control.get('gpu_weight', 0.5)
    
    # Handle GPU temperatures
    gpu_temp_avg = round(sum(gpu_temps)/len(gpu_temps)) if gpu_temps else 0
    gpu_temp_max = max(gpu_temps) if gpu_temps else 0
    
    # Determine which component is dominant
    temp_diff = gpu_temp_max - cpu_temp_avg
    
    debug_info = {
        'cpu_avg': cpu_temp_avg,
        'gpu_avg': gpu_temp_avg,
        'gpu_max': gpu_temp_max,
        'temp_diff': temp_diff
    }
    
    # Check for max overpower condition
    # Get the appropriate curve based on which component is dominant
    if abs(temp_diff) > 10:  # Significant difference
        if temp_diff > 0:  # GPU significantly hotter
            effective_temp = gpu_temp_max
            use_gpu_curve = True
            debug_info['decision'] = 'gpu_dominant'
        else:  # CPU significantly hotter
            effective_temp = cpu_temp_avg
            use_gpu_curve = False
            debug_info['decision'] = 'cpu_dominant'
    else:  # Balanced workload
        effective_temp = round(cpu_temp_avg * cpu_weight + gpu_temp_max * gpu_weight)
        use_gpu_curve = False  # Use CPU curve as default for balanced
        debug_info['decision'] = 'balanced'
        debug_info['weighted_temp'] = effective_temp
    
    return effective_temp, use_gpu_curve, debug_info

def compute_fan_speed(temp_average, use_gpu_curve=False):
    """
    Compute fan speed using appropriate curve (CPU or GPU).
    Maintains backward compatibility with single curve configuration.
    """
    global state
    
    # Determine which curve to use
    if use_gpu_curve and 'temperature_control' in config:
        # Use GPU curve if available and requested
        curve = config['temperature_control'].get('gpu_curve', {})
        if curve and 'temperatures' in curve and 'speeds' in curve:
            temps = curve['temperatures']
            speeds = curve['speeds']
            hysteresis = curve.get('hysteresis', config['host'].get('hysteresis', 2))
        else:
            # Fallback to CPU curve or legacy
            use_gpu_curve = False
    
    if not use_gpu_curve:
        # Use CPU curve or legacy configuration
        if 'temperature_control' in config:
            curve = config['temperature_control'].get('cpu_curve', {})
            if curve and 'temperatures' in curve and 'speeds' in curve:
                temps = curve['temperatures']
                speeds = curve['speeds']
                hysteresis = curve.get('hysteresis', config['host'].get('hysteresis', 2))
            else:
                # Fallback to legacy configuration
                temps = config['host']['temperatures']
                speeds = config['host']['speeds']
                hysteresis = config['host'].get('hysteresis', 2)
        else:
            # Pure legacy configuration
            temps = config['host']['temperatures']
            speeds = config['host']['speeds']
            hysteresis = config['host'].get('hysteresis', 2)
    
    # Handle automatic mode if above highest threshold
    if temp_average > temps[-1]:
        set_fan_control("automatic")
        return
    
    # Find the appropriate speed level with hysteresis
    selected_speed = len(temps)  # Default to automatic (will be reduced in loop)
    for i, threshold in enumerate(temps):
        if temp_average <= threshold and checkHysteresis(temp_average, i):
            selected_speed = i
            break
    
    # Apply the speed if found (and not automatic)
    if selected_speed < len(speeds):
        set_fan_speed(selected_speed)

def main():
    global config
    global state

    print("Starting fan control script.")
    host = config['host']
    print("[{}] Thresholds: {}".format(
        host['name'],
        ", ".join(
            "{}°C ({}%)".format(temp, speed)
            for temp, speed in zip(host['temperatures'], host['speeds'])
        )
    ))
    while True:
        temps = []
        cores = []
        for sensor in sensors.get_detected_chips():
            if sensor.prefix == "coretemp":
                cores.append(sensor)
        for core in cores:
            for feature in core.get_features():
                for subfeature in core.get_all_subfeatures(feature):
                    if subfeature.name.endswith("_input"):
                        temps.append(core.get_value(subfeature.number))
        cpu_temp_avg = round(sum(temps)/len(temps))
        gpu_temps = get_gpu_temperatures()
        if all(temp == 0 for temp in gpu_temps):
            print("Warning: All GPU temps reported as 0°C (check driver).", file=sys.stderr)
        
        # Use improved algorithm with separate curves and max overpower detection
        effective_temp, use_gpu_curve, debug_info = calculate_effective_temperature(cpu_temp_avg, gpu_temps)
        
        if config['general']['debug']:
            print(f"[{host['name']}] CPU_Avg: {debug_info['cpu_avg']} GPU_M: {debug_info['gpu_max']} GPU_A: {debug_info['gpu_avg']}")
            print(f"[{host['name']}] Decision: {debug_info['decision']} -> Effective: {effective_temp}°C, Curve: {'GPU' if use_gpu_curve else 'CPU'}")
        
        compute_fan_speed(effective_temp, use_gpu_curve)
        time.sleep(config['general']['interval'])


def graceful_shutdown(signalnum=None, frame=None):
    """
    Ensures that fan control is returned to automatic mode,
    sensors are cleaned up, and the script exits cleanly.
    This function swallows any errors to guarantee shutdown.
    """
    print(f"Signal {signalnum} received, performing shutdown procedure.")
    # Attempt to set fans to automatic, ignoring failures
    try:
        if state.get('fan_control_mode') is not None:
            set_fan_control("automatic")
    except Exception as e:
        print(f"Error during set_fan_control in shutdown: {e}", file=sys.stderr)
    # Attempt sensors cleanup, ignoring failures
    try:
        sensors.cleanup()
    except Exception as e:
        print(f"Error during sensors.cleanup in shutdown: {e}", file=sys.stderr)
    # Exit regardless
    sys.exit(0)

if __name__ == "__main__":
    # Register OS signals to ensure graceful shutdown
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        parse_opts()
        parse_config()
        main()
    except (getopt.GetoptError, InterruptedError):
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt, shutting down...")
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Ensure cleanup on any exit path
        try:
            graceful_shutdown(None, None)
        except SystemExit:
            pass
        except Exception as e:
            print(f"Unexpected error in final shutdown: {e}", file=sys.stderr)
            sensors.cleanup()
            sys.exit(0)
