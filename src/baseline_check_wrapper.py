#!/usr/bin/env python3

""" Simple wrapper for baseline_check to output into a basic HTML table
johntishey@gmail.com - 2010
"""


from prettytable import PrettyTable
import baseline_check
from sys import argv
import json

mop = argv[1]
try:
    config = ""
    for a in argv:
        if a.endswith("yml"):
            config = str(a)
except:
    config = ""
try:
    before_kw, after_kw = "", ""
    before_kw = argv[3]
    after_kw = argv[4]
except:
    before_kw, after_kw = "", ""

if not config and not after_kw and len(argv) == 4:
    try:
        before_kw, after_kw = "", ""
        before_kw = argv[2]
        after_kw = argv[3]
        if "yml" in before_kw or "yml" in after_kw:
            before_kw, after_kw = "", ""
    except:
        before_kw, after_kw = "", ""

if config or before_kw or after_kw:
    j = baseline_check.module_run(mop, config=config, before_kw=before_kw, after_kw=after_kw)
else:
    j = baseline_check.module_run(mop)
j = json.loads(j)

for device in j.keys():
    ptable = PrettyTable()
    for command, results in j[device].items():
        if not results:
            # ptable.add_row([command, "PASS"])
            pass
        else:
            res_str = ""
            for result in results:
                res_str += f"{result}\n"
            ptable.add_row([f"{command}", res_str])
    output = str(ptable.get_html_string(header=False, title=f"<h3>{device}</h3>"))
    while "<table>" in output:
        output = output.replace("<table>", '<table border="1">')
    print(output)
    print("<br><br>")
