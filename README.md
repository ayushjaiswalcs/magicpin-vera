# Vera Context — magicpin challenge submission

A deterministic, stateful merchant-assistant bot by Ayush Jaiswal. Python 3.11+;
no dependencies, LLM key or outgoing network requests. Run `python3 bot.py`.
For the interactive local demo: `DEMO_MODE=1 python3 bot.py`, then open
http://localhost:8080. Detailed instructions: **START_HERE.md**.

## Approach

`bot.py` exports the required pure `compose(category, merchant, trigger, customer)`
function and serves all five `/v1/*` endpoints, plus teardown. Versioned contexts
replace older snapshots atomically. The scheduler uses the judge's simulated
clock, prioritises urgency, checks expiry/consent, deduplicates per recipient and
suppression key, and sends at most 20 actions per tick. Every first outbound uses
a mock template. Reply handling covers acceptance, onboarding, opt-out, automatic
replies, delays and off-topic requests. Replies read the latest contexts.

Messages use supplied facts, active merchant offers and source-attributed digest
items. Category catalog suggestions are not advertised as active offers.
Customer reminders require matching consent; unrelated marketing is excluded.
No booking, publication, registration or payment is falsely reported as complete.

## Tradeoffs and limits

Rules are predictable and fast, but less flexible than an LLM for unfamiliar
intents, free-text slot selection and nuanced multilingual conversation. English
and limited Hindi-English are implemented; other language preferences fall back
to English. Missing required facts result in suppression, not fabricated content.
The 30 generated fixture rows include **19 messages and 11 documented
suppressions**. Static-scorer acceptance of suppressed rows is not specified;
the live contract explicitly permits empty action lists. These are not 30
successful sends. `submission.jsonl` records the exact decisions transparently.

State is memory-only: use one continuously running instance; no redeploys during
judging. The standard-library server is for this synthetic challenge behind a
hosting platform's HTTPS proxy, not production merchant outreach. Teardown wipes
runtime state. Do not use the unauthenticated challenge endpoints with real data.

## Verification and additional context needed

Run `python3 -m unittest discover -s tests -v` and, with the server running,
`python3 scripts/smoke_test.py`. The smoke test uses the company's original
request client; it resets the target, so run before judging only.
See `TEST_REPORT.md`. No LLM quality score or public-hosting test is claimed.

Most useful additions: complete generated trigger payloads, reconciled dates,
confirmed service eligibility and opening hours, richer consent/language fields,
an official static suppression format, and real authorised action integrations.

## Repository archive
Supporting folders (fixtures, original challenge files, demo UI, scripts, and tests) are bundled in `resources.zip` for browser upload. After cloning, run `python -m zipfile -e resources.zip .` once. Render and Docker do this automatically. The main application source is `bot.py`.
