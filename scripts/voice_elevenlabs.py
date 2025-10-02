#!/usr/bin/env python3
import os
import sys
import json
import time
import shlex
import argparse
import pathlib
import subprocess
import requests

# ==========================
#  Constantes & chemins
# ==========================
ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_OUT_WAV = AUDIO_DIR / "voice.wav"
DEFAULT_LIST_TXT = AUDIO_DIR / "voice.txt"

# ==========================
#  Args
# ==========================
ap = argparse.ArgumentParser(description="ElevenLabs TTS (titre + histoire + cta) avec concat finale")
ap.add_argument("--title-file", help="Texte du titre (fichier)", default=str(ROOT / "story" / "title.txt"))
ap.add_argument("--story-file", help="Texte de l'histoire (fichier)", default=str(ROOT / "story" / "story.txt"))
ap.add_argument("--cta-file",   help="Texte du CTA (fichier)", default=str(ROOT / "story" / "cta.txt"))

# gaps (secondes) : pause après le titre, et avant le cta
ap.add_argument("--gap", type=float, default=None, help="(Déprécié) gap générique (utilise plutôt --gap-title / --gap-cta)")
ap.add_argument("--gap-title", type=float, default=1.0, help="Pause après le Titre (s)")
ap.add_argument("--gap-cta",   type=float, default=1.0, help="Pause entre fin histoire et CTA (s)")

ap.add_argument("--out",       default=str(DEFAULT_OUT_WAV), help="Sortie WAV finale")
ap.add_argument("--list-file", default=str(DEFAULT_LIST_TXT), help="Fichier liste pour concat")

# NOUVEAU : choix du modèle (par env ELEVENLABS_MODEL_ID ou flag)
ap.add_argument(
    "--model-id",
    default=os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5"),
    help="ID du modèle ElevenLabs (ex: eleven_flash_v2_5)"
)

args = ap.parse_args()

# si --gap est fourni, on l'applique aux deux (compat)
if args.gap is not None:
    args.gap_title = float(args.gap)
    args.gap_cta   = float(args.gap)

# ==========================
#  Secrets & voix
# ==========================
API_KEY   = os.environ.get("ELEVENLABS_API_KEY", "").strip()
VOICE_ID  = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
MODEL_ID  = args.model_id.strip()  # <= ajouté

if not API_KEY or not VOICE_ID:
    print("ELEVENLABS_API_KEY ou ELEVENLABS_VOICE_ID manquant(s)", file=sys.stderr)
    sys.exit(1)

# ==========================
#  Helpers
# ==========================
def read_text_file(p: pathlib.Path) -> str:
    if p.exists() and p.stat().st_size:
        return p.read_text(encoding="utf-8").strip()
    return ""

def tts_to_mp3(text: str, mp3_path: pathlib.Path) -> None:
    """
    Appel ElevenLabs TTS -> MP3.
    On passe model_id (Flash v2.5 par défaut) + voice_settings.
    """
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    payload = {
        "text": text,
        "model_id": MODEL_ID,  # <= ajouté
        "voice_settings": {
            "stability": 0.8,
            "similarity_boost": 0.6,
            "style": 0.75,
            "use_speaker_boost": True
        }
    }
    headers = {
        "xi-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if r.status_code != 200:
        print(f"[TTS] HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)
        raise RuntimeError("TTS failed")
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_path.write_bytes(r.content)

def mp3_to_wav(mp3_path: pathlib.Path, wav_path: pathlib.Path) -> None:
    """
    Convertit MP3 -> WAV mono 44.1kHz (paramètres identiques pour concat sans surprise).
    """
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", str(mp3_path),
        "-ac", "1", "-ar", "44100",
        "-sample_fmt", "s16",
        str(wav_path)
    ]
    subprocess.run(cmd, check=True)

def synth_to_wav(text: str, wav_path: pathlib.Path) -> None:
    """
    TTS en deux temps : MP3 depuis ElevenLabs, puis conversion WAV identique.
    """
    tmp_mp3 = wav_path.with_suffix(".mp3")
    tts_to_mp3(text, tmp_mp3)
    mp3_to_wav(tmp_mp3, wav_path)
    try:
        tmp_mp3.unlink(missing_ok=True)
    except Exception:
        pass

def make_silence_wav(wav_path: pathlib.Path, seconds: float) -> None:
    """
    Génère un WAV silence mono 44.1kHz (pour les gaps).
    """
    if seconds <= 0:
        # crée un silence très court (~1ms) pour garder une structure homogène si jamais utilisé
        seconds = 0.001
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=mono",
        "-t", f"{seconds:.3f}",
        "-ac", "1", "-ar", "44100", "-sample_fmt", "s16",
        str(wav_path)
    ]
    subprocess.run(cmd, check=True)

def write_concat_list(paths, list_path: pathlib.Path) -> None:
    """
    Écrit la liste 'ffconcat' (concat demuxer) : lignes "file 'abs_path'".
    """
    lines = []
    for p in paths:
        lines.append(f"file {shlex.quote(str(p))}")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def concat_wavs(list_path: pathlib.Path, out_wav: pathlib.Path) -> None:
    """
    Concat demuxer (toutes les sources = WAV mono 44.1kHz s16).
    """
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(out_wav)
    ]
    subprocess.run(cmd, check=True)

# ==========================
#  Lecture des textes
# ==========================
title_path = pathlib.Path(args.title_file)
story_path = pathlib.Path(args.story_file)
cta_path   = pathlib.Path(args.cta_file)

title_txt = read_text_file(title_path)
story_txt = read_text_file(story_path)
cta_txt   = read_text_file(cta_path)

# ==========================
#  Synthèse & concat
# ==========================
chain = []  # liste des .wav dans l'ordre

# 1) Titre
if title_txt:
    title_wav = AUDIO_DIR / "title.wav"
    print(f"[voice] synthèse TITRE -> {title_wav}")
    synth_to_wav(title_txt, title_wav)
    chain.append(title_wav)

    # gap après le titre
    if args.gap_title and args.gap_title > 0:
        gap_title_wav = AUDIO_DIR / "gap_title.wav"
        print(f"[voice] gap après titre: {args.gap_title:.3f}s")
        make_silence_wav(gap_title_wav, args.gap_title)
        chain.append(gap_title_wav)

# 2) Histoire (obligatoire)
if not story_txt:
    print("Texte histoire manquant/vide", file=sys.stderr)
    sys.exit(1)

story_wav = AUDIO_DIR / "story.wav"
print(f"[voice] synthèse HISTOIRE -> {story_wav}")
synth_to_wav(story_txt, story_wav)
chain.append(story_wav)

# 3) Gap avant CTA
if cta_txt and args.gap_cta and args.gap_cta > 0:
    gap_cta_wav = AUDIO_DIR / "gap_cta.wav"
    print(f"[voice] gap avant CTA: {args.gap_cta:.3f}s")
    make_silence_wav(gap_cta_wav, args.gap_cta)
    chain.append(gap_cta_wav)

# 4) CTA (optionnel)
if cta_txt:
    cta_wav = AUDIO_DIR / "cta.wav"
    print(f"[voice] synthèse CTA -> {cta_wav}")
    synth_to_wav(cta_txt, cta_wav)
    chain.append(cta_wav)

# ==========================
#  Concat finale
# ==========================
out_wav = pathlib.Path(args.out)
out_wav.parent.mkdir(parents=True, exist_ok=True)
list_txt = pathlib.Path(args.list_file)
write_concat_list(chain, list_txt)

print(f"[voice] concat -> {out_wav}")
concat_wavs(list_txt, out_wav)

# petit log de durée
try:
    dur = subprocess.check_output([
        "ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=nk=1:nw=1", str(out_wav)
    ]).decode("utf-8","ignore").strip()
    print(f"[voice] durée finale ≈ {float(dur):.2f}s")
except Exception:
    pass

print("[voice] OK")
