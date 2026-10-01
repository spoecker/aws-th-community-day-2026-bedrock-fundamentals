#!/usr/bin/env python3
"""Demo 1 - tokens are not words. Same as: AWS_REGION=ap-southeast-1 python3 01_tokens.py
(Singapore, because Claude Sonnet 5 is refused from Thailand in this account). Pass --no-pause to run straight through."""
from _launch import run
import sys
run("01_tokens.py", ["--show-api"] + sys.argv[1:], "ap-southeast-1")
