#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
voice_elevenlabs.py
-------------------
Génère une narration à partir d'un transcript texte via ElevenLabs.
- Supporte 1 ou 2 voix (V1/V2).
- Sorties :
    audio/voice.wav
    audio/dialogue_cues.json  (liste [{start, end, text, speaker}])

ENV requis :
  ELEVENLABS_API_KEY
  (au choix)
    ELEVENLABS_VOICE_ID                 # mode 1 voix
  ou ELEVENLABS_VOICE_ID_V1 + ELEVENLABS_VOICE_ID_V2  # mode 2 voix

ENV optionnels :
  ELEVENLABS_MODEL_ID   (defaut: eleven_multilingual_v2)
  ELEVEN_STABILITY      (float 0..1)
  ELEVEN_SIMILARITY     (float 0..1)
  ELEVEN_STYLE          (float 0..1)
  ELEVEN_SPEAKER_BOOST  ("true"/"false")

Dépendances binaires : ffmpeg/ffprobe dans le PATH.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

API_BASE = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

# ---------- Utils ----------

def fail(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    sys.exit(code)

def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        subprocess.run(["ffprobe", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        fail("ffmpeg/ffprobe introuvables dans le PATH. Installe-les ou ajoute-les au PATH.")

def run_ffmpeg_to_wav(input_bytes: bytes, dst_wav: Path, sr: int = 48000, ac: int = 1):
    """Convertit des données audio (mp3/mpeg) en WAV PCM 16-bit mono via ffmpeg."""
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", "pipe:0",
        "-ar", str(sr), "-ac", str(ac),
        "-f", "wav", str(dst_wav)
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p.stdin.write(input_bytes)
    p.stdin.close()
    rc = p.wait()
    if rc != 0 or not dst_wav.exists() or dst_wav.stat().st_size == 0:
        fail("Échec conversion ffmpeg vers WAV.")

def wav_duration_seconds(wav_path: Path) -> float:
    """Retourne la durée d'un WAV (via ffprobe)."""
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(wav_path)
        ], stderr=subprocess.DEVNULL, text=True).strip()
        return float(out)
    except Exception:
        return 0.0

def clean_line_basic(line: str) -> str:
    """Nettoyage léger : supprime espaces chelous, guillemets externes."""
    s = line.strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == '“') or (s[0] == s[-1] == '”')):
        s = s[1:-1].strip()
    return s

# ---------- Parsing transcript ----------

VOICE_TAG_RE = re.compile(r"^\s*(V1|V2|Voix\s*1|Voix\s*2)\s*:\s*(.+)$", re.IGNORECASE)

DIDASCALIE_PREFIXES = (
    "scène", "scene", "intro", "hook", "narrateur", "cta",
    "développement", "developpement", "voix", "voice"
)

SENT_SPLIT_RE = re.compile(r"(?<=[\.\!\?\u2026])\s+")

def parse_transcript(path: Path) -> dict:
    """
    Retourne un dict :
      {
        "mode": "dual"|"single",
        "segments": [ { "speaker": "V1"|"V2", "text": "..." }, ... ]
      }
    Règles :
      - Si des lignes explicitent V1:/V2: => mode dual, segments par ligne.
      - Sinon => mode single, on split en phrases (pour des cues plus fines).
      - On ignore les lignes *entièrement* didascaliques si pas de V1/V2.
    """
    raw = path.read_text(encoding="utf-8", errors="ignore")
    lines = [clean_line_basic(l) for l in raw.splitlines() if clean_line_basic(l)]

    # Détecte balises V1/V2
    dual_segments = []
    dual_detected = False
    for ln in lines:
        m = VOICE_TAG_RE.match(ln)
        if m:
            dual_detected = True
            tag = m.group(1).upper().replace("VOIX", "V").replace(" ", "")
            speaker = "V1" if "1" in tag else "V2"
            text = m.group(2).strip()
            if text:
                dual_segments.append({"speaker": speaker, "text": text})

    if dual_detected and dual_segments:
        return {"mode": "dual", "segments": dual_segments}

    # Sinon: mode single (pas de V1/V2 explicite)
    kept = []
    for ln in lines:
        lower = ln.lower()
        if any(lower.startswith(prefix + ":") for prefix in DIDASCALIE_PREFIXES):
            continue
        kept.append(ln)

    text_single = " ".join(kept).strip()
    if not text_single:
        text_single = " ".join(lines).strip()

    sentences = [s.strip() for s in SENT_SPLIT_RE.split(text_single) if s.strip()]
    segments = [{"speaker": "V1", "text": s} for s in sentences] if sentences else [{"speaker": "V1", "text": text_single}]
    return {"mode": "single", "segments": segments}

# ---------- ElevenLabs TTS ----------

def tts_elevenlabs(api_key: str, voice_id: str, text: str) -> bytes:
    """Appel ElevenLabs TTS -> renvoie audio MP3 (bytes)."""
    import urllib.request
    import urllib.error

    url = f"{API_BASE}/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": DEFAULT_MODEL,
        "output_format": "mp3_44100_128",
        "voice_settings": {}
    }

    def parse_float(name, default=None):
        v = os.getenv(name)
        try:
            return float(v) if v is not None else default
        except Exception:
            return default

    stability = parse_float("ELEVEN_STABILITY")
    similarity = parse_float("ELEVEN_SIMILARITY")
    style = parse_float("ELEVEN_STYLE")
    boost = os.getenv("ELEVEN_SPEAKER_BOOST")

    if stability is not None:
        payload["voice_settings"]["stability"] = stability
    if similarity is not None:
        payload["voice_settings"]["similarity_boost"] = similarity
    if style is not None:
        payload["voice_settings"]["style"] = style
    if boost is not None:
        payload["voice_settings"]["use_speaker_boost"] = (boost.lower() in ("1","true","yes","on"))

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "xi-api-key": api_key
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="ignore")
        fail(f"ElevenLabs HTTPError {e.code}: {msg}")
    except Exception as e:
        fail(f"ElevenLabs échec TTS: {e}")
    return b""

# ---------- Helpers ----------

def chunk_text(text: str, max_len: int = 1200):
    """Coupe proprement par phrases pour rester < max_len."""
    parts = []
    buf = ""
    sentences = [s.strip() for s in SENT_SPLIT_RE.split(text) if s.strip()]
    items = sentences if sentences else [text]
    for s in items:
        if len(buf) + 1 + len(s) <= max_len:
            buf = (buf + " " + s).strip() if buf else s
        else:
            if buf:
                parts.append(buf)
            if len(s) <= max_len:
                buf = s
            else:
                while len(s) > max_len:
                    parts.append(s[:max_len])
                    s = s[max_len:]
                buf = s
    if buf:
        parts.append(buf)
    return parts

def concat_wavs(wav_list, dst_path: Path):
    """Concatène une liste de WAV (même format) en un seul WAV via ffmpeg concat demuxer."""
    if len(wav_list) == 1:
        shutil.copyfile(wav_list[0], dst_path)
        return

    tmp_dir = dst_path.parent
    tmp_dir.mkdir(parents=True, exist_ok=True)
    list_file = tmp_dir / ("concat_%d.txt" % int(time.time()*1000))
    with list_file.open("w", encoding="utf-8") as f:
        for p in wav_list:
            abs_path = str(Path(p).resolve())
            # Echappement POSIX pour single-quoted : ' -> '\'' 
            escaped = abs_path.replace("'", "'\\''")
            f.write("file '" + escaped + "'\n")

    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy", str(dst_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        list_file.unlink(missing_ok=True)
    except Exception:
        pass

# ---------- Build pipeline ----------

def main():
    ap = argparse.ArgumentParser(description="Génère une narration ElevenLabs + cues JSON")
    ap.add_argument("--transcript", required=True, help="Chemin du transcript texte (UTF-8)")
    ap.add_argument("--out", default="audio/voice.wav", help="Chemin du WAV final (défaut: audio/voice.wav)")
    ap.add_argument("--cues", default="audio/dialogue_cues.json", help="Chemin des cues JSON (défaut: audio/dialogue_cues.json)")
    args = ap.parse_args()

    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        fail("ELEVENLABS_API_KEY manquant dans l'environnement.")

    voice_single = os.getenv("ELEVENLABS_VOICE_ID")
    voice_v1 = os.getenv("ELEVENLABS_VOICE_ID_V1")
    voice_v2 = os.getenv("ELEVENLABS_VOICE_ID_V2")

    if voice_v1 and voice_v2:
        mode_voices = "dual"
    elif voice_single:
        mode_voices = "single"
    else:
        fail("Aucune voix configurée. Renseigne ELEVENLABS_VOICE_ID (1 voix) ou ELEVENLABS_VOICE_ID_V1 + ELEVENLABS_VOICE_ID_V2 (2 voix).")

    transcript_path = Path(args.transcript)
    if not transcript_path.exists() or transcript_path.stat().st_size == 0:
        fail(f"Transcript introuvable ou vide: {transcript_path}")

    out_wav = Path(args.out)
    cues_json = Path(args.cues)
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cues_json.parent.mkdir(parents=True, exist_ok=True)

    check_ffmpeg()

    parsed = parse_transcript(transcript_path)
    segments = parsed["segments"]

    def voice_for(speaker: str) -> str:
        sp = (speaker or "V1").upper()
        if mode_voices == "dual":
            return voice_v1 if sp == "V1" else voice_v2
        return voice_single

    tmpdir = Path(tempfile.mkdtemp(prefix="elvtts_"))
    tmp_wavs = []
    total_duration = 0.0

    try:
        for idx, seg in enumerate(segments, 1):
            speaker = seg.get("speaker") or "V1"
            text = seg.get("text", "").strip()
            if not text:
                continue

            text_chunks = chunk_text(text, max_len=1200)
            seg_wavs = []
            for ci, chunk in enumerate(text_chunks, 1):
                mp3_bytes = tts_elevenlabs(api_key, voice_for(speaker), chunk)
                seg_wav = tmpdir / f"seg_{idx:03d}_{ci:02d}.wav"
                run_ffmpeg_to_wav(mp3_bytes, seg_wav, sr=48000, ac=1)
                seg_wavs.append(seg_wav)

            if len(seg_wavs) == 1:
                final_seg_wav = seg_wavs[0]
            else:
                final_seg_wav = tmpdir / f"seg_{idx:03d}_full.wav"
                concat_wavs(seg_wavs, final_seg_wav)

            dur = wav_duration_seconds(final_seg_wav)
            tmp_wavs.append((final_seg_wav, speaker, text, dur))
            total_duration += dur

        concat_wavs([w for (w, _, __, ___) in tmp_wavs], out_wav)

        # Reconstitue les cues cumulées
        cues = []
        cursor = 0.0
        for (w, spk, txt, dur) in tmp_wavs:
            d = wav_duration_seconds(w) or dur
            cues.append({
                "start": round(cursor, 3),
                "end": round(cursor + d, 3),
                "text": txt,
                "speaker": spk
            })
            cursor += d

        cues_json.write_text(json.dumps(cues, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[voice] OK -> {out_wav} ({round(cursor,2)}s), cues -> {cues_json}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

# ---------- Entry ----------
if __name__ == "__main__":
    main()