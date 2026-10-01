"""Shared helpers for the five experiments. Plain boto3, no framework."""
import datetime
import json
import os
import pathlib
import sys
import textwrap
import time

MEASUREMENTS = pathlib.Path(__file__).parent / "measurements"


def region() -> str:
    """The Region the experiments call Bedrock from. Override with AWS_REGION."""
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-7"


def today() -> str:
    return datetime.date.today().isoformat()


def save(name: str, data: dict) -> pathlib.Path:
    """Write a dated JSON file so every number in the talk is reproducible.
    Set MEASUREMENT_TAG (e.g. the account alias) to keep runs from different accounts apart."""
    MEASUREMENTS.mkdir(exist_ok=True)
    tag = os.environ.get("MEASUREMENT_TAG")
    path = MEASUREMENTS / f"{name}-{today()}{'-' + tag if tag else ''}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return path


def pauses_enabled() -> bool:
    """Pause between phases when a person is at the keyboard. DEMO_PAUSE=0 (or --no-pause where the
    script has flags) runs straight through, for recordings, CI and replay."""
    return sys.stdin.isatty() and os.environ.get("DEMO_PAUSE", "1") != "0"


_TITLE: str | None = None     # the demo's title line, printed again at the top of every cleared screen
_RECAP: list[str] = []        # one-line results so far, printed again after each clear so comparisons survive


def clear_enabled() -> bool:
    """Clear the screen at every [Enter], so each part starts at the top and fits a stage-size font.
    Only with a person at the keyboard and a terminal on stdout; DEMO_CLEAR=0 turns it off."""
    return pauses_enabled() and sys.stdout.isatty() and os.environ.get("DEMO_CLEAR", "1") != "0"


def title(text: str) -> None:
    """Print the demo's title line and remember it for the top of every cleared screen."""
    global _TITLE
    if text == _TITLE:          # second half of a two-part demo: the title is already on screen
        return
    _TITLE = text
    print(text + "\n")


def recap(line: str, replace_last: bool = False) -> None:
    """Remember a one-line result. It is shown again under the title after the next clear, so the
    room can still compare this part with the next one once the screen has been wiped.
    replace_last swaps the newest line (a result that is restated once its cause has been revealed)."""
    if replace_last and _RECAP:
        _RECAP[-1] = line
    else:
        _RECAP.append(line)


def wrapped(prefix: str, text: str, width: int = 96) -> str:
    """A long model answer as an indented block, so it wraps under itself instead of at the screen edge."""
    return textwrap.fill(prefix + " ".join(text.split()), width=width, subsequent_indent=" " * len(prefix))


def short(text: str, n: int = 62) -> str:
    """One line of a model answer, for a recap."""
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rstrip() + "…"


def _top(question: str | None) -> None:
    print("\033[2J\033[H", end="")                  # clear the screen, cursor to the top left
    if _TITLE:
        print(_TITLE)
    for i, line in enumerate(_RECAP):
        print(("  so far:  " if i == 0 else "           ") + line)
    if question:
        print(f"\n  ? {question}")
    print(flush=True)


def pause(question: str | None = None, min_wait: float = 0) -> None:
    """Stop before the next numbers print, so the presenter can ask the room first.
    question: printed as the prompt to put to the audience. min_wait: seconds that must pass anyway
    (quota refill), shown as a countdown after Enter (or instead of it when pauses are off).
    After Enter the screen is cleared and the title, the results so far and the question are printed
    again at the top (see clear_enabled)."""
    t0 = time.time()
    if question:
        print(f"\n  ? {question}")
    if pauses_enabled():
        try:
            input("  [Enter to continue] " if question else "\n  [Enter to continue] ")
        except EOFError:
            pass
        if clear_enabled():
            _top(question)
    left = min_wait - (time.time() - t0)
    while left > 0:
        print(f"\r  waiting {left:4.0f} s for the quota to refill ", end="", flush=True)
        time.sleep(min(1, left)); left -= 1
    if min_wait:
        print("\r" + " " * 48 + "\r", end="")


def table(rows: list[list], header: list[str]) -> str:
    """Tiny fixed-width table so the terminal is readable on a projector."""
    cols = [header] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cols) for i in range(len(header))]
    line = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths))
    return "\n".join([line(header), line(["-" * w for w in widths])] + [line(r) for r in cols[1:]])
