#!/usr/bin/env python3


""" Set of utility functions for the baseline_run script

This module contains utility functions for the baseline_run script
to help with getting login credentials and device OS types.

Initially, you will need to modify the get_credentials function to
securely retrieve login credentials from a secure location such as
a password manager or encrypted file.

You may also need to modify the get_os function to implement custom
inventory plugins or other methods to determine the OS type of
network devices.  (Should be a string that Netmiko device_typ format)
"""

import os
import re
from easysnmp import Session


def _convert_netmiko(my_os):
    """Convert format to what netmiko expects for connections
    This can be modified to add more OS types as needed
    depending on how they are stored in your inventory."""
    dev_map = {
        "IOS": "cisco_ios",
        "XR": "cisco_xr",
        "JUNOS": "juniper_junos",
        "TiMOS": "nokia_sros",
        "SROS": "nokia_sros",
        "MDCLI": "nokia_sros",
    }
    try:
        my_os = dev_map[my_os]
        return my_os
    except:
        print(f"ERROR converting {my_os} to netmiko format")


def nokia_classis_or_mdcli(hostname, output):
    """Takes in a router hostname and some SSH session output and
    looks for a prompt to try and determine if it is in classic or mdcli mode
    Args:
        hostname (str): The device hostname
        output (str): The output from the SSH session
    Returns:
        str: The OS type for Netmiko connection - nokia_sros or nokia_mdcli
    """
    # Nokia MDCLI has A|B:<username>@<hostname> as the prompt
    # Classic mode has A|B:<hostname> as the prompt
    # Check if the prompt has a @ in it
    # Iterate over the first 10 lines
    for line in output.splitlines()[:10]:
        if re.match(rf"^\*?[AB]:.*@{hostname}", line):
            return "nokia_mdcli"
    return "nokia_sros"


def get_os(host, config):
    """Utility to get network device OS type using several different methods.

    1. Look in 'override.txt' for manual OS definiations
    2. Use custom inventory plugins to check the device database
    4. Query the device via SNMP

    Args:
        host (str): The device hostname
        config (dict): The configuration dictionary
    Returns:
        str: The OS type for Netmiko connection
    """
    # Check the override file for manual overrides:
    # Should be formatted one per line HOSTNAME OS_TYPE
    my_os = check_override_file(host, config)
    if my_os:
        return my_os
    # Check custom inventory (code required to implement this function)
    my_os = check_custom_inventory(host)
    if my_os:
        return my_os
    # Check SNMP
    my_os = check_snmp(host, config)
    if my_os:
        return my_os
    # if all failed return None
    return


def check_override_file(host, config):
    """Check a file for manual OS overrides
    Args:
        host (str): The device hostname
        config (dict): The configuration dictionary

    Returns:
        str: The OS type for Netmiko connection
    """
    try:
        my_os = ""
        with open(config["os_override_file"]) as f:
            overrides = f.read()
        if host in overrides:
            for line in overrides.splitlines():
                if line.split()[0] == host:
                    my_os = line.split()[1]
    except Exception as _e:
        return
    return my_os


def check_custom_inventory(host):
    """Check a custom inventory database for the OS type
    For example, query a mySQL database
    """
    try:
        # Put custom code here to get os type
        if host == "router1":
            my_os = "cisco_ios"
            return my_os
    except Exception as _e:
        return


def check_snmp(host, config):
    """Try getting the os type via SNMP
    Args:
        host (str): The device hostname
        config (dict): The configuration dictionary
    Returns:
        str: The OS type for Netmiko connection
    """
    try:
        my_os = None
        os_mappings = {
            "Cisco IOS XR Software": "cisco_xr",
            "Cisco IOS Software": "cisco_ios",
            "JUNOS": "juniper_junos",
            "TiMOS": "nokia_sros",
        }

        # SNMP parameters
        community = config["snmp_community"]
        version = config["snmp_version"]
        oid = ".1.3.6.1.2.1.1.1.0"  # sysDescr OID
        # Create an SNMP session
        session = Session(hostname=host, community=community, version=version)
        # Perform an SNMP GET request
        response = session.get(oid)
        # Extract the system description from the response
        for os_type, os_value in os_mappings.items():
            if os_type in str(response.value):
                my_os = os_value
                break
        return my_os
    except Exception as _e:
        return


def get_credentials():
    """Get login credentials for network devices

    Modify this function to securely retrieve login credentials
    from a secure location such as a password manager or
    encrypted file.

    Returns:
        dict: A dictionary containing login credentials
            keys: username, password
    """
    login_info = {"username": "guest", "password": "Password"}
    return login_info


def _expand_user_and_vars_to_abs(path):
    """Expand user and environment variables in a path"""
    path = os.path.expanduser(path)
    path = os.path.expandvars(path)
    path = os.path.abspath(path)
    return path


def normalize_config_paths(config):
    """Takes the paths in the configuration file and makes sure they are
    expanded for user and environment variables and are absolute paths.

    Args:
        config (dict): Loaded Config File Information

    Returns:
        dict: Updated config file data
    """
    # MAIN PROJECT PATH
    if not config.get("project_path"):
        config["project_path"] = os.path.dirname(os.path.realpath(__file__))
    else:
        config["project_path"] = _expand_user_and_vars_to_abs(config["project_path"])
    # MOP FILES PATH
    if not config.get("mop_path"):
        config["mop_path"] = config["project_path"] + "src/mops/"
    else:
        config["mop_path"] = _expand_user_and_vars_to_abs(config["mop_path"])
    # TEST FILES PATH
    if not config.get("testfile_path"):
        config["testfile_path"] = config["project_path"] + "/src/testfiles/"
    else:
        config["testfile_path"] = _expand_user_and_vars_to_abs(config["testfile_path"])
    # TextFSM TEMPLATES PATH
    if not config.get("testfile_path"):
        config["tfsm_templates_path"] = config["project_path"] + "src/tfsm_templates/"
    else:
        config["tfsm_templates_path"] = _expand_user_and_vars_to_abs(config["tfsm_templates_path"])
    # OS OVERRIDE FILE
    if not config.get("os_override_file"):
        config["os_override_file"] = config["project_path"] + "src/configs/os_type_override.txt"
    else:
        config["os_override_file"] = _expand_user_and_vars_to_abs(config["os_override_file"])
    return config
