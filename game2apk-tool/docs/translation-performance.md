# DeepSeek translation performance

The optional translation path uses the official DeepSeek model identifier
`deepseek-v4-flash`. The friendly spellings `v4flash`, `v4-flash`, and
`deepseek-v4flash` are normalized to that identifier; other explicit model
names are still accepted for local testing or future providers.

For V4 Flash requests the tool explicitly sends
`"thinking":{"type":"disabled"}`. Translation is a constrained JSON
transformation, so reasoning tokens add latency without improving the safety
checks. Each request also receives a bounded `max_tokens` value sized from the
input text.

The default scheduler sends up to 20 unique blocks per request and runs up to
4 requests concurrently. Identical source blocks are de-duplicated, results
are consumed and applied in source order, and successful results are reused
from `.state/translation-memory.json` on later builds. Set these optional
environment variables before starting the tool when needed:

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

