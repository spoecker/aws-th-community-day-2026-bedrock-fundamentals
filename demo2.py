#!/usr/bin/env python3
"""Demo 2 - conversation history is application state. Runs the stateless half, pauses, then the
DynamoDB-memory half. Same as: python3 02_memory.py --stateless ; python3 02_memory.py --with-memory
(Bangkok). Pass --no-pause to run straight through."""
from _launch import run
from common import pause
import sys
extra = sys.argv[1:]
run("02_memory.py", ["--stateless"] + extra, "ap-southeast-7")
pause("Now the same two turns, with the history kept in DynamoDB. What changes in the answer?")
run("02_memory.py", ["--with-memory"] + extra, "ap-southeast-7")
