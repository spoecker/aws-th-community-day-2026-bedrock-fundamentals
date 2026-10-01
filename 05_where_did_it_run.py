#!/usr/bin/env python3
"""Experiment 5 - Cross-Region inference decides where your request runs.

Part A: call Converse through several inference profiles from this Region.
Part B: read CloudTrail in this Region and print additionalEventData.inferenceRegion for every
        Converse event of the last hours. CloudTrail lags ~15 minutes, so run part A well before
        you need part B on stage (or run this script twice).
Part C: which models are in-Region here at all (spoiler for ap-southeast-7: none).

    python3 05_where_did_it_run.py            # A + B + C from AWS_REGION (default ap-southeast-7)
    python3 05_where_did_it_run.py --lookup   # B + C only (no new calls)
    python3 05_where_did_it_run.py --hours 6  # how far back to read CloudTrail

Cost: a handful of Converse calls with maxTokens=5, CloudTrail LookupEvents is free. Under $0.01.
"""
import argparse
import collections
import datetime
import json
from textwrap import indent

import os
import boto3
from botocore.exceptions import ClientError

from common import region, save, table, today, pause, title, recap

PROFILES = [
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    "global.anthropic.claude-sonnet-4-6",
    "global.amazon.nova-2-lite-v1:0",
    "apac.amazon.nova-lite-v1:0",
]


def call(rt, profile: str, n: int = 2):
    out = []
    for _ in range(n):
        try:
            r = rt.converse(modelId=profile,
                            messages=[{"role": "user", "content": [{"text": "Reply with one word: hello"}]}],
                            inferenceConfig={"maxTokens": 5})
            out.append(r["usage"]["inputTokens"])
        except ClientError as e:
            out.append(f"ERR {e.response['Error']['Code']}")
    return out


def lookup(reg: str, hours: float, show_event: bool = False):
    ct = boto3.client("cloudtrail", region_name=reg)
    shown = False
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=hours)
    seen = collections.Counter()
    for page in ct.get_paginator("lookup_events").paginate(
            LookupAttributes=[{"AttributeKey": "EventName", "AttributeValue": "Converse"}],
            StartTime=start, EndTime=end):
        for ev in page["Events"]:
            d = json.loads(ev["CloudTrailEvent"])
            mid = (d.get("requestParameters") or {}).get("modelId")
            dest = (d.get("additionalEventData") or {}).get("inferenceRegion")
            if mid:
                seen[(mid, dest or "(not recorded)")] += 1
            if show_event and mid and dest and not shown:
                shown = True
                slim = {"eventTime": d.get("eventTime"), "eventName": d.get("eventName"), "awsRegion": d.get("awsRegion"),
                        "requestParameters": {"modelId": mid},
                        "additionalEventData": {"inferenceRegion": dest},
                        # who called: the principal without the account ID, so this is safe on a projector
                        "userIdentity": {"principal": (d.get("userIdentity") or {}).get("arn", "").split(":")[-1]}}
                print("One raw CloudTrail event, trimmed to the fields that matter:")
                print(indent(json.dumps(slim, indent=2), "  "))
                print("  awsRegion is where you called; additionalEventData.inferenceRegion is where it was served.\n")
                recap(f"one event: called in {d.get('awsRegion')}, served in {dest}")
    return seen


def availability(reg: str):
    b = boto3.client("bedrock", region_name=reg)
    fms = b.list_foundation_models()["modelSummaries"]
    in_region = [m["modelId"] for m in fms if "ON_DEMAND" in m.get("inferenceTypesSupported", [])]
    profile_only = [m["modelId"] for m in fms if m.get("inferenceTypesSupported") == ["INFERENCE_PROFILE"]]
    return in_region, profile_only


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookup", action="store_true", help="skip new calls, only read CloudTrail")
    ap.add_argument("--hours", type=float, default=3)
    ap.add_argument("--no-pause", action="store_true", help="run straight through (recordings, replay)")
    ap.add_argument("--show-api", action="store_true", help="print one raw CloudTrail event before the table")
    a = ap.parse_args()
    if a.no_pause:
        os.environ["DEMO_PAUSE"] = "0"
    reg = region()
    title(f"Experiment 5 - where did it run   (calling from {reg}, {today()})")

    calls = {}
    if not a.lookup:
        rt = boto3.client("bedrock-runtime", region_name=reg)
        for p in PROFILES:
            calls[p] = call(rt, p)
            print(f"  called {p}: inputTokens {calls[p]}")
        print("\n  (CloudTrail needs ~15 min to show these; the lookup below covers earlier calls too)\n")

    pause(f"These calls left {reg}. Where were they actually served?")
    seen = lookup(reg, a.hours, show_event=a.show_api)
    if a.show_api and any(dest != "(not recorded)" for _, dest in seen):
        pause("That was one call. Now every call of the last hours: where did each profile land?")
    rows = [[mid, dest, n] for (mid, dest), n in sorted(seen.items())]
    print(f"CloudTrail in {reg}, Converse events of the last {a.hours:g} h, by additionalEventData.inferenceRegion:")
    print(table(rows, ["profile called", "served in", "calls"]) if rows else "  (no events yet)")

    in_region, profile_only = availability(reg)
    print(f"\nModels in {reg}: {len(in_region)} invocable in-Region on demand, {len(profile_only)} via inference profile only")
    if in_region:
        print("  in-Region on demand: " + ", ".join(in_region))
    print("""
What this means:
  * A global profile may be served in any commercial Region where the model exists; a geographic
    profile stays inside its geography. AWS picks the destination; you find out in CloudTrail.
  * You are billed and logged in the Region you CALLED, with no routing surcharge.
  * If this Region shows zero in-Region models, every call you make here is cross-Region by
    construction. Know that before your compliance team asks.""")
    path = save("05-routing", {"region": reg, "calls": calls, "hours": a.hours,
                               "cloudtrail": [{"profile": m, "served_in": d, "calls": n} for (m, d), n in seen.items()],
                               "in_region_on_demand": in_region, "profile_only": profile_only})
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
