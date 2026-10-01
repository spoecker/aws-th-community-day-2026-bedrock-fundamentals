#!/usr/bin/env python3
"""Extra experiment - does Amazon Nova 2 Lite enforce its TPM quota on in-flight INPUT?

Background: 04_max_tokens_quota.py showed Claude Haiku 4.5 throttling exactly as the docs describe
(in-flight x (input + maxTokens) vs TPM), but Nova 2 Lite accepted 250 in-flight calls at
maxTokens=64000, twice its 8M TPM, without a single 429. This run removes maxTokens from the
picture: N concurrent calls each carrying ~45K real input tokens and maxTokens=5, so ~8.5M input
tokens are in flight against an 8M TPM quota.

    AWS_REGION=ap-southeast-1 python3 extra/nova2_input_storm.py --workers 190                    # ~8.5M, ~$3.50
    AWS_REGION=ap-southeast-1 python3 extra/nova2_input_storm.py --workers 190 --input 90000     # ~17M, ~$7

The script records each call's start and end time and reports the true PEAK tokens in flight, because
with short calls and a start stagger the peak can be well below workers x input.
Cost: input tokens at $0.41/1M (Singapore list, 2026-09-14). Not a demo.
"""
import argparse
import concurrent.futures as cf
import pathlib
import statistics
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # the repo root, for common.py
from common import region, save, today

MODEL = "global.amazon.nova-2-lite-v1:0"


def filler(n_paragraphs: int) -> str:
    """Deterministic, non-repetitive-enough text (no cache, and identical across runs)."""
    return "\n".join(
        f"Paragraph {i}: flight {1000 + i} departs gate {i % 40} at {6 + i % 12:02d}:{(i * 7) % 60:02d}, "
        f"connecting via hub {i % 9} with {i % 3} checked bags and seat {i % 30 + 1}{'ABCDEF'[i % 6]}; "
        f"the fare class is {'YBMHKLQ'[i % 7]} and the change fee is {200 + (i * 37) % 900} baht."
        for i in range(n_paragraphs))


def one(rt, text, delay):
    time.sleep(delay)
    t = time.time()
    try:
        r = rt.converse(modelId=MODEL, messages=[{"role": "user", "content": [{"text": text + "\n\nReply with one word: OK"}]}],
                        inferenceConfig={"maxTokens": 5})
        return {"ok": True, "in": r["usage"]["inputTokens"], "t0": t, "t1": time.time(), "s": round(time.time() - t, 1)}
    except ClientError as e:
        return {"ok": False, "err": e.response["Error"]["Code"], "msg": e.response["Error"]["Message"][:80], "t0": t, "t1": time.time(), "s": round(time.time() - t, 1)}
    except Exception as e:
        return {"ok": False, "err": "LOCAL:" + type(e).__name__, "t0": t, "t1": time.time(), "s": round(time.time() - t, 1)}


def peak_in_flight(res, per_call):
    """Sweep start/end events; the max number of overlapping calls x tokens per call."""
    ev = sorted([(r["t0"], 1) for r in res] + [(r["t1"], -1) for r in res])
    cur = peak = 0
    for _, d in ev:
        cur += d
        peak = max(peak, cur)
    return peak, peak * per_call


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=190)
    ap.add_argument("--input", type=int, default=45_000, help="target input tokens per call")
    ap.add_argument("--stagger", type=float, default=0.015, help="seconds between thread starts")
    a = ap.parse_args()
    TARGET_INPUT = a.input
    reg = region()
    rt = boto3.client("bedrock-runtime", region_name=reg, config=Config(max_pool_connections=300, retries={"max_attempts": 0}, read_timeout=120))
    # calibrate: how many paragraphs make ~TARGET_INPUT tokens on this tokenizer
    probe = one(rt, filler(200), 0)
    per_par = probe["in"] / 200
    n_par = int(TARGET_INPUT / per_par)
    text = filler(n_par)
    check = one(rt, text, 0)
    print(f"Nova 2 Lite input storm   (region {reg}, {today()})")
    print(f"calibration: {per_par:.1f} tokens/paragraph -> {n_par} paragraphs = {check['in']:,} input tokens per call")
    reserved = a.workers * (check["in"] + 5)
    print(f"{a.workers} concurrent calls x {check['in']:,} input tokens = {reserved:,} tokens in flight vs TPM quota 8,000,000\n")
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(lambda i: one(rt, text, i * a.stagger), range(a.workers)))
    wall = round(time.time() - t0, 1)
    ok = [r for r in res if r["ok"]]
    errs = {}
    for r in res:
        if not r["ok"]:
            errs[r["err"]] = errs.get(r["err"], 0) + 1
    msgs = {r["msg"] for r in res if not r["ok"] and "msg" in r}
    print(f"ok={len(ok)}  errors={errs or 'none'}  wall={wall}s  mean call={statistics.mean(r['s'] for r in ok) if ok else 0:.1f}s")
    if msgs:
        print("429 texts:", msgs)
    print(f"input tokens actually processed: {sum(r['in'] for r in ok):,}")
    pk, pk_tokens = peak_in_flight(res, check["in"])
    print(f"true peak in flight: {pk} calls x {check['in']:,} = {pk_tokens:,} tokens  (vs TPM 8,000,000)")
    print("\nReading: if this throttled, Nova enforces TPM on in-flight input and only the maxTokens reservation was absent.\n"
          "If it did not, the 8M TPM quota shown in Service Quotas is not what limits this profile.")
    path = save("extra-nova2-input-storm", {"region": reg, "model": MODEL, "workers": a.workers, "input_per_call": check["in"],
                                             "in_flight_nominal": reserved, "peak_in_flight_calls": pk, "peak_in_flight_tokens": pk_tokens,
                                             "ok": len(ok), "errors": errs, "wall_s": wall, "429_texts": sorted(msgs)})
    print(f"saved {path}")


if __name__ == "__main__":
    main()
