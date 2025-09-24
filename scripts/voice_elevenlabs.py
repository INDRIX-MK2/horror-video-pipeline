#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Synthèse vocale ElevenLabs avec support dialogue V1/V2 (ou fallback 1 voix).

Entrées:
  - --input story/story.txt   (par défaut)
  - --out   audio/voice.wav   (par défaut)
  - --cues  audio/dialogue_cues.json

ENV requis:
  - ELEVENLABS_API_KEY (obligatoire)
  - ELEVENLABS_VOICE_ID            (fallback 1 voix)
  - ELEVENLABS_VOICE_ID_V1 (optionnel, pour V1)
  - ELEVENLABS_VOICE_ID_V2 (optionnel, pour V2)

Sorties:
  - audio/voice.wav
  - audio/dialogue_cues.json  (liste [{speaker, text, start, end}])
"""

import argparse
import io
import json
import os
import re
import sys
import time
import wave
from pathlib import Path

import requests


MODEL_ID = "eleven_multilingual_v2"
VOICE_SETTINGS = {
    "stability": 0.8,
    "similarity_boost": 0.85,
    "style": 0.2,
    "use_speaker_boost": True
}

# -------- Utils --------

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def sanitize_for_ass(text: str) -> str:
    # On garde propre pour éventuels usages ultérieurs
    return text.replace("\r", "").strip()

def strip_directions(line: str) -> str:
    # supprime [entre crochets] et (entre parenthèses)
    line = re.sub(r"\[[^\]]*\]", "", line)
    line = re.sub(r"\([^\)]*\)", "", line)
    # supprime “Intro:”, “Scène:”, etc. au début de ligne
    line = re.sub(r"^\s*(intro|scène|scene|narrateur|cta)\s*:\s*", "", line, flags=re.I)
    return line.strip()

def split_long_text(txt: str, max_len: int = 250) -> list[str]:
    """Découpe prudemment en phrases <= max_len (pour éviter limites API)."""
    txt = " ".join(txt.split())
    if len(txt) <= max_len:
        return [txt]
    # Essai par ponctuation
    parts = re.split(r"(?<=[\.\?\!])\s+", txt)
    out, buf = [], ""
    for p in parts:
        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= max_len:
            buf += " " + p
        else:
            out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    # Si malgré tout trop long, coupe en durs
    final = []
    for seg in out:
        if len(seg) <= max_len:
            final.append(seg)
        else:
            s = seg
            while len(s) > max_len:
                final.append(s[:max_len])
                s = s[max_len:]
            if s:
                final.append(s)
    return [x.strip() for x in final if x.strip()]

def wav_duration_from_bytes(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        return frames / float(rate)

def combine_wavs_same_params(in_files: list[Path], out_file: Path) -> None:
    """Concatène des WAV avec mêmes paramètres (nchannels, sampwidth, framerate)."""
    if not in_files:
        raise RuntimeError("Aucun morceau audio à concaténer.")
    # Paramètres du premier
    with wave.open(str(in_files[0]), "rb") as w0:
        nch, sw, fr = w0.getnchannels(), w0.getsampwidth(), w0.getframerate()
    # Ecriture
    with wave.open(str(out_file), "wb") as wout:
        wout.setnchannels(nch)
        wout.setsampwidth(sw)
        wout.setframerate(fr)
        for f in in_files:
            with wave.open(str(f), "rb") as win:
                if (win.getnchannels(), win.getsampwidth(), win.getframerate()) != (nch, sw, fr):
                    raise RuntimeError(f"Paramètres WAV incompatibles: {f.name}")
                wout.writeframes(win.readframes(win.getnframes()))

def tts_elevenlabs(text: str, voice_id: str, api_key: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": api_key,
        "Accept": "audio/wav",
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": VOICE_SETTINGS
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if r.status_code != 200:
        try:
            info = r.json()
        except Exception:
            info = r.text
        raise RuntimeError(f"TTS HTTP {r.status_code}: {info}")
    return r.content

def parse_dialogue(raw: str) -> list[tuple[str, str]]:
    """
    Renvoie une liste [(speaker, text), ...]
    Détecte V1/V2 (tolère 'Voix 1:' / 'Voix 2:' / 'V1 -' / 'V2 —', etc.)
    Si rien trouvé -> [('V1', full_text)]
    """
    lines = [l.strip() for l in raw.splitlines()]
    segs: list[tuple[str, str]] = []
    speaker_re = re.compile(r"^(v\s*1|voix\s*1|v1)\s*[:\-—]\s*(.+)$", re.I)
    speaker_re2 = re.compile(r"^(v\s*2|voix\s*2|v2)\s*[:\-—]\s*(.+)$", re.I)

    for line in lines:
        if not line:
            continue
        line = strip_directions(line)
        if not line:
            continue

        m1 = speaker_re.match(line)
        m2 = speaker_re2.match(line)
        if m1:
            segs.append(("V1", m1.group(2).strip()))
        elif m2:
            segs.append(("V2", m2.group(2).strip()))
        else:
            # pas de label V1/V2 explicite pour cette ligne
            segs.append(("", line))

    # Si au moins un vrai label trouvé, on va “propager” le dernier speaker
    has_any_label = any(s in ("V1", "V2") for s, _ in segs)
    if has_any_label:
        current = "V1"
        normalized = []
        for s, t in segs:
            if s in ("V1", "V2"):
                current = s
                normalized.append((current, t))
            else:
                normalized.append((current, t))
        segs = normalized
    else:
        # Tout en un bloc V1 si aucun label
        joined = " ".join([t for _, t in segs]).strip()
        segs = [("V1", joined)] if joined else []

    # Nettoyage final + suppressions de lignes vides
    cleaned = []
    for s, t in segs:
        t = sanitize_for_ass(t)
        if t:
            cleaned.append((s, t))
    return cleaned

# -------- Main --------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="story/story.txt", help="Chemin du script .txt")
    ap.add_argument("--out", default="audio/voice.wav", help="Sortie WAV")
    ap.add_argument("--cues", default="audio/dialogue_cues.json", help="Cues JSON")
    args = ap.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("ELEVENLABS_API_KEY manquant", file=sys.stderr)
        sys.exit(1)

    voice_fallback = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    voice_v1 = os.environ.get("ELEVENLABS_VOICE_ID_V1", "").strip() or voice_fallback
    voice_v2 = os.environ.get("ELEVENLABS_VOICE_ID_V2", "").strip() or voice_fallback
    if not voice_v1:
        print("Aucune voix configurée (ELEVENLABS_VOICE_ID ou *_V1/V2).", file=sys.stderr)
        sys.exit(1)

    in_path = Path(args.input)
    out_wav = Path(args.out)
    cues_json = Path(args.cues)
    chunks_dir = out_wav.parent / "chunks"
    ensure_dir(out_wav.parent)
    ensure_dir(chunks_dir)
    ensure_dir(cues_json.parent)

    if not in_path.exists():
        print(f"Script introuvable: {in_path}", file=sys.stderr)
        sys.exit(1)

    raw = read_text(in_path)
    segments = parse_dialogue(raw)
    if not segments:
        print("Script vide après parsing.", file=sys.stderr)
        sys.exit(1)

    # Synthèse morceau par morceau
    cue_list = []
    chunk_files: list[Path] = []
    t_cursor = 0.0
    idx = 0

    for speaker, text in segments:
        # découpe prudente (si réplique très longue)
        parts = split_long_text(text, max_len=250)
        local_duration = 0.0
        for j, part in enumerate(parts):
            idx += 1
            voice_id = voice_v1 if speaker == "V1" else voice_v2
            try:
                audio_bytes = tts_elevenlabs(part, voice_id, api_key)
            except Exception as e:
                print(f"[TTS] Erreur sur segment {idx}: {e}", file=sys.stderr)
                sys.exit(1)

            # durée
            dur = wav_duration_from_bytes(audio_bytes)
            local_duration += dur

            # écrit le chunk
            cf = chunks_dir / f"chunk_{idx:04d}.wav"
            with open(cf, "wb") as f:
                f.write(audio_bytes)
            chunk_files.append(cf)

            # petite pause pour respecter quotas si besoin
            time.sleep(0.05)

        # crée un cue pour TOUTE la réplique (somme des parts)
        cue_list.append({
            "speaker": speaker,
            "text": text,
            "start": round(t_cursor, 3),
            "end": round(t_cursor + local_duration, 3)
        })
        t_cursor += local_duration

    # concatène en un seul WAV
    try:
        combine_wavs_same_params(chunk_files, out_wav)
    except Exception as e:
        print(f"Concat WAV échouée: {e}", file=sys.stderr)
        sys.exit(1)

    # écrit les cues
    cues_json.write_text(json.dumps(cue_list, ensure_ascii=False, indent=2), encoding="utf-8")

    total_dur = 0.0
    if cue_list:
        total_dur = cue_list[-1]["end"]

    print(f"[voice_elevenlabs] {len(cue_list)} répliques, durée totale ~{total_dur:.2f}s")
    print(f"[voice_elevenlabs] audio: {out_wav}")
    print(f"[voice_elevenlabs] cues : {cues_json}")


if __name__ == "__main__":
    main()