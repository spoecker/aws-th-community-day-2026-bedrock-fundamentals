#!/usr/bin/env python3
"""Side experiment - the same account, the same model, different quotas per Region.

Lists the tokens-per-minute and requests-per-minute quotas Service Quotas reports for the
cross-Region inference profiles, and works out which one you would hit first with maxTokens at the
model maximum. Run it for two Regions and compare.

    python3 quotas_by_region.py ap-southeast-7 ap-southeast-1

Cost: $0 (Service Quotas API only).
"""
import collections
import re
import sys

import boto3

from common import save, table, today

MAX_OUT = {"Haiku 4.5": 64000, "Sonnet 4.6": 64000, "Sonnet 4.5 V1": 64000, "Opus 4.7": 128000,
           "Opus 4.6": 128000, "Nova 2 Lite": 64000, "Nova Lite": 5000, "Nova Pro": 5000, "Nova Micro": 5000}
PATTERN = re.compile(r"^(Global cross-region|Cross-region) model inference (tokens|requests) per minute for (.+)$")


def survey(reg: str):
    sq = boto3.client("service-quotas", region_name=reg)
    q = collections.defaultdict(dict)
    for page in sq.get_paginator("list_service_quotas").paginate(ServiceCode="bedrock"):
        for x in page["Quotas"]:
            m = PATTERN.match(x["QuotaName"])
            if m and x.get("Value"):
                fam, kind, model = m.groups()
                q[(fam, model)][kind] = x["Value"]
    rows = []
    for (fam, model), v in sorted(q.items()):
        if "tokens" not in v or "requests" not in v:
            continue
        mo = next((mx for k, mx in MAX_OUT.items() if k in model and "1M" not in model), None)
        if not mo:
            continue
        calls = v["tokens"] / (15 + mo)
        rows.append({"family": fam, "model": model, "tpm": int(v["tokens"]), "rpm": int(v["requests"]),
                     "max_out": mo, "calls_to_tpm": round(calls, 1), "binds_first": "TPM" if calls < v["requests"] else "RPM"})
    return rows


def main():
    regions = sys.argv[1:] or ["ap-southeast-7", "ap-southeast-1"]
    out = {}
    for reg in regions:
        rows = survey(reg)
        out[reg] = rows
        print(f"\n{reg}  ({today()})")
        print(table([[r["family"], r["model"], f"{r['tpm']:,}", f"{r['rpm']:,}", f"{r['max_out']:,}", r["calls_to_tpm"], r["binds_first"]] for r in rows],
                    ["family", "model", "TPM", "RPM", "maxOut", "calls to TPM", "binds first"]))
    print("""
What this means:
  * Quotas are per model AND per Region, and a newer Region can ship with much lower request quotas.
  * "calls to TPM" = TPM / (input + maxTokens). If that is below RPM, the token reservation throttles
    you first; if not, you hit the request quota before maxTokens ever matters.
  * Read your own numbers before you size a workload. All of these are adjustable via Service Quotas.""")
    print(f"\nsaved {save('quotas-by-region', out)}")


if __name__ == "__main__":
    main()
