#!/usr/bin/env python3
"""Experiment 4 - Output-token limits consume quota before the model writes a word.

Bedrock deducts (input tokens + maxTokens) from your tokens-per-minute (TPM) quota at the START of
every request and gives the unused part back when the request finishes. So what your TPM quota
really limits is the number of requests IN FLIGHT at once, multiplied by (input + maxTokens):

    in-flight requests x (input + maxTokens)  must stay under  TPM

A sequential loop never shows this (each call returns its reservation before the next starts, so a
loop only ever hits the requests-per-minute quota). Concurrency shows it immediately.

Phase 0: read the live TPM and RPM quotas and state the load in plain tokens (about 1% of the quota).
Phase A: N concurrent calls, maxTokens = model maximum  -> ThrottlingException for the overflow.
         Only then the reason: what each call reserved, and how many fit. (Ask the room first.)
Phase B: the same N concurrent calls, maxTokens right-sized for the answer -> all succeed.
Phase C: N/6 concurrent calls at the big maxTokens (control) -> all succeed.
Phase D: the fix for the leftovers - exponential backoff with full jitter.

    AWS_REGION=ap-southeast-1 python3 04_max_tokens_quota.py          # recommended: Singapore, Claude Haiku 4.5
    python3 04_max_tokens_quota.py --model sonnet --workers 120        # haiku | nova2 | sonnet

Measured 2026-09-14 (account-specific, re-check yours):
  * Claude Haiku 4.5 from Singapore behaves exactly as the doc says: 117 in flight at 64K -> 74 ok / 43 x 429,
    the same 117 at 600 -> all ok.
  * From ap-southeast-7 the global Claude profiles had a 50 RPM quota (vs 10,000 in Singapore), so the
    script cannot put enough Claude calls in flight there to reach TPM; it warns and you will see RPM 429s.
  * Amazon Nova 2 Lite did NOT throttle at 160 (Bangkok) or 250 (Singapore) in-flight calls at 64K, i.e.
    at twice its TPM quota. The reservation rule is proven for Claude; for Nova 2 Lite it was not observed.

Cost: 3 batches of ~120 calls, ~400 output tokens each -> under $0.50 on Haiku 4.5.
Side effect: this profile's TPM quota in the Region is exhausted for a few seconds.
"""
import argparse
import concurrent.futures as cf
import random
import statistics
import time

import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from common import region, save, table, today, pause, title, recap

PROMPT = "Write a 300-word story about a delayed flight from Bangkok to Chiang Mai."
RIGHT_SIZED = 600  # enough for ~300 words (~400 tokens) with headroom
EXPECTED_OUT = 400  # what a 300-word story comes to, for the "does it fit?" arithmetic before the run

# profile id, the two phrases Service Quotas uses in the quota name, max output tokens (model card)
MODELS = {
    "haiku": ("global.anthropic.claude-haiku-4-5-20251001-v1:0", "Global cross-region", "Haiku 4.5", 64000),
    "nova2": ("global.amazon.nova-2-lite-v1:0", "Global cross-region", "Nova 2 Lite", 64000),
    "sonnet": ("global.anthropic.claude-sonnet-4-6", "Global cross-region", "Sonnet 4.6", 64000),
}


def quotas(reg: str, family: str, model_words: str):
    """The account's live TPM and RPM quotas for this profile, from Service Quotas."""
    sq = boto3.client("service-quotas", region_name=reg)
    tpm = rpm = None
    for page in sq.get_paginator("list_service_quotas").paginate(ServiceCode="bedrock"):
        for q in page["Quotas"]:
            n = q["QuotaName"]
            if family in n and model_words in n and "per minute" in n and q.get("Value"):
                if "tokens" in n:
                    tpm = q["Value"]
                elif "requests" in n:
                    rpm = q["Value"]
    return tpm, rpm


def one_call(rt, model: str, max_tokens: int, delay: float = 0.0):
    time.sleep(delay)  # stagger the start a little so 100+ threads do not hit the local DNS resolver at once
    t = time.time()
    try:
        r = rt.converse(modelId=model, messages=[{"role": "user", "content": [{"text": PROMPT}]}],
                        inferenceConfig={"maxTokens": max_tokens})
        u = r["usage"]
        return {"ok": True, "in": u["inputTokens"], "out": u["outputTokens"], "s": time.time() - t}
    except ClientError as e:
        return {"ok": False, "err": e.response["Error"]["Code"], "s": time.time() - t}
    except Exception as e:  # local problem (DNS, sockets), not a Bedrock answer - count it separately
        return {"ok": False, "err": "LOCAL:" + type(e).__name__, "s": time.time() - t}


def batch(rt, model: str, max_tokens: int, workers: int):
    """Fire `workers` calls at once and summarise."""
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(lambda i: one_call(rt, model, max_tokens, delay=i * 0.015), range(workers)))
    ok = [r for r in res if r["ok"]]
    errs = {}
    for r in res:
        if not r["ok"]:
            errs[r["err"]] = errs.get(r["err"], 0) + 1
    return {"workers": workers, "max_tokens": max_tokens, "ok": len(ok), "errors": errs,
            "reserved_in_flight": workers * (20 + max_tokens),
            "mean_out": round(statistics.mean(r["out"] for r in ok), 0) if ok else 0,
            "mean_call_s": round(statistics.mean(r["s"] for r in ok), 1) if ok else 0,
            "wall_s": round(time.time() - t0, 1)}


def show(label: str, b: dict, reveal: bool = True):
    """reveal=False leaves maxTokens and the reservation out: phase A prints its result before its cause."""
    print(f"  {label}")
    mt = f", maxTokens={b['max_tokens']:,}" if reveal else ""
    print(f"    {b['workers']} concurrent calls{mt}  ->  ok={b['ok']}  errors={b['errors'] or 'none'}")
    res = f"reserved in flight ~{b['reserved_in_flight']:,} tokens; " if reveal else ""
    print(f"    {res}mean output {b['mean_out']:.0f} tokens; mean call {b['mean_call_s']}s; batch took {b['wall_s']}s")


def retry_with_backoff(rt, model: str, base: float = 1.0, max_attempts: int = 8):
    """Full jitter: sleep = random(0, base * 2**attempt)."""
    for attempt in range(max_attempts):
        r = one_call(rt, model, RIGHT_SIZED)
        if r["ok"]:
            print(f"    attempt {attempt + 1}: OK ({r['out']} output tokens)")
            return attempt + 1
        wait = random.uniform(0, base * 2 ** attempt)
        print(f"    attempt {attempt + 1}: {r['err']}, sleeping {wait:.1f}s")
        time.sleep(wait)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=MODELS, default="haiku")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--pause", type=int, default=70, help="seconds between phases so the quota refills")
    ap.add_argument("--no-pause", action="store_true", help="no [Enter] prompts (recordings, replay); the refill wait stays")
    a = ap.parse_args()
    if a.no_pause:
        os.environ["DEMO_PAUSE"] = "0"
    model, family, words, max_out = MODELS[a.model]
    reg = region()
    rt = boto3.client("bedrock-runtime", region_name=reg,
                      config=Config(max_pool_connections=300, retries={"max_attempts": 0}))
    title(f"Experiment 4 - how much quota does a request use?   (region {reg}, {today()})")

    tpm, rpm = quotas(reg, family, words)
    print(f"Model {model}")
    if tpm and rpm:
        fit = int(tpm // (20 + max_out))
        print(f"Live quotas in {reg}: TPM = {tpm:,.0f}   RPM = {rpm:,.0f}")
        workers = a.workers or min(int(fit * 1.5), int(rpm * 0.8))
        if workers <= fit:
            print(f"  NOTE: RPM ({rpm:.0f}) caps the concurrency this script can safely use at {workers}; "
                  f"the throttle in phase A may not appear from this Region.")
    else:
        fit = None
        workers = a.workers or 120
        print("Live quotas: not found in Service Quotas")
    # The room sees the load in plain tokens first. maxTokens is not mentioned until phase A has throttled.
    per_call = 20 + EXPECTED_OUT
    load = round(workers * per_call, -3)
    print(f"\nThe load: {workers} requests at the same moment, each asking for a 300-word story.")
    print(f"  per request: about 20 tokens in, about {EXPECTED_OUT} tokens out")
    print(f"  in total:    {workers} x {per_call} = about {load:,} tokens" + (f", against {tpm:,.0f} tokens per minute" if tpm else ""))
    pause(f"{workers} requests, about {load:,} tokens" + (f", a quota of {tpm:,.0f} per minute" if tpm else "")
          + f". Do all {workers} get an answer?")

    print(f"Phase A - {workers} requests at once")
    A = batch(rt, model, max_out, workers)
    t_a = time.time()
    show("result:", A, reveal=False)
    thr = lambda b: sum(b["errors"].values())
    recap(f"A  {workers} requests at once, ~{A['mean_out']:.0f} tokens each:  {A['ok']} ok, {thr(A)} throttled")
    share = f"about {workers * per_call / tpm:.0%} of the quota" if tpm else "this load"
    pause(f"{thr(A)} of {workers} throttled, at {share}. Why?" if thr(A)
          else f"All {workers} answered this time. What did each request hold while it ran?")

    print(f"Why: every one of those requests carried maxTokens = {max_out:,}, the model maximum")
    print("     (it is also what Converse uses when you leave maxTokens out).")
    print("At request start Bedrock reserves input + maxTokens from the TPM quota and gives the unused")
    print("part back when the call ends. So what counts is what is IN FLIGHT at the same moment:")
    print(f"     {workers} x (20 + {max_out:,}) = {A['reserved_in_flight']:,} tokens reserved" + (f"   vs   {tpm:,.0f} TPM" if tpm else ""))
    if fit:
        print(f"     {tpm:,.0f} / {20 + max_out:,} = about {fit} requests fit. {A['ok']} did.")
    recap(f"A  {workers} at once x maxTokens {max_out:,}:  {A['ok']} ok, {thr(A)} throttled" + (f"   (about {fit} fit)" if fit else ""),
          replace_last=True)
    pause(f"Same {workers} requests, one number changed: maxTokens={RIGHT_SIZED}. How many now?",
          min_wait=max(0, a.pause - (time.time() - t_a)))

    print(f"\nPhase B - the same {workers} concurrent calls at maxTokens={RIGHT_SIZED} (right-sized for the answer)")
    B = batch(rt, model, RIGHT_SIZED, workers)
    show("result:", B)
    recap(f"B  {workers} at once x maxTokens {RIGHT_SIZED}:  {B['ok']} ok, {thr(B)} throttled")
    pause("Control: a sixth of the load, back at the model maximum.", min_wait=a.pause)

    print(f"\nPhase C - control: {max(workers // 6, 5)} concurrent calls at maxTokens={max_out:,}")
    C = batch(rt, model, max_out, max(workers // 6, 5))
    show("result:", C)
    recap(f"C  {C['workers']} at once x maxTokens {max_out:,}:  {C['ok']} ok, {thr(C)} throttled   (control)")

    print("\nPhase D - the fix for the overflow: exponential backoff with full jitter")
    D = None
    if A["errors"]:
        time.sleep(5)
        batch(rt, model, max_out, workers)  # re-create the overflow ...
        D = retry_with_backoff(rt, model)   # ... and recover one call from it

    pause()
    print("The arithmetic (from the Bedrock token-burndown user guide):")
    print(table([["maxTokens 32,000", "3,000 + 1,000 + 32,000 = 36,000", "9,000"],
                 ["maxTokens 1,250", "3,000 + 1,000 + 1,250 = 5,250", "9,000"]],
                ["same request", "deducted at request start", "final after reconciliation"]))
    print(f"""
What this means:
  * TPM limits what is IN FLIGHT: concurrent requests x (input + maxTokens). Same traffic, same
    answers: {A['ok']}/{workers} succeeded with maxTokens={max_out:,} and {B['ok']}/{workers} with maxTokens={RIGHT_SIZED}.
  * Set maxTokens to what the answer needs. Omitted, it is the model maximum.
  * 429 ThrottlingException is YOUR quota (TPM or RPM, and RPM differs per Region). 503 and 529
    are capacity on the service side. Retry 429 with exponential backoff and jitter.""")
    path = save(f"04-quota-{a.model}", {"region": reg, "model": model, "quota_tpm": tpm, "quota_rpm": rpm,
                                       "predicted_fit": fit, "workers": workers, "prompt": PROMPT,
                                       "A_max": A, "B_right_sized": B, "C_control": C, "D_retry_attempts": D})
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
