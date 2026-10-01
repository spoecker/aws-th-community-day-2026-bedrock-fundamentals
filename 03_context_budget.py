#!/usr/bin/env python3
"""Experiment 3 - The context window is a finite budget.

Everything you send must fit in the context window, and everything you send is paid for - every
turn, again. Four runs of the same ten-turn support conversation:

  A0. short system prompt, full history replayed   -> usage.inputTokens climbs every turn (the curve)
  A.  long system prompt (a policy document),      -> the same curve on top of a big fixed cost
      full history replayed
  B.  same as A with a cachePoint after the        -> cacheWriteInputTokens once, then cacheReadInputTokens
      byte-identical system prompt                    (the prefix must be >= 4,096 tokens on Haiku 4.5)
  C.  same as A, sliding window of the last 4 turns -> inputTokens stays flat

    python3 03_context_budget.py             # from AWS_REGION (default ap-southeast-7)

Cost: 40 Converse calls on Haiku 4.5, three runs with a ~8K-token system prompt: about $0.20 at list price.
"""
import argparse
import os
import boto3

from common import region, save, table, today, pause, title, recap

MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

# List prices per 1M tokens, Claude Haiku 4.5 global profile, read from the Bedrock pricing page for
# Asia Pacific (Singapore) on 2026-09-14. Re-read before quoting.
PRICE_IN, PRICE_CACHE_WRITE_5M, PRICE_CACHE_READ = 1.00, 1.25, 0.10

TURNS = [
    "Hi, my name is Alex. I am booked on the 07:10 flight to Chiang Mai next Tuesday.",
    "Can I move it to the afternoon flight on the same day?",
    "Is there a change fee for that?",
    "I have one checked bag already paid for. Does it move with the booking?",
    "What about my seat 14C, will I keep it?",
    "My colleague Bob is on the same booking. Does the change apply to him too?",
    "Can he stay on the morning flight while I take the afternoon one?",
    "How do I pay the fee?",
    "Will I get a new e-ticket by email?",
    "Please summarise everything we agreed.",
]


def policy_document() -> str:
    """A long, deterministic airline policy text so the cached prefix clears the 4,096-token minimum.
    Deterministic on purpose: caching needs a byte-identical prefix on every call."""
    sections = []
    topics = ["ticket changes", "change fees", "checked baggage", "seat selection", "group bookings",
              "split itineraries", "payment methods", "e-ticket delivery", "refunds", "no-show rules",
              "infant travel", "special assistance", "lounge access", "codeshare flights", "weather delays",
              "compensation", "loyalty points", "upgrades", "travel documents", "contact channels"]
    for n, t in enumerate(topics, 1):
        sections.append((
            f"Section {n}: {t.title()}. This section describes the airline's policy on {t}. "
            f"Customers who ask about {t} should be told the standard rule first, then any exception. "
            f"The standard rule for {t} applies to all fares booked directly with the airline, and the "
            f"agent must confirm the booking reference before applying it. Exceptions for {t} exist for "
            f"flexible fares, for members of the loyalty programme at gold tier or above, and for "
            f"changes caused by the airline itself. When a customer's request about {t} cannot be "
            f"resolved by the agent, the case is escalated to the duty manager with a written summary. "
            f"Every answer about {t} must state the fee in Thai baht, the deadline in local time, and the "
            f"channel through which the customer will receive confirmation. Agents must never promise "
            f"outcomes about {t} that depend on another airline or a third party. Records of {t} "
            f"decisions are kept for twelve months. "
        ) * 2)
    return "You are a concise airline support agent. Answer in one or two sentences.\n\n" + "\n".join(sections)


def run(rt, system_blocks, window=None):
    """Run the ten turns; return per-turn usage."""
    history, rows = [], []
    for i, text in enumerate(TURNS, 1):
        history.append({"role": "user", "content": [{"text": text}]})
        sent = history if window is None else history[-window:]
        if sent and sent[0]["role"] != "user":       # a window must start with a user turn
            sent = sent[1:]
        r = rt.converse(modelId=MODEL, system=system_blocks, messages=sent, inferenceConfig={"maxTokens": 120})
        u = r["usage"]
        answer = r["output"]["message"]["content"][0]["text"]
        history.append({"role": "assistant", "content": [{"text": answer}]})
        rows.append({"turn": i, "messages_sent": len(sent), "inputTokens": u["inputTokens"],
                     "cacheWrite": u.get("cacheWriteInputTokens", 0), "cacheRead": u.get("cacheReadInputTokens", 0),
                     "outputTokens": u["outputTokens"]})
    return rows


def cost(rows):
    return sum(r["inputTokens"] * PRICE_IN + r["cacheWrite"] * PRICE_CACHE_WRITE_5M + r["cacheRead"] * PRICE_CACHE_READ
               for r in rows) / 1e6


def summary(tag, rows):
    """One recap line per run, so the four runs can still be compared after the screen is cleared."""
    return f"{tag:<36} input {rows[0]['inputTokens']:>5,} -> {rows[-1]['inputTokens']:>5,} per turn   cost ${cost(rows):.4f}"


def show(label, rows):
    print(f"\n{label}")
    print(table([[r["turn"], r["messages_sent"], r["inputTokens"], r["cacheWrite"], r["cacheRead"], r["outputTokens"]] for r in rows],
                ["turn", "msgs sent", "inputTokens", "cacheWrite", "cacheRead", "output"]))
    total_in = sum(r["inputTokens"] + r["cacheWrite"] + r["cacheRead"] for r in rows)
    print(f"  total input tokens processed: {total_in:,}   input-side cost at list price: ${cost(rows):.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pause", action="store_true", help="run straight through (recordings, replay)")
    if ap.parse_args().no_pause:
        os.environ["DEMO_PAUSE"] = "0"
    reg = region()
    rt = boto3.client("bedrock-runtime", region_name=reg)
    title(f"Experiment 3 - the context window is a finite budget   (region {reg}, {today()})")
    policy = policy_document()
    short_system = [{"text": "You are a concise airline support agent. Answer in one or two sentences."}]
    plain_system = [{"text": policy}]
    cached_system = [{"text": policy}, {"cachePoint": {"type": "default"}}]

    pause("Ten turns, the same short question every turn. Turn 1 costs about 50 input tokens. Turn 10?")
    A0 = run(rt, short_system)
    show("A0. Short system prompt, full history replayed every turn", A0)
    recap(summary("A0 short prompt, full history", A0))
    pause("Now an 8,000-token airline policy goes into the system prompt. What happens to the curve?")
    A = run(rt, plain_system)
    show("A. Long system prompt (the airline policy), full history replayed every turn", A)
    recap(summary("A  8K policy prompt, full history", A))
    pause("Same run with a cachePoint after the policy. Which number changes, and on which turn?")
    B = run(rt, cached_system)
    show("B. Same, with a cachePoint after the system prompt (5-minute TTL)", B)
    recap(summary(f"B  same + cachePoint ({B[0]['cacheWrite'] or B[0]['cacheRead']:,} cached)", B))
    pause("Last: only the latest 4 turns are sent. Does that save more than the cache did?")
    C = run(rt, plain_system, window=4)
    show("C. Sliding window: only the last 4 turns are sent", C)
    recap(summary("C  same as A, last 4 turns only", C))

    pause()
    warm = B[0]["cacheWrite"] == 0 and B[0]["cacheRead"] > 0
    print("\n".join(filter(None, [
        "What this means:",
        f"  * A0: the same short question costs more every turn ({A0[0]['inputTokens']} -> {A0[-1]['inputTokens']} input tokens), because the",
        "    whole conversation is input again. That is the curve every chat app rides.",
        "  * A: put a real system prompt in front and the fixed cost dwarfs the curve:",
        f"    ten turns = {sum(r['inputTokens'] for r in A):,} input tokens.",
        f"  * B: the identical prefix is written to the cache once ({B[0]['cacheWrite']:,} tokens on turn 1) and read",
        "    after that at a tenth of the input price; inputTokens now shows only the non-cached part.",
        "    (cacheWrite is 0 and cacheRead > 0 on turn 1: the prefix was still cached from a run in the" if warm else None,
        "    last 5 minutes. The cache is per account, not per process.)" if warm else None,
        f"    Input-side cost for the ten turns: ${cost(A):.3f} without caching vs ${cost(B):.3f} with.",
        "    If cacheWrite is 0 on turn 1, the prefix was under the model's minimum and was ignored.",
        "  * C: a sliding window flattens the curve but saves little HERE, because the prompt, not the",
        "    history, is the big part. Windowing pays when history dominates; caching pays when the",
        "    static prefix dominates. Both cost you the model's memory of turn 1. Choose on purpose.",
        f"  Prices per 1M (Haiku 4.5 global, Singapore list, 2026-09-14): input ${PRICE_IN:.2f}, cache write ${PRICE_CACHE_WRITE_5M:.2f}, read ${PRICE_CACHE_READ:.2f}.",
    ])))
    path = save("03-context", {"region": reg, "model": MODEL, "policy_chars": len(policy),
                               "A0_short_prompt": A0, "A_full_history": A, "B_cached_prefix": B, "C_window_4": C,
                               "cost_usd": {"A0": cost(A0), "A": cost(A), "B": cost(B), "C": cost(C)}})
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
