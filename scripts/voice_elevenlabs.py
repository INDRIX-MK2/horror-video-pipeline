#!/usr/bin/env python3
import argparse
import os
import sys
import pathlib
import json
import time
import subprocess
import typing
from typing import Optional

# --------- Config minimale ----------
ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "")
ELEVEN_TTS_URL_TMPL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
DEFAULT_MODEL_ID = None  # ex: "eleven_multilingual_v2" si tu veux forcer un modèle

def fail(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)

def check_env() -> None:
    if not ELEVEN_API_KEY:
        fail("ELEVENLABS_API_KEY manquant")
    if not ELEVEN_VOICE_ID:
        fail("ELEVENLABS_VOICE_ID manquant")

def read_text_file(p: pathlib.Path) -> str:
    if not p.exists() or not p.stat().st_size:
        fail(f"Fichier texte manquant/vide: {p}")
    return p.read_text(encoding="utf-8").strip()

def tts_to_wav(text: str, out_path: pathlib.Path, voice_id: Optional[str] = None, model_id: Optional[str] = None) -> None:
    """
    Appelle l'API ElevenLabs et enregistre un WAV (PCM) dans out_path.
    """
    import urllib.request
    import urllib.error

    voice = voice_id or ELEVEN_VOICE_ID
    url = ELEVEN_TTS_URL_TMPL.format(voice_id=voice)

    payload = {
        "text": text,
        # "voice_settings": {"stability": 0.4, "similarity_boost": 0.8},  # optionnel
    }
    if model_id:
        payload["model_id"] = model_id

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("xi-api-key", ELEVEN_API_KEY)
    req.add_header("accept", "audio/mpeg")  # on reçoit du mp3
    req.add_header("content-type", "application/json")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    mp3_tmp = out_path.with_suffix(".mp3")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(mp3_tmp, "wb") as f:
            f.write(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        fail(f"HTTP {e.code} ElevenLabs: {body}")
    except Exception as e:
        fail(f"Erreur TTS ElevenLabs: {e}")

    # Convertir mp3 -> wav (48k stéréo)
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-i", str(mp3_tmp),
        "-ar", "48000",
        "-ac", "2",
        str(out_path)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        fail(f"ffmpeg conversion mp3->wav a échoué: {e}")
    finally:
        try:
            mp3_tmp.unlink(missing_ok=True)
        except Exception:
            pass

def make_silence(seconds: float, out_path: pathlib.Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo",
        "-t", str(seconds),
        str(out_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def concat_wavs_chain(files: typing.List[pathlib.Path], out_path: pathlib.Path) -> None:
    """
    Concatène plusieurs wav "codec copy".
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lst = out_path.parent / "voice_concat.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{p.as_posix()}'\n")
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(lst),
        "-c", "copy",
        str(out_path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def main():
    check_env()

    ap = argparse.ArgumentParser(
        description="ElevenLabs TTS helper (compat: --transcript/--out) + (title/story/cta mode)"
    )
    # --- Mode A (ancien) ---
    ap.add_argument("--transcript", help="Fichier texte à lire (mode ancien)")
    ap.add_argument("--out", help="WAV de sortie (mode ancien ou mode B concat)", default=None)

    # --- Mode B (nouveau, optionnel) ---
    ap.add_argument("--title-file", help="Texte du titre", default=None)
    ap.add_argument("--story-file", help="Texte de l'histoire", default=None)
    ap.add_argument("--cta-file", help="Texte CTA", default=None)
    ap.add_argument("--gap", type=float, default=1.0, help="Silence (s) générique entre segments si gap-title/gap-cta non précisés")
    ap.add_argument("--gap-title", type=float, default=None, help="Silence (s) après le titre (par défaut: --gap)")
    ap.add_argument("--gap-cta", type=float, default=None, help="Silence (s) après l'histoire avant CTA (par défaut: --gap)")
    ap.add_argument("--list-file", default=None, help="Écrit aussi la liste concat (optionnel)")
    ap.add_argument("--voice-id", default=None, help="Override ELEVENLABS_VOICE_ID")
    ap.add_argument("--model-id", default=None, help="Override model_id")
    args = ap.parse_args()

    voice_id = args.voice_id or ELEVEN_VOICE_ID
    model_id = args.model_id or DEFAULT_MODEL_ID

    # Détection du mode
    mode_old = bool(args.transcript and args.out and not (args.title_file or args.story_file or args.cta_file))
    mode_new = bool(args.out and (args.title_file or args.story_file or args.cta_file))

    if not mode_old and not mode_new:
        ap.print_help()
        fail("Utilisation invalide: fournis soit --transcript et --out (mode ancien), soit --out avec au moins un de --title-file/--story-file/--cta-file (mode nouveau).", 2)

    if mode_old:
        # ------- MODE A : rétro-compat (ancien) -------
        tpath = pathlib.Path(args.transcript)
        out_path = pathlib.Path(args.out)
        text = read_text_file(tpath)
        tts_to_wav(text, out_path, voice_id=voice_id, model_id=model_id)
        if not out_path.exists() or not out_path.stat().st_size:
            fail(f"Echec génération WAV: {out_path}")
        print(f"[voice] OK -> {out_path}")
        return

    # ------- MODE B : nouveau (optionnel) -------
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    title_text = read_text_file(pathlib.Path(args.title_file)) if args.title_file else None
    story_text = read_text_file(pathlib.Path(args.story_file)) if args.story_file else None
    cta_text = read_text_file(pathlib.Path(args.cta_file)) if args.cta_file else None

    # Fichiers intermédiaires
    audio_dir = out_path.parent
    title_wav = audio_dir / "title.wav"
    story_wav = audio_dir / "story.wav"
    cta_wav   = audio_dir / "cta.wav"

    chain: typing.List[pathlib.Path] = []

    if title_text:
        tts_to_wav(title_text, title_wav, voice_id=voice_id, model_id=model_id)
        chain.append(title_wav)
        gap_title = args.gap_title if args.gap_title is not None else args.gap
        if gap_title and gap_title > 0:
            sil1 = audio_dir / "silence_after_title.wav"
            make_silence(gap_title, sil1)
            chain.append(sil1)

    if story_text:
        tts_to_wav(story_text, story_wav, voice_id=voice_id, model_id=model_id)
        chain.append(story_wav)
        gap_cta = args.gap_cta if args.gap_cta is not None else args.gap
        if cta_text and gap_cta and gap_cta > 0:
            sil2 = audio_dir / "silence_before_cta.wav"
            make_silence(gap_cta, sil2)
            chain.append(sil2)

    if cta_text:
        tts_to_wav(cta_text, cta_wav, voice_id=voice_id, model_id=model_id)
        chain.append(cta_wav)

    if not chain:
        fail("Aucun segment (title/story/cta) fourni")

    if args.list_file:
        lst = pathlib.Path(args.list_file)
        lst.parent.mkdir(parents=True, exist_ok=True)
        with open(lst, "w", encoding="utf-8") as f:
            for p in chain:
                f.write(f"file '{p.as_posix()}'\n")

    # Concat finale
    concat_wavs_chain(chain, out_path)
    if not out_path.exists() or not out_path.stat().st_size:
        fail(f"Echec concat WAV final: {out_path}")
    print(f"[voice] Chaîne TTS OK -> {out_path}")

if __name__ == "__main__":
    main()