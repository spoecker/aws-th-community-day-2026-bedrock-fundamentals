#!/usr/bin/env python3
"""Experiment 2 - Conversation history is application state.

The model API is stateless: Amazon Bedrock does not keep your conversation between calls. If the
second call knows what the first one said, it is because YOUR code sent the first one again.

    python3 02_memory.py --stateless      # two independent calls; the second one is clueless
    python3 02_memory.py --with-memory    # DynamoDB Query -> Converse(history + new) -> PutItem
    python3 02_memory.py --cleanup        # delete the DynamoDB table

The memory version creates an on-demand DynamoDB table (partition key userId, sort key ts, TTL)
on first use. Idle cost is $0; a few writes and reads cost fractions of a cent.
"""
import argparse
import time

import os
import boto3
from botocore.exceptions import ClientError

from common import region, save, today, pause, title, recap, short, wrapped

MODEL = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
TABLE = "bedrock-fundamentals-conversations"
TTL_SECONDS = 24 * 3600

TURNS = [
    "Hi, I am Alex. I am flying to Bangkok for AWS Community Day on 3 October.",
    "What should I pack for the trip?",
]


def converse(rt, messages):
    r = rt.converse(modelId=MODEL,
                    system=[{"text": "You are a concise travel assistant for an airline. Answer in one sentence."}],
                    messages=messages, inferenceConfig={"maxTokens": 100})
    return r["output"]["message"]["content"][0]["text"], r["usage"]["inputTokens"]


# ---------------------------------------------------------------- stateless
def stateless(rt):
    print("Two independent Converse calls. Each request carries ONLY its own message.\n")
    out = []
    for i, text in enumerate(TURNS):
        if i == 1:
            pause("Call 2 asks what to pack. What will the model answer?")
        msgs = [{"role": "user", "content": [{"text": text}]}]
        answer, in_tok = converse(rt, msgs)
        print(f"  request: {len(msgs)} message(s), {in_tok} input tokens")
        print(f"  user : {text}\n{wrapped('  model: ', answer)}\n")
        recap(f'call 1, user said:    "{short(text)}"' if i == 0 else f'call 2, no memory:    "{short(answer)}"')
        out.append({"messages_sent": len(msgs), "input_tokens": in_tok, "user": text, "model": answer})
    print("The model has never seen this customer before. Every single time.")
    return out


# ---------------------------------------------------------------- with memory
def ensure_table(ddb):
    try:
        ddb.describe_table(TableName=TABLE)
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    print(f"  creating DynamoDB table {TABLE} (on-demand, TTL) ...")
    ddb.create_table(TableName=TABLE, BillingMode="PAY_PER_REQUEST",
                     AttributeDefinitions=[{"AttributeName": "userId", "AttributeType": "S"},
                                           {"AttributeName": "ts", "AttributeType": "N"}],
                     KeySchema=[{"AttributeName": "userId", "KeyType": "HASH"},
                                {"AttributeName": "ts", "KeyType": "RANGE"}])
    ddb.get_waiter("table_exists").wait(TableName=TABLE)
    ddb.update_time_to_live(TableName=TABLE, TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"})


def load_history(ddb, user_id):
    """Call 1 of 3: Query this user's turns, oldest first. Nobody else's.
    One page is enough for a demo; a real application bounds the history and paginates."""
    items = ddb.query(TableName=TABLE, KeyConditionExpression="userId = :u",
                      ExpressionAttributeValues={":u": {"S": user_id}}, ScanIndexForward=True)["Items"]
    return [{"role": i["role"]["S"], "content": [{"text": i["text"]["S"]}]} for i in items]


def store_turn(ddb, user_id, role, text):
    """Call 3 of 3: append one turn with a TTL so idle conversations evaporate."""
    now = time.time_ns() // 1_000_000
    ddb.put_item(TableName=TABLE, Item={"userId": {"S": user_id}, "ts": {"N": str(now)},
                                        "role": {"S": role}, "text": {"S": text},
                                        "ttl": {"N": str(int(time.time()) + TTL_SECONDS)}})


def with_memory(rt, ddb, user_id):
    ensure_table(ddb)
    print(f"Three API calls per turn for user '{user_id}': Query -> Converse(history + new) -> PutItem\n")
    out = []
    for text in TURNS:
        history = load_history(ddb, user_id)                       # 1. Query
        msgs = history + [{"role": "user", "content": [{"text": text}]}]
        answer, in_tok = converse(rt, msgs)                        # 2. Converse with the history
        store_turn(ddb, user_id, "user", text)                     # 3. PutItem (both turns)
        store_turn(ddb, user_id, "assistant", answer)
        print(f"  request: {len(msgs)} message(s) ({len(history)} from DynamoDB), {in_tok} input tokens")
        print(f"  user : {text}\n{wrapped('  model: ', answer)}\n")
        if text == TURNS[1]:
            recap(f'call 2, with memory:  "{short(answer)}"')
        out.append({"messages_sent": len(msgs), "from_history": len(history), "input_tokens": in_tok,
                    "user": text, "model": answer})
    # isolation: another user asks the same question and gets nothing
    other = "bob"
    pause(f"Now user '{other}' asks the same question. What does he get?")
    msgs = load_history(ddb, other) + [{"role": "user", "content": [{"text": TURNS[1]}]}]
    answer, in_tok = converse(rt, msgs)
    print(f"  user '{other}' asks: {TURNS[1]}\n{wrapped('  model: ', answer)}")
    print("\n\"Memory\" is your code re-sending history. The model API stayed stateless the whole time.")
    out.append({"user_id": other, "messages_sent": len(msgs), "model": answer})
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--stateless", action="store_true")
    g.add_argument("--with-memory", action="store_true")
    g.add_argument("--cleanup", action="store_true")
    ap.add_argument("--user", default=f"alex-{int(time.time())}", help="conversation id (default: fresh each run)")
    ap.add_argument("--no-pause", action="store_true", help="run straight through (recordings, replay)")
    a = ap.parse_args()
    if a.no_pause:
        os.environ["DEMO_PAUSE"] = "0"
    reg = region()
    rt = boto3.client("bedrock-runtime", region_name=reg)
    ddb = boto3.client("dynamodb", region_name=reg)
    title(f"Experiment 2 - conversation history is application state   (region {reg}, {today()})")
    if a.cleanup:
        ddb.delete_table(TableName=TABLE)
        print(f"deleted {TABLE}")
        return
    result = stateless(rt) if a.stateless else with_memory(rt, ddb, a.user)
    path = save("02-memory-" + ("stateless" if a.stateless else "with-memory"),
                {"region": reg, "model": MODEL, "turns": result})
    print(f"\nsaved {path}")


if __name__ == "__main__":
    main()
