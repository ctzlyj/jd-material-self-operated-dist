# Self-operated manual import delivery

## Current user workflow

The user imports spreadsheets personally. Reuse ERP discovery, existing generation/cache and image-space upload; do not build a second system or invoke product-writing APIs. This independent Skill uses `plan-resume`, `run-resume` and `export-pending` through `scripts/jd_material_agent.py`. It has no POP mode, direct binding mode or product short-title write route. Do not fall back to the retired mixed Skill on export failure.

Image-file upload and spreadsheet import are different steps. As in the plugin, material rows require real image-space URLs; local files or embedding images into Excel cannot replace those URLs. The manual generation route uploads image files only, then ends at the workbook handoff. If the user also declines image-file uploading, use the offline exporter with already confirmed URLs and report missing links. A paused batch stays paused; no automatic generation or image upload is triggered by exporting its caches.

## Template contract

- Reuse `assets/商品素材导入模板-通用场景.xlsx`: preserve `素材规范说明`, the `通用场景` sheet, all 15 original headers and template styles. A column is the SPU as text; B is blank and applies to every SKU under that authorized SPU. C–E hold its three selling points when requested; F–J remain blank. K–O are transparent, white, scene 1, scene 2 and selling-image URLs. Only planned types are filled, matching the canonical plugin's `self-operated-workbook.js`.
- Each material file has at most **10000 SPU data rows**, not 10000 SKU rows. Keep the captured official frontend's **1048576-byte** file constraint too; a file may split earlier due to compressed bytes. Do not reinterpret a frontend recommendation as a measured service ceiling.
- Reuse `assets/批量维护短标题.xlsx`: sheet `批量维护短标题`, exact header `skuId` and `短标题`, data starts on row 2. Keep each SKU ID a text value. Do not use the older two-header `商品导入短标题模板.xlsx` for this OSW import. No arbitrary 10000-row cap applies: split on actual final XLSX size, **less than 5 MiB**, consistent with the captured native check.
- Follow the plugin's template-preserving OOXML insertion, retaining every original non-data ZIP entry byte-for-byte. Do not execute formula-like strings, change source templates, rename sheets or rewrite platform headers. The exporter verifies widths and original header-only layout before writing.
- Missing required links exclude that entire SPU from the ready material workbook, not its successful short titles. Preserve all of that SPU's SKU IDs in the separate incomplete list. Do not insert fake/local URLs, silently drop rows or regenerate valid images to make a workbook appear complete.

## Offline export of existing work

Use `scripts/jd_material_agent.py export-pending --output-dir <independent-run> --erp <erp> --confirm-token <frozen-plan-token> --delivery-dir <new-delivery-directory>`. It performs no model, browser, upload, binding, short-title or task-create calls. It validates the handoff, original exclusions and independent progress receipts, then projects cache records onto only the pending fields. The low-level `manual_import_export.py` remains an internal library; its unguarded legacy command-line export is disabled so it cannot reintroduce already delivered fields. These details are for Codex; users receive files, not setup instructions.

It verifies every source plan's ERP/output/scope token, merges phase/recovery records by saved task time, keeps all authorized sibling SKUs, and accepts image URLs only from verified image-space receipts or the exact approved source URL. Unknown upload receipts remain incomplete without network reconciliation. Corrupt states, changed plan hashes or changed SPU membership fail rather than silently returning a smaller scope. Conflicting destination XLSX contents require a new delivery directory.

Output includes the two workbook types when rows are ready, a local JSON manifest with source plans/file hashes/full SKU membership, and an incomplete CSV when necessary. Already submitted cached values may be included: state explicitly that this is a cache export, not a fresh scan proving all rows still need maintenance. Do not mark historical pending/rejected/unknown write records as resolved when producing these files.

## Verification and stopping

`tests/test_manual_import_export.py` covers literal string cells, SPU-only rows, exact template preservation, 10000/10001 SPU splitting, more than 10000 title rows, actual byte-size splitting, retained SKU scope, missing/unknown image links and ERP/hash drift. `tests/test_manual_resume.py` covers frozen exclusions and rejects the old unguarded exporter CLI. `tests/test_manual_execution.py` verifies the image-only/manual-delivery boundary, partial recovery and failure isolation. Preserve generated/cache files and frozen write ledgers; no lock removal or automatic production resume is implied.

Report files, counts, bytes and incomplete rows. The success criterion is **upload workbooks generated**, not platform acceptance or score improvement. User uploads material workbooks in the ERP material center and title workbooks in the OSW batch-task creation page. Do not poll or read back those manual imports unless separately requested.
