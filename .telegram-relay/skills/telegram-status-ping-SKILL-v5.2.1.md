---
name: telegram-status-ping
description: Mirror every complete ChatGPT response and all Telegram task notifications to Telegram, make every v5.2 outbound message replyable for 10 minutes, and consume user-initiated Telegram follow-ups in the live ChatGPT turn when possible. Preserves the v5.1 blocker-question path and provides a one-action rollback to v5.1.
version: 5.2.1-replyable-complete-response-large-file-fast-ack
---

# Telegram Complete-Response Mirror + Replyable Control

## Goal

Keep the user informed outside ChatGPT without requiring them to watch the chat.

Use this skill automatically for every task in this project.

When v5.2 is enabled, use the v5.2 unified relay for every normal completion/error/status notification **and for the complete substantive ChatGPT response itself**. Every v5.2 outbound message gets a 10-minute general reply window.

When progress is blocked by a user decision or short text answer **and the current ChatGPT turn can remain active**, keep using the dedicated v5.1-compatible Telegram question path. Explicit yes/no or multiple-choice questions should use buttons when that improves speed; free-text blockers use forced reply. The v5.2 inbound webhook is backward-compatible with this question path.

Send a Telegram ping when:

- the requested task is fully completed;
- a major deliverable or long-running stage is completed;
- work is blocked and the user must provide information, permission, a login, consent, a file, a choice, CAPTCHA/2FA, a Telegram token, or another action;
- an error prevents completion;
- the user explicitly requests a status update.

Do not ping for routine narration, tiny intermediate steps, or duplicate updates.

### Mandatory complete-response mirroring rule

For every substantive assistant response in this project, send the **complete user-facing response** to Telegram before ending the ChatGPT turn.

This includes:

- ordinary answers and explanations;
- task completion responses;
- blocker/error responses;
- research summaries and recommendations;
- implementation reports;
- responses that also include final file deliverables.

Rules:

- mirror the complete response, not merely a short completion summary;
- use `kind: "response"` through the v5.2 unified relay;
- assign a fresh UUID v4 `thread_id` for a new response thread, or reuse the current v5.2 `thread_id` when answering a Telegram follow-up in the same live conversation;
- use a 600-second reply window unless the user explicitly requests a shorter safe window;
- if the response exceeds one Telegram message, let the unified relay split it into safe chunks; every chunk must be registered as replyable under the same `thread_id`;
- if the response exceeds the v5.2 relay maximum, split it into multiple sealed `kind: "response"` deliveries using the same `thread_id`;
- do not replace final deliverable delivery with mirrored text; the mandatory final-deliverable delivery rule still applies separately;
- do not claim the response was mirrored until GitHub Actions reports the Telegram `message_id`/`message_ids` returned by the v5.2 relay.

### Mandatory 10-minute replyability rule

Every Telegram message sent by v5.2 must be replyable for 10 minutes after delivery, including messages emitted directly by the inbound webhook or pickup-acknowledgement path.

This includes:

- complete mirrored responses;
- completion notifications;
- blocker/error notifications sent through the normal v5.2 relay;
- photos, audio, video, document/file deliveries, and large-file link deliveries;
- follow-up answers sent back to Telegram;
- webhook-generated `📥`, `⌛`, empty-reply, late-reply, unmatched-reply, and informational notices;
- `✅ ChatGPT picked up...` acknowledgements.

Every such message must be registered in `telegram_reply_windows`. The rule is literal: a Telegram notice is non-compliant if the user cannot reply directly to that specific Telegram message during its 10-minute window.

The v5.2 unified relay must create a `telegram_reply_windows` record for every returned Telegram message ID. A multi-part response creates one replyable window record per Telegram message, all tied to the same `thread_id`.

The user may initiate a follow-up by replying directly to **any** message in that 10-minute window. The follow-up does not need to be prompted by ChatGPT.

### General user-initiated follow-up lifecycle

The v5.2 inbound webhook stores a timely reply in `telegram_followups` with status `received`.

State model:

```text
received -> consumed
late
```

- `received`: Telegram accepted the user reply and the relay stored it during the active 10-minute window.
- `consumed`: ChatGPT actually picked up the follow-up.
- `late`: the user replied after the window closed; save it, but do not silently pretend the old live turn resumed.

For a live `received` follow-up:

1. call `telegram_wait_for_followup(thread_id, wait_seconds)` in bounded intervals; use a 10-second poll by default and never ask one call to wait more than 15 seconds;
2. the RPC checks approximately every 0.5 seconds while that bounded call is active;
3. read `reply_text` / `reply_value` as the next user message;
4. call `telegram_mark_followup_consumed(followup_id)` and require `true`;
5. that consume RPC asynchronously invokes `telegram-consumption-ack-v52` through Supabase `pg_net`, so Telegram gets the `✅ ChatGPT picked up...` acknowledgement without another GitHub Actions round trip;
6. answer the follow-up in the same ChatGPT turn;
7. mirror that new complete response back to Telegram under the same thread when conversational continuity is useful;
8. open a fresh 10-minute reply window for the new assistant response.

The direct pickup acknowledgement is itself registered as replyable for 10 minutes. Do not wait for the complete follow-up answer before confirming pickup.

When the current ChatGPT turn has already ended, Telegram cannot wake that finished turn by itself. The webhook still stores the timely follow-up. At the start of the next project turn, inspect `telegram_list_unconsumed_followups(...)` and consume relevant saved follow-ups before they are lost or forgotten. Never claim that a finished ChatGPT turn was resumed automatically when it was not.

### Live Telegram continuation behavior

After a complete response is mirrored to Telegram, keep the current ChatGPT turn available for the reply window when the execution environment permits it. Poll in bounded intervals rather than one unbounded call.

If a Telegram follow-up arrives while the turn is live, treat it as a genuine new user message and continue the conversation without requiring the user to retype it in ChatGPT.

If the environment cannot remain live for the entire 10 minutes, fail gracefully: preserve the follow-up server-side and pick it up on the next ChatGPT turn. Do not fake background execution.

For explicit yes/no or finite-choice questions initiated by ChatGPT, use the existing button-capable question relay rather than encoding pseudo-buttons into ordinary response text.

### Mandatory final-deliverable delivery rule

If a task creates, edits, converts, repairs, exports, or otherwise produces one or more **final user-facing files**, Telegram must receive the deliverable itself when it fits the verified Telegram path, or a verified temporary download link when the file is too large for direct Telegram delivery. A text-only completion ping is not sufficient.

Rules:

- deliver every final artifact that the user is expected to download, open, review, install, submit, or reuse;
- send the final version, not an intermediate, preview, stale, or superseded copy;
- for a modified input file, deliver the modified output that represents the completed task;
- if there are multiple final deliverables, deliver all of them unless the user explicitly asked for only a subset;
- for a direct Telegram attachment, require the attachment's returned Telegram `message_id`;
- for an oversize temporary-link delivery, require both a successfully created temporary-host link **and** the Telegram `message_id` of the replyable link message;
- do not mark the Telegram completion requirement satisfied merely because a separate text status message was delivered;
- never weaken privacy just to satisfy delivery. A sensitive/private oversize file must be encrypted **before** third-party temporary hosting; if that cannot be done safely, report the Telegram deliverable as blocked rather than uploading plaintext;
- if neither direct attachment nor a verified safe overflow route is available, treat Telegram completion as **blocked/incomplete** and report the exact limitation.

A task with final file deliverables is Telegram-complete only when each required deliverable is either **verified as directly attached** or **verified as available through an approved temporary-link overflow path**.

---

## Production architecture

### v5.2 parallel path

The v5.2 path is additive and reversible. It does **not** overwrite the preserved v5.1 functions/workflow.

```text
ChatGPT complete response / normal notification / media
  -> encrypt locally with current relay public key
  -> public GitHub issue `telegram-v52: ...` containing ciphertext only
  -> `.github/workflows/telegram-v52.yml`
  -> GitHub OIDC
  -> Supabase `telegram-unified-relay-v52`
       -> deliver to Telegram
       -> register every Telegram message ID in `telegram_reply_windows`
  -> Telegram
       -> user may reply directly for 10 minutes
  -> `telegram-inbound-webhook-v52`
       -> preserve v5.1 blocker-question handling first
       -> otherwise store general reply in `telegram_followups`
  -> live ChatGPT polls `telegram_wait_for_followup`
```

Activation/rollback uses encrypted `telegram-v52-control:` issues through the same v5.2 workflow and Supabase `telegram-v52-control`.

The original architecture below remains the preserved **v5.1 fallback** and continues to serve explicit blocker questions.

```text
ChatGPT
  -> build the private status/media payload
  -> encrypt payload locally with the current RSA relay public key
  -> public GitHub issue containing ciphertext only
  -> free GitHub Actions runner
  -> GitHub OIDC identity token
  -> Supabase Edge Function: telegram-status-relay
       -> validate GitHub OIDC claims
       -> decrypt the sealed payload with the RSA private key from Supabase Vault
       -> prepare text/media
       -> call Telegram Bot API directly
  -> Telegram
```

Netlify is no longer part of the critical delivery path.

Never fall back to the old private `Veektall/fluent-booking-site` Actions/Netlify Telegram relay.

### Relay repository

```text
Veektall/MyTorchlightApp-
```

Workflow:

```text
.github/workflows/telegram-status.yml
```

v5.2 workflow:

```text
.github/workflows/telegram-v52.yml
```

Current relay public key file:

```text
telegram-relay-public.pem
```

Always fetch `telegram-relay-public.pem` from `main` immediately before encrypting a new payload. Never cache a previous key across unrelated runs.

### Supabase relay

Project:

```text
kwulmnvxhybbxlsdcwcn
```

Function slugs:

```text
telegram-status-relay
telegram-question-relay
telegram-inbound-webhook
telegram-reply-expiry-watch
```

v5.2 additional slugs:

```text
telegram-unified-relay-v52
telegram-inbound-webhook-v52
telegram-v52-control
telegram-inline-document-v52
telegram-large-file-link-v52
telegram-consumption-ack-v52
```

`telegram-status-relay` handles one-way completion/blocker/media delivery. `telegram-question-relay` sends interactive questions. Telegram replies arrive through `telegram-inbound-webhook`; `telegram-reply-expiry-watch` closes live wait windows and sends expiry notices.

The function uses custom GitHub OIDC validation, so platform `verify_jwt` is intentionally disabled. The function itself performs strict authorization.

Private server-side data belongs in Supabase Vault. Never place the Telegram bot token or RSA private key in GitHub, chat text, generated files, or public logs.

---

## Supported Telegram payloads

### v5.2 complete response

```json
{
  "kind": "response",
  "thread_id": "UUID_V4",
  "reply_window_seconds": 600,
  "message": "Complete ChatGPT response..."
}
```

The v5.2 relay accepts complete response text up to 32,000 characters and splits it into Telegram-safe chunks (target approximately 3,800 characters). It returns `message_ids`, `thread_id`, and `expires_at`.

Normal v5.2 text/media payloads also include `thread_id` and `reply_window_seconds` so every outbound message is registered as replyable.

### Small inline text documents

For small UTF-8 text deliverables up to 40 KiB, prefer `telegram-v52-inline:` with Supabase `telegram-inline-document-v52`. Put the document text **inside the private encrypted payload** rather than creating a temporary public staging object. The public GitHub issue remains ciphertext-only. The inline-document relay sends the decrypted bytes as a Telegram document, registers the returned `message_id` in `telegram_reply_windows`, and gives it the same 10-minute reply window.

Use encrypted public staging for larger or binary local/generated files. Never put the plaintext file beside the sealed envelope.

### Text

```json
{
  "kind": "text",
  "message": "Task completed..."
}
```

Maximum status text: 4,000 characters.

### Photo

```json
{
  "kind": "photo",
  "media_url": "https://example.com/image.png",
  "filename": "image.png",
  "mime_type": "image/png",
  "caption": "Completed image."
}
```

### Audio

```json
{
  "kind": "audio",
  "media_url": "https://example.com/audio.mp3",
  "filename": "audio.mp3",
  "mime_type": "audio/mpeg",
  "caption": "Completed audio."
}
```

### Video

```json
{
  "kind": "video",
  "media_url": "https://example.com/video.mp4",
  "filename": "video.mp4",
  "mime_type": "video/mp4",
  "caption": "Completed video."
}
```

### Generic file/document

```json
{
  "kind": "document",
  "media_url": "https://example.com/output.pdf",
  "filename": "output.pdf",
  "mime_type": "application/pdf",
  "caption": "Completed file."
}
```

The relay fetches URL media server-side and uploads the bytes to Telegram using multipart/form-data. Telegram does not need to fetch the original URL itself.

Caption limit: 1,024 characters.

Operational size guardrails:

- photo: at most 10 MB;
- audio: at most 50 MB;
- video: at most 50 MB;
- document/file: at most 50 MB.

Reject oversize direct-media payloads before Telegram staging whenever their size is known.

### Large-file overflow delivery

A file larger than Telegram's verified direct relay limit is **not automatically a failed Telegram deliverable**. Use the v5.2 temporary-link route when the artifact can be transferred safely.

Trigger:

```text
telegram-v52-large: SHORT TASK NAME
```

Supabase route:

```text
telegram-large-file-link-v52
```

Private payload shape:

```json
{
  "thread_id": "UUID_V4",
  "source_url": "https://credential-free-source.example/final.bin",
  "filename": "final.bin",
  "mime_type": "application/octet-stream",
  "size_bytes": 73400320,
  "provider": "auto",
  "sensitive": false
}
```

Production provider policy:

- `> 50 MB` through `<= 100 MB`: prefer **TempFile.org**. The production integration uses its server-side URL-import API, so the relay does not need to buffer the whole file. Configure 24 hours by default; never exceed the provider's 48-hour limit.
- `> 100 MB` through `<= 4 GB`: prefer **temp.sh**. This path has passed a live provider + Telegram smoke test. Files expire after roughly 3 days. The relay streams from an existing safe HTTPS source into the provider rather than buffering the full object.
- `> 4 GB`: no verified free overflow provider is currently configured. Do not claim Telegram delivery support; report the deliverable as blocked or use a separately approved host.
- **file.io is disabled in the automatic production path.** Its documentation advertises file sharing/API upload, but live anonymous upload verification returned HTTP 405 from this relay environment. Do not silently fall back to it.

Security rules for overflow hosting:

- the source URL must be credential-free HTTPS;
- the relay may not expose a local/private plaintext artifact merely to get a share link;
- if `sensitive: true`, require `source_is_encrypted: true`; otherwise reject the third-party upload;
- tell the user which provider holds the temporary file and its approximate expiry;
- the Telegram link message itself gets a fresh 10-minute reply window;
- only call the overflow delivery complete after the provider returns a usable link and Telegram returns the link message's `message_id`.

Current implementation boundary: the overflow relay can transfer an artifact that already has a safe HTTPS source. It does **not** magically upload an arbitrary local-only multi-gigabyte ChatGPT artifact without first establishing a safe transfer source. Do not hide this boundary.

---

## Local/generated files

A normal ChatGPT artifact often has no Telegram-fetchable public HTTPS URL.

Under the mandatory final-deliverable delivery rule, a final local/generated artifact that fits the direct Telegram route must still be attached; use the encrypted staging procedure below rather than replacing the attachment with a text-only status ping. If it exceeds the direct limit, use the approved overflow-link route only when its security/source requirements are satisfied.

Do not expose the plaintext artifact publicly just to send it to Telegram.

Use encrypted GitHub staging.

### 1. Encrypt the file locally

Generate:

- a fresh random 32-byte AES key;
- a fresh random 12-byte IV.

Encrypt the **raw file bytes** with:

```text
AES-256-GCM
AAD: none
Tag: standard 16 bytes / 128 bits
```

Store the AES-GCM output bytes exactly as ciphertext followed by the GCM tag, matching Web Crypto / Python `AESGCM.encrypt(...)` semantics.

Never reuse the staged-file key or IV.

### 2. Stage only ciphertext

Write the encrypted bytes to the public relay repository under a unique path such as:

```text
.telegram-relay/staging/<uuid>.enc
```

Security requirements:

- use only `Veektall/MyTorchlightApp-`;
- use only the `.telegram-relay/staging/` path;
- only `.enc` objects are accepted;
- never put the AES key, IV, plaintext file, token, or caption beside the ciphertext;
- never commit plaintext local artifacts;
- use a binary-safe GitHub operation for the ciphertext bytes. Do not route arbitrary binary ciphertext through a UTF-8 text file helper.

### 3. Put the file decryption material inside the already-encrypted status payload

Instead of `media_url`, send:

```json
{
  "kind": "document",
  "caption": "Finished output.",
  "staged_file": {
    "url": "https://raw.githubusercontent.com/Veektall/MyTorchlightApp-/main/.telegram-relay/staging/<uuid>.enc",
    "key": "BASE64_32_BYTE_AES_KEY",
    "iv": "BASE64_12_BYTE_IV",
    "filename": "output.pdf",
    "mime_type": "application/pdf"
  }
}
```

The `staged_file.key` and `staged_file.iv` are secret decryption material. They are allowed **only because the entire JSON payload is itself sealed with the status-payload RSA/AES envelope below**.

The GitHub issue body remains ciphertext-only.

### 4. Supabase private staging and cleanup

For a valid staged file, Supabase must:

1. validate the raw GitHub URL belongs to the approved repository and staging prefix;
2. fetch the ciphertext with a hard byte limit;
3. decrypt it with the staged-file AES key/IV;
4. reject an empty or oversized plaintext;
5. upload the plaintext bytes temporarily into private Supabase Storage bucket:

```text
telegram-relay-staging
```

6. send the plaintext bytes to Telegram;
7. delete the private Storage object in a `finally` cleanup step.

The Storage object is never public. It exists only long enough to prove private staging works and to keep the file off public plaintext infrastructure.

After verified Telegram delivery, delete the encrypted `.telegram-relay/staging/<uuid>.enc` path from `main`.

Do not claim the media pipeline is clean until both temporary Storage and the public encrypted staging object are gone.

---

## Encrypt the status payload

### 1. Build private plaintext JSON

Build the normal text/media payload as compact UTF-8 JSON.

Never place the Telegram bot token in this payload.

### 2. Seal it

For every new payload:

1. fetch the current `telegram-relay-public.pem` from `main`;
2. generate a fresh random 32-byte AES key;
3. generate a fresh random 12-byte IV;
4. encrypt the JSON with AES-256-GCM and no AAD;
5. wrap the AES key with the relay RSA public key using RSA-OAEP with:
   - OAEP hash: SHA-256;
   - MGF1 hash: SHA-256;
6. base64-encode:
   - wrapped AES key;
   - IV;
   - ciphertext + GCM tag.

The **public** issue body must contain only:

```json
{
  "v": 1,
  "wrapped_key": "BASE64_RSA_OAEP_WRAPPED_AES_KEY",
  "iv": "BASE64_AES_GCM_IV",
  "ciphertext": "BASE64_AES_GCM_CIPHERTEXT_WITH_TAG"
}
```

Do not place plaintext task text, filenames, credentials, or file-decryption keys next to this envelope.

---

## Create the trigger issue

Use the public repository:

```text
Veektall/MyTorchlightApp-
```

For v5.1 normal status/media delivery use a title beginning with:

```text
telegram-status:
```

For v5.1-compatible blocker questions use:

```text
telegram-question:
```

For v5.2 normal complete response/status/media use:

```text
telegram-v52:
```

For v5.2 control/rollback use:

```text
telegram-v52-control:
```

For small v5.2 inline text documents use:

```text
telegram-v52-inline:
```

For large-file link delivery use:

```text
telegram-v52-large:
```

The issue body is the sealed envelope only.

Do not add plaintext secret task descriptions, Telegram credentials, token hints, private media URLs, or secret labels.

---

## Delivery verification

Creating the issue means **queued**, not delivered.

After creating the issue:

1. fetch the issue comments;
2. if no bot result exists yet, say the relay is queued/running, not delivered;
3. wait for the existing run rather than creating duplicate issues;
4. treat the delivery as successful only when `github-actions[bot]` comments a successful result containing the Telegram `message_id` or `message_ids`.

For v5.1 the expected live-success form is:

```text
Telegram delivered successfully. Message ID: <id>
```

For v5.2 the expected live-success form is:

```text
Telegram v5.2 delivered successfully. Message ID: <id>; Message IDs: [...]; Thread ID: <uuid>; Reply window expires: <timestamp>
```

If the issue exists but the bot comment is absent, do not claim delivery.

For tasks with final file deliverables, verify the `message_id` for each required direct attachment, or for oversize artifacts verify both the temporary-host link and the Telegram link-message `message_id`. A verified text-only status message does not satisfy the final-deliverable delivery rule.

---

## Credential-free relay preflight

Use a preflight whenever you change the relay architecture or media handling before a Telegram token is available, or when you want to test the real encrypted route without sending a Telegram message.

Add this field inside the **private encrypted payload**:

```json
{
  "dry_run": true
}
```

A dry run still uses:

```text
ChatGPT
  -> RSA/AES sealed GitHub issue
  -> GitHub Actions
  -> GitHub OIDC
  -> Supabase relay
```

but Supabase validates/prepares the payload without calling Telegram.

For media, preflight also performs the real media fetch/preparation step. For encrypted local staging it must also:

- fetch the encrypted GitHub staging object;
- decrypt it;
- upload the plaintext to private Supabase Storage;
- report `storage_tested: true`;
- delete the temporary private Storage object.

The GitHub bot comment must explicitly say **preflight**, for example:

```text
Telegram relay preflight passed. Kind: document; bytes: 12345; private storage tested: true.
```

Never describe a preflight as Telegram delivery.

---

## v5.2 general follow-up polling and fast pickup

For a normal v5.2 response/notification/media/link thread, wait with:

```sql
select *
from public.telegram_wait_for_followup('THREAD_UUID'::uuid, 10);
```

The default wait is 10 seconds and each call is clamped to at most 15 seconds. Re-call it while the same ChatGPT turn is live and the reply window remains active.

When it returns `received`:

```sql
select public.telegram_mark_followup_consumed('FOLLOWUP_UUID'::uuid);
```

Require `true`. This marks the follow-up consumed and asynchronously invokes `telegram-consumption-ack-v52` through `pg_net`. The acknowledgement goes directly Supabase -> Telegram rather than Supabase -> GitHub issue -> Actions -> Telegram.

Production latency target: once ChatGPT has detected the follow-up and marks it consumed, the `✅` Telegram pickup acknowledgement should normally dispatch within a few seconds. A live v5.2.1 test measured approximately **1.71 seconds from `consumed_at` to `pickup_ack_sent_at`**.

`📥` remains the webhook's immediate relay-receipt signal. `✅` is the separate proof that ChatGPT actually consumed the stored follow-up.

---

## Two-way Telegram blocker questions

Use the interactive path only when all of the following are true:

- progress is blocked by exactly one user choice or short text answer;
- the answer is safe to accept from the configured Telegram chat;
- the current ChatGPT turn can remain alive long enough to wait for the answer;
- the decision does not require a file upload, login flow, CAPTCHA, 2FA, secret credential, or other interaction that Telegram text/buttons cannot safely carry.

For a question with a small set of options, prefer Telegram buttons. For a free-text answer, use a forced reply.

For secrets, files, CAPTCHA/2FA, consent screens, or other actions that cannot be safely completed as a Telegram text/button reply, send a normal blocker status ping instead.

### Question payload

Use a fresh UUID v4 `request_id`.

```json
{
  "kind": "question",
  "request_id": "UUID_V4",
  "prompt": "Continue with the destructive cleanup?",
  "timeout_seconds": 600,
  "options": [
    { "label": "Yes", "value": "yes" },
    { "label": "No", "value": "no" }
  ]
}
```

Rules:

- `prompt` must be non-empty and at most 3,500 characters;
- `timeout_seconds` must be 15..600;
- `options` may contain at most 8 choices;
- each option label is at most 60 characters;
- each option value is at most 500 characters;
- if `options` is empty or omitted, use a free-text forced reply.

When `options` is non-empty, Telegram uses inline buttons. Otherwise it uses a forced direct reply.

### Encrypt and trigger the question

Encrypt the private question JSON using the same fresh AES-256-GCM + RSA-OAEP-SHA256 procedure described above.

Create a public issue with a title beginning:

```text
telegram-question:
```

The v5.1 workflow routes that issue to:

```text
telegram-question-relay
```

Do not consider the question delivered until GitHub Actions reports a Telegram `message_id`.

That `message_id` proves Telegram accepted the question.

### Live wait loop

After verified question delivery, wait for the reply using the production database function:

```sql
select *
from public.telegram_wait_for_reply('REQUEST_UUID'::uuid, 80);
```

`p_wait_seconds` is clamped to 1..100 seconds. Re-call it as needed while the same ChatGPT turn is alive and while `seconds_remaining > 0`.

Possible statuses:

- `waiting` — no reply yet; continue the live wait loop if the turn can stay active;
- `received` — Telegram relay has accepted a timely reply;
- `consumed` — ChatGPT already picked up the reply;
- `expired` — the active response window closed with no timely reply;
- `late` — a reply arrived only after expiry;
- `missing` — the request record does not exist.

Do not claim that ChatGPT received the user's answer merely because the webhook stored it. `received` means the relay has it; ChatGPT pickup is a separate step.

### Consume a timely reply

When the wait function returns `received`:

1. read `reply_value` as the machine-usable answer and `reply_text` as the display form;
2. immediately mark the response picked up:

```sql
select public.telegram_mark_chatgpt_picked_up('REQUEST_UUID'::uuid);
```

3. require the function to return `true`;
4. send a normal encrypted status ping such as `✅ ChatGPT picked up your Telegram reply and is continuing the task.`;
5. require a Telegram `message_id` for that pickup acknowledgement;
6. continue the original task using the reply.

The pickup acknowledgement is intentional. The inbound webhook first tells the user that the relay received the answer (`📥`); this second ping confirms that ChatGPT itself consumed it (`✅`).

Do not echo sensitive reply contents in the acknowledgement.

### Expiry and late replies

The question relay launches `telegram-reply-expiry-watch`. When the active window closes, it marks pending requests `expired` and sends a Telegram `⌛` notice.

If the user answers after expiry, the webhook records the answer as `late` and tells the user that the old ChatGPT turn will not resume automatically.

When the live wait loop returns `expired` or `late`:

- stop polling;
- do not consume the reply into the old turn;
- do not pretend the task resumed;
- finish the current ChatGPT turn as blocked, stating that the active Telegram reply window closed.

A later ChatGPT turn may inspect the stored late reply and decide whether it is still safe/relevant to use, but must not silently treat it as if it arrived during the original live decision window.

### Webhook configuration

The Telegram webhook is an infrastructure operation, not something to repeat on every task.

The production webhook URL is:

```text
https://kwulmnvxhybbxlsdcwcn.supabase.co/functions/v1/telegram-inbound-webhook
```

When v5.2 is active, the production webhook URL is:

```text
https://kwulmnvxhybbxlsdcwcn.supabase.co/functions/v1/telegram-inbound-webhook-v52
```

`telegram-question-relay` can configure the v5.1 webhook using an encrypted `configure_webhook` payload. v5.2 activation/rollback uses `telegram-v52-control` to swap and verify the appropriate webhook URL.

The webhook must accept only Telegram `message` and `callback_query` updates and must authenticate Telegram with the Vault-backed webhook secret.

Never expose the webhook secret or bot token.

### Two-way production state

Database tables:

```text
public.telegram_pending_requests
public.telegram_inbound_updates
public.telegram_reply_windows
public.telegram_followups
public.telegram_relay_feature_flags
```

RPCs:

```text
public.telegram_wait_for_reply(uuid, integer)
public.telegram_mark_chatgpt_picked_up(uuid)
public.telegram_wait_for_followup(uuid, integer)
public.telegram_list_unconsumed_followups(integer)
public.telegram_mark_followup_consumed(uuid)
public.telegram_v52_enabled()
```

v5.1 blocker lifecycle:

```text
pending
  +-> received -> consumed
  |
  +-> expired -> late (if a reply arrives after closure)
```

v5.2 general lifecycle:

```text
reply window
  +-> received -> consumed
  |
  +-> late
```

Security controls:

- RLS enabled on all Telegram state tables;
- no public RLS policies;
- polling/consume RPCs restricted to `service_role` and `postgres`;
- webhook accepts only the configured Telegram chat ID;
- Telegram webhook secret-token header required;
- duplicate Telegram `update_id` values are ignored;
- replies must target the exact Telegram message ID of an active request/window;
- public GitHub issues remain ciphertext-only;
- user replies are never accepted as a channel for credentials, BotFather tokens, 2FA codes, or other secrets.

---

## Telegram token provisioning

The production Telegram bot token belongs in Supabase Vault under:

```text
telegram_bot_token
```

Never ask the user to paste the BotFather token into the normal ChatGPT conversation.

Preferred provisioning path:

1. reuse an existing valid Telegram bot token from another **private connected secret store** when the user has authorized the migration;
2. transfer it secret-to-secret without exposing the plaintext token in assistant-visible output;
3. normalize an optional leading `bot` prefix if the source stores it that way;
4. store the destination token in Supabase Vault;
5. verify it with a real live Telegram delivery and returned `message_id`;
6. only after successful destination verification, delete the source secret if the user explicitly requested migration/removal;
7. verify the source secret is gone.

If no private source secret exists, use Supabase's authenticated Vault/Secrets UI or another authenticated provider-owned secret-entry surface.

Do not create or use a custom public credential page merely to collect the Telegram bot token.

### Never retrieve a credential for display

Do not use Netlify, Supabase, GitHub, or any other tool to retrieve the Telegram token merely so it can be shown, echoed, summarized, logged, cited, or reproduced in ChatGPT.

Credential migration is complete only when:

- the destination secret exists;
- live Telegram delivery succeeds;
- a Telegram `message_id` proves delivery;
- any explicitly requested source cleanup has been verified.

---

## Failure handling

### `Telegram relay failed.`

Inspect:

1. the GitHub Actions workflow run;
2. the safe diagnostic class in the run logs;
3. Supabase Edge Function logs if needed.

Do not create duplicate issues while the first workflow is merely queued or in progress.

### Token missing

If the relay reports that the Telegram token is not configured:

- do not attempt to display or retrieve the secret;
- use the approved private provisioning path above;
- verify with a live message after provisioning.

### Encryption/decryption failure

If the relay cannot open a sealed payload:

- fetch `telegram-relay-public.pem` again from `main`;
- create a **fresh** AES key and IV;
- re-encrypt the full payload;
- create a new issue;
- never reuse the failed AES key, IV, or sealed envelope.

### Media fetch/staging failure

Check only:

- HTTPS source URL validity;
- approved GitHub staging path;
- media size;
- MIME type;
- sanitized filename;
- AES key length = 32 bytes;
- IV length = 12 bytes;
- whether private Storage cleanup occurred.

Never expose the token or private key while debugging.

### GitHub tool unavailable

The supported production route requires GitHub issue creation because GitHub OIDC authorizes Supabase.

If GitHub tooling is unavailable:

- report that Telegram delivery cannot currently be triggered;
- do not fall back to a public plaintext issue;
- do not fall back to the old private billing-dependent repo.

---

## Keepalive

To reduce Supabase free-project inactivity risk, the public relay workflow includes a daily keepalive job.

It sends a lightweight `HEAD` request to the Supabase relay and does **not** send a Telegram message.

Keep it unless the Supabase project moves to a plan/architecture where inactivity is no longer relevant.

---

## Security invariants

- Public GitHub issue: ciphertext only.
- Public GitHub staged media: ciphertext only.
- Fresh AES key + IV for every status envelope.
- Fresh AES key + IV for every staged local file.
- Relay RSA private key: Supabase Vault only.
- Telegram bot token: Supabase Vault only.
- Telegram token never passes through ChatGPT.
- Telegram token never passes through GitHub.
- No Netlify dependency for delivery.
- No fallback to private GitHub Actions billing-dependent workflows.
- HTTPS-only external media.
- Approved-repository/path restriction for encrypted staging.
- Remove temporary private Storage objects after media preparation/delivery.
- Remove encrypted GitHub staging paths after verified completion.
- Require Telegram `message_id` before saying a message was delivered.
- When the task produces final user-facing files, require each deliverable to be either directly attached and verified or, only when oversize, delivered through an approved verified temporary-link path; text-only completion is non-compliant.

---

## Current implementation test standard

Before declaring a relay architecture change healthy, require:

1. text preflight through a real encrypted issue;
2. local encrypted-file preflight;
3. successful private Storage staging;
4. zero leftover private staging objects after cleanup;
5. after a Telegram token is configured, one live test each for:
   - text;
   - photo;
   - audio;
   - video;
   - document/file;
6. a valid Telegram `message_id` for every live one-way test;
7. two-way webhook configuration verified;
8. one live button question that transitions `pending -> received -> consumed`;
9. one live free-text question that transitions `pending -> received -> consumed`;
10. one expiry test that produces the Telegram `⌛` closure notice;
11. one late-reply test that records `late` and does not resume the old turn;
12. a verified pickup acknowledgement status ping after each consumed live reply;
13. a live final-deliverable task where the actual generated file is attached to Telegram and its attachment `message_id` is verified, proving that text-only completion cannot satisfy the deliverable rule.
14. one live v5.2 complete-response delivery with a verified `message_id` and registered 10-minute reply window;
15. one live **user-initiated** reply to a normal v5.2 response that transitions `received -> consumed` without an assistant-initiated question;
16. verification that the v5.2 feature flag is reversible and that `rollback_v51` restores the v5.1 webhook;
17. RLS enabled on `telegram_reply_windows`, `telegram_followups`, and `telegram_relay_feature_flags`, with v5.2 RPCs executable only by `service_role`/`postgres`.
18. one live encrypted inline-text-document delivery proving a small generated text file can reach Telegram without any plaintext public staging object;
19. one live TempFile.org overflow-link test with a verified Telegram `message_id`;
20. one live >100 MB temp.sh overflow-provider test before that provider is allowed in automatic production routing;
21. one measured fast-pickup test proving `telegram_mark_followup_consumed` triggers `telegram-consumption-ack-v52` through `pg_net` and records a Telegram acknowledgement `message_id`;
22. verification that webhook-generated `📥`, `⌛`, informational, unmatched, and pickup-ack messages are themselves registered in `telegram_reply_windows` and are replyable for 10 minutes.

Do not call the relay fully production-tested until the applicable tests above have passed.

---

## v5.2 rollback to v5.1

v5.2.1 is an experimental additive layer. The preserved v5.1 functions and `.github/workflows/telegram-status.yml` must remain intact.

Persistent rollback documentation lives at:

```text
.telegram-relay/rollback/v5.1/ROLLBACK.md
.telegram-relay/rollback/v5.1/STATUS.md
```

### Fast rollback

Create a fresh RSA/AES sealed issue:

```text
telegram-v52-control: rollback
```

with private plaintext payload:

```json
{"action":"rollback_v51"}
```

The control function must perform rollback in this safety order:

1. set `v5_2_general_replies = false`;
2. restore the Telegram webhook URL to `telegram-inbound-webhook`;
3. verify Telegram reports the v5.1 webhook URL;
4. resume the v5.1 skill/protocol.

No destructive database rollback is required. The additive v5.2 tables/RPCs/functions may remain dormant.

### Reactivate v5.2

Use a freshly sealed control payload:

```json
{"action":"activate_v52"}
```

Activation switches Telegram to `telegram-inbound-webhook-v52`, verifies it, and then enables the v5.2 feature flag.

### Rollback invariant

Never delete or overwrite the preserved v5.1 production functions merely because v5.2 is active. A failed v5.2 experiment must remain recoverable by feature-disable + webhook restore, not by reconstructing old code.

---

## Mental checksum

**v5.2.1:** complete response -> Telegram -> every Telegram message is replyable for 10 minutes -> user may initiate follow-up -> 10-second polling detects it -> `pg_net` sends fast `✅` pickup acknowledgement -> answer continues on the same thread.

**Rollback:** disable v5.2 first -> restore v5.1 webhook -> use preserved v5.1 path.


**Delivery:** Encrypt locally; GitHub proves identity; Supabase opens and prepares; Telegram's `message_id` proves arrival. Final files go direct when they fit; oversize files may use a verified temporary link. Text alone does not count.

**Two-way:** `📥` means the relay received the answer; `✅` means ChatGPT consumed it; `⌛` means the live turn stopped waiting.
