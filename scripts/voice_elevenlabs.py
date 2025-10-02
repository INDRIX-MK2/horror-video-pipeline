#!/usr/bin/env python3
import argparse, os, sys, json, pathlib, shlex, subprocess, tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

"""
Génère 0..3 segments (title/story/cta) via ElevenLabs et les concatène, avec des silences
entre segments. Écrit la chaîne concat audio/voice.wav et la liste audio/voice.txt (chemins ABS).
Tolérant : accepte --gap (appliqué aux deux), ou bien --gap-title et --gap-cta séparés.
"""

def must_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        print(f"{name} manquant", file=sys.stderr)
        sys.exit(1)
    return v

def save_wav_bytes(b: bytes, out_path: pathlib.Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        f.write(b)

def tts_elevenlabs(text: str, voice_id: str, api_key: str) -> bytes:
    if not text.strip():
        return b""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("xi-api-key", api_key)
    try:
        with urlopen(req, timeout=60) as r:
            return r.read()
    except HTTPError as e:
        msg = e.read().decode("utf-8", "ignore")
        print(f"[TTS] HTTP {e.code} -> {msg}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"[TTS] URL error -> {e}", file=sys.stderr)
        sys.exit(1)

def make_silence(seconds: float, out_path: pathlib.Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # WAV PCM 16 mono 48k
    cmd = [
        "ffmpeg","-nostdin","-y",
        "-f","lavfi","-i",f"anullsrc=r=48000:cl=mono",
        "-t",str(max(0.0, seconds)),
        "-c:a","pcm_s16le",
        str(out_path)
    ]
    subprocess.run(cmd, check=True)

def concat_wavs(abs_paths, out_path: pathlib.Path, list_file: pathlib.Path):
    list_file.parent.mkdir(parents=True, exist_ok=True)
    with list_file.open("w", encoding="utf-8") as f:
        for p in abs_paths:
            f.write(f"file {shlex.quote(str(p))}\n")
    cmd = [
        "ffmpeg","-nostdin","-y",
        "-f","concat","-safe","0",
        "-i",str(list_file),
        "-c","copy",
        str(out_path)
    ]
    subprocess.run(cmd, check=True)

def read_txt(p: pathlib.Path) -> str:
    if not p.exists() or not p.stat().st_size:
        return ""
    return p.read_text(encoding="utf-8").strip()

def main():
    ap = argparse.ArgumentParser(description="ElevenLabs TTS chain (title -> gap -> story -> gap -> cta)")
    ap.add_argument("--title-file", type=str, help="fichier texte du titre")
    ap.add_argument("--story-file", type=str, help="fichier texte de l'histoire")
    ap.add_argument("--cta-file",   type=str, help="fichier texte du CTA")

    # gaps
    ap.add_argument("--gap", type=float, default=None, help="appliquer le même gap (s) avant histoire et avant cta")
    ap.add_argument("--gap-title", type=float, default=1.0, help="silence après le titre (s)")
    ap.add_argument("--gap-cta",   type=float, default=1.0, help="silence avant le CTA (s)")

    # sorties
    ap.add_argument("--out", type=str, default="audio/voice.wav")
    ap.add_argument("--list-file", type=str, default="audio/voice.txt")

    args = ap.parse_args()

    # Tolérance : si --gap est fourni, l’appliquer aux deux s’il ne sont pas spécifiés
    if args.gap is not None:
        if ap.get_default("gap_title") == args.gap_title:
            args.gap_title = args.gap
        if ap.get_default("gap_cta") == args.gap_cta:
            args.gap_cta = args.gap

    # Envs
    api_key = must_env("ELEVENLABS_API_KEY")
    voice_id = must_env("ELEVENLABS_VOICE_ID")

    # Entrées
    title_txt = read_txt(pathlib.Path(args.title_file)) if args.title_file else ""
    story_txt = read_txt(pathlib.Path(args.story_file)) if args.story_file else ""
    cta_txt   = read_txt(pathlib.Path(args.cta_file))   if args.cta_file   else ""

    out_path  = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = pathlib.Path(args.list_file)

    tmp = pathlib.Path("audio")
    tmp.mkdir(parents=True, exist_ok=True)

    chain = []  # chemins ABS dans l’ordre
    # 1) Title
    if title_txt:
        b = tts_elevenlabs(title_txt, voice_id, api_key)
        title_wav = tmp / "title.wav"
        save_wav_bytes(b, title_wav)
        chain.append(title_wav.resolve())
        # gap après le titre
        if args.gap_title > 0:
            g1 = tmp / "gap_after_title.wav"
            make_silence(args.gap_title, g1)
            chain.append(g1.resolve())

    # 2) Story
    if story_txt:
        b = tts_elevenlabs(story_txt, voice_id, api_key)
        story_wav = tmp / "story.wav"
        save_wav_bytes(b, story_wav)
        chain.append(story_wav.resolve())
        # gap avant CTA
        if cta_txt and args.gap_cta > 0:
            g2 = tmp / "gap_before_cta.wav"
            make_silence(args.gap_cta, g2)
            chain.append(g2.resolve())

    # 3) CTA
    if cta_txt:
        b = tts_elevenlabs(cta_txt, voice_id, api_key)
        cta_wav = tmp / "cta.wav"
        save_wav_bytes(b, cta_wav)
        chain.append(cta_wav.resolve())

    if not chain:
        print("Aucun segment audio généré (title/story/cta vides ?)", file=sys.stderr)
        sys.exit(1)

    concat_wavs(chain, out_path, list_file)
    print(f"[voice] OK -> {out_path} | list: {list_file}")

if __name__ == "__main__":
    main()
