#!/usr/bin/env python3


"""
Add functions here to create custom commands for testing.

Custom functions must start with 'custom_' and take the 'self' object

For exmample, SROS doesn't have a sane view of BGP neighbors that can
be directly parsed the way that baseline_check expects.  So, you can
create a custom command to parse the output, and make it into a more
standard format, with one line per neighbor.
johntishey@gmail.com - 2024
"""

import textfsm
import math


def textfsm_parse(template_file, raw_text_data):
    """Returns a dict output of textfsm parsed template
    Params:
        template_file str - The location of the template file on disk
        raw_text_data str - The command output to be parsed
    """
    try:
        template = open(template_file)
    except:
        return
    re_table = textfsm.TextFSM(template)
    data = re_table.ParseText(raw_text_data)
    results = []
    for row in data:
        row_data = {}
        for i, item in enumerate(row):
            row_data[re_table.header[i].lower()] = item
        results.append(row_data)
    template.close()
    return results


def custom_nokia_sros_router_bgp_summary_family_ipv4(device):
    """Nokia - show router bgp summary family ipv4
    Takes the output from Nokia 'SROS show router bgp summary family ipv4'
    and parses it with TextFSM to get the neighbor, AS, and state.  Then capture
    that info as a fake command output for testing in the differentiator.
    Adds a fake command "show router bgp summary ipv4" to the baseline output.
    Args:
        device (object): The Run instance from the differentiator
    Returns:
        object: The Run instance from the differentiator
    """
    for kw in ["before", "after"]:
        if device.output[kw].get("show router bgp summary family ipv4"):
            template = (
                f"{device.cfg['tfsm_templates_path']}/nokia_sros_show_router_bgp_summary_family.textfsm"
            )
            cmd_output = device.output[kw].get("show router bgp summary family ipv4")
            fake_input = ""
            for line in cmd_output:
                fake_input += line + "\n"
            data = textfsm_parse(template, fake_input)
            if data:
                fake_output = ""
                for neigh in data:
                    # neighbor, as, state
                    if not neigh["state"]:
                        neigh["state"] = "Established"
                    fake_output += f'{neigh["neighbor"]}  {neigh["as"]}  {neigh["state"]}\n'
                device.output[kw]["show router bgp summary ipv4"] = fake_output.splitlines()
    return device.output


def custom_nokia_sros_show_redundancy_multichassis_sync(device):
    """Nokia - show redundancy multi-chassis sync
    Takes the output from Nokia 'SROS show redundancy multi-chassis sync'
    and parses it with TextFSM to get the peer IP, number of entries, and the
    state of the database sync.  Then capture that info as a fake command output
    for testing in the differentiator.
    Replaces the output of "show redundancy multi-chassis sync" to the baseline output.
    Args:
        device (object): The Run instance from the differentiator
    Returns:
        object: The Run instance from the differentiator
    """
    for kw in ["before", "after"]:
        if device.device.output[kw].get("show redundancy multi-chassis sync"):
            template = f"{device.device.cfg['tfsm_templates_path']}/nokia_sros_show_redundancy_multichassis_sync.textfsm"
            cmd_output = device.device.output[kw].get("show redundancy multi-chassis sync")
            fake_input = ""
            for line in cmd_output:
                fake_input += line + "\n"
            data = textfsm_parse(template, fake_input)
            if data:
                fake_output = ""
                for peer in data:
                    # if local and remote are witin 0.5%, call it good
                    max_percent = 0.005
                    delta = abs(int(peer["num_entries"]) - int(peer["rem_num_entries"]))
                    if delta > math.ceil(float(int(peer["num_entries"])) * max_percent):
                        outcome = "NOT_SYNC"
                    else:
                        outcome = "IN_SYNC"
                    # peer_ip        entries  rem_entries db_sync_state  outcome  peer_name
                    # 192.168.0.1  1234   1234        inSync        IN_SYNC  router2
                    fake_output += f'{peer["peer_ip"]} {peer["num_entries"]} {peer["rem_num_entries"]} {peer["db_sync_state"]} {outcome} {peer["peer_name"]}\n'
                device.output[kw]["show redundancy multi-chassis sync"] = fake_output.splitlines()
    return device.output
