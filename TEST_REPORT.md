# Verification report

Status: local functional verification completed; public deployment and submission pending.

| Check | Result |
| --- | --- |
| Python module compilation | Passed |
| Automated suite | 36 tests passed |
| HTTP checks using company's original BotClient | 11 checks passed |
| Dataset load | 5 categories, 50 merchants, 200 customers, 100 triggers |
| Interactive demo scenario API | Research, performance, customer, reviews passed |
| Demo isolation | Judge state remained empty after demo scenarios |
| Malformed JSON / array request / oversize request | Rejected with 400 / 400 / 413 |
| Static output generation | 30 rows: 19 messages, 11 documented suppressions |
| Original supplied company files | Preserved unmodified in `official/` |
| LLM quality scoring | Not run; no provider credentials available |
| Public HTTPS reachability | Not tested; not deployed |
| Actual WhatsApp, Google posting or booking | Not connected; no claim of real execution |

The automated suite checks version conflicts and replacement, deterministic
composition, mock template rendering, duplicate ticks and concurrent requests,
expiry and not-before times, missing digest data, updated context in first sends
and replies, immediate draft delivery, auto-reply handling, STOP, decline, delays,
onboarding, off-topic replies, unknown conversations, repeated/conflicting turns,
wrong-recipient protection, consent, customer attribution, corrected weekday
formatting from ISO timestamps, the 20-action cap, per-recipient deduplication,
and teardown. All 100 generated triggers were exercised through `compose()`.

`test-results/http-smoke.json` records the actual unscored HTTP run. It uses the
company's unchanged HTTP client class, with valid conversation IDs and explicit
simulated dates. It does not claim to run or pass the company's LLM scoring stage.
The browser demo's underlying HTTP routes were checked; a visual browser render
was not inspected in this environment.

## Issues in the supplied challenge files

1. The generator creates 75 additional triggers with placeholder payloads. Some
   category/trigger combinations are incompatible. Missing appointments, competitor
   names, milestones and consent are suppressed rather than invented.
2. Several seed triggers expire in May/June 2026. The supplied simulator uses the
   current wall clock. Running it in September will legitimately suppress those
   expired triggers. Our HTTP test uses explicit April/November simulated dates.
3. The supplied replay tests invent conversation IDs without first starting those
   conversations through `/v1/tick`. This server returns 404 rather than accepting
   an unbound conversation. Our replay tests follow the documented lifecycle.
4. The simulator warmup loads only five merchants and no customers; full evaluation
   also omits customer loading. Our smoke test loads the full generated dataset.
5. Some sample slot labels have incorrect weekdays. This bot formats weekdays
   from the supplied ISO timestamp rather than repeating the inconsistent label.
6. The main brief permits useful URLs, but an example document says URLs are a
   hard fail. Current bot messages do not generate URLs, avoiding that discrepancy.
7. Same-version response guidance varies. The API uses the explicit example's
   409 stale-version response and leaves stored state unchanged.
8. Static JSONL suppression representation is not defined by the company.
   Our output retains all 30 test IDs with explicit suppression reasons. Do not
   claim these are 30 sent messages; the organiser may require a different static
   representation. The live API permits an empty actions array.
