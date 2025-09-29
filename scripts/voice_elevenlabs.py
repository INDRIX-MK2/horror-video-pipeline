#!/usr/bin/env python3
import argparse, os, sys, pathlib, json, subprocess, shlex, time
import urllib.request

API = "https://api.elevenlabs.io/v1/text-to-speech"

def tts_mp3(api_key: str, voice_id: str, text: str, out_mp3: pathlib.Path) -> None:
    req = urllib.request.Request(
        f"{API}/{voice_id}",
        data=json.dumps({
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.7}
        }).encode("utf-8"),
        headers={
            "xi-api-key": api_key,
            "accept": "audio/mpeg",
            "content-type": "application/json",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=300) as r, open(out_mp3, "wb") as f:
        f.write(r.read())

def ffprobe_dur(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error","-show_entries","format=duration","-of","default=nk=1:nw=1", str(path)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def mp3_to_wav(src: pathlib.Path, dst: pathlib.Path) -> None:
    subprocess.run(["ffmpeg","-nostdin","-y","-i",str(src),"-ac","1","-ar","22050",str(dst)], check=True)

def silence_wav(dst: pathlib.Path, seconds: float=1.0):
    subprocess.run(["ffmpeg","-nostdin","-y","-f","lavfi","-i",f"anullsrc=r=22050:cl=mono","-t",f"{seconds:.3f}",str(dst)], check=True)

def concat_wavs(wavs, out_path: pathlib.Path):
    lst = out_path.parent / "voice.txt"
    with lst.open("w", encoding="utf-8") as f:
        for p in wavs:
            f.write(f"file {shlex.quote(str(p))}\n")
    subprocess.run(["ffmpeg","-nostdin","-y","-f","concat","-safe","0","-i",str(lst),"-c","copy",str(out_path)], check=True)

def main():
    ap = argparse.ArgumentParser(description="ElevenLabs TTS (title + story + cta + silences)")
    ap.add_argument("--transcript", required=True, help="story/story.txt")
    ap.add_argument("--title", required=True, help="story/title.txt")
    ap.add_argument("--cta", required=True, help="story/cta.txt")
    ap.add_argument("--gap", type=float, default=1.0, help="silence between blocks (seconds)")
    ap.add_argument("--out", default="audio/voice.wav")
    args = ap.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY","")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID","")
    if not api_key or not voice_id:
        print("ELEVENLABS_API_KEY / ELEVENLABS_VOICE_ID manquants", file=sys.stderr); sys.exit(1)

    out_dir = pathlib.Path("audio"); out_dir.mkdir(parents=True, exist_ok=True)

    title_txt = pathlib.Path(args.title).read_text(encoding="utf-8").strip()
    story_txt = pathlib.Path(args.transcript).read_text(encoding="utf-8").strip()
    cta_txt   = pathlib.Path(args.cta).read_text(encoding="utf-8").strip()

    # Fichiers intermédiaires
    title_mp3 = out_dir/"title.mp3"; story_mp3 = out_dir/"story.mp3"; cta_mp3 = out_dir/"cta.mp3"
    title_wav = out_dir/"title.wav"; story_wav = out_dir/"story.wav"; cta_wav = out_dir/"cta.wav"
    sil_wav   = out_dir/"silence_1s.wav"
    final_wav = pathlib.Path(args.out)

    # TTS mp3 -> wav
    tts_mp3(api_key, voice_id, title_txt, title_mp3)
    tts_mp3(api_key, voice_id, story_txt, story_mp3)
    tts_mp3(api_key, voice_id, cta_txt,   cta_mp3)
    mp3_to_wav(title_mp3, title_wav)
    mp3_to_wav(story_mp3, story_wav)
    mp3_to_wav(cta_mp3,   cta_wav)

    silence_wav(sil_wav, seconds=max(0.1, args.gap))

    # Concatenation: title + gap + story + gap + cta
    chain = [title_wav, sil_wav, story_wav, sil_wav, cta_wav]
    concat_wavs(chain, final_wav)

    # petit journal des durées (utile pour debug)
    tl = {
        "title":  {"start": 0.0, "dur": ffprobe_dur(title_wav)},
        "gap1":   {"dur": max(0.1, args.gap)},
        "story":  {"dur": ffprobe_dur(story_wav)},
        "gap2":   {"dur": max(0.1, args.gap)},
        "cta":    {"dur": ffprobe_dur(cta_wav)},
        "final":  {"dur": ffprobe_dur(final_wav)},
    }
    (out_dir/"timeline.json").write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[voice_elevenlabs] OK ->", final_wav)

if __name__ == "__main__":
    main()
