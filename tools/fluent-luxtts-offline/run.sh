#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
exec "$ROOT/python/bin/python3" "$@"
