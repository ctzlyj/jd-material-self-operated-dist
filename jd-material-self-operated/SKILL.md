---
name: jd-material-self-operated
description: Automatically maintain a JD colleague's own self-operated ERP product materials from first use or a saved task, generate and upload images, bind through APIs and verify short titles. Also supports explicit manual workbook delivery. Not for POP shops.
---

# 自营商品素材维护

Use this distribution's `scripts/self_operated_cli.py` entrypoints and bundled runtime. The default manual client remains read-only for product fields; explicit direct commands use the separately scoped `direct_binding.py` client. Neither client contains POP operations. Never route self-operated work through the retired mixed Skill or its segmented executors.

## One-request first use

When a colleague authorizes automatic generation, upload, API binding and verification for their own products, read `references/first-use.md` and run `maintain-self-operated --confirm GENERATE_UPLOAD_BIND_AND_VERIFY`. The agent handles installation, tools and command arguments. Do not ask for a shop name, old handoff, spreadsheet, SKU list or a second write confirmation. The entry discovers the real logged-in ERP, applies the native owner filter, freezes a new plan, then automatically runs one, ten and the remaining SPUs. Existing tasks resume in their original directories, never by fabricating a historical split handoff. Login, product permission and a model key still must actually exist; explain the specific missing prerequisite rather than claiming unattended success.

## Business scope

- If the user asks to skip image failures, use the explicit direct runner's `--defer-incomplete` policy described in `references/direct-maintenance.md`: preserve partial images, skip rather than regenerate failures, continue other SPUs, and export the failure/pending list. Quota, authentication and unknown-write pauses still apply.

- Self-operated procurement has no personal shop. New colleague tasks use only the authenticated ERP's own product filter. Broader visible permissions do not authorize other owners. Historical explicitly authorized tasks retain their original frozen scope.
- Default manual mode generates missing materials, uploads image files and delivers workbooks for the user to import. It never writes product fields or creates import tasks. Explicit user authorization to generate, upload, bind and verify selects direct mode; read `references/direct-maintenance.md` first. Never infer direct authorization from a manual plan.
- Keep request-bound hashes and audit records; do not ask for a second post-generation write-list confirmation within the explicitly authorized mode and scope. Never claim a score improvement from upload or binding acceptance alone.
- Keep all sibling SKUs. Reuse valid cached images and verified URLs. No semantic or visual model review. Keep the existing four image workers, one start per second, bounded retries and actual quota-exhaustion pause; do not invent a total request cap.
- Read `references/manual-import-delivery.md` for manual delivery and `references/resume.md` for legacy continuation, not as prerequisites to a colleague's new task. The final material workbook has one text SPUID per row and blank SKU column. The OSW title workbook has `skuId` and `短标题` headers and starts data at row 2.

## Entry points

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

Discover capabilities through O2 first. Use the bundled, pinned `webcli-browser-runtime` companion's safe transport, dedicated background sessions and existing authentication. Do not focus or navigate working tabs. Do not edit npm packages or bypass a merge-required guard.

If the process lacks the model key, the agent runs `scripts/secure_launcher.py -- <command>` for local masked entry. Never request the key in chat, print it, persist it or copy it from historical conversations. A login or quota failure pauses work with cache intact.

Report generated files, real HTTP request counts, binding acceptance, exact persisted values, audit status, remaining tasks, timing and recovery separately. Workbook delivery, accepted writes and old unrelated pending materials are not interchangeable. Source details and queue counts are cached unless explicitly refreshed.

## Protected distribution

Before execution read `references/protected-service.md`. No local private-core fallback is allowed.
