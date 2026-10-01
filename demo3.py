#!/usr/bin/env python3
"""Demo 3 - the context window is a finite budget. Same as: AWS_REGION=ap-southeast-1 python3 03_context_budget.py
Do not run it within 5 minutes of the live run: the prompt cache is per account and turn 1 would show a cache read."""
from _launch import run
import sys
run("03_context_budget.py", sys.argv[1:], "ap-southeast-1")
