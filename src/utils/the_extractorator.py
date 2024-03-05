#!/usr/bin/env python3

"""
baseline_check module to extract commands and output
johntishey@gmail.com - 2017
"""

import re


def run(device):
    """Get device prompt and call the extract function"""
    # prompt is for matching lines, prompt_re is for removing the prompt from the line
    if device.os_type == "juniper_junos":
        prompt_re = re.compile("deip@" + device.hostname + "(\-re[01])?\> ?", re.IGNORECASE)
    elif device.os_type == "cisco_ios":
        prompt_re = re.compile(device.hostname + "#", re.IGNORECASE)
    elif device.os_type == "cisco_xr":
        prompt_re = re.compile("RP/0/.*/CPU[01]:" + device.hostname + "#", re.IGNORECASE)
    elif device.os_type == "nokia_sros":
        prompt_re = re.compile("\*?[AB]\:(.*@)?" + device.hostname + "#\ ?", re.IGNORECASE)
    elif device.os_type == "nokia_mdcli":
        prompt_re = re.compile("\*?[AB]\:(.*@)?" + device.hostname + "#\ ?", re.IGNORECASE)
    else:
        return "ERROR: " + device.hostname + " OS not found or not yet supported"
    output = extract(device, prompt_re)
    return output


# Split into individual commands
def extract(device, prompt):
    """extract commands from baselines"""
    # Open the before and after baseline files and loop through lines
    output = {}
    for each_file in device.files:
        with open(each_file, "r", errors="replace", encoding="utf-8") as f:
            baseline_text = f.readlines()
        commands = {}
        current_command = ""
        for line in baseline_text:
            line = line.rstrip()
            # if there's a prompt, set it as a new command
            # and capture subsequent lines under it
            if re.match(prompt, line) or line.startswith("[COMMAND]"):
                if line[-1] != ">" and line[-1] != "#":
                    line = prompt.sub("", line)
                    line = line.replace("[COMMAND] ", "")
                    current_command = line
                    commands[current_command] = []
            else:
                if current_command != "":
                    if line != "" and line[:7] != "{master" and line != "[]":
                        commands[current_command].append(line)
        if device.config.before_kw.lower() in str(each_file).lower():
            output["before"] = commands
        else:
            output["after"] = commands
    return output
