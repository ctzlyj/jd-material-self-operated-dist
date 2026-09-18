# Opt-in Gemini routing

Available as an opt-in source route, not a production speed certification. Existing tasks and the legacy default are unchanged. Private source/maintainer installation changes do not update protected colleague distribution or its server core.

## Model roles

`run-direct` and `maintain-self-operated` accept:

- `--image-routing legacy`: unchanged GPT behavior, the default for old tasks.
- `--image-routing gemini-flash`: white, scene1 and scene2 use `Gemini-3.1-Flash-Image-Preview-joybuilder`.
- `--image-routing gemini-pro`: those kinds use `Gemini-3-Pro-Image-Preview-joybuilder`.
- `--selling-image-model gpt-image-2|gemini-flash|gemini-pro`: selling images only, default GPT. Gemini choices require a non-legacy route.

Gemini requires explicit `--dual-key-images` and no-generation-retries, without same-request resource probes. Text stays on the existing primary credential. Product-Pro and Oxygen-Imagen are not enabled. Transparency never dispatches a model request: reuse existing local white-to-transparent processing and valid images/URLs.

Both Gemini identifiers use `POST /v1/images/gemini_flash/generations`, frozen user text and original reference bytes in `inlineData`, with IMAGE/TEXT and square 1K configuration. Locate the image among mixed response parts, require a complete decodable image, then reuse existing 800-square transformations. A safety block, non-STOP terminal reason or body disconnect is not success. No semantic or visual scoring is added.

Parts marked `thought: true` are intermediate outputs, never deliverable images. Exclude them before requiring exactly one final image; an intermediate image alone remains failure. Preserve only final/intermediate image counts in response diagnostics, not intermediate content or signatures. Native responses have contained both kinds, so neither selecting the first image nor rejecting the response solely because it contains an intermediate image is valid. Do not use benchmarks that selected intermediate images as final-output speed evidence. Retain prior failed fingerprints and do not replay old SPUs after this parser correction.

## Eligibility and concurrency

New CLI invocations default to total concurrency two for Pro and one for Flash; legacy stays four. Explicit arguments and frozen routing still govern existing tasks. A prior four-worker Gemini evaluation is never silently rewritten by the new defaults: pass its original settings or stop for review. Four is not recommended without a separately authorized successful bounded validation. Live samples contained a Pro disconnect at two and missing Flash final images at one; neither maximum stability nor production speedup is established. Read `secure-credentials.md` before requesting a missing credential, and do not request re-entry when current authorization and existing configuration are already recorded.

Check current authorization class and documented limits through O2. Key authorization, catalog access, marketing claims of high concurrency, and a successful image do not establish production permission. If only BASE is supported and the API states BASE is development-only/no-SLA/prohibited in production, do not maintain products without independent provider evidence of production eligibility. Do not automatically change authorization.

Local evaluation concurrency is 1, 2 or 4 TOTAL across all models and both Keys, not four per model. Four allows at most two per Key; one uses the original primary slot; two uses one slot per Key. Preserve minimum global one-second and same-Key two-second start intervals. These settings are not a discovered provider maximum or a stable throughput guarantee. Do not add a pool per model or switch a failed request to another Key/model.

All models share the original persisted 429 cooldown/deadline: valid Retry-After first, otherwise existing 60/120-second behavior and each blocked Key's own recovery proof. Auth/quota, scope errors, pause and unknown product writes retain their stops.

## Persistence and retries

Before execution, freeze `.state/image-routing.json` with models, kinds, concurrency and retry policy bound by SHA. Changed/default CLI arguments cannot reset a routed task. Do not switch an already executed legacy task, mutate its plan/hash, or create a parallel queue around unresolved writes.

Gemini identity binds the actual model, endpoint and complete frozen payload. Persist a create-exclusive reservation under `.state/dual-key-generation/gemini-requests/` before HTTP. Crash, partial body or an existing reservation never causes an automatic replay after restart. Keep failure fingerprints, attempts and valid caches; a missing image file does not authorize clearing a reservation.

Gemini performs ZERO automatic retries, including RemoteProtocolError/ReadError. GPT selling retains the original once-after-five-seconds, same-Key/frozen-request exception and durable retry reservations. Neither applies to unknown uploads, bindings or short-title writes.

Capture headers/status before body consumption. Log only bounded allowlisted metadata, request/response/image SHA, model/kind, Key slot, numeric usage and raw cost with unverified unit. Never log reference Base64, thoughtSignature, credentials or full response bodies. HTTP 200 without a complete image remains failure, not zero cost.

## Validation and rollout

Run the `test_gemini_routing.py` regressions, full independent suite, clean non-destructive installation tests and project suite. These cover exact bytes, both models, mixed response parts, shared slots/cooldown, safety stop, redaction, body loss, crash reservations, frozen routes and legacy compatibility.

Provider production eligibility and original unknown-write resolution come first. Then use explicitly authorized unmaintained SPUs: one complete SPU, then ten at concurrency one; expand to two/four only within provider limits and after each stage passes. Preserve all sibling SKUs/exclusions. Stage changes require separately frozen evaluation configurations, never mutation of an active run or repeated attempts on failed SPUs.

Compare the same required image kinds/workloads. Separate request latency, queue time, technical valid rate, uploads, binding acceptance and exact final readback. Small no-error samples do not prove a maximum stable concurrency. Stop expansion on throttling, auth/quota errors, rising disconnects, unknown writes, absent production permission or no end-to-end gain. Ordinary failures skip the entire SPU with full SKU/reason/evidence/SHA; no regeneration or repair.

Rollback keeps the old installed release and all production receipts/caches. Use the repository's three-way-aware installer only after validation; stage local conflicts rather than overwrite. No protected distribution or authorization service deployment is implied.
