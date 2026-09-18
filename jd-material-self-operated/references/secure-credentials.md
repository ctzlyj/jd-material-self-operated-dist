# One-time local credential setup

The old launcher deliberately kept input only in one child process. Another tool call, restarted agent or terminal therefore lost it. Its legacy command allowlist also asked for a key on current read-only commands. These were launcher/setup defects, not evidence of invalid model permission.

Resolve each required slot in order: nonempty current process environment, Windows current-user Environment registry, then this Skill's OS-protected credential store. Read current-user configuration directly so a newly configured key is available even if the desktop agent inherited an older empty environment. Never overwrite a nonempty process credential, change keys after quota/auth failures or copy another person's key. A stale nonempty process environment remains authoritative; `--credential-status` identifies that source without revealing its value.

Only generation commands can request missing input. Help, provider info, handoff/plan/export, verification, `--plan-only` and `--cached-only` do not request keys. The normal `self_operated_cli.py` entry and secure launcher share the same resolver; do not wrap every diagnostic in a fresh key prompt. Single-key mode needs only the primary slot. Explicit dual-key mode asks only for a missing second, distinct key.

## Storage and consent

The masked local dialog explains that confirmation saves to the current OS user's encrypted credential store. Cancel stops once; do not reopen the dialog or fall back to asking in chat. `--session-only` explicitly disables storage. The agent must never pass a key in argv, scripts, logs, generated workbooks, chat or Git.

Windows uses current-user DPAPI, not machine-wide protection. Only encrypted blobs are atomically written under `%LOCALAPPDATA%/JDMaterialSelfOperated/credentials/`; the store is outside the Skill, task and repository. Ordinary upgrades preserve it. New encrypted credentials do not create or change user environment variables. Existing user environment values are read for compatibility, not copied into another store.

macOS uses the OS Keychain through `keyring`; Linux requires Secret Service/libsecret. Plaintext, null and unreviewed third-party backends are rejected. No usable OS keyring means stop with a setup explanation or use explicitly selected session-only mode; never silently save plaintext. Windows DPAPI cross-process behavior is tested on Windows; other OS backends need acceptance on the colleague's actual OS.

Concurrent first-use configuration is serialized per user store and rechecks the saved slot after obtaining the lock, avoiding duplicate dialogs. A crashed configuration lock is not automatically deleted from its historical PID; inspect the actual process first. Damaged/foreign-user ciphertext, locked keyrings and save failures stop with a redacted message instead of repeatedly prompting.

## Agent-operated diagnostics

`python scripts/secure_launcher.py --credential-status` prints only each slot's configured boolean and source, not a key, prefix, length, fingerprint or network validation result. It does not authenticate to the ERP service or call a model.

`python scripts/secure_launcher.py --configure-credentials` configures only missing primary input. Add `--dual-key-images` only if two keys are needed. Already configured slots are reused. A current-user environment value being present does not prove it is valid for production; record the user's/provider's authorization separately, without repeatedly asking for the key.

`python scripts/secure_launcher.py -- <self_operated_cli subcommand and unchanged arguments>` runs a task using the resolver. `--session-only` before `--` keeps newly entered credentials only in the child environment. Setup does not authorize a maintenance scope or resume paused tasks.

Only when the user explicitly requests removal, run `python scripts/secure_launcher.py --forget-credentials --key-slot 1` (or 2). This removes only that encrypted slot, not current/user environment values or product receipts. For rotation, identify the authoritative source, update it explicitly and verify status; never automatically clear working credentials or loop on 401/429.

## Upgrade and validation

Retain the three-way-aware installer and original installation source. The credential-only colleague revision can retain its existing protected `.9` core/version routing; Gemini source changes require separately compatible server core deployment and are not implied by this client fix. Do not distribute a maintainer/private installation to solve credential prompts.

Run `test_secure_credentials.py`, the full relevant source/protected suite and a clean install. Tests use synthetic values: repeated fresh environments, encrypted cross-process reads, current-user environment discovery, no-prompt diagnostics, missing second slot, distinct keys, cancellation, invalid input, damaged store failure, session-only mode, lock recheck and redacted status. Real maintenance, model charges and colleague authorization are separate acceptance steps.
