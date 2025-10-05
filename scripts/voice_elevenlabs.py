#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys, json, pathlib, subprocess, requests, shlex

# -----------------------
# Helpers
# -----------------------
def ensure_dir(p: pathlib.Path):
    if p.suffix:
        p.parent.mkdir(parents=True, exist_ok=True)
    else:
        p.mkdir(parents=True, exist_ok=True)

def ffprobe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=nk=1:nw=1", str(path)],
            stderr=subprocess.DEVNULL
        ).decode("utf-8","ignore").strip()
        return max(0.0, float(out))
    except Exception:
        return 0.0

def to_wav(src_path: pathlib.Path, dst_path: pathlib.Path):
    ensure_dir(dst_path)
    subprocess.run([
        "ffmpeg","-nostdin","-y","-i",str(src_path),
        "-ar","44100","-ac","1","-c:a","pcm_s16le", str(dst_path)
    ], check=True)

def make_silence_wav(out_path: pathlib.Path, duration: float):
    if duration <= 0:
        return
    ensure_dir(out_path)
    subprocess.run([
        "ffmpeg","-nostdin","-y",
        "-f","lavfi","-i","anullsrc=r=44100:cl=mono",
        "-t",str(duration),
        "-ar","44100","-ac","1","-c:a","pcm_s16le", str(out_path)
    ], check=True)

def eleven_tts(text: str, mp3_out: pathlib.Path, api_key: str, voice_id: str, model_id: str):
    if not text.strip():
        return False
    ensure_dir(mp3_out)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.3,
            "similarity_boost": 0.7
        }
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    if r.status_code != 200:
        print(f"[voice] ElevenLabs HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)
        return False
    mp3_out.write_bytes(r.content)
    return True

def write_concat_list(order_paths, list_path: pathlib.Path):
    ensure_dir(list_path)
    with list_path.open("w", encoding="utf-8") as f:
        for p in order_paths:
            # format attendu par le demuxer concat
            f.write(f"file {shlex.quote(str(p))}\n")

def concat_wavs(order, out_path: pathlib.Path, list_path: pathlib.Path|None):
    ensure_dir(out_path)
    # fichier de liste interne (même dossier que out) pour concat
    internal_list = out_path.with_name("voice.txt")
    write_concat_list(order, internal_list)
    if list_path:
        # si demandé, écrire aussi la même liste à l’endroit souhaité par le workflow
        write_concat_list(order, list_path)

    subprocess.run([
        "ffmpeg","-nostdin","-y","-f","concat","-safe","0",
        "-i",str(internal_list),
        "-c","copy",str(out_path)
    ], check=True)

# -----------------------
# CLI
# -----------------------
import argparse
ap = argparse.ArgumentParser(description="Synthesize title/story/cta with ElevenLabs and write full timeline.")
ap.add_argument("--title-file", default="story/title.txt")
ap.add_argument("--story-file", default="story/story.txt")
ap.add_argument("--cta-file",   default="story/cta.txt")

ap.add_argument("--gap",        type=float, default=None, help="gap (s) after title and before CTA (overrides specific gaps)")
ap.add_argument("--gap-title",  type=float, default=1.0,  help="gap (s) after title")
ap.add_argument("--gap-cta",    type=float, default=1.0,  help="gap (s) before CTA")

ap.add_argument("--out",        default="audio/voice.wav")
ap.add_argument("--list-file",  default=None, help="(optionnel) Chemin où écrire la liste des segments WAV concaténés")

args = ap.parse_args()

# Harmonise gaps si --gap fourni
if args.gap is not None:
    args.gap_title = args.gap
    args.gap_cta   = args.gap

root = pathlib.Path(__file__).resolve().parent.parent
t_title = root / args.title_file
t_story = root / args.story_file
t_cta   = root / args.cta_file

out_wav = root / args.out
audio_dir = out_wav.parent
ensure_dir(out_wav)

external_list = (root / args.list_file) if args.list_file else None

title_mp3 = audio_dir / "title.mp3"
story_mp3 = audio_dir / "story.mp3"
cta_mp3   = audio_dir / "cta.mp3"
title_wav = audio_dir / "title.wav"
story_wav = audio_dir / "story.wav"
cta_wav   = audio_dir / "cta.wav"
gap1_wav  = audio_dir / "gap_after_title.wav"
gap2_wav  = audio_dir / "gap_before_cta.wav"
timeline  = audio_dir / "timeline.json"

# -----------------------
# Inputs
# -----------------------
title_txt = t_title.read_text(encoding="utf-8", errors="ignore") if t_title.exists() else ""
story_txt = t_story.read_text(encoding="utf-8", errors="ignore") if t_story.exists() else ""
cta_txt   = t_cta.read_text(encoding="utf-8", errors="ignore")   if t_cta.exists()   else ""

if not story_txt.strip():
    print("[voice] story/story.txt manquant ou vide.", file=sys.stderr)
    sys.exit(1)

# -----------------------
# ElevenLabs creds
# -----------------------
api_key  = os.environ.get("ELEVENLABS_API_KEY","").strip()
voice_id = os.environ.get("ELEVENLABS_VOICE_ID","").strip()
model_id = os.environ.get("ELEVENLABS_MODEL_ID","eleven_flash_v2_5").strip()

if not api_key or not voice_id:
    print("[voice] ELEVENLABS_API_KEY et/ou ELEVENLABS_VOICE_ID manquants.", file=sys.stderr)
    sys.exit(1)

# -----------------------
# TTS
# -----------------------
title_ok = False
cta_ok   = False

if title_txt.strip():
    title_ok = eleven_tts(title_txt, title_mp3, api_key, voice_id, model_id)
    if title_ok:
        to_wav(title_mp3, title_wav)

story_ok = eleven_tts(story_txt, story_mp3, api_key, voice_id, model_id)
if not story_ok:
    print("[voice] Échec TTS sur l'histoire.", file=sys.stderr)
    sys.exit(1)
to_wav(story_mp3, story_wav)

if cta_txt.strip():
    cta_ok = eleven_tts(cta_txt, cta_mp3, api_key, voice_id, model_id)
    if cta_ok:
        to_wav(cta_mp3, cta_wav)

# Gaps
gap_title = max(0.0, float(args.gap_title))
gap_cta   = max(0.0, float(args.gap_cta))
if title_ok and gap_title > 0:
    make_silence_wav(gap1_wav, gap_title)
if cta_ok and gap_cta > 0:
    make_silence_wav(gap2_wav, gap_cta)

# -----------------------
# Concat order + timeline
# -----------------------
order = []
segments = {}  # name -> (start,end)

t = 0.0
if title_ok:
    order.append(title_wav)
    d = ffprobe_duration(title_wav)
    segments["title"] = (t, t+d)
    t += d
    if gap_title > 0:
        order.append(gap1_wav); t += ffprobe_duration(gap1_wav)

order.append(story_wav)
d = ffprobe_duration(story_wav)
segments["story"] = (t, t+d)
t += d

if cta_ok:
    if gap_cta > 0:
        order.append(gap2_wav); t += ffprobe_duration(gap2_wav)
    order.append(cta_wav)
    d = ffprobe_duration(cta_wav)
    segments["cta"] = (t, t+d)
    t += d

# Concat + (optionnel) fichier liste externe
concat_wavs(order, out_wav, external_list)
total = ffprobe_duration(out_wav)

# -----------------------
# Write timeline.json
# -----------------------
tl = {}
if "title" in segments:
    s,e = segments["title"]; tl["title"] = {"start": round(s,3), "end": round(e,3)}
if "story" in segments:
    s,e = segments["story"]; tl["story"] = {"start": round(s,3), "end": round(e,3)}
if "cta" in segments:
    s,e = segments["cta"];   tl["cta"]   = {"start": round(s,3), "end": round(e,3)}
tl["gaps"]  = {"title_after": round(gap_title,3), "cta_before": round(gap_cta,3)}
tl["total"] = round(total,3)

ensure_dir(timeline)
timeline.write_text(json.dumps(tl, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"[voice] OK -> {out_wav} (total ~{total:.2f}s)")
print(f"[voice] timeline -> {timeline}")
for k in ("title","story","cta"):
    if k in tl: print(f"[voice] {k}: {tl[k]['start']}→{tl[k]['end']}")
if external_list:
    print(f"[voice] list-file -> {external_list}")
