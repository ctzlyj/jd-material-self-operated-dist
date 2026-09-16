---
name: jd-material-self-operated
description: Automatically maintain a JD colleague's own self-operated ERP product materials from first use or a saved task, generate and upload images, bind through APIs and verify short titles. Also supports explicit manual workbook delivery. Not for POP shops.
---

# 自营商品素材维护

Use this distribution's `scripts/self_operated_cli.py` entrypoints and bundled runtime. The default manual client remains read-only for product fields; explicit direct commands use the separately scoped `direct_binding.py` client. Neither client contains POP operations. Never route self-operated work through the retired mixed Skill or its segmented executors.

## One-request first use

When a colleague authorizes automatic generation, upload, API binding and verification for their own products, read `references/first-use.md` and run `maintain-self-operated --confirm GENERATE_UPLOAD_BIND_AND_VERIFY`. The agent handles installation, tools and command arguments. Do not ask for a shop name, old handoff, spreadsheet, SKU list or a second write confirmation. The entry discovers the real logged-in ERP, applies the native owner filter, freezes a new plan, then automatically runs one, ten and the remaining SPUs. Existing tasks resume in their original directories, never by fabricating a historical split handoff. Login, product permission and a model key still must actually exist; explain the specific missing prerequisite rather than claiming unattended success.

## Business scope

- Default failure policy: skip an SPU after ordinary generation failure, definitive upload failure or native audit rejection; continue other authorized SPUs and deliver every sibling SKU with the specific native reason and evidence SHA for colleague appeal. Never regenerate, repair, re-upload or rebind failed/rejected work automatically, including in a new task. Only an explicit request naming the rejected SPUs and correction requirements permits a targeted repair. First-use plans freeze `--regenerate-rejected-spu-ids <IDs>` for that exception; generic maintenance authorization does not imply it. Existing valid images, URLs, plans and receipts remain intact. Unknown writes still reconcile or stop, not skip as confirmed failure. See `references/rejected-materials.md`.

- An unknown image upload still stops by default. Only after explicit authorization to isolate its whole SPU without replay, use `quarantine-upload` as described in `references/upload-quarantine.md`, then continue the original `run-direct`. Keep the original unknown receipt, full SKU scope and valid images; new or changed unknown writes still stop. Quarantine is unfinished work, never readback-matched completion.

- For an explicitly requested single-key versus dual-key image benchmark, read `references/image-key-comparison.md`. Keep one total four-worker limiter and one global one-start-per-second gate. Use the bundled metrics helpers, preserve same-key recovery and cached outputs, and do not enable production dual-key scheduling from an incomplete or interrupted comparison.

- When explicitly authorized to maintain the current visible SKUs despite a reduction, use `run-direct --current-visible-skus`. Successful complete native counts must agree; do not treat query errors or missing pages as a smaller scope. Preserve frozen plans and field exclusions, record the removed SKUs, and use the revised membership for generation, writes and final readback. Read `references/current-visible-skus.md`.

- When the user requests one final readback after all writes, use `run-direct --defer-readback` for the authorized write phase and `verify-direct` after every scope has finished writing. Receipts stay incomplete until that read-only finalizer verifies and updates the canonical progress. New first-use tasks support `maintain-self-operated --defer-readback`, keeping immediate one/ten-SPU pilots and automatically finalizing the remaining scope. Read `references/final-readback.md`; uncertain writes still reconcile immediately.

- For OSW versus direct-product entry comparisons, short-title category errors, or authorized automatic Excel tasks, read `references/osw-short-title-tasks.md`. Explicit direct runs can use `--short-title-transport osw`; the default remains `product`. Preserve per-SKU successes even when the overall task fails.

- Native audit rejection is unfinished work, even when a URL exists, an earlier submission was accepted, or the displayed score is still high. Preserve the platform rejection reason, old URL, full SKU membership and receipts. Reuse compatible approved companion images; do not replay the same rejected image URL or disguise it with a new filename. Corrected replacements use the existing generation/upload/binding/readback flow. A repair accepted and read back as pending is not audit-approved or score-refreshed. Read `references/rejected-materials.md`.

- A direct-owner filter returning no rows does not prove an explicitly named SPU is unavailable to the logged-in ERP: delegated visibility can differ. For user-authorized named products, compare native selected availability read-only. `maintain-self-operated --include-delegated --target-spu-ids ...` opts into at most 50 explicit SPUs under the same verified ERP; it never expands to all visible products or changes an existing owner-scoped plan. Default first use remains owner-only. Visibility is not a guarantee of write permission or proof of when a delegation took effect.

- Direct maintenance defaults to `--defer-incomplete` and `--no-generation-retries`: preserve partial images, skip rather than regenerate failures, continue other SPUs, and export the failure/pending list. Do not use `--repair-segment` for business failures without a specific repair request. Quota, authentication and unknown-write pauses still apply.

- Self-operated procurement has no personal shop. New colleague tasks use only the authenticated ERP's own product filter. Broader visible permissions do not authorize other owners. Historical explicitly authorized tasks retain their original frozen scope.
- Default manual mode generates missing materials, uploads image files and delivers workbooks for the user to import. It never writes product fields or creates import tasks. Explicit user authorization to generate, upload, bind and verify selects direct mode; read `references/direct-maintenance.md` first. Never infer direct authorization from a manual plan.
- Keep request-bound hashes and audit records; do not ask for a second post-generation write-list confirmation within the explicitly authorized mode and scope. Never claim a score improvement from upload or binding acceptance alone.
- Keep all sibling SKUs. Reuse valid cached images and verified URLs. No semantic or visual model review. Keep four image workers, one start per second, bounded resource cooldown and actual quota-exhaustion pause; ordinary failed generation gets no automatic retry. Do not invent a total request cap.
- Read `references/manual-import-delivery.md` for manual delivery and `references/resume.md` for legacy continuation, not as prerequisites to a colleague's new task. The final material workbook has one text SPUID per row and blank SKU column. The OSW title workbook has `skuId` and `短标题` headers and starts data at row 2.

## Entry points

- Explicit direct maintenance can opt in to `--image-transport direct-http` on `run-direct` or `maintain-self-operated`. It uses the verified background browser profile only to obtain in-memory image-space credentials, then pools five native HTTP upload/query connections. Product binding and titles keep the established backend flow. Original file hashes, durable upload intents, exact readback and unknown-write protection remain mandatory; no automatic browser fallback or upload retry. See `references/direct-maintenance.md`.

- When the user explicitly authorizes temporary resource cooldown, add `run-direct --resource-cooldown`: pause new image dispatch, retry the exact blocked request alone after 60 seconds and then 120 seconds, and stop after 300 continuous seconds without verified recovery. Preserve the same credential/payload and cache the successful probe image. Valid probe output ends that episode; a later resource block starts its own window. Repeated failures or process restart do not reset an unresolved window. Do not reclassify resource errors as ordinary image skips or rotate credentials. Default immediate-stop behavior, quota/authentication and unknown-write protection remain unchanged.

- For an explicitly authorized direct run, opt in to `run-direct --pipeline` to overlap one next segment's generation with the current segment's upload/binding. One shared model limiter and one browser writer remain. Frozen lookahead groups survive pauses and batch-size changes; interrupted generation retains partial cache without permanently skipping cancelled images. `--cached-only` never starts the producer. Use runner wall time, not sums of overlapping segment times, for throughput.

Commands are for the agent, not setup homework for the user:

- For a resource-paused existing direct segment, `run-direct --cached-only --limit <at-most-50> --defer-incomplete` completes ready cached fields without any model calls or reference downloads. It never advances to new segments, removes missing material work, or clears resource-pause evidence. Read `references/direct-maintenance.md` for bounded active/repair selection and phase timing semantics.
- `provider-info`: offline version/provider inspection.
- `inspect-handoff --handoff <receipt> --erp <erp>`: verify queue and exclusion SHA values, ERP, full SKU scope and field-level exclusions without querying platform completion.
- `plan-resume --handoff <receipt> --erp <erp> --output-dir <new-run> --cache-dir <old-run-directories>`: freeze an independent dry-run plan; never edit old plans, locks or receipts.
- `export-pending --erp <erp> --output-dir <new-run> --confirm-token <plan-token> --delivery-dir <new-delivery>`: offline export restricted to the pending field-level scope.
- `run-resume --erp <erp> --output-dir <new-run> --confirm-token <plan-token> --confirm GENERATE_AND_UPLOAD_IMAGES_ONLY --limit <pilot-count>`: verified scope, generation, image upload and manual workbook delivery. The token binds the existing user authorization; it is not another user confirmation.
- `plan-direct --handoff <receipt> --erp <erp> --output-dir <new-direct-run> --cache-dir <source-runs>`: freeze the full original remaining field scope and SHA-bound source receipts, including later manual-mode image caches. Workbook-ready does not mean API-bound.
- `run-direct --erp <erp> --output-dir <direct-run> --confirm-token <direct-token> --confirm GENERATE_UPLOAD_BIND_AND_VERIFY --limit <pilot-count>`: explicit direct binding, required short-title writes and exact immediate readback. After one and ten validated SPUs, omit the limit to continue; unresolved jobs stay recorded as pending work.
- `run-titles` with the same direct scope arguments: while new image generation is unavailable, process only unattempted short-title fields without image requests, uploads or material binding. Preserve canonical full-SPU segments and their title receipts for later `run-direct`; title-only progress never completes or removes material tasks. See `references/direct-maintenance.md`.
- `plan-self-operated --erp <erp> --target-spu-id <id> --output-dir <new-scope>`: read-only discovery for a new authorized scope, never a way to bypass a pending handoff.

Before live execution verify both independent releases, clean installs, templates, state isolation and the exclusion regressions. Start with one SPU then ten before scaling. Never start an old writer. A legacy unknown upload stops the affected migration; preserve its receipt and reconcile read-only, never blindly replay it.

## Authentication and background work

For explicitly authorized dual-key production with terminal failure skipping, read `references/dual-key-generation.md` and use `run-direct --dual-key-images --no-generation-retries --defer-incomplete --defer-readback`. The two credentials retain two slots each, one global four-slot limit and the original one-start-per-second gate, with conservative two-second same-key pacing. This opt-in is not a claim of proven speedup; single-key remains the default. Do not combine it with same-request resource probes.

The sole automatic retry exception in dual-key mode is an interrupted image response (`httpx.RemoteProtocolError` or `httpx.ReadError`): wait five seconds, then make at most one extra attempt with the same credential and frozen payload through the same gates. Read `references/image-transport-retry.md` for persistent retry reservations, audit counts and stop rules. It never reopens historical failures, retries safety rejection or uncertain product writes, or changes single-key/text behavior.

Dual-key 429 cooldown follows valid `Retry-After`; absent/invalid values use 60 seconds initially and 120 seconds thereafter, without retrying the failed image. Keep the original thirty-minute deadline, any longer persisted wait and each blocked credential's own recovery proof. Never shorten a known server wait, reopen an exhausted episode or resume a paused task merely because the Skill was upgraded.

Discover capabilities through O2 first. Use the bundled, pinned `webcli-browser-runtime` companion's safe transport, dedicated background sessions and existing authentication. Do not focus or navigate working tabs. Do not edit npm packages or bypass a merge-required guard.

If the process lacks the model key, the agent runs `scripts/secure_launcher.py -- <command>` for local masked entry. Never request the key in chat, print it, persist it or copy it from historical conversations. A login or quota failure pauses work with cache intact.

Report generated files, real HTTP request counts, binding acceptance, exact persisted values, audit status, remaining tasks, timing and recovery separately. Workbook delivery, accepted writes and old unrelated pending materials are not interchangeable. Source details and queue counts are cached unless explicitly refreshed.

## Protected distribution

Before execution read `references/protected-service.md`. No local private-core fallback is allowed.
