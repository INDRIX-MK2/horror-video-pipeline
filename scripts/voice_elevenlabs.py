#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Génère l'audio (title -> story -> cta) avec ElevenLabs, ajoute des silences,
puis concatène en un WAV final. Écrit aussi audio/voice.txt (chemins ABSOLUS)
pour ffmpeg concat.

ENV requis:
- ELEVENLABS_API_KEY
- ELEVENLABS_VOICE_ID

Exemple:
python scripts/voice_elevenlabs.py \
  --title-file story/title.txt \
  --story-file story/story.txt \
  --cta-file   story/cta.txt \
  --gap 0.0 \
  --gap-title 1.0 \
  --gap-cta   1.0 \
  --out audio/voice.wav \
  --list-file audio/voice.txt
"""

import argparse
import json
import os
import pathlib
import subprocess
import sys
from typing import List

import requests


def ensure_dir(p: pathlib.Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def read_text(path: pathlib.Path) -> str:
    if not path or not path.exists() or path.stat().st_size == 0:
        return ""
    return path.read_text(encoding="utf-8").strip()


def ffmpeg_check() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        print("[voice] ERREUR: ffmpeg introuvable dans le PATH.", file=sys.stderr)
        sys.exit(1)


def make_silence(out_wav: pathlib.Path, seconds: float) -> None:
    seconds = max(0.0, float(seconds))
    if seconds <= 0.0:
        seconds = 0.01
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-t",
        f"{seconds:.3f}",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def tts_elevenlabs(text: str, out_wav: pathlib.Path, api_key: str, voice_id: str) -> None:
    if not text:
        make_silence(out_wav, 0.1)
        return

    url = "https://api.elevenlabs.io/v1/text-to-speech/{}/stream".format(voice_id)
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {
            "stability": 0.6,
            "similarity_boost": 0.8,
            "style": 0.0,
            "use_speaker_boost": True,
        },
    }

    with requests.post(url, headers=headers, json=payload, stream=True, timeout=120) as r:
        if r.status_code >= 400:
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            print("[voice] ERREUR ElevenLabs {}: {}".format(r.status_code, detail), file=sys.stderr)
            sys.exit(1)

        mp3_tmp = out_wav.with_suffix(".mp3")
        with open(mp3_tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    # MP3 -> WAV
    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        str(mp3_tmp),
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "pcm_s16le",
        str(out_wav),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # cleanup
    try:
        mp3_tmp.unlink()
    except Exception:
        pass


def concat_wavs_chain(files: List[pathlib.Path], out_path: pathlib.Path, list_file: pathlib.Path) -> None:
    ensure_dir(out_path.parent)
    ensure_dir(list_file.parent)

    with open(list_file, "w", encoding="utf-8") as f:
        for p in files:
            abs_p = p.resolve().as_posix()
            # Échapper la quote simple pour le concat demuxer
            abs_quoted = abs_p.replace("'", "'\\''")
            f.write("file '{}'\n".format(abs_quoted))

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def probe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nk=1:nw=1",
                str(p),
            ]
        ).decode("utf-8", "ignore")
        return float(out.strip())
    except Exception:
        return 0.0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Génère la voix (title/story/cta) avec ElevenLabs et concatène en WAV final.")
    ap.add_argument("--title-file", type=str, default="", help="Chemin texte du titre (optionnel)")
    ap.add_argument("--story-file", type=str, default="", help="Chemin texte de l'histoire (souvent présent)")
    ap.add_argument("--cta-file", type=str, default="", help="Chemin texte du CTA (optionnel)")

    ap.add_argument("--gap", type=float, default=0.0, help="Silence générique (si ni titre ni gaps spécifiques)")
    ap.add_argument("--gap-title", type=float, default=1.0, help="Silence APRÈS le titre")
    ap.add_argument("--gap-cta", type=float, default=1.0, help="Silence AVANT le CTA")

    ap.add_argument("--out", type=str, default="audio/voice.wav", help="Fichier WAV final")
    ap.add_argument("--list-file", type=str, default="audio/voice.txt", help="Fichier liste concat FFmpeg")

    return ap.parse_args()


def main() -> None:
    ffmpeg_check()

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    if not api_key or not voice_id:
        print("[voice] ERREUR: ELEVENLABS_API_KEY ou ELEVENLABS_VOICE_ID manquant(s).", file=sys.stderr)
        sys.exit(1)

    args = parse_args()

    out_wav = pathlib.Path(args.out)
    list_file = pathlib.Path(args.list_file)
    audio_dir = out_wav.parent
    ensure_dir(audio_dir)

    title_txt = read_text(pathlib.Path(args.title_file)) if args.title_file else ""
    story_txt = read_text(pathlib.Path(args.story_file)) if args.story_file else ""
    cta_txt = read_text(pathlib.Path(args.cta_file)) if args.cta_file else ""

    if not title_txt and not story_txt and not cta_txt:
        print("[voice] ERREUR: aucun texte fourni (title/story/cta vides).", file=sys.stderr)
        sys.exit(1)

    # Fichiers cibles
    title_wav = audio_dir / "title.wav"
    story_wav = audio_dir / "story.wav"
    cta_wav = audio_dir / "cta.wav"
    gap_title_wav = audio_dir / "gap_title.wav"
    gap_generic_wav = audio_dir / "gap_generic.wav"
    gap_cta_wav = audio_dir / "gap_cta.wav"

    chain: List[pathlib.Path] = []

    # Titre
    if title_txt:
        tts_elevenlabs(title_txt, title_wav, api_key, voice_id)
        chain.append(title_wav)
        if args.gap_title > 0.0:
            make_silence(gap_title_wav, args.gap_title)
            chain.append(gap_title_wav)
    elif args.gap > 0.0:
        make_silence(gap_generic_wav, args.gap)
        chain.append(gap_generic_wav)

    # Histoire
    if story_txt:
        tts_elevenlabs(story_txt, story_wav, api_key, voice_id)
        chain.append(story_wav)

    # Gap avant CTA
    if cta_txt and args.gap_cta > 0.0:
        make_silence(gap_cta_wav, args.gap_cta)
        chain.append(gap_cta_wav)

    # CTA
    if cta_txt:
        tts_elevenlabs(cta_txt, cta_wav, api_key, voice_id)
        chain.append(cta_wav)

    if not chain:
        print("[voice] ERREUR: rien à concaténer (chaîne vide).", file=sys.stderr)
        sys.exit(1)

    concat_wavs_chain(chain, out_wav, list_file)

    # timeline.json (facultatif, utile pour debug)
    timeline = []
    cur = 0.0
    for p in chain:
        d = probe_duration(p)
        timeline.append({"file": str(p.resolve()), "start": cur, "end": cur + d, "duration": d})
        cur += d
    (audio_dir / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")

    print("[voice] OK -> {}".format(out_wav))
    print("[voice] Liste concat -> {}".format(list_file))
    print("[voice] Timeline -> {}".format(audio_dir / "timeline.json"))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print("[voice] ERREUR FFmpeg:", e, file=sys.stderr)
        try:
            # e.cmd peut ne pas exister sous tous les Python, on protège
            print("CMD:", " ".join([str(x) for x in getattr(e, "cmd", [])]), file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)
    except requests.RequestException as e:
        print("[voice] ERREUR réseau ElevenLabs:", e, file=sys.stderr)
        sys.exit(1)