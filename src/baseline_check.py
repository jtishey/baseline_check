#!/usr/bin/env python3

"""
This is a script to parse and compare info from before and after
making changes to network devices in a managable fashion.
USAGE: baseline_check -m <MOP_NUM>
(The term "MOP" is used here to represent a change ID or work order number)
johntishey@gmail.com.com - 2017
"""

import os
import re
import sys
import json
import yaml
import logging
import argparse
import colorama

from utils.baseline_utils import get_os
from utils.baseline_utils import nokia_classis_or_mdcli
from utils.baseline_utils import normalize_config_paths
from utils import the_extractorator
from utils import the_differentiator
from utils import the_recyclanator


def arguments():
    """Parse entered CLI arguments with argparse"""
    # fmt: off
    p = argparse.ArgumentParser(
        description="Parse and compare before/after baseline files.",
        formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=25),
        epilog=".",
    )
    r = p.add_argument_group("REQUIRED OPTIONS", "")
    c = p.add_argument_group("CONFIGURATION OPTIONS", "")
    o = p.add_argument_group("OUTPUT OPTIONS", "")
    r.add_argument("-m", "--mop", help="Specify a MOP number / Change ID to parse", required=True)
    # Config Options
    c.add_argument("-a", "--after", help='Keyword to identify "After" files', metavar="POST")
    c.add_argument("-b", "--before", help='Keyword to identify "Before" files', metavar="PRE")
    c.add_argument("-d", "--dev", help="Run baseline checks on a specific device only", metavar="DEV",)
    c.add_argument("-f", "--file", help="Specify a different config file (default=config.yml)")
    c.add_argument("-p", "--path", help="Explicit folder path where the baselines are located", metavar="PATH",)
    c.add_argument("-o", "--override", action="count", default=0, help="Ignore previous log files and force new check",)
    # Output Options:
    o.add_argument("-l", "--log", action="count", default=0, help="Display no output, only log to file",)
    o.add_argument("-c", "--config", action="count", default=0, help="Display configuration diff only",)
    o.add_argument("-j", "--json", action="count", default=0, help="Display a JSON-format quiet output",)
    o.add_argument("-n", "--no_color", action="count", default=0, help="Do not display colors on pass/failed tests",)
    o.add_argument("-q", "--quiet", action="count", default=0, help="Display quiet output - Only shows failed tests",)
    o.add_argument("-r", "--routes", action="count", default=0, help="Display removed routes only")
    o.add_argument("-s", "--summary", action="count", default=0, help="Display summary output only")
    o.add_argument("-v", "--verbose", action="count", default=0, help="Display verbose output")
    args = vars(p.parse_args())
    tag1, tag2, stest, verbose, explicit_path = "", "", [], 20, ""
    override, no_color = False, False
    cfg = os.path.dirname(os.path.realpath(__file__)) + "/configs/config.yml"
    mop = args["mop"]
    if args["before"]:
        tag1 = args["before"]
    if args["after"]:
        tag2 = args["after"]
    if args["verbose"]:  # VERBOSITY LEVELS:
        verbose = 10     # 10 = DEBUG    / VERBOSE
    #   default = 20     # 20 = INFO     / DEFAULT
    if args["quiet"]:    # 30 = WARN     / QUIET
        verbose = 30     # 40 = ERROR    / SUMMARY
    if args["summary"]:  # 50 = CRITICAL / unused
        verbose = 40     #########################
    # CUSTOM VALUES:     # 60 = LOG ONLY
    if args["config"]:   # 61 = CONFIG ONLY
        verbose = 61     # 62 = ROUTES ONLY
    if args["log"]:      # 63 = JSON QUIET
        verbose = 60
    if args["routes"]:
        verbose = 62
    if args["json"]:
        verbose = 63
    if args["dev"]:
        for device in args["dev"].split(","):
            stest.append(device)
    if args["file"]:
        cfg = args["file"]
    if args["override"]:
        override = True
    if args["path"]:
        explicit_path = args["path"]
    if args["no_color"]:
        no_color = True
    # fmt: on
    return mop, tag1, tag2, stest, cfg, explicit_path, override, verbose, no_color


class Config(object):
    """Variables used by all devices"""

    def __init__(self, mop_number, **kwargs):
        """Init variables"""
        if not mop_number:
            (
                self.mop_number,
                self.before_kw,
                self.after_kw,
                self.stest,
                cfg_file,
                self.exp_path,
                self.override,
                self.verbose,
                self.no_color,
            ) = arguments()
        else:
            if kwargs.get("config"):
                cfg_file = kwargs.get("config")
            else:
                cfg_file = os.path.dirname(os.path.realpath(__file__)) + "/config.yml"
            self.before_kw = kwargs.get("before_kw")
            self.after_kw = kwargs.get("after_kw")
            self.mop_number = mop_number
            (
                self.stest,
                self.verbose,
                self.exp_path,
            ) = (
                [],
                63,
                "",
            )
            self.override, self.no_color = True, True
        if not os.path.exists(cfg_file):
            if os.path.exists(os.path.dirname(os.path.realpath(__file__)) + "/" + cfg_file):
                cfg_file = os.path.dirname(os.path.realpath(__file__)) + "/" + cfg_file
            else:
                print("ERROR: Unable to open config file")
                exit(1)
        with open(cfg_file, encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self.cfg = normalize_config_paths(self.cfg)
        self.logger = logging.getLogger("BaselineCheck")
        self.mop_path = ""
        self.before_files = []
        self.after_files = []
        self.after_config, self.before_config = [], []
        self.after_routes, self.before_routes = [], []
        self.routes_kw = ".next-hop-routes."
        self.vpn_routes_kw = ".vpn-routes."
        self.PASS_COLOR = ""
        self.FAIL_COLOR = ""

    def folder_search(self):
        """Method to recursivly seach for a folder name"""
        if self.exp_path == "":
            self.exp_path = self.cfg["mop_path"]
        os.chdir(self.exp_path)
        found_list = []
        for root, dirnames, _filenames in os.walk("."):
            for directory in dirnames:
                if str(directory) == str(self.mop_number):
                    found_list.append(os.path.abspath(root + "/" + directory))
        if len(found_list) == 1:
            self.mop_path = found_list[0]
            if self.verbose != 63:
                print("\nFound " + self.mop_path)
        elif len(found_list) > 1:
            # if log file only or json, just use the newest folder
            # if self.verbose in [60, 63]:
            best_fldr = found_list[0]
            newest = os.path.getctime(best_fldr)
            for fldr in found_list:
                if os.path.getctime(fldr) > newest:
                    newest = os.path.getctime(fldr)
                    best_fldr = fldr
            self.mop_path = best_fldr
            # Removed the option to pick when multiple baselines are found
            # Now just picks the newest one - better for automated processes.
            # else:
            #    print("\nFound " + str(len(found_list)) + " baselines for MOP " +
            #          self.mop_number + ":")
            #    print("-" * 36)
            #    for i, mop_folder in enumerate(found_list):
            #        print(str(i + 1) + ': ' + mop_folder)
            #    selection = input("\nSelect a folder to test: ")
            #    print("\n")
            #    try:
            #        selection = int(selection)
            #        self.mop_path = found_list[selection - 1]
            #    except:
            #        print("ERROR: Please enter the number of the selection only\n")
            #        exit(1)
        else:
            print("ERROR: MOP number not found!")
            exit(1)
        if os.path.exists(self.mop_path + "/BaselineParser.log") or os.path.exists(
            self.mop_path + "/BaselineCheck.log"
        ):
            if self.override is False and self.verbose != 10 and self.verbose != 61:
                the_recyclanator.Run(self)

    def file_search(self):
        """Creates 2 sorted lists - before & after filenames"""
        file_list = os.listdir(self.mop_path)
        for _file in file_list:
            f_part = _file.split("_")
            if len(f_part) > 3:
                before_keywords = self.cfg["before_keywords"]
                after_keywords = self.cfg["after_keywords"]
                if "diff" not in _file and "nmap" not in _file:
                    try:
                        # Look for default before keywords if needed:
                        if self.before_kw == "":
                            for word in before_keywords:
                                if str(f_part[-2]).lower() == word.lower():
                                    self.before_kw = word
                                    continue
                        # Look for default after keywords if needed:
                        if self.after_kw == "":
                            for word in after_keywords:
                                if str(f_part[-2]).lower() == word.lower():
                                    self.after_kw = word
                                    continue
                        # Gather flattened config file names
                        if "Flattened" in _file:
                            if str(f_part[-2]).lower() == str(self.after_kw).lower():
                                self.after_config.append(str(_file))
                            if str(f_part[-2]).lower() == str(self.before_kw).lower():
                                self.before_config.append(str(_file))
                        elif "routes" in _file:
                            # Gather routes file names:
                            if self.routes_kw in _file or ".routes." in _file:
                                if str(f_part[-2]).lower() == str(self.after_kw).lower():
                                    self.after_routes.append(str(_file))
                                if str(f_part[-2]).lower() == str(self.before_kw).lower():
                                    self.before_routes.append(str(_file))
                            # Gather VPN routes file names:
                            elif self.vpn_routes_kw in _file:
                                if str(f_part[-2]).lower() == str(self.after_kw).lower():
                                    self.after_vpn_routes.append(str(_file))
                                if str(f_part[-2]).lower() == str(self.before_kw).lower():
                                    self.before_vpn_routes.append(str(_file))
                            else:
                                continue
                        # Skip "prefix" files:
                        elif "prefixes" in _file:
                            continue
                        else:
                            # Gather pre/post baseline files
                            if str(f_part[-2]).lower() == str(self.before_kw).lower():
                                self.before_files.append(_file)
                            elif str(f_part[-2]).lower() == str(self.after_kw).lower():
                                self.after_files.append(_file)
                    except:
                        continue
        if len(self.before_files) == 0 or len(self.after_files) == 0:
            if self.before_kw != "pre":
                self.before_kw = "pre"
                self.after_kw = "post"
                self.file_search()
            else:
                print("\nBefore/After files not found\n")
                exit(1)
        else:
            self.before_files.sort()
            self.after_files.sort()
            os.chdir(self.cfg["project_path"])

    def setup_logging(self):
        """Set logging format, level, and handlers"""
        # Define Colors (or lack of)
        if self.no_color:
            self.PASS_COLOR = ""
            self.FAIL_COLOR = ""
        else:
            self.PASS_COLOR = colorama.Fore.GREEN
            self.FAIL_COLOR = colorama.Fore.LIGHTRED_EX
        log_file = self.mop_path + "/" + "BaselineCheck.log"
        if os.path.exists(log_file) and self.verbose != 61:
            os.remove(log_file)
        msg_only_formatter = logging.Formatter("%(message)s")
        if self.verbose != 63:
            self.logger.setLevel(logging.DEBUG)
        # File Handler:
        # Log to file, unless -c / --config is specified (61) (because not all tests are run)
        if self.verbose != 61:
            fh = logging.FileHandler(log_file)
            fh.setFormatter(msg_only_formatter)
            fh.setLevel(logging.INFO)
            self.logger.addHandler(fh)
        # Stream Handler:  - set level based on verbose settings (-c -q -l -s -v)
        # Log to stdout unless -l / --log is specified for log file only mode
        if self.verbose not in [60, 62, 63]:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(msg_only_formatter)
            if self.verbose < 50:
                sh.setLevel(self.verbose)
            else:
                # set debug for config output mode
                sh.setLevel(10)
            self.logger.addHandler(sh)

    def get_routes(self):
        """create a dict of before/after routes
        x = {dev: {prefix: nexthop, ...}}"""
        # TODO: Add route capture to baseline_run for this.
        self.after_routes_list = {}
        self.before_routes_list = {}
        for _file in self.after_routes:
            dev_name = _file.replace(self.routes_kw + self.after_kw + ".log", "")
            dev_name = dev_name.replace(".routes." + self.after_kw + ".log", "")
            dev_name = dev_name.replace(str(self.mop_number) + ".", "")
            if dev_name != self.mop_number and not re.search("^[a-z]{4}[0-9]{2}\-[a-z]{2}$", dev_name):
                self.after_routes_list[dev_name] = {}
                with open(self.mop_path + "/" + _file, encoding="utf-8") as f:
                    routes = f.readlines()
                for line in routes:
                    if "ERROR:" in line:
                        self.before_routes_list[dev_name]["ERROR"] = "ERROR"
                        break
                    elif re.match("^[0-9]", line):
                        self.after_routes_list[dev_name][line.split()[0]] = line.split()[-1]
        self.before_routes_list = {}
        for _file in self.before_routes:
            dev_name = _file.replace(self.routes_kw + self.before_kw + ".log", "")
            dev_name = dev_name.replace(".routes." + self.before_kw + ".log", "")
            dev_name = dev_name.replace(str(self.mop_number) + ".", "")
            if dev_name != self.mop_number and not re.search(r"^[a-z]{4}[0-9]{2}\-[a-z]{2}$", dev_name):
                self.before_routes_list[dev_name] = {}
                with open(self.mop_path + "/" + _file, encoding="utf-8") as f:
                    routes = f.readlines()
                for line in routes:
                    if "ERROR:" in line:
                        self.before_routes_list[dev_name]["ERROR"] = "ERROR"
                        break
                    elif re.match("^[0-9]", line):
                        self.before_routes_list[dev_name][line.split()[0]] = line.split()[-1]


class Device(object):
    """Create Device Object"""

    def __init__(self, config=None):
        """Init device variables and inherit from Config"""
        self.config = config
        self.hostname = ""
        self.os_type = ""
        self.results = ""
        self.files = []
        self.output = []
        self.skip_device = False

    def assign_values(self, host, i):
        """Assign device-specific values"""
        self.hostname = host
        self.skip_device = False
        # self.files includes the before AND after filename for the device
        try:
            self.files.append(os.path.abspath(self.config.mop_path + "/" + self.config.before_files[i]))
            for item in self.config.after_files:
                if self.hostname in item:
                    self.files.append(os.path.abspath(self.config.mop_path + "/" + item))
        except IndexError:
            pass
        if len(self.files) < 2:
            self.output = "ERROR: Missing baseline for " + host + "\n"
            self.skip_device = True
        # Get OS Type - Using special "nokia_mdcli" os_type because Nokia MDCLI
        # commands and output can vary from Classic mode.  Still uses 'nokia_sros' in netmiko
        self.os_type = get_os(host, self.config.cfg)
        if self.os_type == "nokia_sros":
            with open(self.files[0], "r", errors="replace", encoding="utf-8") as f:
                baseline_text = f.readlines()
            self.os_type = nokia_classis_or_mdcli(self.hostname, baseline_text)


def _execute(ran_by, **kwargs):
    """
    Starts execution of the baseline_check
    """
    # Init config, find folder/MOP files and setup logger
    config_file = kwargs.get("config")
    before_kw = kwargs.get("before_kw")
    after_kw = kwargs.get("after_kw")
    CONFIG = Config(ran_by, config=config_file, before_kw=before_kw, after_kw=after_kw)
    CONFIG.folder_search()
    CONFIG.file_search()
    CONFIG.get_routes()
    CONFIG.setup_logging()
    logger = CONFIG.logger
    json_output = {}

    # One device at a time - copy the config, parse, and compare
    for i, file_name in enumerate(CONFIG.before_files):
        hostname = ""
        file_name = file_name.split("_")
        del file_name[0]
        del file_name[-2:]
        for word in file_name:
            if len(hostname) > 0:
                hostname = hostname + "." + word
            else:
                hostname = word
        if CONFIG.stest and hostname not in CONFIG.stest:
            continue
        device = Device(config=CONFIG)
        device.assign_values(hostname, i)
        if device.skip_device is True:
            continue
        # Get commands and output from baseline files
        logger.warning("\nRunning %s:", device.hostname)
        logger.warning("-" * 64)

        ###########################################################################
        #  TEMP PATCH: Strip last domain names before continuing
        if device.hostname[-4:] == ".net" or device.hostname[-4:] == ".com":
            hostname = device.hostname.split(".")
            del hostname[-1]
            del hostname[-1]
            device.hostname = ".".join(hostname)
        ###########################################################################

        device.output = the_extractorator.run(device)

        # Execute the diff on the command output
        if isinstance(device.output, dict):
            output = the_differentiator.Run(device)
            if CONFIG.verbose == 63:
                json_output[device.hostname] = output.json_output[device.hostname]
        else:
            logger.error(CONFIG.PASS_COLOR + device.output + colorama.Style.RESET_ALL)
    logger.debug(colorama.Style.RESET_ALL)
    # Update log file permissions
    try:
        if os.path.exists(CONFIG.mop_path + "/" + "BaselineCheck.log"):
            os.chmod(CONFIG.mop_path + "/" + "BaselineCheck.log", 0o777)
    except:
        pass
    print("")
    return json_output


def module_run(mop, **kwargs):
    """
    Run the baseline_check script as a module from another python script
    Returns a json structured object with the failed tests.
    MOP Keywords must be either pre/post or before/after.
    :param mop: MOP identifier to check.
    """
    config = kwargs.get("config")
    before_kw = kwargs.get("before_kw")
    after_kw = kwargs.get("after_kw")
    json_output = _execute(mop, config=config, before_kw=before_kw, after_kw=after_kw)
    return json_output


if __name__ == "__main__":
    run = _execute("")
    if run:
        print(json.dumps(run, indent=4, sort_keys=True))
