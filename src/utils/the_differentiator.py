#!/usr/bin/env python3

"""
baseline_check module to compare command output from baselines
johntishey@gmail.com - 2017
"""

import colorama
import difflib
import logging
import jinja2
import math
import yaml
import re


from . import custom_commands


class Run(object):
    """Run tests on the before and after commands"""

    def __init__(self, device):
        """Compare output of commands according to test rules
        device.output['before'] and device.output['after'] contain the outputs"""
        self.device = device
        self.test_list = self.device.config.cfg[(self.device.os_type)]
        self.test_path = f"{self.device.config.cfg['testfile_path']}/{self.device.os_type}"
        self.pre, self.post = "", ""
        self.pass_status = ""
        self.delta_value = ""
        self.is_reflector = False
        self.has_default = ""
        self.has_discard = ""
        self.section_id = ""
        self.summary = {}
        self.PASS_COLOR = device.config.PASS_COLOR
        self.FAIL_COLOR = device.config.FAIL_COLOR
        # Create an object and ignore color for json output
        self.json_output = {}
        self.json_output[self.device.hostname] = {}
        self.json_output[self.device.hostname]["show configuration"] = []
        if self.device.config.verbose == 63:
            self.FAIL_COLOR = ""
        self.json = bool(self.device.config.verbose == 63)
        # Run only config diff if -c option is used
        if self.device.config.verbose == 61:
            self.config_diff_flat()
            return

        # EXECUTE CHECKS ::::
        self.build_custom_commands()
        self.get_command_lists()
        self.config_diff_flat()
        self.test_ping_output()
        self.print_summary()

    def build_custom_commands(self):
        """Run all of the "custom_" functions in the custom_commands module
        These functions take hard to parse output and make it into a more
        standard format. Either repalcing the original command output, or
        adding a new command to the baseline output.
        """
        functions_to_call = [function for function in dir(custom_commands) if function.startswith("custom_")]
        for function in functions_to_call:
            try:
                self.device.output = getattr(custom_commands, function)(self.device)
            except Exception as _e:
                pass

    def get_command_lists(self):
        """For each yaml file in the config file, open testfile and gather command output."""
        logger = logging.getLogger("BaselineCheck")
        for test_case in self.test_list:
            # Don't read the ping command testfiles
            if test_case == "test_pings.yml":
                continue
            # Read all the other testfiles
            try:
                with open(self.test_path + "/" + test_case, encoding="utf-8") as f:
                    self.test_values = yaml.safe_load(f)
            except:
                if self.json:
                    self.json_output[self.device.hostname][test_case] = [
                        f"ERROR: Could not load {self.test_path}/{test_case}"
                    ]
                else:
                    logger.info("\n")
                    logger.error(
                        self.FAIL_COLOR + "ERROR:  Could not load " + self.test_path + "/" + test_case
                    )
                    logger.info("\n")
                continue
            try:
                if isinstance(self.test_values[0]["command"], list):
                    continue
                log_msg = "******** Command: " + self.test_values[0]["command"] + " ********"
                logger.info(log_msg)
                self.before_cmd_output = self.device.output["before"][(self.test_values[0]["command"])]
                self.after_cmd_output = self.device.output["after"][(self.test_values[0]["command"])]
                self.json_output[self.device.hostname][self.test_values[0]["command"]] = []
            except KeyError:
                log_msg = "ERROR:  " + self.test_values[0]["command"] + " not found in the baseline!"
                logger.info(log_msg)
                logger.info("\n")
                continue
            self.before_cmd_output = self.filter_output(self.before_cmd_output)
            self.after_cmd_output = self.filter_output(self.after_cmd_output)
            self.test_cmd_output()

    def filter_output(self, command_output):
        """Remove blacklisted lines and non-iterator lines from command output"""
        testable_output = []
        wrap_word = ""
        for i, line in enumerate(command_output):
            skip_flag = False
            if wrap_word == command_output[i - 1]:
                line = wrap_word + " " + line
            wrap_word = ""
            # Skip lines that include a blacklisted word
            for word in self.test_values[0]["blacklist"]:
                if word in line:
                    skip_flag = True
            # If an iterator is set, skip lines that don't have the iterator
            if self.test_values[0]["iterate"] != ["all"]:
                iter_match = False
                for word in self.test_values[0]["iterate"]:
                    if word in line:
                        iter_match = True
                if iter_match is False:
                    skip_flag = True
            if skip_flag:
                continue
            # Check for possible line wrap
            try:
                line_wr = line.split()
                if len(line_wr) == 1:
                    if command_output[i + 1][:4] == "    ":
                        wrap_word = line_wr[0]
                        continue
            except:
                pass
            testable_output.append(line)
        return testable_output

    def test_cmd_output(self):
        """Gets before/after command and yaml test values to compare"""
        # Reset totals and variables
        self.summary[(self.test_values[0]["command"])] = {"PASS": 0, "FAIL": 0}
        line = ""
        self.pass_status = "UNSET"
        if len(self.before_cmd_output) == 0:
            self.exists(line)
            if self.pass_status != "UNSET":
                self.delta_value = 0
                self.print_result()
        else:
            for line in self.before_cmd_output:
                self.pass_status = "UNSET"
                self.delta_value = 0
                skip_line = False
                try:
                    if self.test_values[0]["section"]:
                        for word in self.test_values[0]["section"]:
                            if line.startswith(word):
                                self.section_id = line[len(word) :]
                                skip_line = True
                except KeyError:
                    pass
                if skip_line:
                    continue
                # NO-DIFF =  All indexes must match before/after
                if "no-diff" in self.test_values[0]["tests"][0]:
                    self.no_diff(line.split())
                # DELTA = Delta between 2 integers must be less than specified
                elif "delta" in self.test_values[0]["tests"][0]:
                    self.delta(line.split())
                # EXISTS = Should have at least one line matched by the iterator
                elif "exists" in self.test_values[0]["tests"][0]:
                    self.exists(line)
                # NOT-EXISTS = Should have no lines matched by the iterator
                elif "not-exists" in self.test_values[0]["tests"][0]:
                    self.exists(line)
                # If testing didn't find a match, mark as failed
                if self.pass_status == "UNSET":
                    self.pass_status = "FAIL"
                    self.post = ""
                self.print_result()
        self.after_only_lines()
        self.print_totals()

    def no_diff(self, line):
        """Execute no-diff tests (indicating all indexes match before/after)"""
        line_id = self.test_values[0]["tests"][0]["no-diff"][0]
        after_line = ""
        for after_line in self.after_cmd_output:
            try:
                after_line_orig = after_line
                after_line = after_line.split()
                if line[line_id] == after_line[line_id]:
                    for index in self.test_values[0]["tests"][0]["no-diff"]:
                        # If an index fails, mark as failed
                        try:
                            if line[index] != after_line[index]:
                                self.pass_status = "FAIL"
                                break
                        except:
                            self.pass_status = "FAIL"
                    # If it looped through indexes without failing, mark as pass
                    if self.pass_status == "UNSET":
                        self.pass_status = "PASS"
                    self.after_cmd_output.remove(after_line_orig)
                    break
            except IndexError:
                continue
        self.pre = line
        self.post = after_line

    def delta(self, line):
        """Execute delta tests (identifier / index/percent)"""
        line_id = self.test_values[0]["tests"][0]["delta"][0]
        index = self.test_values[0]["tests"][0]["delta"][1]
        max_percent = self.test_values[0]["tests"][0]["delta"][2]
        after_line = ""
        after_section_id = ""
        for after_line in self.after_cmd_output:
            skip_line = False
            try:
                for word in self.test_values[0]["section"]:
                    if after_line.startswith(word):
                        after_section_id = after_line[len(word) :]
                        skip_line = True
                        break
            except:
                pass
            if skip_line:
                continue
            try:
                after_line_orig = after_line
                after_line = after_line.split()
                if line[line_id] == after_line[line_id] and self.section_id == after_section_id:
                    line[index] = line[index].replace("%", "")
                    after_line[index] = after_line[index].replace("%", "")
                    # If before and after have a number in the match position:
                    if line[index].isdigit() and after_line[index].isdigit():
                        self.delta_value = abs(int(line[index]) - int(after_line[index]))
                        # If the difference is greater than allowed:
                        if self.delta_value > math.ceil(float(line[index]) * max_percent):
                            self.pass_status = "FAIL"
                        else:
                            self.pass_status = "PASS"
                    else:
                        # If they are not numbers, but they match:
                        if line[index] == after_line[index]:
                            self.pass_status = "PASS"
                            self.delta_value = "0"
                        else:
                            # If they are not both numbers and dont match
                            self.pass_status = "FAIL"
                            self.delta_value = "100%"
                    self.after_cmd_output.remove(after_line_orig)
                    break
            except IndexError:
                continue
        # If it gets out of the loop with no match in after:
        if self.pass_status == "UNSET":
            if line[index].isdigit():
                self.delta_value = line[index]
                self.pass_status = "FAIL"
                after_line = ["null"] * 12
            else:
                self.delta_value = "100%"
                self.pass_status = "FAIL"
                after_line = ["null"] * 12
        self.pre = line
        self.post = after_line

    def exists(self, line):
        """Execute exists/not-exists tests"""
        if "not-exists" in self.test_values[0]["tests"][0]:
            if line != "":
                self.pass_status = "FAIL"
            else:
                self.pass_status = "PASS"
                line = ["null"] * 12
        elif "exists" in self.test_values[0]["tests"][0]:
            if line != "":
                self.pass_status = "PASS"
            else:
                self.pass_status = "FAIL"
        self.pre = line
        self.post = line
        try:
            self.after_cmd_output.remove(line)
        except:
            pass

    def after_only_lines(self):
        """Account for lines in AFTER that aren't in BEFORE"""
        logger = logging.getLogger("BaselineCheck")
        if len(self.after_cmd_output) > 0:
            after_section_id = ""
            # IF TEST IS EXISTS OR NON-EXISTS:
            if "exists" in self.test_values[0]["tests"][0] or "not-exists" in self.test_values[0]["tests"][0]:
                after_line = ""
                for after_line in self.after_cmd_output:
                    self.pre = after_line
                    self.post = ""
                    if "not-exists" in self.test_values[0]["tests"][0]:
                        self.summary[(self.test_values[0]["command"])]["FAIL"] += 1
                        msg = jinja2.Template(str(self.test_values[0]["tests"][0]["err"]))
                        if self.json:
                            self.json_output[self.device.hostname][self.test_values[0]["command"]].append(
                                msg.render(device=self.device, pre=self.pre, post=self.post)
                            )
                        logger.warning(
                            self.FAIL_COLOR
                            + msg.render(device=self.device, pre=self.pre, post=self.post)
                            + colorama.Style.RESET_ALL
                        )
                    elif "exists" in self.test_values[0]["tests"][0]:
                        self.summary[(self.test_values[0]["command"])]["PASS"] += 1
                        msg = jinja2.Template(str(self.test_values[0]["tests"][0]["info"]))
                        logger.info(
                            self.PASS_COLOR
                            + msg.render(device=self.device, pre=self.pre, post=self.post)
                            + colorama.Style.RESET_ALL
                        )
            # IF TEST IS NO-DIFF OR DELTA:
            else:
                for after_line in self.after_cmd_output:
                    skip_line = False
                    try:
                        for word in self.test_values[0]["section"]:
                            if after_line.startswith(word):
                                after_section_id = after_line[len(word) :]
                                skip_line = True
                                break
                    except:
                        pass
                    if skip_line:
                        continue
                    self.summary[(self.test_values[0]["command"])]["FAIL"] += 1
                    self.post = after_line.split()
                    self.pre = [
                        "null",
                        "null",
                        "null",
                        "null",
                        "null",
                        "null",
                        "null",
                        "null",
                    ]
                    if "no-diff" in self.test_values[0]["tests"][0]:
                        line_id = self.test_values[0]["tests"][0]["no-diff"][0]
                    elif "delta" in self.test_values[0]["tests"][0]:
                        line_id = self.test_values[0]["tests"][0]["delta"][0]
                        self.delta_value = "100%"
                    try:
                        self.pre[line_id] = self.post[line_id]
                    except:
                        continue
                    msg = jinja2.Template(str(self.test_values[0]["tests"][0]["err"]))
                    if self.json:
                        self.json_output[self.device.hostname][self.test_values[0]["command"]].append(
                            msg.render(
                                device=self.device,
                                pre=self.pre,
                                post=self.post,
                                delta=self.delta_value,
                                section_id=after_section_id,
                            )
                        )
                    logger.warning(
                        self.FAIL_COLOR
                        + msg.render(
                            device=self.device,
                            pre=self.pre,
                            post=self.post,
                            delta=self.delta_value,
                            section_id=after_section_id,
                        )
                        + colorama.Style.RESET_ALL
                    )

    def print_result(self):
        """Print and count the results"""
        logger = logging.getLogger("BaselineCheck")
        if self.pass_status == "FAIL":
            self.summary[(self.test_values[0]["command"])]["FAIL"] += 1
            msg = jinja2.Template(str(self.test_values[0]["tests"][0]["err"]))
            if self.post == "" or self.post == []:
                self.post = ["null"] * 12
            if self.json:
                self.json_output[self.device.hostname][self.test_values[0]["command"]].append(
                    msg.render(
                        device=self.device,
                        pre=self.pre,
                        post=self.post,
                        delta=self.delta_value,
                        section_id=self.section_id,
                    )
                )
            logger.warning(
                self.FAIL_COLOR
                + msg.render(
                    device=self.device,
                    pre=self.pre,
                    post=self.post,
                    delta=self.delta_value,
                    section_id=self.section_id,
                )
                + colorama.Style.RESET_ALL
            )
        else:
            self.summary[(self.test_values[0]["command"])]["PASS"] += 1
            msg = jinja2.Template(str(self.test_values[0]["tests"][0]["info"]))
            if not self.post:
                self.post = ["null"] * 12
            logger.debug(
                self.PASS_COLOR
                + msg.render(
                    device=self.device,
                    pre=self.pre,
                    post=self.post,
                    delta=self.delta_value,
                    section_id=self.section_id,
                )
                + colorama.Style.RESET_ALL
            )

    def print_totals(self):
        """Print command test results for all lines of that command output"""
        logger = logging.getLogger("BaselineCheck")
        if self.summary[(self.test_values[0]["command"])]["FAIL"] == 0:
            if self.summary[(self.test_values[0]["command"])]["PASS"] == 0:
                if self.test_values[0]["ignore-null"]:
                    logger.info("PASS! No output matched\n")
                    self.summary[(self.test_values[0]["command"])]["PASS"] += 1
                else:
                    if self.json:
                        self.json_output[self.device.hostname][self.test_values[0]["command"]].append(
                            "FAIL! No output matched for {self.test_values[0]['command']}"
                        )
                    logger.warning("FAIL! No output matched for %s", self.test_values[0]["command"])
                    logger.info("\n")
                    self.summary[(self.test_values[0]["command"])]["FAIL"] += 1
            else:
                logger.info(
                    "PASS! All %s tests passed!\n",
                    str(self.summary[(self.test_values[0]["command"])]["PASS"]),
                )
        else:
            logger.info(
                "FAIL! %s tests passed, %s tests failed!\n",
                str(self.summary[(self.test_values[0]["command"])]["PASS"]),
                str(self.summary[(self.test_values[0]["command"])]["FAIL"]),
            )

    def config_diff_flat(self):
        """Run diff on before and after FLATTENED config"""
        logger = logging.getLogger("BaselineCheck")
        before_cfg = ""
        after_cfg = ""
        line_count = 0
        try:
            for _file in self.device.config.before_config:
                if self.device.hostname in _file:
                    with open(self.device.config.mop_path + "/" + _file, encoding="utf-8") as f:
                        before_cfg = f.readlines()
            for _file in self.device.config.after_config:
                if self.device.hostname in _file:
                    with open(self.device.config.mop_path + "/" + _file, encoding="utf-8") as f:
                        after_cfg = f.readlines()
        except:
            self.config_diff()
            return
        if not before_cfg or not after_cfg:
            self.config_diff()
            return
        logger.info("******** Command: Flat Config Diff ********")
        self.summary["show configuration"] = {"PASS": 0, "FAIL": 0}
        diff = difflib.unified_diff(before_cfg, after_cfg)
        cfg_diff = "\n".join(diff)
        if cfg_diff and re.search(r"[a-zA-z]", cfg_diff, re.M):
            if self.json:
                self.json_output[self.device.hostname]["show configuration"].append(
                    "FAILED! Configuration changed for " + self.device.hostname
                )
            logger.warning(self.FAIL_COLOR + "FAILED! Configuration changed for " + self.device.hostname)
            cfg_output = ""
            for line in cfg_diff.splitlines():
                line_count += 1
                if "@@" in line:
                    line = "~" * 20
                    if line_count < 100:
                        logger.debug(line)
                if "+++" not in line and "---" not in line and line != "":
                    if line[0] == "+":
                        self.summary["show configuration"]["FAIL"] += 1
                        if line_count < 100:
                            logger.warning(line)
                            cfg_output += f"{line}\n"
                    elif line[0] == "-":
                        self.summary["show configuration"]["FAIL"] += 1
                        if line_count < 100:
                            logger.warning(line)
                            cfg_output += f"{line}\n"
            logger.info("\n")
        else:
            log_msg = f"PASS! No changes in {self.device.hostname} configuration\n"
            logger.info(log_msg)
            self.summary["show configuration"]["PASS"] += 1

    def config_diff(self):
        """Run diff on before and after config"""
        logger = logging.getLogger("BaselineCheck")
        self.summary["show configuration"] = {"PASS": 0, "FAIL": 0}
        cmds = {
            "juniper_junos": "show configuration | display set",
            "cisco_ios": "show run",
            "cisco_xr": "show configuration running-config formal",
            "nokia_sros": "admin display-config",
            "nokia_mdcli": "admin show configuration",
        }
        logger.info("******* Command: %s ********", cmds[self.device.os_type])
        try:
            line_count = 0
            before_cfg = self.device.output["before"][(cmds[self.device.os_type])]
            after_cfg = self.device.output["after"][(cmds[self.device.os_type])]
        except KeyError:
            if self.json:
                self.json_output[self.device.hostname]["show configuration"].append(
                    f"ERROR: {cmds[self.device.os_type]} not found in {self.device.hostname} baseline"
                )
            log_msg = f"ERROR: {cmds[self.device.os_type]} not found in {self.device.hostname} baseline"
            logger.warning(log_msg)
            logger.info("\n")
            return

        diff = difflib.unified_diff(before_cfg, after_cfg)
        cfg_diff = "\n".join(diff)
        if cfg_diff and self.device.os_type == "nokia_sros" and len(cfg_diff.splitlines()) < 50:
            fixed_diff = ""
            for line in cfg_diff.splitlines():
                if (
                    line[:3] not in ["+++", "---", "-# ", "+# ", "@@ "]
                    and line.strip() != "configure"
                    and line.strip()[:1] != "#"
                    and not line.strip().startswith("exit")
                    and re.search(r"[a-zA-Z]", line)
                ):
                    fixed_diff += line + "\n"
            cfg_diff = fixed_diff
        if cfg_diff:
            if self.device.os_type == "nokia_sros":
                fixed_diff = ""
                for line in cfg_diff.splitlines():
                    if (
                        line[:3] not in ["+++", "---", "-# ", "+# ", "@@ "]
                        and line.strip() != "configure"
                        and line.strip()[:1] != "#"
                        and not line.strip().startswith("exit")
                        and re.search(r"[a-zA-Z]", line)
                    ):
                        fixed_diff += line + "\n"
                cfg_diff = fixed_diff
            if self.json:
                self.json_output[self.device.hostname]["show configuration"].append(
                    f"FAILED! Configuration changed for {self.device.hostname}"
                )
            logger.warning("FAILED! Configuration changed for %s (use -c to view)", self.device.hostname)
            cfg_output = ""
            for line in cfg_diff.splitlines():
                line_count += 1
                if "@@" in line:
                    line = "=" * 36
                    if self.json:
                        if line_count < 100:
                            self.json_output[self.device.hostname]["show configuration"].append(line)
                    if line_count < 100:
                        logger.warning(line)
                if (
                    "+++" not in line
                    and "---" not in line
                    and line[:2] not in ["+!", "-!", "+#", "-#"]
                    and line != ""
                ):
                    if line[0] == "+":
                        if self.json:
                            if line_count < 100:
                                self.json_output[self.device.hostname]["show configuration"].append(line)
                        if line_count < 100:
                            logger.warning(line)
                        self.summary["show configuration"]["FAIL"] += 1
                        if line_count < 100:
                            cfg_output += f"{line}\n"
                    elif line[0] == "-":
                        if self.json:
                            if line_count < 100:
                                self.json_output[self.device.hostname]["show configuration"].append(line)
                        if line_count < 100:
                            logger.warning(line)
                        self.summary["show configuration"]["FAIL"] += 1
                        if line_count < 100:
                            cfg_output += f"{line}\n"
            logger.info("\n")
        else:
            log_msg = f"PASS! No changes in {self.device.hostname} configuration\n"
            logger.info(log_msg)
            self.summary["show configuration"]["PASS"] += 1

    def test_ping_output(self):
        """Run ping tests"""
        logger = logging.getLogger("BaselineCheck")
        logger.info("******** Testing ping commands ********")
        self.ping_totals = {"PASS": 0, "FAIL": 0, "SKIP": 0}
        self.summary["ping checks"] = {"PASS": 0, "FAIL": 0}
        for self.ping_test in self.device.output["before"].keys():
            if self.ping_test[:4] == "ping":
                try:
                    self.before_cmd_output = self.device.output["before"][self.ping_test]
                    self.after_cmd_output = self.device.output["after"][self.ping_test]
                except KeyError:
                    self.ping_totals["SKIP"] += 1
                    continue
                self.execute_ping_check()

        if self.ping_totals["FAIL"] == 0:
            logger.info(
                "PASS! %s ping checks passed! (%s skipped) \n",
                str(self.ping_totals["PASS"]),
                str(self.ping_totals["SKIP"]),
            )
            self.summary["ping checks"]["PASS"] = self.ping_totals["PASS"]
        else:
            logger.info(
                "FAIL! %s tests passed, %s tests failed!\n",
                str(self.ping_totals["PASS"]),
                str(self.ping_totals["FAIL"]),
            )
            self.summary["ping checks"]["FAIL"] = self.ping_totals["FAIL"]

    def execute_ping_check(self):
        """Test ping commands - no testfile needed"""
        logger = logging.getLogger("BaselineCheck")
        ping_vars = {
            "juniper_junos": {"iterword": "packets", "match_index": 6},
            "nokia_sros": {"iterword": "packets", "match_index": 6},
            "nokia_mdcli": {"iterword": "packets", "match_index": 6},
            "cisco_ios": {"iterword": "Success", "match_index": 3},
            "cisco_xr": {"iterword": "Success", "match_index": 3},
        }
        iterword = ping_vars[self.device.os_type]["iterword"]
        match_index = ping_vars[self.device.os_type]["match_index"]
        # Look for the results line in the BEFORE
        found_match = False
        line, after_line = "", ""
        for line in self.before_cmd_output:
            if iterword in line:
                line = line.split()
                found_match = True
                break
        if not found_match:
            self.ping_totals["SKIP"] += 1
            return
        # Look for the results line in the AFTER
        found_match = False
        for after_line in self.after_cmd_output:
            if iterword in after_line:
                after_line = after_line.split()
                found_match = True
                break
        if not found_match:
            if self.json:
                self.json_output[self.device.hostname]["PingChecks"].append(
                    "FAILED! " + self.ping_test + " not found in the after baseline"
                )
            log_msg = "FAILED! " + self.ping_test + " not found in the after baseline"
            logger.warning(log_msg)
            self.ping_totals["FAIL"] += 1
            return
        # Standardize output across platforms
        if self.device.os_type == "juniper_junos" or self.device.os_type == "nokia_sros":
            success_rate = str(100 - int(line[match_index].replace("%", "").split(".")[0]))
            success_rate_after = str(100 - int(after_line[match_index].replace("%", "").split(".")[0]))
        else:
            success_rate = str(line[match_index])
            success_rate_after = str(after_line[match_index])
        # Compare BEFORE and AFTER packet loss results
        if line[match_index] == after_line[match_index]:
            logger.debug(
                self.PASS_COLOR
                + "PASSED! "
                + self.ping_test
                + " "
                + success_rate
                + "% success before and after"
                + colorama.Style.RESET_ALL
            )
            self.ping_totals["PASS"] += 1
        else:
            if self.json:
                self.json_output[self.device.hostname]["PingChecks"].append(
                    "FAILED! "
                    + self.ping_test
                    + " pre="
                    + success_rate
                    + "% post="
                    + success_rate_after
                    + "% success"
                )
            logger.warning(
                self.FAIL_COLOR
                + "FAILED! "
                + self.ping_test
                + " pre="
                + success_rate
                + "% post="
                + success_rate_after
                + "% success"
                + colorama.Style.RESET_ALL
            )
            self.ping_totals["FAIL"] += 1

    def print_summary(self):
        """Print test results summary"""
        logger = logging.getLogger("BaselineCheck")
        passed, failed, config = 0, 0, 0
        config = self.summary["show configuration"]["FAIL"]
        failed_list = []
        for command in self.summary:
            if self.summary[command]["PASS"] > 0:
                passed += 1
            if self.summary[command]["FAIL"] > 0:
                failed += 1
                failed_list.append(command)
        logger.warning("-" * 64)
        error_msg = (
            self.device.hostname
            + " totals:  "
            + "  PASSED: "
            + str(passed)
            + "  FAILED: "
            + str(failed)
            + "  CONFIG: "
            + str(config)
        )
        logger.error(error_msg)
        logger.info("-" * 64)
        for test in failed_list:
            fail_cnt = self.summary[test]["FAIL"]
            msg = "  Failed - " + str(fail_cnt) + " lines - " + str(test)
            logger.info(msg)
        unset_color = colorama.Fore.RESET + "\n"
        logger.info(unset_color)
