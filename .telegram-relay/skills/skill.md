---
name: telegram-status-ping
version: current
---

# Telegram Status Ping — Canonical Loader

Active version: **v5.3.2-persistent-live-tail-hardening**.

Load in order:

1. `.telegram-relay/skills/telegram-status-ping-SKILL-v5.3.1.md`
2. `.telegram-relay/skills/telegram-status-ping-SKILL-v5.3.2.md`

The second file is the higher-priority execution override.

The full self-contained cross-chat copy is the Google Drive **Skills for chatgpt** entry named **telegram status ping skill v5.3.2**. That existing registry file is now named `skill.md` inside the **Telegram Status Ping Skill** folder.

Key v5.3.2 rules:

- `waiting` is non-terminal during the 600-second live tail.
- Use bounded long polls; production applies a 45-second minimum and 55-second maximum.
- Verify the separate pickup acknowledgement for every consumed reply.
- After answering a Telegram follow-up, start a fresh 600-second tail.
- Mirrored responses use Telegram-native HTML formatting instead of raw ChatGPT Markdown.
- Run Inbox Rescue at the beginning of each project turn.

Live acceptance on 2026-08-13 verified reply capture, acknowledgement, natural 600-second expiry, backward-compatible polling, transient-delivery recovery, and continuation from a different GROK chat.
