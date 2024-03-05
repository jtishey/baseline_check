#!/usr/bin/env python3

"""
baseline_compare module to reuse existing log files to save resources
johntishey@gmail.com - 2017
"""


class Run(object):
    """Method is called when an existing log file is found and override is false"""

    def __init__(self, CONFIG):
        """Gets CONFIG object from baseline_check and output based on that"""
        colors = ["\x1b[91m", "\x1b[91m", "\x1b[32m", "\x1b[37m"]
        # All we really have to do is open the log file and figure out how to print it
        try:
            with open(CONFIG.mop_path + "/BaselineCheck.log", encoding="utf-8") as f:
                prev_run = f.readlines()
        except:
            try:
                with open(CONFIG.mop_path + "/BaselineParser.log", encoding="utf-8") as f:
                    prev_run = f.readlines()
            except:
                print("ERROR: Could not open log file")
                exit(1)

        print("Using log file from previous check, use -o to override and run new checks\n")

        output = ""
        sum_flag, cfg_flag, dev_flag, routes_flag = False, False, False, False
        for line in prev_run:
            # sum_flag means it is currently parsing the Totals/summary section
            #    at the end of each device.
            # sum_flag gets turned on by line with 'totals' in it
            #   and off by line starting with 'Running' indicating the next device.
            # dev_flag means the device should be parsed.
            # dev_flag gets turned on by line starting with 'Running'
            #  if the second word in that line is a device name
            #  specified by the -d flag, and turned off if it is not in -d
            #  always gets turned on if -d is not used
            # cfg_flag means it is currently parsing the config diff.
            # cfg_flag gets turned on by a line with "Command: <show run>"
            #   and turned off by the ping checks section.
            for color in colors:
                line = line.replace(color, "")
            if line.startswith("-----") and sum_flag and CONFIG.verbose > 20:
                continue
            if line.startswith("Running"):
                sum_flag = False
                dev_flag = bool(line.split()[1][:-1] in CONFIG.stest)
            elif "Core BGP Routes Check" in line:
                cfg_flag = False
                sum_flag = False
                routes_flag = True
            elif (
                "Command: show run" in line
                or "Command: show config" in line
                or "Command: admin display-config" in line
            ):
                cfg_flag = True
                routes_flag = False
            elif "Testing ping commands" in line:
                cfg_flag = False
                routes_flag = False
            elif "totals:" in line:
                sum_flag = True
                routes_flag = False

            # set dev_flag to true if not set so it outputs all devs
            if len(CONFIG.stest) == 0:
                dev_flag = True

            if dev_flag:
                # VERBOSE = 10
                if CONFIG.verbose == 10:
                    output = output + line
                # NORMAL = 20
                elif CONFIG.verbose == 20:
                    if line.startswith("PASSED") is False:
                        output = output + line
                # QUIET = 30
                elif CONFIG.verbose == 30:
                    if line[:5] not in ["PASSE", "PASS!", "FAIL!", "  Fai"]:
                        if cfg_flag is False and line[:9] != "******** " and line != "\n":
                            output = output + line
                        else:
                            if line[:6] in ["FAILED", "NOTICE"]:
                                output = output + line
                # CCONFIG = 61
                elif CONFIG.verbose == 61:
                    if cfg_flag is True:
                        output = output + line
                # ROUTES-ONLY = 62
                elif CONFIG.verbose == 62:
                    if line.startswith("Running"):
                        txt = "\n" + line.split()[-1][:-1] + " Core BGP Routes Check\n"
                        output = output + txt
                    elif routes_flag:
                        if "REMOVED" in line:
                            output = output + line
                        elif line.startswith("PASS!"):
                            output = output + line
                # SUMMARY = 40
                elif CONFIG.verbose == 40:
                    if sum_flag is True:
                        #    if line[:5] != '-----' and line != '\n':
                        if " totals:  " in line:
                            output = output + line
        while "\n\n\n" in output:
            output = output.replace("\n\n\n", "\n\n")
        output = output.replace("\n\nFAIL", "\nFAIL")
        output = output.replace("\n\nERROR", "\nERROR")
        output = output.replace("Running ", "\nRunning ")
        print(output)
        exit()
