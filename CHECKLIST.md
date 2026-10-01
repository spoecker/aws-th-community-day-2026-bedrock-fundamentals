# The pre-agent checklist

Five checks to run on one plain model call before you build agents, RAG or anything else on top
of it. Agents and RAG multiply every one of these; fix them at one call, not at a thousand.

Each check names the script that measures it.

## 1. Tokens — `01_tokens.py`
- [ ] I measured `usage.inputTokens` on **my** model with **my users'** language and real text,
      not an estimate from an English rule of thumb.
- [ ] I know my model's per-call overhead (the "Hi" row) and whether a newer model version changes
      the tokenizer.
- [ ] My cost model uses the metered number (Converse `usage`), not a counter's estimate.

## 2. State — `02_memory.py`
- [ ] I decided where conversation history lives (my store, or a managed one), who can read it,
      and when it expires.
- [ ] Every request sends exactly the history I intend, and a different user can never receive
      another user's turns.
- [ ] I know which managed-state services exist in my Region before I promise them.

## 3. Budget — `03_context_budget.py`
- [ ] History is bounded on purpose: a window, a summary, or a deliberate decision to pay for all
      of it.
- [ ] Long static prefixes (system prompt, tool definitions) sit first and carry a `cachePoint`
      that meets the model's minimum; I checked `cacheWriteInputTokens` on the first call.
- [ ] Per-user data comes after the checkpoint (the cache is per account).

## 4. Quota — `04_max_tokens_quota.py`, `quotas_by_region.py`
- [ ] `maxTokens` is set to what the answer needs. Omitted, it is the model maximum.
- [ ] TPM is sized as **in-flight requests × (input + maxTokens)** with the output multiplier
      added for the reconciliation; RPM is checked for **my** Region and account.
- [ ] 429 is retried with exponential backoff and jitter; 503 and 529 are handled as capacity,
      not as my quota.

## 5. Routing — `05_where_did_it_run.py`
- [ ] I chose the profile type (in-Region, geographic, global) on purpose and know which
      destinations it allows.
- [ ] `additionalEventData.inferenceRegion` in CloudTrail is on my dashboard, and my compliance
      team has seen it.
- [ ] I know that a global profile's destination list can change, and that from some Regions
      the newest models are global-only.
