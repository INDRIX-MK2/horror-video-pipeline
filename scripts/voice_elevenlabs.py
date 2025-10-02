#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Synthèse Titre + (gap) + Histoire + (gap) + CTA via ElevenLabs (Flash v2.5),
concat en audio/voice.wav et écriture de audio/timeline.json.

Dépendances: requests, ffmpeg installé dans le PATH.
Variables env: ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
Optionnel: ELEVENLABS_MODEL_ID (défaut: eleven_flash_v2_5)
"""

import os, sys, json, pathlib, argparse, subprocess, tempfile
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

API_KEY   = os.environ.get("ELEVENLABS_API_KEY", "").strip()
VOICE_ID  = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
MODEL_ID  = os.environ.get("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5").strip()  # Flash v2.5 par défaut

def die(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    sys.exit(code)

def ffprobe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", str(path)]
        ).decode("utf-8", "ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def tts_to_wav(text: str, out_wav: pathlib.Path):
    """Appelle ElevenLabs (Flash v2.5) -> MP3 puis convertit en WAV mono 44.1k s16."""
    if not API_KEY or not VOICE_ID:
        die("ELEVENLABS_API_KEY ou ELEVENLABS_VOICE_ID manquant(e).")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream"
    headers = {
        "xi-api-key": API_KEY,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": MODEL_ID,               # Flash v2.5
        "output_format": "mp3_44100_128"    # fiable, puis conversion WAV
    }

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        mp3_path = pathlib.Path(tmp.name)

    r = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
    if r.status_code != 200:
        die(f"[voice] HTTP {r.status_code} ElevenLabs: {r.text[:500]}")

    with open(mp3_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 14):
            if chunk:
                f.write(chunk)

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-i", str(mp3_path),
         "-ac", "1", "-ar", "44100", "-acodec", "pcm_s16le", str(out_wav)],
        check=True
    )
    try:
        mp3_path.unlink(missing_ok=True)
    except Exception:
        pass

def make_silence(duration_sec: float, out_wav: pathlib.Path):
    """Génère un silence WAV mono 44.1k s16."""
    d = max(0.0, float(duration_sec))
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y",
         "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono",
         "-t", f"{d:.3f}",
         "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
         str(out_wav)],
        check=True
    )

def concat_wavs(paths, out_wav: pathlib.Path, list_path: pathlib.Path | None = None):
    """
    Concatène via demuxer concat en utilisant un fichier-liste à chemins ABSOLUS.
    Si list_path est fourni, il sera utilisé/écrit. Sinon, audio/voice.txt est utilisé.
    """
    if list_path is None:
        list_path = AUDIO_DIR / "voice.txt"

    def esc(p: pathlib.Path) -> str:
        s = str(p.resolve())
        s = s.replace("'", r"'\''")
        return f"file '{s}'"

    list_path.parent.mkdir(parents=True, exist_ok=True)
    list_path.write_text("\n".join(esc(p) for p in paths) + "\n", encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0",
         "-i", str(list_path), "-c", "copy", str(out_wav)],
        check=True
    )

def read_text_file(p: pathlib.Path) -> str:
    if not p.exists() or p.stat().st_size == 0:
        return ""
    return p.read_text(encoding="utf-8").strip()

def main():
    ap = argparse.ArgumentParser(description="ElevenLabs TTS (Flash v2.5) -> voice.wav + timeline.json")
    ap.add_argument("--title-file", default=str((ROOT / "story" / "title.txt")))
    ap.add_argument("--story-file", default=str((ROOT / "story" / "story.txt")))
    ap.add_argument("--cta-file",   default=str((ROOT / "story" / "cta.txt")))
    # gaps (secondes)
    ap.add_argument("--gap", type=float, default=None, help="Applique cette valeur aux 2 gaps si fourni.")
    ap.add_argument("--gap-title", type=float, default=1.0, help="Silence après le titre (s).")
    ap.add_argument("--gap-cta",   type=float, default=1.0, help="Silence avant le CTA (s).")
    # sortie finale
    ap.add_argument("--out", default=str(AUDIO_DIR / "voice.wav"))
    # (nouveau) fichier liste concat optionnel
    ap.add_argument("--list-file", default=str(AUDIO_DIR / "voice.txt"))
    args = ap.parse_args()

    if args.gap is not None:
        args.gap_title = float(args.gap)
        args.gap_cta   = float(args.gap)

    title_txt = read_text_file(pathlib.Path(args.title_file))
    story_txt = read_text_file(pathlib.Path(args.story_file))
    cta_txt   = read_text_file(pathlib.Path(args.cta_file))

    if not title_txt:
        die("title.txt manquant ou vide")
    if not story_txt:
        die("story.txt manquant ou vide")
    if not cta_txt:
        die("cta.txt manquant ou vide")

    p_title = AUDIO_DIR / "title.wav"
    p_story = AUDIO_DIR / "story.wav"
    p_cta   = AUDIO_DIR / "cta.wav"
    p_gap1  = AUDIO_DIR / "gap_after_title.wav"
    p_gap2  = AUDIO_DIR / "gap_before_cta.wav"
    p_final = pathlib.Path(args.out)
    p_tl    = AUDIO_DIR / "timeline.json"
    p_list  = pathlib.Path(args.list_file) if args.list_file else None

    # Synthèses
    print("[voice] synthèse TITRE   ->", p_title)
    tts_to_wav(title_txt, p_title)

    print("[voice] synthèse HISTOIRE ->", p_story)
    tts_to_wav(story_txt, p_story)

    # gaps
    print(f"[voice] gap après titre: {args.gap_title:.3f}s")
    make_silence(args.gap_title, p_gap1)

    print("[voice] synthèse CTA     ->", p_cta)
    tts_to_wav(cta_txt, p_cta)

    print(f"[voice] gap avant CTA  : {args.gap_cta:.3f}s")
    make_silence(args.gap_cta, p_gap2)

    # Concat: titre, gap, histoire, gap, cta
    chain = [p_title, p_gap1, p_story, p_gap2, p_cta]
    print("[voice] concat ->", p_final)
    concat_wavs(chain, p_final, list_path=p_list)

    # Durées et timeline
    d_title = ffprobe_duration(p_title)
    d_story = ffprobe_duration(p_story)
    d_cta   = ffprobe_duration(p_cta)
    d_gap1  = ffprobe_duration(p_gap1)
    d_gap2  = ffprobe_duration(p_gap2)
    d_final = ffprobe_duration(p_final)

    # Offsets
    t0_title = 0.0
    t1_title = t0_title + d_title

    t0_story = t1_title + d_gap1
    t1_story = t0_story + d_story

    t0_cta   = t1_story + d_gap2
    t1_cta   = t0_cta + d_cta

    timeline = {
        "title": {"file": str(p_title), "start": round(t0_title,3), "duration": round(d_title,3)},
        "gap_after_title": round(d_gap1,3),
        "story": {"file": str(p_story), "start": round(t0_story,3), "duration": round(d_story,3)},
        "gap_before_cta": round(d_gap2,3),
        "cta": {"file": str(p_cta), "start": round(t0_cta,3), "duration": round(d_cta,3)},
        "total": round(d_final, 3),
        "model_id": MODEL_ID,
        "voice_id": VOICE_ID
    }
    p_tl.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[voice] durée finale = {d_final:.2f}s")
    print(f"[voice] timeline -> {p_tl}")

if __name__ == "__main__":
    main()