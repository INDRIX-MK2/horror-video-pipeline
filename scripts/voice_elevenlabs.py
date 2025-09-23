#!/usr/bin/env python3
import os, sys, json, pathlib, subprocess, requests, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"
STORY = ROOT / "story" / "story.txt"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
WAV = AUDIO_DIR / "voice.wav"
DUR_JSON = AUDIO_DIR / "duration.json"

API_KEY = os.environ.get("ELEVENLABS_API_KEY","").strip()
VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID","").strip()

if not API_KEY:
    print("ELEVENLABS_API_KEY manquant", file=sys.stderr); sys.exit(1)
if not VOICE_ID:
    print("ELEVENLABS_VOICE_ID manquant", file=sys.stderr); sys.exit(1)
if not STORY.exists():
    print("Story manquante", file=sys.stderr); sys.exit(1)

text = STORY.read_text(encoding="utf-8").strip()
if not text:
    print("Story vide", file=sys.stderr); sys.exit(1)

url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
headers = {
    "xi-api-key": API_KEY,
    "accept": "audio/wav",
    "Content-Type": "application/json"
}
payload = {
    "text": text,
    "model_id": "eleven_multilingual_v2",
    "voice_settings": {
        "stability": 0.4,
        "similarity_boost": 0.7,
        "style": 0.3,
        "use_speaker_boost": True
    }
}

r = requests.post(url, headers=headers, json=payload, timeout=120)
if r.status_code != 200:
    print(f"ElevenLabs HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)
    sys.exit(1)

WAV.write_bytes(r.content)

# Probe duration via ffprobe
cmd = [
    "ffprobe","-v","error","-show_entries","format=duration",
    "-of","default=nw=1:nk=1", str(WAV)
]
try:
    dur = float(subprocess.check_output(cmd, text=True).strip())
except Exception as e:
    print(f"ffprobe erreur: {e}", file=sys.stderr); sys.exit(1)

DUR_JSON.write_text(json.dumps({"seconds": dur}, ensure_ascii=False), encoding="utf-8")
print(f"Audio saved to {WAV} (dur={dur:.2f}s)")