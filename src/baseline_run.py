#!/usr/bin/env python3

"""
This is a script to login to network devices and capture output
from commands before and after making changes, for the purpose of
comparing the outputs before/after with the baseline_check script.
0.132.98.92/30 
johntishey@gmail.com - 2019
"""

import os
import sys
import yaml
import argparse
import threading
import datetime
from queue import Queue
from netmiko import ConnectHandler

from utils.baseline_utils import get_credentials
from utils.baseline_utils import get_os
from utils.baseline_utils import normalize_config_paths


def arguments():
    """
    Grab arguments from cli - Requires devices, ticket number, and before/after keyword.
    """
    parser = argparse.ArgumentParser(description="Runs a before/after baseline against network devices.")
    parser.add_argument("-d", "--dev", help="Comma-seperated list of hosts", required=True)
    parser.add_argument(
        "-k",
        "--keyword",
        help="Specify if this run is before/after making changes",
        required=True,
    )
    parser.add_argument("-m", "--mop", help="MOP/Change/Ticket number for tracking", required=True)
    parser.add_argument("-c", "--config", help="Alternate config file", required=False)
    args = vars(parser.parse_args())
    dev = args["dev"]
    keyword = args["keyword"]
    mop_id = args["mop"]
    config_file = os.path.dirname(os.path.realpath(__file__)) + "/configs/config.yml"
    if args["config"]:
        config_file = args["config"]
    return dev, keyword, mop_id, config_file


def _load_config(config_file):
    """
    Loads baseline_run configuration file
    :param config_file: (str) Define a config file (Default=config.yml)
    """
    if not os.path.exists(config_file):
        if os.path.exists(os.path.dirname(os.path.realpath(__file__)) + "/" + config_file):
            config_file = os.path.dirname(os.path.realpath(__file__)) + "/" + config_file
        else:
            print("ERROR: Unable to open config file")
            sys.exit(1)
    try:
        with open(config_file, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        print(str(e))
        sys.exit(1)
    # Expand ~'s and $'s in the config file paths and follow symlinks
    cfg = normalize_config_paths(cfg)
    return cfg


def _worker(work_queue, cfg, key_word, mop_id):
    """worker function that executes thread queue"""
    while True:
        device = work_queue.get()
        # Open a netmiko connection to a device
        auth_info = get_credentials()
        # Get OS Type
        device_type = get_os(device, cfg)
        try:
            device_object = {
                "device_type": device_type,
                "ip": device,
                "username": auth_info["username"],
                "password": auth_info["password"],
                "timeout": 180,
                "session_timeout": 60,
            }
            net_connect = ConnectHandler(**device_object)
        except Exception as e:
            print(str(e))
            work_queue.task_done()
            continue

        try:
            # Run commands and get output from network device
            output = ""
            # Build Config Command Map
            cmds = {
                "juniper_junos": "show configuration | display set",
                "cisco_ios": "show run",
                "cisco_xr": "show configuration running-config formal",
                "nokia_sros": "admin display-config",
                "nokia_mdcli": "admin show configuration",
            }
            # Nokia in Model Driven mode puts user@hostname as prompt
            if device_type == "nokia_sros" and "@" in net_connect.base_prompt:
                device_type = "nokia_mdcli"
            # Turn off timestamps for XR show run
            if device_type == "cisco_xr":
                net_connect.send_command("terminal exec prompt no-timestamp")
            # Run commands from testfiles + show running config
            net_connect.find_prompt()
            output += f"\n[DEVICE] {device}"
            output += f"\n[KEYWORD] {key_word}"
            output += f"\n[MOP] {mop_id}"
            output += f"\n[DEVICE_TYPE] {device_type}"
            output += f"\n[BASE_PROMPT] {net_connect.base_prompt}\n\n"
            for command in cfg["commands"][device_type]:
                output += f"\n\n[COMMAND] {command}\n"
                output += net_connect.send_command(command)
            # Capture Configuration
            output += f"\n\n[COMMAND] {cmds[device_type]}\n"
            output += net_connect.send_command(cmds[device_type])
            # Capture Pings
            ping_cmds = {
                "juniper_junos": "ping rapid <<TARGET>>",
                "cisco_ios": "ping <<TARGET>>",
                "cisco_xr": "ping <<TARGET>>",
                "nokia_sros": "ping rapid <<TARGET>>",
                "nokia_mdcli": "//ping rapid <<TARGET>>",
            }
            ping_vrf_cmds = {
                "juniper_junos": "ping rapid routing-instance <<VRF>> <<TARGET>>",
                "cisco_ios": "ping vrf <<VRF>> <<TARGET>>",
                "cisco_xr": "ping vrf <<VRF>> <<TARGET>>",
                "nokia_sros": "ping rapid router <<VRF>> <<TARGET>>",
                "nokia_mdcli": "//ping rapid router <<VRF>>  <<TARGET>>",
            }

            for target in cfg["ping_targets"]:
                if target.get("vrf"):
                    cmd = ping_vrf_cmds[device_type]
                    cmd = cmd.replace("<<TARGET>>", target["ip"])
                    cmd = cmd.replace("<<VRF>>", target["vrf"])
                else:
                    cmd = ping_cmds[device_type]
                    cmd = cmd.replace("<<TARGET>>", target["ip"])
                output += f"\n\n[COMMAND] {cmd}\n"
                output += net_connect.send_command(cmd)
            net_connect.disconnect()
        except Exception as e:
            output += "\n"
            output += str(e)

        try:
            # Construct the file path to save the log
            t = datetime.datetime.utcnow().date()
            file_path = f"{t.year}/{t.month:02d}_{t.strftime('%B')[:3]}/{t.day:02d}_{t.month:02d}_{t.year:02d}/{mop_id}/"
            file_name = f"{mop_id}_{device}_{key_word}_log"

            # Make sure all the folders exist, and create them if needed
            if os.path.exists(f"{cfg['mop_path']}"):
                if not os.path.exists(f"{cfg['mop_path']}/{t.year}"):
                    os.mkdir(f"{cfg['mop_path']}/{t.year}")
                if not os.path.exists(f"{cfg['mop_path']}/{t.year}/{t.month:02d}_{t.strftime('%B')[:3]}"):
                    os.mkdir(f"{cfg['mop_path']}/{t.year}/{t.month:02d}_{t.strftime('%B')[:3]}")
                if not os.path.exists(
                    f"{cfg['mop_path']}/{t.year}/{t.month:02d}_{t.strftime('%B')[:3]}/{t.day:02d}_{t.month:02d}_{t.year:02d}"
                ):
                    os.mkdir(
                        f"{cfg['mop_path']}/{t.year}/{t.month:02d}_{t.strftime('%B')[:3]}/{t.day:02d}_{t.month:02d}_{t.year:02d}"
                    )
                if not os.path.exists(
                    f"{cfg['mop_path']}/{t.year}/{t.month:02d}_{t.strftime('%B')[:3]}/{t.day:02d}_{t.month:02d}_{t.year:02d}/{mop_id}"
                ):
                    os.mkdir(
                        f"{cfg['mop_path']}/{t.year}/{t.month:02d}_{t.strftime('%B')[:3]}/{t.day:02d}_{t.month:02d}_{t.year:02d}/{mop_id}"
                    )
                if os.path.exists(f"{cfg['mop_path']}/{file_path}/{file_name}"):
                    os.remove(f"{cfg['mop_path']}/{file_path}/{file_name}")
            else:
                print("ERROR: MOP folder does not exist, update the config file")
        except Exception as e:
            print(str(e))

        # Save output to a file
        try:
            with open(f"{cfg['mop_path']}/{file_path}/{file_name}", "w+", encoding="utf8") as f:
                f.write(output)
            work_queue.task_done()
        except Exception as e:
            print(str(e))
            work_queue.task_done()


def get_commands(cfg):
    """
    Extracts a list of commands from the baseline_check testfiles
    This is the list of commands that will be run against each device
    in the baseline_run.
    :param cfg: the baseline_check config yaml object
    """
    # commands = {dev_os: [command1, command2], ...}
    commands = {
        "cisco_ios": [],
        "cisco_xr": [],
        "juniper_junos": [],
        "nokia_sros": [],
        "nokia_mdcli": [],
    }

    for dev_os in commands:
        if dev_os not in cfg.keys():
            continue
        for test_file in cfg[dev_os]:
            try:
                with open(f"{cfg['testfile_path']}/{dev_os}/{test_file}", encoding="utf8") as f:
                    test = yaml.safe_load(f)
                if isinstance(test[0]["command"], list):
                    for c in test[0]["command"]:
                        commands[dev_os].append(c)
                else:
                    commands[dev_os].append(test[0]["command"])
            except Exception as e:
                print(str(e))
                sys.exit(1)
    return commands


def get_baseline(dev, key_word, mop, cfg_file):
    """
    Gets info from cli arguments or external call and starts the script.
        :param dev: (str) Comma-seperated list of device names
        :param key_word: (str) Before/after or pre/post key_word
        :param mop:  (str) Ticket number tracking the changes being made
    """
    # Argument validations
    if [arg for arg in [dev, key_word, mop] if "_" in arg]:
        print("Arguments may not contain underscores")
        exit(1)
    cfg = _load_config(cfg_file)
    cfg["commands"] = get_commands(cfg)
    work_queue = Queue(maxsize=cfg["max_queue"]) or 0
    _lock = threading.RLock()
    devices = dev.split(",")

    # Create worker threads that sleep until they have something in the queue
    for _i in range(cfg["max_threads"]) or 10:
        t = threading.Thread(target=_worker, args=(work_queue, cfg, key_word, mop))
        t.setDaemon(True)
        t.start()
    # Add work to the queue for the worker threads
    for device in devices:
        device = device.rstrip()
        work_queue.put(device)
    # Dont continue until the queue is empty
    work_queue.join()


if __name__ == "__main__":
    devices, kw, mop, cfg_file = arguments()
    get_baseline(devices, kw, mop, cfg_file)
