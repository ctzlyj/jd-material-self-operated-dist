# Bounded browser sessions in custom batch orchestrators

## Reproduced failure

`first_use.owned_client()` derives session names from the resolved output directory. Changing that directory on an existing Python client changes the material, product and image session names and resets initialization flags; it does not release the preceding names. Initial discovery without a supplied client also creates a random identity-probe session before adopting the output-derived name. Repeated custom batches can therefore accumulate tabs despite passing the same Python client and using background mode.

## Validated caller pattern

- Keep one sequential batch owner and its execution lock. Do not run an independent planner alongside the writer merely to improve throughput.
- Before browser I/O, validate the batch root, selected ERP and exact group output. Construct `direct_binding.create_direct_client(args)` with the real ERP, frozen owner mode, output directory and selected profile. Supply that deterministic client to `first_use.plan_new(args, client=client)` and `direct_resume.run_direct(args, client=client)`. This avoids the disposable random first-use session and preserves normal ERP and complete-SKU preflight.
- Reuse the client inside that one group only. Track its exact `session`, `product_session`, `image_session` and `session + '-osw-titles'`. These are at most four dedicated leases; they are not a license to use or close other sessions.
- In `finally`, including after failed discovery, generation or product writes, use existing WebCLI `browser <session> --window background tab list`, then `close` for each nonempty owned session. Verify the same session's list is empty before proceeding. Do not call `bind`, `focus`, broad tab/window closure or URL-based cleanup.
- If the list is malformed, ownership is unclear, multiple unexpected tabs appear, close is uncertain or a tab remains, stop the batch. Do not open the next group. Preserve the exact cleanup receipt and leave unrelated work alone.
- Parent pause must block planning before any identity discovery and at every group boundary. Preserve separate group plans, full SKU scopes, accepted/unknown receipts, valid images, URLs, retry reservations and unresolved cross-group cooldown deadlines. Closing tabs does not cancel or reconcile a product write.

This is a validated orchestration pattern, not a claim that existing unwrapped first-use clients automatically release sessions. It does not change WebCLI packages, protected-service behavior or historical task authorization.

## Validation and retention

Caller tests cover multiple groups with a fixed maximum lease count, no closure of user/other-task leases, exception cleanup, cleanup failure blocking the next group, and rejecting outputs outside the batch root. Two real read-only groups returned their owned sessions to zero; a subsequent ten-SPU generation/upload/binding/title/readback run matched all ten and released its three used leases. These observations validate lifecycle and that bounded run, not a comparative throughput improvement or every future batch.

Keep the caller's lifecycle tests and the pinned safe-transport overlay. After a client/session naming or WebCLI close-contract update, run those tests and two read-only groups before writes. Do not replace package files, clear browser profiles, erase checkpoints or fall back to uncontrolled session creation. If the upstream client later implements release, semantically merge the caller ownership rules rather than stacking two competing lifecycle owners.
