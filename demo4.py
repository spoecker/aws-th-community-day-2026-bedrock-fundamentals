#!/usr/bin/env python3
"""Demo 4 - output-token limits consume quota. Same as:
AWS_REGION=ap-southeast-1 python3 04_max_tokens_quota.py --model haiku --pause 20"""
from _launch import run
import sys
run("04_max_tokens_quota.py", ["--model", "haiku", "--pause", "20"] + sys.argv[1:], "ap-southeast-1")
