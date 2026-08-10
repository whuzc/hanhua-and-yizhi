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

The default scheduler sends up to 60 unique logical blocks per request and runs
up to 4 requests concurrently. Normal body text uses a compact line-oriented
TXT/TSV protocol once a batch contains at least 8 blocks. A request is capped
at the smaller of the configured block count, 60 blocks, or roughly 12,000
source characters. These are deliberately conservative operational limits:
even when a model advertises a much larger context/output window, reasoning,
target-language expansion, exact row recovery, and useful retry granularity
make filling that window a poor reliability trade-off.

Identical source blocks are de-duplicated, results are consumed and applied in
source order, and successful results are reused from
`.state/translation-memory.json` on later builds. Set these optional environment
variables before starting the tool when needed:

高级作弊标签使用独立的 `.state/cheat-label-translation-memory.json`，不会在预览
时加载正文缓存。桌面 UI 预览按最多 96 个标签一个 TXT/TSV 文档分批，避免单个大请求
长时间占用内存；正文仍使用下面的上下文批次策略。

当高级作弊翻译选择 `high` 或 `max` 思考强度时，桌面路径会自动使用单路、每批最多
24 个标签的 JSON 请求；思考强度仍按用户选择发送。`low` 或关闭思考继续使用最多 96
个标签的紧凑文档批次，以在速度和上下文之间取舍。

Source filtering happens before any request: pure Chinese blocks are skipped
and preserved. A mixed block stays together for context, while Han runs are
protected and restored unchanged; only its surrounding non-Chinese text may
change. The inspection report exposes the candidate and skipped counts.

RPG Maker MV `101` + consecutive `401/405` lines are extracted as one message
block. Body TXT documents retain every message segment and mark contiguous
event-list or database-record contexts explicitly. The prompt asks DeepSeek to
read each context together (pronouns, tone, terminology, speakers, and choices)
while returning the same entry IDs, segment count, line order, and boundaries.
Documents stay within one source JSON file and do not merge unrelated maps or
databases into one context.

The complete review input/output is written locally as
`.state/body-translation-source.txt` and
`.state/body-translation-result.txt`. Exact request/response documents are also
stored under `.state/body-translation-batches/`; provider results are read back
from those UTF-8 files before validation and JSON application. These files may
contain game dialogue and therefore remain local `.state` artifacts; they never
contain the API key and must not be published with a release.

The practical trade-off is straightforward: `low` is the quickest thinking
choice, `high` is the default balance, and `max` spends the most reasoning
budget for difficult or nuance-heavy passages. Because the model service and
network can vary, these are configuration choices rather than a guaranteed
quality ranking for every sentence; review the generated diff before shipping.

```powershell
# Conservative values for a rate-limited account
$env:GAME2APK_TRANSLATION_CONCURRENCY = "2"  # 1..8
$env:GAME2APK_TRANSLATION_BATCH_SIZE = "24"   # 1..100; body requests are capped at 60
$env:GAME2APK_TRANSLATION_DOCUMENT_CHARS = "12000" # 1000..48000; 12000 recommended
```

The scheduler retries transient HTTP responses (`408`, `425`, `429`, and
`5xx`) up to two times with bounded exponential backoff, jitter, and a safe
`Retry-After` value when supplied by the provider. A cancel request interrupts
backoff and stops queued requests; an in-flight HTTP request finishes or times
out before its worker exits. API keys are passed only in memory, are never
included in prompts, logs, reports, cache files, or command-line arguments,
and third-party translation still requires an explicit confirmation.

If a TXT completion ends because of output length, the same document is retried
once with thinking disabled and then split recursively, preferably at a context
boundary. A malformed singleton is retained in its original language and
reported as one failure; successful siblings are still cached and applied.
