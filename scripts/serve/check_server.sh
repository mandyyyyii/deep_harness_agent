#!/usr/bin/env bash
# Smoke-test an SGLang server: check /v1/models + a simple completion.
# Usage: bash check_server.sh [host:port]
set -euo pipefail

ENDPOINT="${1:-localhost:8051}"
URL="http://$ENDPOINT/v1"

echo "Checking $URL ..."

# 1. Model list
echo -n "  /v1/models: "
MODEL=$(curl -sf "$URL/models" | python3 -c "import json,sys; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null)
if [ -n "$MODEL" ]; then
  echo "OK ($MODEL)"
else
  echo "FAIL"; exit 1
fi

# 2. Simple completion
echo -n "  chat completion: "
RESP=$(curl -sf "$URL/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hi\"}],\"max_tokens\":16}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'][:50])" 2>/dev/null)
if [ -n "$RESP" ]; then
  echo "OK ($RESP)"
else
  echo "FAIL"; exit 1
fi

echo "Server at $URL is healthy."
