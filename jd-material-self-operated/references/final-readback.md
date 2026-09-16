# Final batch readback

Use this explicit mode when the user prefers uninterrupted generation/upload/binding followed by one final verification phase. It changes scheduling, not ERP authorization, complete sibling-SKU membership, desired values, exclusion ledgers or the definition of completion. Immediate readback remains the compatible default.

## Execution

- `run-direct --defer-readback` retains the usual direct scope token and authorization. A normal successful material/title response is persisted, but no post-write business-value query blocks the next segment. Pre-write identity, permission, full SKU scope and conflict checks remain.
- The runner records `awaiting-final-readback`; no accepted-only SPU becomes complete. Partial image failures and explicit title rejections are retained. OSW source/log reconciliation remains necessary to know which rows were accepted; this is distinct from the deferred product-value readback.
- For several existing frozen plans, finish their write phases sequentially under the parent writer lock, then run `verify-direct --erp <erp> --output-dir <original-run> --confirm-token <original-direct-token>` for each original plan. Do not rebuild or merge those plans to consolidate verification.
- `maintain-self-operated --defer-readback` keeps immediate one/ten-SPU pilots, defers the remaining write phase, then automatically calls the finalizer. A crash after writes can resume finalization without regenerating images or resubmitting accepted values.

## Verification and recovery

The finalizer is read-only on JD. It rejects active writers, unknown intents and changed deferred state/request hashes. It reuses the existing authoritative scope query for title values instead of querying titles again, and batches material reads within the native limits. A final phase is not a promise of one unlimited HTTP request.

Complete matching evidence produces new immutable segment reports and one atomic canonical progress update; old reports remain archived by reference. Generation failures, native audit rejections, incomplete reads and mismatched titles cannot become complete. An unchanged final receipt is reusable without another query. Refreshed information scores and final platform audit approval are not established merely by matching desired values.

When the user explicitly requests a fresh final check of a previously finalized pending scope, use `verify-direct --refresh-readback`. It rechecks only the remaining recorded deferred SPUs, without generation, uploads, binding, title writes or a new pass over already completed products. Preserve the prior final marker by SHA and produce new immutable readback/report evidence. The default still reuses an unchanged final receipt; refresh does not bypass unknown-write, scope or state-hash gates.

An uncertain upload, binding response or title write does not wait for the final phase: reconcile it immediately or stop without replay. Never treat an old accepted receipt whose value is still missing as permission to switch routes and resubmit blindly. Preserve original images, URLs, intents and source SHA values.

Regression coverage: `tests/test_deferred_readback.py` checks normal-success query deferral, accepted-title no-replay, immediate unknown-write handling, immutable-state guards, incomplete-evidence rejection, final promotion and final-receipt reuse. Existing direct scope, full-SKU, exclusion and failure tests remain applicable.
