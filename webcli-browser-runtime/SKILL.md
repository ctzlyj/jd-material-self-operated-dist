---
name: webcli-browser-runtime
description: Use when WebCLI repeated uploads hit lexical collisions, browser commands abort after about 30 seconds or replay after lost responses, or preserving tested runtime overlays across official updates.
---

# WebCLI Browser Runtime

Check O2 and read its WebCLI guide first. This supplements native WebCLI browser operations; it does not implement a business API or provide authentication.

## Reproduced defect

WebCLI 1.1.3 `BasePage.evaluateWithArgs` prepends top-level `const` declarations to persistent browser evaluation. A successful first upload leaves `markerAttr` in that context; its cleanup and subsequent uploads redeclare it. The CLI exits 1 with empty stdout and a SyntaxError on stderr. This is not an ERP permission failure or a failed image API response.

The same upstream version also aborts each daemon HTTP request at 30 seconds while browser commands have a 120-second default deadline. `sendCommandRaw` retries an AbortError or lost response with up to four different command IDs. An eval may contain a mutation, so a lost response is not permission to dispatch it again. Three observed roughly 122-second failures had an exact stderr hash matching `This operation was aborted`; the preserved upstream function reproduces four dispatches in regression tests.

## Execution

Resolve the installed Node WebCLI entry point and invoke:

```text
node --import <file-URL-of-webcli-preload.mjs> <webcli-main.js> <unchanged-webcli-arguments>
```

On Windows, encode the absolute preload path as a file URL, for example with Python `Path(...).resolve().as_uri()`; a raw drive-letter ESM specifier is rejected by Node. The process-local overlay gives argument declarations lexical block scope while preserving evaluation completion values, promises, argument serialization and identifier checks. It does not reload or focus tabs, change authentication, retry mutations, modify installed packages, or set global NODE_OPTIONS. Only the caller's explicitly selected session is affected.

Use Node.js 22.15+ with synchronous module hooks; Codex prepares a supported runtime instead of asking colleagues to configure it. The verified transport hook sets an explicit browser deadline (default 120 seconds) and allows another 10 seconds for the HTTP response. It dispatches each command once. Abort, lost/malformed response, daemon timeout, duplicate-ID or ambiguous navigation/disconnection responses become `command_result_unknown`, without leaking transient error wording that would trigger an outer Page retry. Explicit authentication and business errors remain visible. A read-only caller may reconcile and perform a bounded retry itself; write callers must inspect durable receipts and remote state, not replay automatically.

## Validate and stop

Run `node --test <skill-dir>/tests/scoped-arguments.test.mjs`, then transfer at least three files through a dedicated background session and check exact filenames/content hashes. File-input transfer does not itself validate a site's upload API. After any uncertain site upload, independently reconcile remote state before retrying.

Also run `command-transport.test.mjs` and `command-hook.test.mjs`. They exercise the preserved upstream retry defect, deadline alignment, one dispatch after response loss, ordinary error visibility, actual module interception and unchanged package files. A dedicated background-page 35-second in-memory probe must complete with exactly one execution; it does not call a business API. Keep mutation acceptance/readback validation separate from that transport proof.

`upstream-baseline.json` records the observed upstream method hash; `references/upstream-evaluate-with-args.txt` preserves its exact source for three-way merges and has a hash regression test. The patch activates only for that implementation. On an upstream method change, preserve the local overlay, save the upstream candidate under `~/.webcli/patch-candidates/scoped-arguments/<hash>.js`, and stop with `WEBCLI_RUNTIME_MERGE_REQUIRED`. Compare old baseline, local patch and new candidate; update the baseline only after semantic review, regression tests and repeated live file-transfer validation. Unchanged methods continue working across unrelated official updates. Never reset local customizations or edit npm installation files.

The command transport has its own exact source/hash baseline, `references/upstream-send-command-raw.txt`, and merge candidates under `~/.webcli/patch-candidates/command-transport/<hash>.js`. Both guards must pass before the CLI runs. The module hook changes only the loaded verified function, not installed files; unrelated upstream changes remain intact. Preserve local-only files and stage conflicting upstream changes for a three-way merge. Never update hashes merely to bypass a failure.

Rollback means omitting `--import`; no package or global environment is changed. Do not use rollback to ignore repeated-upload failures or blindly retry a possibly accepted mutation. Business Skills should call this helper rather than copy its implementation.

If a transport upgrade cannot be verified, stop writes rather than roll back to the known command-redispatch behavior. Activate changes only after the current writer reaches a checkpoint with no unresolved upload, binding or text-write intents; retain generated files, frozen requests and accepted receipts.
