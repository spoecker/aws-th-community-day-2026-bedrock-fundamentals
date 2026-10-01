# Five Amazon Bedrock fundamentals, measured

Companion code for the talk **"Before You Build an Agent: Five Amazon Bedrock Fundamentals,
Measured Live"** (AWS Community Day Thailand 2026). Five small experiments, plain `boto3`, no
framework. Each prints the raw evidence (the `usage` block, CloudTrail fields, Service Quotas values)
and saves a dated JSON file under `measurements/` so every number in the talk is reproducible.

| # | Script | The fundamental | What you will see |
|---|---|---|---|
| 1 | `01_tokens.py` | Tokens are not words | the same sentence in EN/DE/ZH/TH on four models; Thai ≈ 2.4× to 3.6× English depending on the tokenizer, 1.2× on Nova 2 Lite; per-call overhead; CountTokens vs what is billed |
| 2 | `02_memory.py` | Conversation history is application state | two stateless calls (the second answer is generic: the model has no idea where you are going), then memory in three API calls with DynamoDB (the answer becomes Bangkok-in-October specific), and a second user who gets the generic answer |
| 3 | `03_context_budget.py` | The context window is a finite budget | input tokens 50 → 545 over ten turns (25 Sep; 624 on 14 Sep, the answers vary in length); the same ten turns $0.081 with an 8K policy prompt replayed vs $0.020 with a `cachePoint` (25 Sep); a sliding window flattens the curve |
| 4 | `04_max_tokens_quota.py` | Output-token limits consume quota | 117 concurrent calls at `maxTokens` 64 000 → 41 throttled (78 predicted to fit, 76 did; 25 Sep from the stage runner, 74/43 from a laptop on 14 Sep); the same 117 at 600 → all succeed |
| 5 | `05_where_did_it_run.py` | Cross-Region inference decides where your request runs | CloudTrail `inferenceRegion` for calls made from Bangkok: Melbourne, Tokyo, Sydney, Oregon, Ohio, N. Virginia |
| – | `quotas_by_region.py` | Quotas are per model *and* per Region | the same account: 50 vs 10 000 requests per minute for the same profile in two Regions |

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python3 demo1.py     # tokens (Singapore)
python3 demo2.py     # stateless, then with DynamoDB memory (Bangkok)
python3 demo3.py     # context budget (Singapore)
python3 demo4.py     # concurrency storm, 20 s refill pauses (Singapore)
python3 demo5.py --fire   # 15+ min before: make the routing calls
python3 demo5.py          # then: read where CloudTrail says they ran (Bangkok)
```

`demoN.py` are one-line launchers that fix the Region and flags used in the talk; each stops at its
reveal points and waits for Enter (`--no-pause` or `DEMO_PAUSE=0` runs straight through). At every
Enter the screen is cleared and the title, a one-line recap of the results so far and the question are
printed again at the top, so each part fits a stage-size font: the tallest screen is 25 rows at 100
columns (measured 2026-10-01). `DEMO_CLEAR=0` keeps the old scrolling output. The
experiments themselves take `AWS_REGION` from the environment and a few flags:

```bash
export AWS_REGION=ap-southeast-1        # or ap-southeast-7
python3 01_tokens.py
python3 02_memory.py --stateless && python3 02_memory.py --with-memory
python3 03_context_budget.py
python3 04_max_tokens_quota.py --model haiku --pause 20
python3 05_where_did_it_run.py            # calls + lookup;  --lookup --hours 3 reads CloudTrail only
```

You need an AWS account with Bedrock model access for Claude Haiku 4.5, Claude Sonnet 5, Nova Lite
and Nova 2 Lite in the Region you call from, plus `cloudtrail:LookupEvents`,
`servicequotas:ListServiceQuotas`, and DynamoDB create/query/put/delete on one table for script 2
(`02_memory.py --cleanup` deletes it). A full run of all scripts costs well under $1.

## Extra: the open question

`extra/nova2_input_storm.py` pushes ~8.5M real input tokens through Nova 2 Lite in one burst (about
$3.50). Measured 2026-09-14: zero throttles against an 8M TPM quota, just as there were none at
2× the quota with `maxTokens` 64 000. For Claude the same designs throttle at the quota line. Why
Nova 2 Lite differs is not documented; if you know, open an issue.

## On a stage: run from inside AWS

`stage/` has a CloudFormation template for a small EC2 runner reached with Session Manager: the
laptop holds one HTTPS terminal, no credentials, and the 100+ concurrent calls of experiment 4
never touch the venue network. See [stage/README.md](stage/README.md). Measured 2026-09-14 from a
runner in Bangkok calling Singapore: 76 of 117 concurrent calls fit at `maxTokens` 64 000 (78
predicted; 74 from the laptop the same day), all 117 at 600.

## No network on stage?

`python3 replay.py <1-5>` prints the latest saved measurement for an experiment without calling
AWS, so what you show is still a real, dated result from this account.

## What the numbers mean, and what they do not

- Every measurement is dated. Tokenizers, quotas, prices and inference-profile routing change;
  when your numbers differ, that is new information, not an error.
- The measured findings are exactly that: measured in one account on one day. The documented
  behaviour is quoted with its AWS source in the talk; where the two disagree (CountTokens vs
  billed tokens; Nova 2 Lite and the `maxTokens` reservation) the scripts say so instead of hiding it.
- Files named `…-second-account.json` are the same experiments run in a second AWS account, to check that a
  result is not a property of one account.
- `blog/images/` holds the diagrams and terminal screenshots used in the write-up of the talk.
- Nothing here is an AWS statement. The scripts are MIT licensed; use them, break them, report back.
