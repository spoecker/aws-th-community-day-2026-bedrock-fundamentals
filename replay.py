#!/usr/bin/env python3
"""Replay the latest saved measurement for an experiment, without calling AWS.

For a stage with no network: every script writes measurements/<name>-<date>.json; this prints the
most recent one for the experiment you name in the same shape the live run prints, so what is on
screen is still a real, dated measurement from this account rather than a slide.

    python3 replay.py 1            # tokens
    python3 replay.py 2            # memory: the stateless half, then the DynamoDB half
    python3 replay.py 3            # context budget
    python3 replay.py 4            # concurrency storm on Claude Haiku 4.5  (4 nova2 = the open question)
    python3 replay.py 5            # routing
    python3 replay.py 3 --json     # the raw file instead of the summary
    python3 replay.py list         # what is available
"""
import json
import re
import sys

from common import MEASUREMENTS, table

PREFIX = {"1": ["01-tokens"], "2": ["02-memory-stateless", "02-memory-with-memory"], "3": ["03-context"],
          "4": ["04-quota-haiku"], "5": ["05-routing"], "q": ["quotas-by-region"]}


def latest(prefix: str):
    """Newest file named <prefix>-YYYY-MM-DD.json. Files with an account tag after the date
    (…-2026-09-14-second-account.json) are other accounts' runs and are only used when asked for by name."""
    files = [f for f in MEASUREMENTS.glob(f"{prefix}-*.json") if re.fullmatch(re.escape(prefix) + r"-\d{4}-\d{2}-\d{2}\.json", f.name)]
    if not files:
        files = list(MEASUREMENTS.glob(f"{prefix}*.json"))
    return sorted(files, key=lambda f: re.findall(r"\d{4}-\d{2}-\d{2}", f.name)[-1:] + [f.name])[-1] if files else None


def show_tokens(d):
    rows = []
    for name, m in d["models"].items():
        c = m["input_tokens"]
        ok = all(isinstance(c.get(k), int) for k in ("hi", "en", "th"))
        rows.append([name, c.get("hi"), c.get("en"), c.get("de"), c.get("zh"), c.get("th"),
                     f"{c['th'] / c['en']:.1f}x" if ok else "n/a",
                     f"{(c['th'] - c['hi']) / (c['en'] - c['hi']):.1f}x" if ok else "n/a"])
    print(table(rows, ["model", '"Hi"', "EN", "DE", "ZH", "TH", "TH/EN", "net of Hi"]))
    ct = d.get("count_tokens_us_east_1_haiku45") or {}
    if ct:
        print("\nCountTokens vs what Converse billed for Haiku 4.5:")
        print(table([[k, v["count_tokens"], v["converse_usage"],
                      v["count_tokens"] - v["converse_usage"] if isinstance(v["count_tokens"], int) else "n/a"]
                     for k, v in ct.items()], ["text", "CountTokens", "Converse usage", "delta"]))


def show_memory(d):
    for t in d.get("turns", d if isinstance(d, list) else []):
        if "user_id" in t:
            print(f"  user '{t['user_id']}' asks the same question ({t.get('messages_sent')} message sent)\n  model: {t['model']}\n")
            continue
        hist = f" ({t['from_history']} from DynamoDB)" if "from_history" in t else ""
        print(f"  request: {t['messages_sent']} message(s){hist}, {t['input_tokens']} input tokens")
        print(f"  user : {t['user']}\n  model: {t['model']}\n")


def show_context(d):
    names = {"A0_short_prompt": "A0 short prompt, full history", "A_full_history": "A  8K policy prompt, full history",
             "B_cached_prefix": "B  same, cachePoint after the policy", "C_window_4": "C  same, 4-turn window"}
    cost = d.get("cost_usd", {})
    rows = []
    for key, label in names.items():
        r = d[key]
        rows.append([label, f"{r[0]['inputTokens']:,} -> {r[-1]['inputTokens']:,}", f"{r[0]['cacheWrite']:,}",
                     f"{r[1]['cacheRead']:,}", f"${cost.get(key.split('_')[0], 0):.3f}"])
    print(table(rows, ["run", "input tokens, turn 1 -> 10", "cacheWrite turn 1", "cacheRead turn 2", "input-side cost"]))
    print("  input-side cost = input tokens + cache writes + cache reads at list price; output tokens are not in it.")


def show_quota(d):
    print(f"Model {d['model']}   TPM {d['quota_tpm']:,.0f}   RPM {d['quota_rpm']:,.0f}")
    print(f"Prediction: about {d['predicted_fit']} calls fit in flight at the model maximum.\n")
    rows = []
    for key, label in (("A_max", "A  model maximum"), ("B_right_sized", "B  right-sized"), ("C_control", "C  control")):
        p = d.get(key)
        if p:
            rows.append([label, p.get("workers"), f"{p.get('max_tokens'):,}", p.get("ok"),
                         ", ".join(f"{n} x {k}" for k, n in (p.get("errors") or {}).items()) or "none"])
    print(table(rows, ["phase", "concurrent calls", "maxTokens", "ok", "errors"]))


def show_routing(d):
    rows = [[c["profile"], c["served_in"], c["calls"]] for c in sorted(d.get("cloudtrail", []), key=lambda c: (c["profile"], c["served_in"]))]
    print(f"CloudTrail in {d['region']}, Converse events -> additionalEventData.inferenceRegion:")
    print(table(rows, ["profile called", "served in", "calls"]) if rows else "  (no events in the saved window)")
    print(f"\nModels in {d['region']}: {len(d.get('in_region_on_demand', []))} invocable in-Region on demand, "
          f"{len(d.get('profile_only', []))} via inference profile only")


SHOW = {"01-tokens": show_tokens, "02-memory-stateless": show_memory, "02-memory-with-memory": show_memory,
        "03-context": show_context, "04-quota-haiku": show_quota, "04-quota-nova2": show_quota, "05-routing": show_routing}


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    raw = "--json" in sys.argv
    if not args or args[0] == "list":
        for f in sorted(MEASUREMENTS.glob("*.json")):
            print(" ", f.name)
        return
    prefixes = PREFIX.get(args[0], [args[0]])
    if len(args) > 1:
        prefixes = [re.sub(r"-haiku$", "", prefixes[0]) + "-" + args[1]]
    for prefix in prefixes:
        f = latest(prefix)
        if not f:
            sys.exit(f"no measurement found for {prefix!r}; run the experiment first")
        d = json.loads(f.read_text())
        date = re.findall(r"\d{4}-\d{2}-\d{2}", f.name)[-1]
        print(f"REPLAY of {f.name} - measured {date}, called from {d.get('region', '?')} (saved measurement, no AWS call made)\n")
        if raw or prefix not in SHOW:
            print(json.dumps(d, indent=2, ensure_ascii=False))
        else:
            SHOW[prefix](d)
        print()


if __name__ == "__main__":
    main()
