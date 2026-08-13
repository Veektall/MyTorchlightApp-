---
name: telegram-status-ping
description: Mirror every substantive ChatGPT response to Telegram, keep the originating turn alive for a mandatory 10-minute reply tail, rescue replies after abnormal turn termination, accept rich Telegram inputs, and deliver final artifacts. Uses local Whisper for voice transcription and preserves v5.2.2/v5.2.1/v5.1 rollback paths.
version: 5.3.1-enforced-live-tail-poll-loop
---

# Telegram Complete-Response Mirror + Enforced Mandatory Live Tail

## Purpose

Use this skill automatically for every task in this project. Telegram is a second conversation surface, not merely a notification sink.

The operating promise is:

**Answer -> mirror -> verify -> wait 10 minutes -> consume + acknowledge -> understand -> answer again -> restart 10 minutes. No reply -> close naturally.**

The production relay repository is `Veektall/MyTorchlightApp-`. Supabase project: `kwulmnvxhybbxlsdcwcn`.

---

## Rule 0 — Do not terminate the ChatGPT turn while the live tail is active

This is the critical v5.3.1 execution invariant. A Telegram reply window can stay open in Supabase after ChatGPT has already ended its turn; that is **not** a live tail.

In ChatGPT runtimes that expose a visible non-terminal response/update channel plus a terminal `final` channel:

- present the substantive user-facing answer through the visible **non-terminal** channel while work continues;
- mirror and verify that answer on Telegram;
- keep calling the follow-up polling RPC in the **same originating turn**;
- do **not** emit a terminal/final response while the polling result is `waiting`;
- emit the terminal/final response only after the live window has actually expired with no follow-up, or when the runtime forcibly terminates the turn;
- if a follow-up arrives, process it, answer again through the non-terminal visible channel, mirror it, and restart the 10-minute tail before any terminal/final response.

**Important:** returning a visible answer to the user is not the same thing as ending the turn. Ending the turn stops tool execution and therefore stops live polling.

If the runtime has no way to show a visible answer without terminating tool execution, the strict same-turn 10-minute live-tail guarantee is not implementable in that runtime. In that case, preserve the reply window and rely on Inbox Rescue, but do not claim the same-turn tail succeeded.

---

## Rule 1 — Mirror every substantive response

Before ending any substantive ChatGPT response, send the complete user-facing response to Telegram through the v5.2 unified encrypted relay.

This includes ordinary answers, explanations, research summaries, implementation reports, completion reports, blockers, errors, and responses that also contain downloadable artifacts.

Use:

```json
{
  "kind": "response",
  "thread_id": "UUID_V4_OR_CURRENT_THREAD",
  "reply_window_seconds": 600,
  "message": "COMPLETE USER-FACING RESPONSE"
}
```

Rules:

- mirror the complete response, not a shortened completion ping;
- reuse the current thread when continuing a live Telegram conversation;
- otherwise create a fresh UUID v4 thread;
- split long responses safely while keeping all chunks on the same thread;
- every returned Telegram message ID must be registered as replyable;
- issue creation, encryption success, HTTP 200, or preflight are not delivery proof;
- only a verified Telegram `message_id`/`message_ids` proves delivery.

---

## Rule 2 — Every outbound Telegram message is replyable for 10 minutes

Every v5.2/v5.3 Telegram message gets a 600-second reply window unless the user explicitly requests a shorter safe window.

This includes:

- mirrored responses;
- completion/blocker/error notices;
- photos, audio, video, and documents;
- oversize-file link messages;
- follow-up answers;
- `📥` receipt notices;
- `✅` ChatGPT-pickup acknowledgements;
- `⌛` expiry notices;
- other webhook informational notices.

Every outbound message must have a `telegram_reply_windows` record. A multi-part response gets one row per Telegram message ID, all attached to the same thread.

The user may initiate a new follow-up by replying directly to any still-active message. ChatGPT does not need to ask first.

---

## Rule 3 — Mandatory 10-minute conversational tail

A Telegram reply window alone is not enough. **Every substantive response must keep the originating ChatGPT turn actively alive for the full reply window.**

After sending a substantive response:

1. mirror it to Telegram;
2. verify Telegram delivery and capture `thread_id` plus expiry;
3. show the response to the user;
4. do **not** end the ChatGPT turn;
5. repeatedly call:

```sql
select *
from public.telegram_wait_for_followup('THREAD_UUID'::uuid, 10);
```

The `10` above is **one short-poll slice (about 10 seconds), not the total reply-window duration**. Production intentionally caps one database wait call at 15 seconds. Therefore a healthy 10-minute tail requires many consecutive calls.

6. inspect the returned status and obey this loop exactly:

```text
waiting  -> DO NOT END THE TURN; immediately call telegram_wait_for_followup(...) again
received -> consume/verify ✅ acknowledgement; process the input; answer; mirror; restart 600-second tail
expired  -> live window is finished; terminal/final response may now close the turn
missing  -> treat as relay/state failure; report it rather than pretending the tail ran
late     -> do not treat it as an in-window live-tail success; preserve/report according to late-reply policy
```

7. `waiting` is never a terminal condition. A single `waiting` result does **not** mean “wait completed,” “no reply,” or “10 minutes elapsed.” It only means the current short-poll slice ended without a reply.
8. continue bounded polling until a follow-up arrives or the active window actually expires;
9. when a follow-up arrives, consume it immediately, verify the `✅` pickup acknowledgement, process it, answer, mirror the new answer, and start a fresh 10-minute tail;
10. if no reply arrives, end naturally only after an `expired` result (or equivalent verified expiry timestamp), not after an arbitrary number of poll calls.

Do not invent a fake question merely to justify waiting. A natural question is fine when genuinely useful. A passive Telegram footer is preferred:

```text
Reply within 10 minutes to continue. No reply closes the live window.
```

### Terminal conditions

The tail ends only when:

- a follow-up is received and the conversation moves to the new response/tail;
- the reply window expires with no follow-up; or
- the execution environment forcibly terminates the turn.

A forced early termination is not success. The Inbox Rescue rule below must recover any stored reply on the next project turn.

---

## Rule 4 — Mandatory Inbox Rescue at the start of every project turn

Before unrelated work on every new project turn, inspect for timely Telegram follow-ups whose status is still `received`.

Consume the newest relevant unconsumed reply first, trigger/verify its `✅` pickup acknowledgement, and treat it as user input before proceeding.

This rescue is mandatory even when the newest visible user message arrived through the ChatGPT app.

The user should never need to complain that a valid Telegram reply was missed.

Mental model:

**Live Tail prevents normal misses. Inbox Rescue catches abnormal turn termination.**

---

## Rule 5 — Follow-up state and acknowledgement semantics

General follow-up states:

```text
received -> consumed
late
```

- `received`: the Telegram webhook durably captured a timely reply.
- `consumed`: ChatGPT actually picked it up.
- `late`: it arrived after the reply window ended.

On `received`, call:

```sql
select public.telegram_mark_followup_consumed('FOLLOWUP_UUID'::uuid);
```

Require `true`.

The consume RPC asynchronously triggers `telegram-consumption-ack-v52` through `pg_net`. Require the resulting Telegram acknowledgement message ID before saying ChatGPT received the reply.

Canonical user-facing acknowledgement:

```text
✅ ChatGPT received your Telegram reply and is continuing.
```

`📥` means the relay has the message. `✅` means ChatGPT consumed it. These are intentionally separate facts.

The acknowledgement rule is format-independent: text, buttons, voice notes, photos, audio, video, animation, and documents all receive the same ChatGPT-pickup guarantee.

---

## Rule 6 — Rich Telegram input

Accepted reply kinds:

- text;
- callback/button;
- voice note;
- audio attachment;
- photo;
- video;
- video note;
- animation;
- generic document/file.

The active rich webhook is:

```text
telegram-inbound-webhook-v522
```

For media, store metadata in `telegram_followups.media` and bytes temporarily in private bucket:

```text
telegram-inbound-v52
```

The bucket must remain private. Never expose the Telegram bot token or private media retrieval token in user-visible output, public GitHub issues, logs, or final artifacts.

### JSON invariant

`telegram_followups.media` must always be a JSON object, never a JSON-encoded string scalar.

Production has the defensive database trigger:

```text
normalize_telegram_followup_media_jsonb
```

It converts accidentally double-encoded media JSON into a real object before storage. Do not remove this guard unless every writer is proven type-safe and an equivalent invariant replaces it.

### Private byte retrieval

ChatGPT retrieves stored media through the service-only chunk bridge. Relevant RPCs include:

```text
telegram_enqueue_followup_media_chunk
telegram_get_media_chunk_result
telegram_read_followup_media_chunk
telegram_mark_followup_media_processed
```

Do not publish the private retrieval URL as a workaround.

---

## Rule 7 — Voice/audio understanding uses local Whisper first

Voice input must not depend on Gemini or GitHub Actions billing.

Primary voice path:

```text
Telegram OGG/audio
  -> private Supabase temporary storage
  -> ChatGPT private byte retrieval
  -> ffmpeg: mono 16 kHz WAV
  -> local Whisper base.en Q5_1 / whisper.cpp v1.8.6
  -> transcript
  -> ChatGPT interprets transcript as user input
  -> media marked processed
  -> media deleted
```

The portable Whisper bundle is registered in the user's Google Drive `Skills for chatgpt` sheet under **Tools -> audio transcription tool**.

Gemini/Gemma may be optional fallback or cross-checks when materially useful, but they are not hard dependencies for ordinary Telegram voice input.

Do not claim successful voice understanding merely because the OGG file was stored. The transcript must actually be produced and used.

---

## Rule 8 — Media is temporary working memory, not an archive

Inbound Telegram media follows a bounded lifecycle:

```text
receive -> private store -> ChatGPT pickup -> semantic processing -> immediate delete
```

Cleanup safeguards:

- after successful processing, call `telegram_mark_followup_media_processed` and queue immediate deletion;
- if a consumed media item is not explicitly finalized, delete after about 30 minutes;
- abandoned/unconsumed media has a 24-hour hard TTL;
- cleanup/reconciliation runs every 5 minutes;
- reconcile stale metadata when the object is already missing;
- remove orphaned storage objects;
- if the inbound bucket exceeds 256 MiB, retire the oldest media whose active 10-minute reply window has ended until usage falls to 192 MiB;
- media inside an active reply window is protected from pressure cleanup.

Never accumulate Telegram media indefinitely.

---

## Rule 9 — Explicit yes/no or finite-choice blockers may use buttons

When ChatGPT genuinely needs one short decision and the live turn can wait, the preserved v5.1-compatible question relay may use Telegram buttons.

Question payload example:

```json
{
  "kind": "question",
  "request_id": "UUID_V4",
  "prompt": "Continue?",
  "timeout_seconds": 600,
  "options": [
    {"label":"Yes","value":"yes"},
    {"label":"No","value":"no"}
  ]
}
```

Do not use Telegram questions for passwords, API keys, CAPTCHA, 2FA, login screens, or other secret credentials.

Normal responses do not need artificial buttons/questions merely to keep the live tail open.

---

## Rule 10 — Final deliverables must themselves reach Telegram

If a task creates, edits, converts, repairs, exports, or otherwise produces a final user-facing file, a text completion notice is insufficient.

Send the actual final artifact to Telegram and verify its own `message_id`, or use the approved oversize-link route when direct delivery is impossible.

Rules:

- send the final version, not an intermediate or stale copy;
- if multiple final deliverables exist, send all unless the user requests a subset;
- direct attachment delivery and response mirroring are separate requirements;
- do not expose a private artifact in plaintext merely to satisfy delivery;
- if safe delivery is impossible, report Telegram deliverable status as blocked instead of pretending success.

### Small text documents

Use `telegram-inline-document-v52` for small text artifacts that fit the encrypted issue transport. The current relay accepts decrypted inline documents up to 128 KiB and supports gzip-compressed content inside the already-encrypted payload.

### Direct media guardrails

Operational verified direct limits:

- photo: 10 MB;
- audio: 50 MB;
- video: 50 MB;
- generic document/file: 50 MB.

### Oversize files

Verified overflow policy:

- >50 MB through <=100 MB: TempFile.org temporary-link route;
- >100 MB through <=4 GB: temp.sh temporary-link route;
- >4 GB: no verified automatic free route; report blocked or use a separately approved host.

Sensitive oversize artifacts must be encrypted before third-party temporary hosting. Never silently upload sensitive plaintext.

---

## Rule 11 — Encryption and public GitHub hygiene

Public GitHub issues must contain ciphertext only.

For every relay payload:

1. fetch `telegram-relay-public.pem` fresh from `main` immediately before encryption;
2. generate a fresh random 32-byte AES key;
3. generate a fresh random 12-byte IV;
4. encrypt compact UTF-8 JSON with AES-256-GCM, no AAD;
5. wrap the AES key with RSA-OAEP using SHA-256 for OAEP and MGF1;
6. create the public issue using only:

```json
{
  "v": 1,
  "wrapped_key": "BASE64",
  "iv": "BASE64",
  "ciphertext": "BASE64"
}
```

Never place plaintext task text, Telegram credentials, private media URLs/tokens, file decryption keys, or secret filenames beside the envelope.

Trigger prefixes:

```text
telegram-v52:          normal response/status/media
telegram-v52-inline:   inline text document
telegram-v52-large:    oversize temporary-link delivery
telegram-v52-control:  activation/rollback control
telegram-question:     preserved blocker-question path
```

Creating an issue means queued, not delivered. Only the bot's verified Telegram `message_id` proves arrival.

---

## Rule 12 — Authorization and secrets

The relay validates GitHub Actions OIDC before decrypting. Production authorization binds the expected repository, owner, actor, workflow, event, main branch, GitHub-hosted runner, issuer, audience, signature, and token lifetime.

Telegram bot token, RSA private key, internal relay secret, chat ID, and webhook secret belong in Supabase Vault/private server-side state. Never print or return them to the user.

RLS remains enabled on Telegram reply/follow-up tables, and privileged polling/consume RPCs remain restricted to service-role/postgres paths.

Do not weaken these controls merely to make polling easier.

---

## Rule 13 — Failure handling

If relay delivery fails:

- inspect the existing GitHub Actions run and Supabase safe error class;
- do not spawn duplicate issues while the original run is still progressing;
- on encryption failure, refetch the current public key and create entirely fresh AES material;
- on rich-media failure, preserve the original private bytes until processing succeeds or cleanup TTL applies;
- never switch to a plaintext public workaround;
- never claim Telegram delivery without a Telegram message ID.

If the live ChatGPT turn is unexpectedly terminated, rely on Inbox Rescue on the next project turn rather than pretending the old turn resumed itself.

---

## Rule 14 — Rollback must remain easy

v5.3 is an additive orchestration/robustness layer over v5.2.2. It must not destroy preserved fallback resources.

### Roll back only the live-tail experiment

Return orchestration to the preserved v5.2.2 behavior. The media-normalization trigger may remain because it only canonicalizes malformed JSON. No destructive database rollback is required.

### Roll back rich input to v5.2.1

Use the existing encrypted control action:

```json
{"action":"rollback_v521"}
```

This restores `telegram-inbound-webhook-v52` while leaving the v5.2 feature flag enabled.

### Roll back to v5.1

Use:

```json
{"action":"rollback_v51"}
```

Safety order:

1. disable v5.2 general replies;
2. restore the original v5.1 webhook;
3. verify Telegram reports the v5.1 webhook;
4. resume v5.1 behavior.

### Reactivate rich v5.2.2/v5.3 transport

Use the preserved activation path for `activate_v522`, then apply the v5.3 orchestration rules.

Never delete the preserved v5.1 functions simply because a newer version is active.

---

## Acceptance standard for v5.3

Do not call v5.3 healthy unless these behaviors have live proof:

1. a complete substantive response reaches Telegram with a verified message ID;
2. ChatGPT keeps polling after that response instead of immediately ending the turn; at least three consecutive `waiting` short-poll returns must be proven to continue in the same turn;
3. a user-initiated text reply during the tail is detected, consumed, and gets a verified `✅` acknowledgement;
4. the next answer restarts a fresh 10-minute tail;
5. a full no-reply tail ends naturally after expiry;
6. a reply near the end of a window is still consumed in the same live turn;
7. a forced early termination leaves the reply durable and Inbox Rescue consumes it on the next turn;
8. voice note: private capture -> pickup acknowledgement -> byte retrieval -> local Whisper transcript -> ChatGPT use -> deletion;
9. document/photo/video inputs can be privately retrieved and processed without public exposure;
10. double-encoded `media` JSON is normalized automatically;
11. immediate deletion, 30-minute consumed fallback, 24-hour TTL, 5-minute reconciliation, and 256/192 MiB pressure ceiling are verified;
12. a final generated file reaches Telegram as the actual attachment or approved oversize link;
13. v5.2.2/v5.2.1/v5.1 rollback remains operational.

A real v5.3.1 live-tail text test succeeded when a user-initiated Telegram reply was detected during the active tail and the ChatGPT pickup acknowledgement was returned through the fast acknowledgement path.

---

## Mental checksum

**Normal conversation (v5.3.1):**

`Answer (non-terminal visible) -> Telegram -> verified ID -> repeat 10-second polls while status=waiting -> reply -> consume -> ✅ -> understand -> answer -> restart clock; only expiry may close the turn.`

**If ChatGPT is killed early:**

`Telegram webhook keeps reply -> next project turn runs Inbox Rescue -> consume -> ✅ -> continue.`

**Voice:**

`Telegram audio -> private bytes -> local Whisper -> ChatGPT understanding -> delete bytes.`

**End of conversation:**

`No reply for 10 minutes -> tail expires -> turn closes naturally.`
