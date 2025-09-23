#!/usr/bin/env bash
set -euo pipefail

: "${DROPBOX_APP_KEY:?DROPBOX_APP_KEY manquant}"
: "${DROPBOX_APP_SECRET:?DROPBOX_APP_SECRET manquant}"
: "${DROPBOX_REFRESH_TOKEN:?DROPBOX_REFRESH_TOKEN manquant}"
: "${OUT_NAME:?OUT_NAME manquant}"

FILE="final_video/${OUT_NAME}"
[ -s "$FILE" ] || { echo "Fichier absent: $FILE"; exit 1; }

# 1) Obtenir un access token court via refresh_token
TOKEN=$(curl -sS -u "${DROPBOX_APP_KEY}:${DROPBOX_APP_SECRET}" \
  -d "grant_type=refresh_token&refresh_token=${DROPBOX_REFRESH_TOKEN}" \
  https://api.dropboxapi.com/oauth2/token | python3 -c 'import sys,json; s=sys.stdin.read().strip(); print(json.loads(s).get("access_token",""))')

[ -n "$TOKEN" ] || { echo "Impossible d'obtenir un access_token"; exit 1; }

REMOTE_DIR="/horror"
TS="$(date +"%Y%m%d_%H%M%S")"
REMOTE_PATH="${REMOTE_DIR}/${TS}_${OUT_NAME}"

SIZE=$(stat -c%s "$FILE")
if [ "$SIZE" -le $((150*1024*1024)) ]; then
  # Upload direct
  API_ARG=$(printf '{ "path": "%s", "mode": "add", "autorename": true, "mute": false }' "$REMOTE_PATH")
  curl -sS -X POST "https://content.dropboxapi.com/2/files/upload" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Dropbox-API-Arg: ${API_ARG}" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @"${FILE}" >/dev/null
else
  # Upload par session (15MB chunks)
  SID=$(curl -sS -X POST "https://content.dropboxapi.com/2/files/upload_session/start" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/octet-stream" \
    -H 'Dropbox-API-Arg: {"close": false}' \
    --data-binary "" | python3 -c 'import sys,json; print(json.loads(sys.stdin.read())["session_id"])')

  CHUNK=$((15*1024*1024))
  OFF=0
  I=0
  while [ "$OFF" -lt "$SIZE" ]; do
    dd if="$FILE" bs="$CHUNK" skip="$I" count=1 status=none | \
    curl -sS -X POST "https://content.dropboxapi.com/2/files/upload_session/append_v2" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H "Content-Type: application/octet-stream" \
      -H "Dropbox-API-Arg: {\"cursor\": {\"session_id\": \"${SID}\", \"offset\": ${OFF}}, \"close\": false}" \
      --data-binary @- >/dev/null
    OFF=$((OFF+CHUNK))
    I=$((I+1))
  done

  COMMIT=$(printf '{ "cursor": {"session_id": "%s", "offset": %s}, "commit": {"path": "%s", "mode": "add", "autorename": true, "mute": false} }' "$SID" "$SIZE" "$REMOTE_PATH")
  curl -sS -X POST "https://content.dropboxapi.com/2/files/upload_session/finish" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/octet-stream" \
    -H "Dropbox-API-Arg: ${COMMIT}" \
    --data-binary "" >/dev/null
fi

# Lien partageable
PAYLOAD=$(printf '{"path":"%s"}' "$REMOTE_PATH")
resp=$(curl -sS -X POST "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data "$PAYLOAD")
url=$(printf "%s" "$resp" | python3 -c 'import sys,json; s=sys.stdin.read(); print(json.loads(s).get("url",""))' || true)

if [ -z "$url" ]; then
  resp=$(curl -sS -X POST "https://api.dropboxapi.com/2/sharing/list_shared_links" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    --data "$PAYLOAD")
  url=$(printf "%s" "$resp" | python3 -c 'import sys,json; s=sys.stdin.read(); j=json.loads(s); print((j.get("links") or [{}])[0].get("url",""))' || true)
fi

[ -n "$url" ] || { echo "Lien Dropbox introuvable (vérifie les scopes)"; exit 1; }

dl="${url/\?dl=0/?dl=1}"
mkdir -p final_video
printf '%s\n' "$dl" > final_video/dropbox_link.txt
echo "Dropbox: $dl"