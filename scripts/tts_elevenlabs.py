#!/usr/bin/env python3
import os, sys, pathlib, json, urllib.request

API_KEY  = os.environ.get("ELEVENLABS_API_KEY", "").strip()
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
TEXT     = pathlib.Path("story/story.txt").read_text(encoding="utf-8") if pathlib.Path("story/story.txt").exists() else ""

if not API_KEY:
    print("ELEVENLABS_API_KEY manquant", file=sys.stderr)
    sys.exit(1)
if not VOICE_ID:
    print("ELEVENLABS_VOICE_ID manquant", file=sys.stderr)
    sys.exit(1)
if not TEXT.strip():
    print("Texte introuvable: story/story.txt", file=sys.stderr)
    sys.exit(1)

out_dir = pathlib.Path("audio")
out_dir.mkdir(parents=True, exist_ok=True)
out_file = out_dir/"voice.mp3"

url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
payload = {
    "text": TEXT,
    "model_id": "eleven_multilingual_v2",
    "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True}
}
data = json.dumps(payload).encode("utf-8")

req = urllib.request.Request(
    url,
    data=data,
    headers={
        "xi-api-key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg"
    },
    method="POST"
)

try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        audio = resp.read()
        if not audio:
            raise RuntimeError("Flux audio vide")
        out_file.write_bytes(audio)
        print(f"OK: {out_file} ({out_file.stat().st_size} octets)")
except Exception as e:
    print(f"Erreur ElevenLabs: {e}", file=sys.stderr)
    sys.exit(1)