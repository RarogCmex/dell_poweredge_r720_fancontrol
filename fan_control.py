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
            timeout=5,  # Prevent hanging
            check=True,
        )
        
        # Split and validate output
        temps_raw = result.stdout.strip().split('\n')
        temperatures = []
        
        for temp_str in temps_raw:
            try:
                temp = int(temp_str)
                if 0 <= temp <= 200:  # Validate plausible range
                    temperatures.append(temp)
                else:
                    print(f"Warning: Invalid GPU temperature '{temp_str}' (ignored)", file=sys.stderr)
            except ValueError:
                print(f"Warning: Non-numeric GPU temperature '{temp_str}' (ignored)", file=sys.stderr)
        
        if not temperatures:
            print("Error: No valid GPU temperatures found. Using fallback (0°C).", file=sys.stderr)
            return [0]
        
        return temperatures

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
    'host': []
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
    if wanted_percentage == state['fan_speed']:
        return
    if 5 <= wanted_percentage <= 100:
        wanted_percentage_hex = "{0:#0{1}x}".format(wanted_percentage, 4)
        if state['fan_control_mode'] != "manual":
            set_fan_control("manual")
            time.sleep(1)
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
    print(host)
    if 'hysteresis' not in list(host.keys()):
        host['hysteresis'] = 0
    if len(host['temperatures']) != 3:
        raise ConfigError('Host "{}" has {} temperature thresholds instead of 3.'.format(host['name'], len(host['temperatures'])))
    if len(host['speeds']) != 3:
        raise ConfigError('Host "{}" has {} fan speeds instead of 3.'.format(host['name'], len(host['speeds'])))
    # TODO: check presence/validity of values instead of keys presence only
    state.update({
        'is_remote': 'remote_temperature_command' in host,
        'fan_control_mode': 'automatic',
        'fan_speed': 0
    })

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
    if temp_average <= host['temperatures'][0] and checkHysteresis(temp_average, 0):
        set_fan_speed(0)
    elif host['temperatures'][0] < temp_average <= host['temperatures'][1] and checkHysteresis(temp_average, 1):
        set_fan_speed(1)
    elif host['temperatures'][1] < temp_average <= host['temperatures'][2] and checkHysteresis(temp_average, 2):
        set_fan_speed(2)
    elif host['temperatures'][2] < temp_average:
        set_fan_control("automatic")

def main():
    global config
    global state

    print("Starting fan control script.")
    host = config['host']
    print("[{}] Thresholds of {}°C ({}%), {}°C ({}%) and {}°C ({}%)".format(
            host['name'],
            host['temperatures'][0], host['speeds'][0],
            host['temperatures'][1], host['speeds'][1],
            host['temperatures'][2], host['speeds'][2],
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
        gpu_temp_avg = round(sum(gpu_temps)/len(gpu_temps))
        gpu_temp_max = max(gpu_temps)
        temp_eff = round((cpu_temp_avg + gpu_temp_max + gpu_temp_max + gpu_temp_avg) / 4)
        if config['general']['debug']:
            print(f'[{host['name']}] CPU_Avg: {cpu_temp_avg} GPU_M: {gpu_temp_max} GPU_A: {gpu_temp_avg}')
        max_temp_eff = max(temp_eff, cpu_temp_avg)
        compute_fan_speed(max_temp_eff)
        time.sleep(config['general']['interval'])


def graceful_shutdown(signalnum, frame):
    print(f"Signal {signalnum} received, giving up control")
    set_fan_control("automatic")
    sys.exit(0)

if __name__ == "__main__":
    # Reset fan control to automatic when getting killed
    signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        try:
            parse_opts()
        except (getopt.GetoptError, InterruptedError):
            sys.exit(1)
        parse_config()
        main()
    finally:
        sensors.cleanup()
