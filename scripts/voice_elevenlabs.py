#!/usr/bin/env python3
import os, sys, json, re, tempfile, subprocess, shlex, pathlib, time, urllib.request

import argparse
ap = argparse.ArgumentParser()
ap.add_argument("--transcript", required=True, help="Chemin .txt")
ap.add_argument("--out", default="audio/voice.wav", help="WAV de sortie")
ap.add_argument("--cues", default="audio/dialogue_cues.json", help="JSON des cues")
args = ap.parse_args()

API_KEY = os.environ.get("ELEVENLABS_API_KEY","").strip()
if not API_KEY:
    print("ELEVENLABS_API_KEY manquant", file=sys.stderr); sys.exit(1)

VOICE_SINGLE = os.environ.get("ELEVENLABS_VOICE_ID","").strip()
VOICE_V1 = os.environ.get("ELEVENLABS_VOICE_ID_V1","").strip()
VOICE_V2 = os.environ.get("ELEVENLABS_VOICE_ID_V2","").strip()
use_dual = bool(VOICE_V1 and VOICE_V2)

if not (use_dual or VOICE_SINGLE):
    print("Configure ELEVENLABS_VOICE_ID (1 voix) OU ELEVENLABS_VOICE_ID_V1+V2 (2 voix)", file=sys.stderr)
    sys.exit(1)

def has(cmd):
    try:
        subprocess.run([cmd,"-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

if not has("ffmpeg") or not has("ffprobe"):
    print("ffmpeg/ffprobe manquants", file=sys.stderr); sys.exit(1)

tpath = pathlib.Path(args.transcript)
if not tpath.exists() or not tpath.stat().st_size:
    print(f"Transcript introuvable: {tpath}", file=sys.stderr); sys.exit(1)

out_path = pathlib.Path(args.out); out_path.parent.mkdir(parents=True, exist_ok=True)
cues_path = pathlib.Path(args.cues); cues_path.parent.mkdir(parents=True, exist_ok=True)

raw_text = tpath.read_text(encoding="utf-8").strip()
lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

seg_re = re.compile(r"^\s*(?:voix|v|voice)\s*([12])\s*[:\-]\s*(.+)$", re.IGNORECASE)
segments = []
current_voice = "1" if use_dual else "S"
for ln in lines:
    m = seg_re.match(ln)
    if m and use_dual:
        current_voice = m.group(1)
        content = m.group(2).strip()
        if content: segments.append((current_voice, content))
    else:
        segments.append((current_voice, ln))

def tts_eleven(chunk, voice_id):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": chunk,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.25,
            "use_speaker_boost": True
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "xi-api-key": API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        },
        method="POST"
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except Exception:
            if attempt == 3: raise
            time.sleep(1.5*(attempt+1))

def mp3_to_wav(mp3_bytes, wav_out):
    tmp_mp3 = wav_out.with_suffix(".mp3")
    tmp_mp3.write_bytes(mp3_bytes)
    subprocess.run([
        "ffmpeg","-nostdin","-y","-i",str(tmp_mp3),
        "-ar","16000","-ac","1", str(wav_out)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def wav_dur(path):
    out = subprocess.check_output([
        "ffprobe","-v","error","-select_streams","a:0","-show_entries","stream=duration",
        "-of","default=nk=1:nw=1", str(path)
    ]).decode("utf-8","ignore").strip()
    try: return float(out)
    except: return 0.0

tempdir = pathlib.Path(tempfile.mkdtemp(prefix="tts_"))
parts, cues = [], []
t0 = 0.0

for idx,(v,content) in enumerate(segments, start=1):
    voice_id = (VOICE_V1 if v in ("1","S") else VOICE_V2) if use_dual else VOICE_SINGLE
    mp3 = tts_eleven(content, voice_id)
    wav = tempdir / f"seg_{idx:03d}.wav"
    mp3_to_wav(mp3, wav)
    dur = wav_dur(wav)
    parts.append(wav)
    cues.append({
        "index": idx,
        "voice": "1" if (use_dual and v in ("1","S")) else ("2" if use_dual else "1"),
        "text": content,
        "start": round(t0,3),
        "end": round(t0+dur,3)
    })
    t0 += dur

# concat
concat_list = tempdir / "list.txt"
with concat_list.open("w", encoding="utf-8") as f:
    for p in parts:
        f.write(f"file '{p.resolve().as_posix()}'\n")

subprocess.run([
    "ffmpeg","-nostdin","-y","-f","concat","-safe","0","-i",str(concat_list),
    "-c","copy", str(out_path)
], check=True)

cues_path.write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[voice] audio: {out_path}  | cues: {cues_path}")