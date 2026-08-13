---
name: telegram-status-ping
version: current
---

# Telegram Status Ping — Canonical Loader

Active version: **v5.3.2-persistent-live-tail-hardening**.

Load in order:

1. `.telegram-relay/skills/telegram-status-ping-SKILL-v5.3.1.md`
2. `.telegram-relay/skills/telegram-status-ping-SKILL-v5.3.2.md`

The second file is the higher-priority execution override. The full self-contained cross-chat copy is the Google Drive **Skills for chatgpt** entry named **telegram status ping skill v5.3.2**; the referenced Drive file is the canonical `Telegram Status Ping Skill / skill.md`.

Key v5.3.2 rules:

- `waiting` is non-terminal during the 600-second live tail.
- Use bounded long polls; production applies a 45-second minimum and 55-second maximum.
- Verify the separate pickup acknowledgement for every consumed reply.
- After answering a Telegram follow-up, start a fresh 600-second tail.
- For ordinary text/status/follow-up answers, prefer `telegram_private_mirror_v532`; keep the encrypted GitHub relay for media, documents, encrypted staging, control, and rollback.
- The preferred text sender uses Telegram HTML and converts Markdown tables into stacked mobile cards rather than raw pipe grids; ordered steps, headings, bullets, code, and quotes are rendered natively.
- Run Inbox Rescue at the beginning of each project turn.

Live acceptance on 2026-08-13 verified reply capture, acknowledgement, natural 600-second expiry, backward-compatible polling, transient-delivery recovery, continuation from a different GROK chat, and repaired mobile table rendering (Telegram message 1878).
