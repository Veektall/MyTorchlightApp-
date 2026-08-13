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

Production `public.telegram_wait_for_followup(uuid, integer)` now accepts a bounded wait slice up to 55 seconds. Use approximately 50-second slices:

```sql
select *
from public.telegram_wait_for_followup('THREAD_UUID'::uuid, 50);
```

Interpretation:

```text
waiting  -> non-terminal; immediately poll again in the same turn
received -> verify pickup ack; process; answer; mirror; restart 600-second tail
expired  -> terminal condition; final response may close the turn
missing  -> relay/state failure; report it
late     -> not an in-window live-tail success
```

A 600-second window therefore normally requires about 11–13 calls rather than ~60 fragile 10-second calls.

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

The fallback reads Telegram credentials from Supabase Vault server-side, splits long text into safe chunks, sends directly to Telegram, registers every verified Telegram message ID in `telegram_reply_windows`, and is restricted to privileged service execution.

## Cross-chat source of truth

Future project chats should load the current Telegram skill from the shared `Skills for chatgpt` registry. The Drive entry is `telegram status ping skill v5.3.2`. This file is the versioned GitHub backup. `.telegram-relay/skills/CURRENT.md` points to the active version.

## Live proof

On 2026-08-13, Telegram message 1836 opened a 600-second window. ChatGPT stayed alive across repeated ~50-second polls. A user-initiated reply (`Test ok`) was captured in the same turn with 277 seconds remaining. The separate pickup acknowledgement was verified as Telegram message 1839. The next answer then opened a fresh 600-second window.

Mental checksum:

`Answer -> verified Telegram ID -> 50s bounded polls until 600s terminal condition -> reply -> verified ✅ ack -> answer -> fresh 600s tail.`
