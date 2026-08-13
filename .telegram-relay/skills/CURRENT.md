# Current Telegram Status Ping Skill

Active version: **v5.3.2-persistent-live-tail-hardening**

Stable loader: `.telegram-relay/skills/skill.md`.

Expanded load order:

1. `.telegram-relay/skills/telegram-status-ping-SKILL-v5.3.1.md`
2. `.telegram-relay/skills/telegram-status-ping-SKILL-v5.3.2.md` as the higher-priority execution override.

Shared cross-chat registry: Google Drive spreadsheet **Skills for chatgpt** -> row **telegram status ping skill v5.3.2**. The existing registry file ID is now the canonical Drive file **Telegram Status Ping Skill / skill.md**.

Critical invariant: while `telegram_wait_for_followup(...)` returns `waiting`, do not emit the terminal/final ChatGPT response. Use ~50-second bounded polls until the 600-second window returns `received` or verified `expired`.

Production compatibility guard: requests below 45 seconds, including legacy `(..., 10)` calls, automatically use a 45-second floor with a 55-second ceiling.

The production private mirror has bounded Telegram retries and converts ChatGPT Markdown to safe Telegram-native HTML before delivery.
