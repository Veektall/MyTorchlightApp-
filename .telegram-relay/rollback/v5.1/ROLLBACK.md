# Telegram v5.2 rollback to v5.1

v5.2 is intentionally additive. The original v5.1 Edge Functions and `.github/workflows/telegram-status.yml` remain untouched.

## One-command-path rollback

Send an RSA/AES sealed `telegram-v52-control:` issue through `.github/workflows/telegram-v52.yml` with plaintext payload:

```json
{"action":"rollback_v51"}
```

The control function performs rollback in this safety order:

1. set `v5_2_general_replies` feature flag to `false`;
2. restore the Telegram webhook URL to `telegram-inbound-webhook` (v5.1);
3. verify Telegram reports the v5.1 webhook URL.

Then use the v5.1 skill/protocol again. No destructive migration rollback is required; the v5.2 tables/functions may remain dormant.

## Activation

The inverse control payload is:

```json
{"action":"activate_v52"}
```

Activation switches the webhook to `telegram-inbound-webhook-v52`, verifies it, then enables the feature flag.

## Safety invariant

If activation or rollback is interrupted, disabling the feature flag is sufficient to turn off general v5.2 reply-window behavior. The v5.2 webhook is backward-compatible with v5.1 assistant-initiated question replies.
