# Preserved v5.1 production paths

These v5.1 resources were deliberately left unchanged while v5.2 was added in parallel:

- `.github/workflows/telegram-status.yml`
- Supabase Edge Function `telegram-status-relay`
- Supabase Edge Function `telegram-question-relay`
- Supabase Edge Function `telegram-inbound-webhook`
- Supabase Edge Function `telegram-reply-expiry-watch`
- database tables `telegram_pending_requests` and `telegram_inbound_updates`
- RPCs `telegram_wait_for_reply` and `telegram_mark_chatgpt_picked_up`

v5.2 uses separate resources (`telegram-v52.yml`, `telegram-unified-relay-v52`, `telegram-inbound-webhook-v52`, and `telegram-v52-control`) plus additive tables/RPCs.
