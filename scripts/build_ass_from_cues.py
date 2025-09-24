#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Construit un fichier ASS (sous-titres) à partir de audio/dialogue_cues.json
Les styles V1 et V2 sont colorés différemment.

Entrées:
  --cues  audio/dialogue_cues.json
  --out   subs/captions.ass

Options style (facultatif):
  --playresx 1080 --playresy 1920
  --font "Montserrat" --fontsize 22
  --margin_v 160
"""

import argparse
import json
from pathlib import Path
import math
import textwrap


def ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def fmt_time(t: float) -> str:
    # ASS: h:mm:ss.cs (centisecondes)
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - math.floor(t)) * 100))
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def ass_escape(s: str) -> str:
    # protéger { } \ et normaliser les retours
    s = s.replace("\\", "\\\\")
    s = s.replace("{", "(").replace("}", ")")
    s = s.replace("\r", "").replace("\n", r"\N")
    return s


def wrap_text(text: str, width: int = 42) -> str:
    # retour à la ligne doux (2 lignes max)
    lines = textwrap.wrap(text, width=width)
    if len(lines) <= 2:
        return r"\N".join(lines)
    return r"\N".join(lines[:2]) + r"\N" + r"\h".join(lines[2:])


def build_ass(cues_path: Path, out_path: Path,
              playresx=1080, playresy=1920,
              font="Montserrat", fontsize=22, margin_v=160) -> None:
    data = json.loads(cues_path.read_text(encoding="utf-8"))
    ensure_dir(out_path)

    # Styles: V1 blanc, V2 légèrement bleuté — à ajuster selon goûts
    header = f"""[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: {playresx}
PlayResY: {playresy}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTokV1,{font},{fontsize},&H00FFFFFF,&H00FFFFFF,&H32000000,&H96000000,0,0,0,0,100,100,0,0,1,3,0,2,60,60,{margin_v},1
Style: TikTokV2,{font},{fontsize},&H00FFD7B5,&H00FFD7B5,&H32000000,&H96000000,0,0,0,0,100,100,0,0,1,3,0,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".rstrip("\n")

    lines = [header]

    for cue in data:
        speaker = str(cue.get("speaker", "V1")).upper()
        text = str(cue.get("text", "")).strip()
        start = float(cue.get("start", 0.0))
        end = float(cue.get("end", 0.0))
        if not text or end <= start:
            continue

        style = "TikTokV1" if speaker == "V1" else "TikTokV2"
        safe = ass_escape(text)
        wrapped = wrap_text(safe, width=42)
        s_ts = fmt_time(start)
        e_ts = fmt_time(end)

        line = f"Dialogue: 0,{s_ts},{e_ts},{style},,0,0,{margin_v},,{{\\fad(100,100)}}{wrapped}"
        lines.append(line)

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cues", default="audio/dialogue_cues.json")
    ap.add_argument("--out", default="subs/captions.ass")
    ap.add_argument("--playresx", type=int, default=1080)
    ap.add_argument("--playresy", type=int, default=1920)
    ap.add_argument("--font", default="Montserrat")
    ap.add_argument("--fontsize", type=int, default=22)
    ap.add_argument("--margin_v", type=int, default=160)
    args = ap.parse_args()

    cues = Path(args.cues)
    outp = Path(args.out)

    if not cues.exists():
        print(f"Cues introuvable: {cues}")
        raise SystemExit(1)

    build_ass(
        cues_path=cues,
        out_path=outp,
        playresx=args.playresx,
        playresy=args.playresy,
        font=args.font,
        fontsize=args.fontsize,
        margin_v=args.margin_v,
    )
    print(f"[build_ass] écrit: {outp}")


if __name__ == "__main__":
    main()