#!/usr/bin/env python3
"""Experiment 1 - Tokens are not words.

The same sentence in four languages, sent to several models. The number that matters is
usage.inputTokens in the Converse response: it is what CloudWatch meters and what you pay for.

    python3 01_tokens.py                 # from AWS_REGION (default ap-southeast-7)
    AWS_REGION=ap-southeast-1 python3 01_tokens.py

Cost: a few dozen Converse calls with maxTokens=1. Well under $0.01.
"""
import argparse
import json
import os
from textwrap import indent

import boto3
from botocore.exceptions import ClientError

from common import region, save, table, today, pause, title, recap

TEXTS = {
    "hi": "Hi",
    "en": "Hello, I would like to change my flight to next Tuesday morning. Is there a fee for that?",
    "de": "Hallo, ich möchte meinen Flug auf nächsten Dienstagmorgen umbuchen. Fällt dafür eine Gebühr an?",
    "zh": "您好，我想把航班改到下周二早上。这样改需要手续费吗？",
    "th": "สวัสดีครับ ผมต้องการเปลี่ยนเที่ยวบินเป็นเช้าวันอังคารหน้า มีค่าธรรมเนียมสำหรับการเปลี่ยนไหมครับ",
}

# Inference profiles invocable from Singapore. From Thailand, Claude Sonnet 5 was refused in my account on every
# try between 2026-09-21 and 2026-10-01 ("not available for this account"); the cause is not established.
MODELS = {
    "Claude Haiku 4.5": "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "Claude Sonnet 5": "global.anthropic.claude-sonnet-5",
    "Nova Lite": "apac.amazon.nova-lite-v1:0",
    "Nova 2 Lite": "global.amazon.nova-2-lite-v1:0",
}


def input_tokens(rt, model_id: str, text: str):
    """One Converse call, one token, read usage.inputTokens."""
    try:
        r = rt.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": text}]}],
            inferenceConfig={"maxTokens": 1},
        )
        return r["usage"]["inputTokens"]
    except ClientError as e:
        return f"ERR {e.response['Error']['Code']}"


def show_one_call(rt, model_id: str, text: str):
    """The raw evidence, once: the exact Converse request and the usage block the response carries.
    usage.inputTokens is what the bill is made of; everything else in the talk is derived from it."""
    req = {"modelId": model_id, "messages": [{"role": "user", "content": [{"text": text}]}],
           "inferenceConfig": {"maxTokens": 1}}
    print("The call (bedrock-runtime Converse):")
    q = lambda v: json.dumps(v, ensure_ascii=False)          # the same JSON, laid out to fit a stage-size terminal
    print("\n".join(["  {",
                     f'    "modelId": {q(model_id)},',
                     '    "messages": [ { "role": "user", "content": [ { "text":',
                     f"      {q(text)}",
                     "    } ] } ],",
                     f'    "inferenceConfig": {q(req["inferenceConfig"])}',
                     "  }"]))
    r = rt.converse(**req)
    print("\nThe response's usage block - the metered numbers:")
    print(indent(json.dumps(r["usage"], indent=2), "  "))
    print()


def count_tokens_us_east_1(text: str):
    """CountTokens is free and Claude-only. Measured 2026-09: it rejects inference profiles from
    ap-southeast-1/7 and only answers for the base model ID in us-east-1, so we ask there."""
    rt = boto3.client("bedrock-runtime", region_name="us-east-1")
    try:
        r = rt.count_tokens(
            modelId="anthropic.claude-haiku-4-5-20251001-v1:0",
            input={"converse": {"messages": [{"role": "user", "content": [{"text": text}]}]}},
        )
        return r["inputTokens"]
    except ClientError as e:
        return f"ERR {e.response['Error']['Code']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pause", action="store_true", help="run straight through (recordings, replay)")
    ap.add_argument("--show-api", action="store_true", help="print the first Converse request and the usage block it returns")
    a = ap.parse_args()
    if a.no_pause:
        os.environ["DEMO_PAUSE"] = "0"
    reg = region()
    rt = boto3.client("bedrock-runtime", region_name=reg)
    title(f"Experiment 1 - tokens are not words   (region {reg}, {today()})")
    if a.show_api:
        show_one_call(rt, MODELS["Claude Haiku 4.5"], TEXTS["en"])
    pause("The same sentence in Thai and in English, on Claude Haiku 4.5: 2x the tokens? 3x? 5x?")

    results = {}
    rows = []
    for name, mid in MODELS.items():
        counts = {lang: input_tokens(rt, mid, text) for lang, text in TEXTS.items()}
        results[name] = {"model_id": mid, "input_tokens": counts}
        ok = all(isinstance(counts[k], int) for k in ("hi", "th", "en"))
        # Per-call overhead is the "Hi" row; subtract it so the ratio compares the text, not the framing.
        net = (counts["th"] - counts["hi"]) / (counts["en"] - counts["hi"]) if ok else None
        gross = counts["th"] / counts["en"] if ok else None
        rows.append([name, counts["hi"], counts["en"], counts["de"], counts["zh"], counts["th"],
                     f"{gross:.1f}x" if gross else "n/a", f"{net:.1f}x" if net else "n/a"])
    print(table(rows, ["model", '"Hi"', "EN", "DE", "ZH", "TH", "TH/EN", "net of Hi"]))
    print('  TH/EN = the Thai sentence vs the English one; "net of Hi" removes the fixed per-call framing.')
    print("\ncharacters: " + ", ".join(f"{k}={len(v)}" for k, v in TEXTS.items()))
    h, s5, n2 = (results.get(k, {}).get("input_tokens", {}) for k in ("Claude Haiku 4.5", "Claude Sonnet 5", "Nova 2 Lite"))
    recap(f"EN vs TH tokens:  Haiku 4.5 {h.get('en')} vs {h.get('th')}   Sonnet 5 {s5.get('en')} vs {s5.get('th')}"
          f"   Nova 2 Lite \"Hi\" = {n2.get('hi')}")

    pause("CountTokens is free and answers before you send anything. Will it match what Converse billed?")
    print("\nCountTokens (free, Claude only, base model ID in us-east-1) vs what Converse billed for Haiku 4.5:")
    ct_rows = []
    ct = {}
    for lang in ("hi", "en", "th"):
        c = count_tokens_us_east_1(TEXTS[lang])
        billed = results["Claude Haiku 4.5"]["input_tokens"][lang]
        ct[lang] = {"count_tokens": c, "converse_usage": billed}
        delta = c - billed if isinstance(c, int) and isinstance(billed, int) else "n/a"
        ct_rows.append([lang, c, billed, delta])
    print(table(ct_rows, ["text", "CountTokens", "Converse usage", "delta"]))

    print("""
What this means:
  * Thai costs 2.4x to 3.6x English depending on the tokenizer, and 1.2x on Nova 2 Lite.
    The current Claude tokenizer (Sonnet 5 / Opus 5) charges ~30% more tokens for the same
    English sentence than Haiku 4.5 and about the same for Thai, so the ratio moved.
    Measure with YOUR model and YOUR users' language; do not assume a ratio.
  * The "Hi" row is per-call overhead you pay on every request. Compare the models.
  * usage.inputTokens is the metered number. CountTokens is a free estimate, and for Haiku 4.5
    it reports a constant offset above what is billed.""")
    path = save("01-tokens", {"region": reg, "texts": TEXTS, "chars": {k: len(v) for k, v in TEXTS.items()},
                              "models": results, "count_tokens_us_east_1_haiku45": ct})
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
