---
name: telegram-status-ping
version: 5.3.2-persistent-live-tail-hardening
inherits: .telegram-relay/skills/telegram-status-ping-SKILL-v5.3.1.md
---

# Telegram Status Ping v5.3.2 — Persistent Live-Tail Hardening

Load the full v5.3.1 skill first. Then apply these v5.3.2 rules as higher-priority overrides. All unchanged rich-input, media-cleanup, artifact-delivery, security, and rollback rules remain inherited from v5.3.1.

## Critical execution invariant

A reply window that remains open after ChatGPT emits its terminal/final response is not a live tail. While the active thread returns `waiting`, do not emit the terminal/final ChatGPT response.

Use visible non-terminal updates while work continues. Finalize only after a verified `expired` result, after processing a received reply into a new response/tail, or if the runtime forcibly terminates the turn.

## Persistent polling behavior

Production `public.telegram_wait_for_followup(uuid, integer)` has a 45-second compatibility floor and a 55-second ceiling. Use approximately 50-second slices:

```sql
select *
from public.telegram_wait_for_followup('THREAD_UUID'::uuid, 50);
```

Older skill copies that still call `telegram_wait_for_followup(..., 10)` are intentionally stretched by production to at least 45 seconds. This makes the fix effective even before an older chat reloads the current skill.

Interpretation:

```text
waiting  -> non-terminal; immediately poll again in the same turn
received -> verify pickup ack; process; answer; mirror; restart 600-second tail
expired  -> terminal condition; final response may close the turn
missing  -> relay/state failure; report it
late     -> not an in-window live-tail success
```

A 600-second no-reply window therefore normally needs roughly 11–14 bounded calls instead of about 60 fragile 10-second calls.

## Pickup acknowledgement verification

The wait RPC consumes a timely reply idempotently and queues the separate ChatGPT pickup acknowledgement. Before claiming ChatGPT received the Telegram reply, call:

```sql
select *
from public.telegram_wait_for_pickup_ack('FOLLOWUP_UUID'::uuid, 20);
```

Require `status='acked'` and a non-null `pickup_ack_message_id`.

## Private delivery fallback

Primary delivery remains the encrypted GitHub Actions -> Supabase relay. If the ChatGPT GitHub connector itself blocks creation of the opaque ciphertext issue before GitHub receives it, do not switch to plaintext public transport. Use the privileged private fallback:

```sql
select public.telegram_private_mirror_v532(
  'THREAD_UUID'::uuid,
  'COMPLETE USER-FACING RESPONSE',
  600,
  'response'
);
```

The fallback reads Telegram credentials from Supabase Vault server-side, splits long text into safe chunks, sends directly to Telegram, registers every verified Telegram message ID in `telegram_reply_windows`, and is restricted to privileged service execution. Its production HTTP path uses a 5-second connect timeout, 10-second request timeout, and up to three bounded retries for transient network errors, 5xx responses, or 429 responses.

## Cross-chat source of truth

Future project chats should load the current Telegram skill from the shared `Skills for chatgpt` registry. The Drive entry is `telegram status ping skill v5.3.2`. This file is the versioned GitHub backup. `.telegram-relay/skills/CURRENT.md` points to the active version.

## Live proof

On 2026-08-13, Telegram message 1836 opened a 600-second window. ChatGPT stayed alive across repeated ~50-second polls. A user-initiated reply (`Test ok`) was captured in the same turn with 277 seconds remaining. The separate pickup acknowledgement was verified as Telegram message 1839. The next answer opened a fresh 600-second window.

Cross-chat/backward-compatibility proof: after opening Telegram message 1848, the legacy `telegram_wait_for_followup(..., 10)` signature returned `waiting` with 544 seconds remaining only after the hardened long-poll floor, proving production—not just this chat's prompt—enforces the longer slice. A reproduced 1-second Telegram connection timeout on the private fallback was then corrected with the bounded timeout/retry migration and the same delivery path succeeded.

Natural-expiry proof: Telegram message 1856 opened a dedicated no-reply acceptance window. The same ChatGPT turn stayed active through every bounded poll for the complete 600 seconds and ended only when `telegram_wait_for_followup` returned `expired` with `seconds_remaining=0`. This verifies the no-reply terminal path that v5.3.0 previously failed to sustain.

Mental checksum:

`Answer -> verified Telegram ID -> bounded long polls until the 600s terminal condition -> reply -> verified ✅ ack -> answer -> fresh 600s tail.`
