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

def get_gpu_temperatures() -> list[int]:
    """
    Fetch GPU temperatures using nvidia-smi with safety checks.
    Returns a list of temperatures (or [0] as fallback if errors occur).
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
                    print(f"Warning: Invalid GPU temperature '{temp_str}' (ignored)", file=sys.stderr)
            except ValueError:
                print(f"Warning: Non-numeric GPU temperature '{temp_str}' (ignored)", file=sys.stderr)
        
        if not temperatures:
            print("Error: No valid GPU temperatures found. Using fallback (0°C).", file=sys.stderr)
            return [0]
        
        return temperatures
    except KeyboardInterrupt:
        raise  # Re-raise to allow main loop to handle
    except subprocess.TimeoutExpired:
        print("Error: nvidia-smi timed out (driver hung?). Using fallback (0°C).", file=sys.stderr)
        return [0]
    except subprocess.CalledProcessError as e:
        print(f"Error: nvidia-smi failed (exit={e.returncode}): {e.stderr.strip()}", file=sys.stderr)
        return [0]
    except Exception as e:
        print(f"Error: Unexpected error in get_gpu_temperatures(): {str(e)}", file=sys.stderr)
        return [0]
        

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

def compute_fan_speed(temp_average):
    global state
    host = config['host']
    temps = host['temperatures']
    speeds = host['speeds']
    
    # Handle automatic mode if above highest threshold
    if temp_average > temps[-1]:
        set_fan_control("automatic")
        return
    
    # Find the appropriate speed level
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
        gpu_temp_avg = round(sum(gpu_temps)/len(gpu_temps))
        gpu_temp_max = max(gpu_temps)
        temp_eff = round((cpu_temp_avg + gpu_temp_max + gpu_temp_max + gpu_temp_avg) / 4)
        if config['general']['debug']:
            print(f"[{host['name']}] CPU_Avg: {cpu_temp_avg} GPU_M: {gpu_temp_max} GPU_A: {gpu_temp_avg}")
        max_temp_eff = max(temp_eff, cpu_temp_avg)
        compute_fan_speed(max_temp_eff)
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
