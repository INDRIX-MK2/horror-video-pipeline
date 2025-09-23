#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import json, subprocess, shlex, math, sys
import os

# ---------- Utilitaires ----------
def repo_root() -> Path:
    # ce fichier est dans subtitles/, on remonte à la racine du repo
    return Path(__file__).resolve().parents[1]

def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")

def ass_time(t: float) -> str:
    if t < 0: t = 0.0
    h = int(t // 3600); t -= h * 3600
    m = int(t // 60);   t -= m * 60
    s = int(t)
    cs = int(round((t - s) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def ffprobe_duration(path: Path) -> float:
    # renvoie 0.0 si échec (on ne crash pas)
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(path)
        ]
        out = subprocess.check_output(cmd, text=True)
        j = json.loads(out)
        dur = float(j.get("format", {}).get("duration", 0.0))
        return max(0.0, dur)
    except Exception:
        return 0.0

# ---------- Paramètres par défaut ----------
R = repo_root()
DEFAULT_HEADER = """[Script Info]
; Aegisub file
Title: TikTok Horror Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.601
PlayResX: 1080
PlayResY: 1920
Timer: 100,0000

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,Inter,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H55000000,0,0,0,0,100,100,0,0,1,3,0,2,50,50,100,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

def load_header(explicit: Path | None) -> str:
    # priorité à un header fourni, sinon on tente subtitles/ass_header.ass,
    # sinon fallback embarqué
    if explicit and explicit.is_file() and explicit.stat().st_size > 0:
        return read_text(explicit)
    candidate = R / "subtitles" / "ass_header.ass"
    if candidate.is_file() and candidate.stat().st_size > 0:
        return read_text(candidate)
    return DEFAULT_HEADER

def split_into_lines(words, total_duration):
    """
    On découpe en lignes lisibles avec durées régulières.
    Règle simple :
      - viser ~2.0 s par ligne (min 1.5 / max 3.5)
      - 1 à 8 mots par ligne
    """
    n = max(1, len(words))
    if total_duration <= 0:
        # fallback si on ne connaît pas la durée audio : 70 s par défaut
        total_duration = 70.0
    target = max(1.5, min(3.0, total_duration / max(1, math.ceil(n / 5))))
    lines = []
    buf = []
    acc = 0.0
    i = 0
    while i < n:
        buf.append(words[i])
        acc += target / max(1, 5)  # approx ~5 mots par ligne
        # on ferme la ligne si >1.5 s et fin de phrase ou on dépasse 3.5 s
        end_sentence = words[i].endswith(('.', '!', '?', '…'))
        if (acc >= 1.5 and end_sentence) or acc >= 3.5 or len(buf) >= 8:
            lines.append((" ".join(buf).strip(), acc))
            buf, acc = [], 0.0
        i += 1
    if buf:
        lines.append((" ".join(buf).strip(), max(1.5, min(3.5, acc or 2.0))))
    # renormalise pour coller exactement à total_duration
    total = sum(d for _, d in lines) or 1.0
    scale = total_duration / total
    lines = [(txt, d * scale) for (txt, d) in lines]
    return lines

def make_karaoke_line(text: str, start: float, dur: float):
    """
    Répartition équitable de \k par mot (centisecondes).
    """
    words = [w for w in text.split() if w.strip()]
    if not words:
        return start, start + dur, text
    per = int(round((dur * 100) / max(1, len(words))))  # cs par mot
    kara = "".join([f"{{\\k{per}}}{w} " for w in words]).rstrip()
    return start, start + dur, kara

def main():
    # arguments simples via variables d'env (évite argparse pour rester court)
    header_arg = os.environ.get("ASS_HEADER", "").strip()
    story_path = os.environ.get("STORY_PATH", "story/story.txt").strip()
    audio_path = os.environ.get("AUDIO_PATH", "audio/voice.wav").strip()
    out_path = os.environ.get("ASS_OUT", "subtitles/captions.ass").strip()

    header = load_header(Path(header_arg) if header_arg else None)

    story_file = (R / story_path).resolve()
    audio_file = (R / audio_path).resolve()
    out_file = (R / out_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if not story_file.is_file():
        print(f"[build_ass] story manquant: {story_file}", file=sys.stderr)
        sys.exit(1)

    text = read_text(story_file).strip()
    # enlève toute didascalie type "Intro:" "Scène:" etc.
    # (protection au cas où)
    lines_raw = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # supprime un éventuel label "Intro:" etc.
        ln = ln.split(":", 1)[-1].strip() if ":" in ln[:12] else ln
        lines_raw.append(ln)
    text = " ".join(lines_raw)
    words = text.split()

    dur = ffprobe_duration(audio_file)
    timed = split_into_lines(words, dur)

    # construit le document ASS
    events = []
    t = 0.0
    for txt, d in timed:
        s, e, kara = make_karaoke_line(txt, t, d)
        events.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},TikTok,,0,0,0,,{kara}")
        t = e

    out_file.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    print(f"[build_ass] écrit: {out_file} (durée audio détectée: {dur:.2f}s)")

if __name__ == "__main__":
    main()