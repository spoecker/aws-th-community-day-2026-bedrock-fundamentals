"""Shared launcher for demo1.py ... demo5.py: fix the Region and flags a stage run needs, then run
the experiment script in-process (so the [Enter] pauses and the saved measurements are unchanged)."""
import os
import runpy
import sys


def run(script: str, args: list[str], region: str) -> None:
    """The launcher fixes the calling Region (the runner's shell exports its own, which must not win);
    `--region <name>` on the launcher overrides it for experiments elsewhere."""
    args = list(args)
    if "--region" in args:
        i = args.index("--region"); region = args[i + 1]; del args[i:i + 2]
    os.environ["AWS_REGION"] = region
    os.environ.pop("AWS_DEFAULT_REGION", None)
    sys.argv = [script] + args
    runpy.run_path(script, run_name="__main__")
