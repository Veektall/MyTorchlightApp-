# Current Telegram Status Ping Skill

Active version: **v5.3.2-persistent-live-tail-hardening**

Load, in order:

1. `.telegram-relay/skills/telegram-status-ping-SKILL-v5.3.1.md`
2. `.telegram-relay/skills/telegram-status-ping-SKILL-v5.3.2.md` as the higher-priority execution override.

Shared cross-chat registry: Google Drive spreadsheet **Skills for chatgpt** -> row **telegram status ping skill v5.3.2**.

Critical invariant: while `telegram_wait_for_followup(...)` returns `waiting`, do not emit the terminal/final ChatGPT response. Use ~50-second bounded polls until the 600-second window returns `received` or verified `expired`.
