# OSW product entry and short-title tasks

## Product queries

`https://osw.jd.com/ware/wareList?loginType=2&businessModel=2` is the procurement portal entry. It can embed `https://wares-jdm.jd.com/ware/wareList?businessModel=2&loginType=2`; verify the current iframe URL rather than assuming that these are separate product systems. The embedded page's merchant-facing title does not determine the authenticated business mode.

Both entries can support native ERP identity, explicit selected-SPU visibility and full sibling-SKU reads. Preserve the same ERP, business context, owner/delegated scope, exact selected IDs, native counts and authoritative field checks. Available visibility alone is not ownership or write permission. Never replace the complete sibling set with displayed representative rows.

The OSW portal exposes its native `window.oswAxios` transport. Read-only research has validated the same product-service payloads through that transport and through the existing direct-page fetch implementation. This does not establish identical browser runtimes or permission to bypass either page's authentication. Do not copy an arbitrary direct-page fetch into the portal and treat a transport timeout as proof that the business API is unavailable. Verify the current page and native runtime first; uncertain writes must not be retried as part of transport diagnosis.

Measure page initialization separately from steady-state business queries. Alternate both routes on the same frozen SPU/SKU sample, compare complete returned values, and retain failed probes outside successful-latency statistics. A small median difference across a few runs is not a general speed guarantee. Avoid new duplicate tabs: use automation-owned sessions only, reuse each session during its comparison, and do not touch user work tabs.

## Two short-title routes

| Route | Payload | Completion evidence |
| --- | --- | --- |
| Product-service direct update | `dsm.product.manage.SkuInfoWriteViewService.batchUpdateShortTitle`; rows contain only `productId`, `skuId`, `shortTitle` plus native access context | Exact per-row outcomes and independent authoritative SKU readback |
| OSW batch task | `POST https://sitebatchnew.jd.com/site/new/task/addtaskV2`; multipart `upload`, `type=272`, `taskname` | Task identity, complete downloaded row log, downloaded source SHA and independent authoritative SKU readback |

The OSW workbook has only `skuId` and `短标题` columns. `272` is a task type, not a product category ID. Preserve the official template and its file-size rules. The task processor is `batchModifyShortTitleMerge`; the observed task configuration uses `siteId=384`. Recheck current native configuration and permission before a new task; that site ID is not a shop ID.

These routes do not send a category ID in the short-title rows. The backend can still validate existing product/category relationships while updating SKU attributes. A category error does not prove the agent sent or changed a category. Direct updates and OSW tasks can produce different outcomes for sibling SKUs under the same SPU. OSW has repaired definite direct-update rejections, but it can also reject updates with category-not-found errors. Do not infer the platform's internal deletion/migration cause or change categories to force success.

Programmatic Excel submission eliminates manual uploading, not the asynchronous task queue. Authorization to avoid manual work is not automatically a requirement to avoid every Excel-backed API; an explicit no-import-task restriction still applies. Explain this distinction when choosing the route.

## Task and row outcomes

An overall OSW `status=3` can coexist with successful rows. It must not turn the entire workbook into a retry queue. Preserve each successful SKU and its exact title; failed rows retain native reasons. Task `status=0` alone is also not enough to prove a field update.

Use native task queries at `/site/task/taskInfosNew`, source download at `/site/task/downsourcefile` and row-log download at `/site/task/downlog`. Match the exact returned task ID, task name, creator ERP and type. Freeze workbook bytes, request fields, source plan and complete sibling membership before upload. Persist an unknown intent before the single create call. A lost create response is reconciled by task records, not another create call.

After a terminal task state, verify the source file SHA, exact row-log membership and actual short titles. Separate matching rows, definite rejected rows, accepted-but-not-yet-matching rows and unresolved writes. Any unexpected sibling change or incomplete readback requires reconciliation. Keep successful rows when another row fails, and never resubmit the same native rejection merely to benchmark it.

To test a different route after a definite rejection, preserve the original rejected request and SHA, confirm the target is still unchanged and there is no accepted or unknown write for that SKU, then submit the same authorized title through the explicitly selected route. Do not treat different routes as interchangeable retries for an uncertain result.

## Current implementation boundary

The default `run-direct` and `run-titles` implementation uses the product-service direct update. With explicit authorization, add `--short-title-transport osw` to either runner or `maintain-self-operated`. This selects native OSW automatic tasks for the existing frozen title fields; manual delivery and POP remain unchanged. It does not automatically fall back after an uncertain write.

The task page is initialized once per client and reused. Native ERP verification still runs on every action. Each task keeps its source workbook, single-create intent, task ID, downloaded source, row log and SHA under the original batch's `.state/osw-title-tasks`. A restart may look up an uncertain task by its exact name, but never recreate it. Missing/ambiguous task records, changed source bytes, pending tasks after the bounded query window or incomplete row logs stop for reconciliation.

Switching an existing product-route audit archives its original bytes and SHA. Only definitive old product-route rejections become eligible for the explicitly selected OSW route; accepted titles remain retained, and unresolved product writes block the switch. OSW row rejections are not automatically retried. Partial successes and failures flow into the existing title audit and exact sibling readback. Read external comparison/repair handoffs before resuming and import their matching values and definitive failures into the canonical segment first; this transport does not discover external receipts automatically.

Regression coverage in `test_osw_title_tasks.py` includes partial task failure, cached source tampering, unknown-create no-replay, old-route archive preservation, accepted-row reuse, OSW-rejection skip, CLI isolation and page initialization reuse. Production scope validation and the existing full-SKU readback regressions remain mandatory.

Report request acceptance, row success, persisted target matches, approval and information-score refresh separately. A fast rejection is not successful throughput, and one route with zero successful writes cannot establish a successful-latency comparison against the other.
