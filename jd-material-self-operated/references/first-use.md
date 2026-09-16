# First use: owned ERP to direct maintenance

The colleague gives one explicit authorization to generate, upload, bind and read back their own missing product materials. Commands below are executed by the agent, not homework for the colleague. Default manual delivery remains available when explicitly requested.

## Setup

For a protected distribution, first read `protected-service.md`. Verify and install the whole distribution using its `tools/install.py`, retaining the transport companion. Inspect Python, Node and dependency availability and prepare missing tools through O2 first; do not ask the colleague to understand commands. Read the installed Skill directly after installation if automatic discovery has not refreshed. Do not overwrite an unprotected production installation.

The administrator must enable this ERP for the self-operated Skill at the protected service. Plugin and POP eligibility do not apply. HiOffice and the business browser must be logged into the same ERP; the entry checks both and selects a matching connected browser profile in isolated background sessions. If login or Browser Bridge needs human interaction, request only that action, never credentials in chat. A unavailable authorization service is not a skippable product failure.

Use an existing secure `JD_LLM_API_KEY` environment. If absent, run `scripts/secure_launcher.py -- <entry command>` for masked local entry; never request, print, save or copy keys from chat. Do not rotate keys around resource restrictions.

## One entry

`python scripts/self_operated_cli.py maintain-self-operated --confirm GENERATE_UPLOAD_BIND_AND_VERIFY`

Add `--resource-cooldown` only when authorized: same request and key, retry after 60/120 seconds, stop after 300 continuous seconds without recovery. Add `--plan-only` for read-only planning with no model, uploads or product writes.

No ERP argument is required in the protected colleague flow. `--erp` is an optional expected-identity check, never impersonation. The native inventory query is forced to the authenticated owner, not all visible products. `--output-dir` optionally fixes a task location; otherwise the entry uses the normal per-ERP/per-scope Documents directory. Existing first-use tasks reuse frozen plans and completed phases; a changed target or an old split task is rejected rather than overwritten. For a later newly authorized maintenance cycle after completion, the agent selects a new dated directory; do not silently create duplicate tasks during recovery. Never substitute this entry for an already-pending production handoff or lose its exclusions.

The entry freezes `.state/self-operated-plan.json` and a SHA-bound v2 `.state/direct-plan.json`. It does not invent an exclusion ledger, a split pause or an old task. After authorization it executes one SPU, ten SPUs, then the remaining scope, recording stages in `.state/first-use-progress.json`. It shares one background writer, four image workers, at most one image start per second, finite retries and one next-segment prefetch. Every sibling SKU and required field is preserved. Inspect the durable result: a command returning JSON is not proof of completion.

## Failures and evidence

Ordinary failed generation is single-attempt by default. Native rejected SPUs are held before generation/writes and listed with all sibling SKUs for appeal, even when discovery finds other missing fields. Definitive image failure skips later binding/title writes for that SPU; already accepted fields are retained. Only a specific user request for named rejected products permits `--regenerate-rejected-spu-ids <IDs>`, frozen with the plan hash. Do not invent that request from general maintenance authorization or restart a failed SPU in a fresh directory. See `rejected-materials.md`.

An explicitly authorized named delegated scope is an opt-in exception to the default owner filter: add `--include-delegated` with one to fifty `--target-spu-ids` (or one `--target-spu-id`). No unbounded scan is allowed. The same logged-in ERP must receive every selected ID from the native available-permissions query. The frozen v2 origin is `selected-permission-erp-v1`; owner-only plans keep their original origin and cannot be switched on resume. A directly owned empty result alone does not establish lack of delegated access. See `rejected-materials.md` for rejected-field repair and audit accounting.

Product-level inspection failures can be excluded only with complete inventory pagination and explicit nonoverlapping failed SPUs. Preserve the original unsafe inspection result rather than changing it to success. Image/content and known business failures skip the affected work and continue. No new semantic/visual audit and no category changes are introduced. Preserve valid images and all accepted, rejected or unknown receipts. Authentication, scope changes, incomplete global reads, true quota exhaustion and unknown writes require safe interruption/reconciliation; never replay blindly.

`first-use-summary.json` records the result and `全流程失败与待核实SKU清单.csv` combines initial inspection failures and execution failures, retaining all known sibling SKUs and source hashes. An unknown SKU scope is explicitly blank, not guessed. `inspectionFailedSpus` is separate from the runner's pending count. `remainingSpus` includes deferred unresolved SPUs, not just unattempted ones; `finished-with-failures` means all eligible items were attempted, not everything succeeded. An all-failed inspection must not be described as nothing to maintain.

Report real wall time and completed work from immutable segment reports. Synthetic test speed is not production throughput. Distinguish model output, uploaded files, API acceptance, exact persisted readback, final audit and information-score refresh. This entry does not wait for final review or a score refresh. Tell the colleague where the complete failure list is, including on interruption.
