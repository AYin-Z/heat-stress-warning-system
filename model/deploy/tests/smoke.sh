#!/bin/sh
set -eu

base_url="${BASE_URL:-http://127.0.0.1:8001}"

curl --fail --silent "${base_url}/healthz"
curl --fail --silent "${base_url}/readyz"
curl --fail --silent --request POST "${base_url}/api/watch/upload/" \
  --header 'Content-Type: application/json' \
  --header 'X-Device-ID: WATCH-TEST-001' \
  --data '{"heart_rate":88,"skin_temperature":35.2,"timestamp":"2026-07-15T10:30:00+08:00"}'

