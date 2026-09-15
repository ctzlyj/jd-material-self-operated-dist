# Field-level handoff and safe cache reuse

This page describes manual mode. For explicitly authorized direct API maintenance use `references/direct-maintenance.md`; that mode conservatively migrates product-write receipts and retains workbook-ready SPUs until their binding is verified.

The handoff's byte SHA values bind the exclusion ledger and pending queue. The queue also records the semantic exclusion hash and original frozen plan hash. Validate them all before making an independent plan. Never rewrite the original plan or set its resume blocker to false.

Manual takeover is sufficient for exclusion: it is not evidence of platform import success. Material fields and SKU titles are independent. Reject reintroduced delivered fields, fully delivered SPUs, changed SKU ownership, or changed ERP. Keep title-only partial SPUs when their material work remains.

The new run directory must be outside all old cache roots. Copy only technically valid image files, existing reference files, generated text and verified image URLs into new variant-bound state. Preserve source hashes and the complete sibling SKU list. Do not copy product-binding intents or replay unknown uploads. A legacy image-upload intent may be carried only when its exact local image matches the frozen SHA; preserve its unknown status and source-ledger SHA. The existing native uploader reconciles it read-only and refuses resubmission. A same-name remote file with different bytes is not a valid receipt.

The live pipeline verifies current ERP and exact SKU membership before generation and again before image upload. It does not rediscover scores or change the pending field scope. A partial failure generates a partial workbook and pauses at a segment boundary; quota/authentication/unknown response failures preserve the cache and receipt. Do not reset a failed segment into another directory to force progress.

Validate one SPU, then ten, recording actual time and cached versus newly generated work. `--defer-incomplete` allows isolated known failures or unresolved legacy uploads to remain in a separate failed-segment ledger while other SPUs continue. The original queue is unchanged. New uncertain uploads always pause; deferral cannot bypass that guard. Stop if deferred failures exceed 20 percent after at least ten processed SPUs. Without that flag, a partial segment pauses and retries its original group and directory. Do not call the inherited four-worker/one-start-per-second settings a newly measured official maximum. Final delivery is upload workbooks, not automatic import or score completion.

Common code is independently vendored. `SPLIT_PROVENANCE.json` is the initial three-way comparison baseline, not permission to regenerate over this repository. The companion transport also has its own exact upstream function baselines and merge candidates. Official upgrades must preserve local-only files and stage conflicts rather than overwrite local changes.
