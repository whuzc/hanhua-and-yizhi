# DeepSeek translation performance

The optional translation path uses the official DeepSeek model identifier
`deepseek-v4-flash`. The friendly spellings `v4flash`, `v4-flash`, and
`deepseek-v4flash` are normalized to that identifier; other explicit model
names are still accepted for local testing or future providers.

For V4 Flash requests the tool sends a `thinking` mode explicitly. It defaults
to `{"type":"enabled"}` with `reasoning_effort="high"`; the browser and CLI
also offer `low`, `high`, and `max`. Choosing `{"type":"disabled"}` is the
speed-first option and omits reasoning effort from the request. Each request
also receives a bounded `max_tokens` value sized from the input text; high/max
reserve a larger floor so reasoning tokens cannot consume the JSON output
budget on longer passages.

The default scheduler sends up to 20 unique blocks per request and runs up to
4 requests concurrently. Identical source blocks are de-duplicated, results
are consumed and applied in source order, and successful results are reused
from `.state/translation-memory.json` on later builds. Set these optional
environment variables before starting the tool when needed:

Source filtering happens before any request: pure Chinese blocks are skipped
and preserved. A mixed block stays together for context, while Han runs are
protected and restored unchanged; only its surrounding non-Chinese text may
change. The inspection report exposes the candidate and skipped counts.

RPG Maker MV `101` + consecutive `401/405` lines are extracted as one message
block. The prompt asks DeepSeek to read all lines in that block together for
context (pronouns, tone, and terminology), while returning the same line count
and order. Parallelism is between independent blocks; it is not word-by-word
translation and does not merge unrelated events into one context.

The practical trade-off is straightforward: `low` is the quickest thinking
choice, `high` is the default balance, and `max` spends the most reasoning
budget for difficult or nuance-heavy passages. Because the model service and
network can vary, these are configuration choices rather than a guaranteed
quality ranking for every sentence; review the generated diff before shipping.

```powershell
# Conservative values for a rate-limited account
$env:GAME2APK_TRANSLATION_CONCURRENCY = "2"  # 1..8
$env:GAME2APK_TRANSLATION_BATCH_SIZE = "12"   # 1..100
```

The scheduler retries transient HTTP responses (`408`, `425`, `429`, and
`5xx`) up to two times with bounded exponential backoff, jitter, and a safe
`Retry-After` value when supplied by the provider. A cancel request interrupts
backoff and stops queued requests; an in-flight HTTP request finishes or times
out before its worker exits. API keys are passed only in memory, are never
included in prompts, logs, reports, cache files, or command-line arguments,
and third-party translation still requires an explicit confirmation.
