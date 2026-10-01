#!/usr/bin/env python3
"""Demo 5 - where did it actually run. On stage: python3 demo5.py  (= 05_where_did_it_run.py --lookup --hours 3,
reads CloudTrail for the calls fired earlier). Before the talk, 15+ minutes ahead: python3 demo5.py --fire
(= 05_where_did_it_run.py, makes the calls so CloudTrail has them by the time you look)."""
from _launch import run
import sys
args = sys.argv[1:]
if "--fire" in args:
    args.remove("--fire")
    run("05_where_did_it_run.py", args, "ap-southeast-7")
else:
    run("05_where_did_it_run.py", ["--lookup", "--hours", "3", "--show-api"] + args, "ap-southeast-7")
