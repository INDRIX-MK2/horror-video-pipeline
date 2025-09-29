#!/usr/bin/env python3
import argparse, os, sys, json, pathlib, subprocess, shlex, time
from urllib import request
from urllib.error import HTTPError

API = "https://api.elevenlabs.io/v1/text-to-speech"

def must_env(name: str) -> str:
    v = os.getenv(name, "").strip()
    if not v:
        print(f"[voice] ERREUR: variable d'env {name} manquante", file=sys.stderr)
        sys.exit(1)
    return v

def ffprobe_duration(p: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration",
            "-of","default=nk=1:nw=1", str(p)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def tts_to_mp3(text: str, voice_id: str, out_mp3: pathlib.Path, api_key: str, model: str="eleven_multilingual_v2"):
    payload = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }).encode("utf-8")

    req = request.Request(
        f"{API}/{voice_id}",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "xi-api-key": api_key
        },
        method="POST"
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            out_mp3.write_bytes(resp.read())
    except HTTPError as e:
        msg = e.read().decode("utf-8","ignore")
        print(f"[voice] HTTP {e.code} {msg}", file=sys.stderr)
        sys.exit(1)

def to_wav_441k_stereo(inp: pathlib.Path, out_wav: pathlib.Path):
    subprocess.run([
        "ffmpeg","-nostdin","-y",
        "-i", str(inp),
        "-ar","44100","-ac","2","-c:a","pcm_s16le",
        str(out_wav)
    ], check=True)

def gen_silence_wav(out_wav: pathlib.Path, seconds: float):
    subprocess.run([
        "ffmpeg","-nostdin","-y",
        "-f","lavfi","-i",f"anullsrc=r=44100:cl=stereo",
        "-t", f"{seconds:.3f}",
        "-ar","44100","-ac","2","-c:a","pcm_s16le",
        str(out_wav)
    ], check=True)

def concat_wavs(wavs, out_wav: pathlib.Path):
    # Concat demuxer => besoin d’un file list
    flist = out_wav.with_suffix(".txt")
    with flist.open("w", encoding="utf-8") as f:
        for w in wavs:
            f.write(f"file {w.as_posix()}\n")
    subprocess.run([
        "ffmpeg","-nostdin","-y","-f","concat","-safe","0",
        "-i", str(flist),
        "-c","copy",
        str(out_wav)
    ], check=True)
    try: flist.unlink()
    except: pass

def main():
    ap = argparse.ArgumentParser(description="Synthesize ElevenLabs: title -> 2s gap -> story -> cta")
    ap.add_argument("--transcript", required=True, help="story/story.txt (histoire SANS didascalies)")
    ap.add_argument("--out", default="audio/voice.wav")
    ap.add_argument("--title", help="story/title.txt")
    ap.add_argument("--cta", help="story/cta.txt (sinon phrase par défaut)")
    ap.add_argument("--gap", type=float, default=2.0, help="silence entre titre et histoire (sec)")
    args = ap.parse_args()

    api_key = must_env("ELEVENLABS_API_KEY")
    voice_id = must_env("ELEVENLABS_VOICE_ID")

    tpath = pathlib.Path(args.transcript)
    if not tpath.exists() or not tpath.stat().st_size:
        print("[voice] ERREUR: transcript vide/manquant", file=sys.stderr)
        sys.exit(1)
    story = tpath.read_text(encoding="utf-8")

    title_txt = ""
    if args.title:
        p = pathlib.Path(args.title)
        if p.exists() and p.stat().st_size:
            title_txt = p.read_text(encoding="utf-8").strip()

    cta_txt = ""
    if args.cta:
        p = pathlib.Path(args.cta)
        if p.exists() and p.stat().st_size:
            cta_txt = p.read_text(encoding="utf-8").strip()
    if not cta_txt:
        cta_txt = "Tu as aimé ? Abonne-toi et partage pour plus d’histoires…"

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    work = out.parent
    mp3_title = work/"title.mp3"
    mp3_story = work/"story.mp3"
    mp3_cta   = work/"cta.mp3"
    wav_title = work/"title.wav"
    wav_story = work/"story.wav"
    wav_cta   = work/"cta.wav"
    wav_gap   = work/"gap.wav"

    # TTS
    if title_txt:
        tts_to_mp3(title_txt, voice_id, mp3_title, api_key)
        to_wav_441k_stereo(mp3_title, wav_title)
    tts_to_mp3(story, voice_id, mp3_story, api_key)
    to_wav_441k_stereo(mp3_story, wav_story)
    tts_to_mp3(cta_txt, voice_id, mp3_cta, api_key)
    to_wav_441k_stereo(mp3_cta, wav_cta)

    if args.gap > 0.0:
        gen_silence_wav(wav_gap, args.gap)

    # Concat
    chain = []
    if title_txt:
        chain.append(wav_title)
        if args.gap > 0.0:
            chain.append(wav_gap)
    chain.append(wav_story)
    chain.append(wav_cta)

    concat_wavs(chain, out)

    # Timeline
    title_d = ffprobe_duration(wav_title) if title_txt else 0.0
    gap_d   = args.gap if title_txt else 0.0
    story_d = ffprobe_duration(wav_story)
    cta_d   = ffprobe_duration(wav_cta)
    total   = ffprobe_duration(out)

    timeline = {
        "title": title_d,
        "gap": gap_d,
        "story": story_d,
        "cta": cta_d,
        "total": total
    }
    (work/"timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[voice] OK. Durées: {timeline}")

if __name__ == "__main__":
    main()