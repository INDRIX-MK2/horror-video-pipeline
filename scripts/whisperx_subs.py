#!/usr/bin/env python3
import argparse, os, sys, json, subprocess, shlex, math, pathlib

def ffprobe_duration(path: str) -> float:
    try:
        out = subprocess.check_output(
            ["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",path],
            stderr=subprocess.STDOUT
        ).decode().strip()
        return float(out)
    except Exception:
        return 0.0

def ass_header() -> str:
    # Style unique "TikTok"
    return "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        # Texte blanc, contour noir, aligné bas-centre
        "Style: TikTok,Inter,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,30,30,80,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]) + "\n"

def sec_to_ass_ts(t: float) -> str:
    if t < 0: t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - math.floor(t)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def ass_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")

def write_dialog(fh, start, end, text):
    fh.write(f"Dialogue: 0,{sec_to_ass_ts(start)},{sec_to_ass_ts(end)},TikTok,,0,0,0,,{text}\n")

def whisperx_align(audio_path: str, transcript: str):
    """
    Retourne une liste de segments:
      [{"start":float,"end":float,"words":[{"word":str,"start":float,"end":float}, ...]}]
    ou None si WhisperX indisponible/échoue.
    """
    try:
        import torch  # noqa
        import whisperx  # noqa
    except Exception:
        return None

    device = "cpu"
    try:
        model = whisperx.load_model("base", device)  # base pour runner GitHub CPU
        audio = whisperx.load_audio(audio_path)
        result = model.transcribe(audio, batch_size=8)
        lang = result.get("language") or "fr"
        model_a, metadata = whisperx.load_align_model(language_code=lang, device=device)
        aligned = whisperx.align(result["segments"], model_a, metadata, audio, device,
                                 return_char_alignments=False)
        segs = []
        for seg in aligned.get("segments", []):
            words = []
            for w in seg.get("words", []):
                if w.get("start") is None or w.get("end") is None:
                    continue
                words.append({"word": w.get("word","").strip(), "start": float(w["start"]), "end": float(w["end"])})
            if not words:
                # fallback: segment entier
                s = float(max(seg.get("start",0.0), 0.0))
                e = float(max(seg.get("end", s + 0.8), s + 0.8))
                txt = (seg.get("text") or "").strip()
                words = [{"word": w, "start": s, "end": e} for w in txt.split()]
            s = float(words[0]["start"]) if words else float(seg.get("start",0.0))
            e = float(words[-1]["end"]) if words else float(seg.get("end", s+0.8))
            segs.append({"start": s, "end": e, "words": words})
        return segs or None
    except Exception:
        return None

def build_kara_line(words):
    """
    Construit une ligne avec balises \\k par mot (centisecondes).
    """
    bits = []
    for w in words:
        dur = max(0.01, float(w["end"]) - float(w["start"]))
        cs = int(round(dur * 100))  # centisecondes
        token = ass_escape(w["word"])
        bits.append("{\\k" + str(cs) + "}" + token + " ")
    return "".join(bits).rstrip()

def fallback_segments(audio_dur: float, transcript: str):
    """
    Sans WhisperX: répartit linéairement les mots sur toute la durée, en lignes ~3s.
    """
    words = [w for w in transcript.split() if w.strip()]
    if not words or audio_dur <= 0:
        return []

    per_word = max(audio_dur / max(len(words),1), 0.25)  # min 0.25s/mot
    segs = []
    t = 0.0
    buf = []
    acc = 0.0
    for w in words:
        buf.append({"word": w, "start": t+acc, "end": t+acc+per_word})
        acc += per_word
        if acc >= 3.0 and len(buf) >= 3:  # ~3s par ligne
            segs.append({"start": buf[0]["start"], "end": buf[-1]["end"], "words": buf[:]})
            t += acc
            buf, acc = [], 0.0
    if buf:
        segs.append({"start": buf[0]["start"], "end": buf[-1]["end"], "words": buf[:]})
    # clamp à la durée audio
    for s in segs:
        s["start"] = max(0.0, min(s["start"], audio_dur))
        s["end"] = max(s["start"]+0.05, min(s["end"], audio_dur))
    return segs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--out", default="subtitles/captions.ass")
    ap.add_argument("--ass-style", help="(ignoré, style interne)", default=None)
    args = ap.parse_args()

    audio = args.audio
    story = args.transcript
    outp = args.out

    if not os.path.isfile(audio):
        print(f"Audio introuvable: {audio}", file=sys.stderr); sys.exit(1)
    if not os.path.isfile(story):
        print(f"Transcript introuvable: {story}", file=sys.stderr); sys.exit(1)

    text = pathlib.Path(story).read_text(encoding="utf-8").strip()
    # Nettoyage: retirer didascalies éventuelles
    text = text.replace("Intro", "").replace("Scène", "").replace("Narrateur", "")
    text = " ".join(text.split())

    dur = ffprobe_duration(audio)
    if dur <= 0:
        print("Durée audio invalide", file=sys.stderr); sys.exit(1)

    segs = whisperx_align(audio, text)
    if not segs:
        segs = fallback_segments(dur, text)

    out_dir = os.path.dirname(outp) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(outp, "w", encoding="utf-8") as f:
        f.write(ass_header())
        for seg in segs:
            line = build_kara_line(seg["words"])
            write_dialog(f, seg["start"], seg["end"], line)

    print(f"[whisperx_subs] écrit: {os.path.abspath(outp)} (durée audio: {dur:.2f}s)")

if __name__ == "__main__":
    main()