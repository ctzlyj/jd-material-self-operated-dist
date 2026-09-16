# Interrupted image-response recovery

## Scope and reason

The dual-key wrapper previously forced every HTTP request to one attempt. The underlying client wrapped interrupted reads as `ModelTransientError`, losing their typed cause. A response ending with `peer closed connection without sending complete message body (incomplete chunked read)` was therefore immediately treated as terminal product failure.

The client now retains the original exception cause. Only `httpx.RemoteProtocolError` and `httpx.ReadError` raised while requesting `/images/edits` qualify. Error-message substring matching is not used. This is the sole exception to dual-key `--no-generation-retries`; single-key and text behavior are unchanged.

## Bounds and safety

- Wait five seconds after the interruption, checking cancellation, pause, quota, authentication and resource stops every second. Reserve the same worker/key slot throughout.
- Retry at most once with the exact original method, URL, headers and payload. Keep the same prompt, reference image and model. Both dispatches pass the shared global one-second gate and same-key two-second gate; total concurrency remains four and each key at most two.
- Respect any concurrent global cooldown before the second dispatch. A new HTTP 429 uses the existing cooldown policy and is not retried again. Content rejection, HTTP 400/5xx, invalid image data, connection/write errors and timeouts do not qualify for this new exception. Quota exhaustion and authentication still stop further requests.
- The provider may have already generated or billed the first image before its response was lost. The extra request can incur another charge; this is bounded recovery, not guaranteed idempotence or proof of faster throughput.
- A terminal second failure skips the affected SPU with all sibling SKUs, the concrete reason and evidence. Do not regenerate its companion images or reopen historical failure fingerprints. Existing valid images remain reusable.
- Uploads, material binding and short-title writes are entirely outside this policy. An unknown write requires read-only reconciliation or a safe stop, never transport retry.

## Evidence and restart

Before waiting, persist `.state/dual-key-generation/transport-retries/<requestHash>.json` to reserve the only extra attempt. Keep separate UUID records for each attempt; link them with `retryOf`, `retryAttemptId`, `retryNumber` and the unchanged request hash/key slot. The first failure remains recorded even if the second attempt succeeds. Record the error type, request timing and `recoveryElapsedSeconds`, never credentials or image payloads.

Count records with `startedAt` as dispatches and `valid-image` records as usable outputs; queued/cancelled retries are not HTTP requests. Failed HTTP attempts and terminal failed SPUs are different metrics. Recovery duration includes the five-second wait, any additional cooldown and the retry response time.

A reservation survives cancellation or process loss and prevents a new retry allowance after restart, including after a recovered response. Reuse the saved image cache; if it was not persisted, leave the item pending for evidence reconciliation rather than silently generating again. Never delete reservation/failure records merely to clear a backlog. This upgrade does not resume any paused queue or retry past failures.

## Verification and rollback

Run `python -m unittest discover -s jd-material-self-operated/tests -p test_dual_key_generation.py -v` from the repository, then `python tools/verify_release.py`. Tests cover identical key/payload, both rate gates, two-attempt exhaustion, restart reservation, pause/auth/quota/resource stops, HTTP errors, primary-only text, redaction, and an actual truncated chunked response from a loopback HTTP server. These tests use no model gateway or production writes and do not establish production speed or cost savings.

Install only at a safe checkpoint with the existing non-destructive installer. Keep its baseline and merge candidates; preserve local-only files and production evidence. To revert the policy, safely stop new dispatches and use the verified previous source through the same merge process, retaining all reservations and receipts. Do not reset production state or restart workers as part of deployment.
