#!/usr/bin/env python3
import argparse, pathlib, sys, json, subprocess, shlex

def load_timeline(p: pathlib.Path):
    if p and p.exists() and p.stat().st_size:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def main():
    ap = argparse.ArgumentParser(description="Render final video with title first + CTA at end")
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--subs", required=True)             # .ass
    ap.add_argument("--output", required=True)
    ap.add_argument("--title-file", required=True)       # story/title.txt
    ap.add_argument("--cta-file", required=True)         # story/cta.txt
    ap.add_argument("--timeline", default="audio/timeline.json")
    args = ap.parse_args()

    v = pathlib.Path(args.video)
    a = pathlib.Path(args.audio)
    s = pathlib.Path(args.subs)
    out = pathlib.Path(args.output)
    tfile = pathlib.Path(args.title_file)
    cfile = pathlib.Path(args.cta_file)
    tline = pathlib.Path(args.timeline)

    for p in [v,a,s,tfile,cfile]:
        if not p.exists() or not p.stat().st_size:
            print(f"[render_final] ERREUR: manquant => {p}", file=sys.stderr)
            sys.exit(1)
    out.parent.mkdir(parents=True, exist_ok=True)

    tl = load_timeline(tline)
    title_d = float(tl.get("title", 0.0))
    gap_d   = float(tl.get("gap", 0.0))
    cta_d   = float(tl.get("cta", 4.0))
    total_d = float(tl.get("total", 0.0))

    # Si pas de timeline, on met des valeurs par défaut safe
    if total_d <= 0:
        # Probe durée audio => pour CTA approx = 4s fin
        try:
            outd = subprocess.check_output([
                "ffprobe","-v","error","-show_entries","format=duration",
                "-of","default=nk=1:nw=1", str(a)
            ]).decode().strip()
            total_d = float(outd)
        except Exception:
            total_d = 60.0
    if cta_d <= 0: cta_d = 4.0
    cta_start = max(0.0, total_d - cta_d)

    # Font DejaVu dispo sur ubuntu-latest
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    # Filters:
    # - v0: préparation vidéo (format, léger mouvement, etc.)
    # - v1: sous-titres .ass
    # - v2: titre en haut-centre pendant [0, title_d]
    # - v3: CTA en bas-centre pendant [cta_start, total]
    base = (
        "setpts=PTS-STARTPTS,"
        "scale=1200:2133:force_original_aspect_ratio=increase,"
        "rotate=0.005*sin(2*PI*t):fillcolor=black,"
        "crop=1080:1920,"
        "unsharp=5:5:0.5:5:5:0.0,"
        "eq=contrast=1.05:brightness=0.02,"
        "fps=30"
    )

    title_enable = f"between(t,0,{title_d:.3f})" if title_d > 0 else "lt(t,0)"
    cta_enable   = f"gte(t,{cta_start:.3f})"

    sub_filter = f"subtitles={shlex.quote(str(s))}"
    draw_title = (
        f"drawtext=fontfile={shlex.quote(font)}:"
        f"textfile={shlex.quote(str(tfile))}:"
        f"enable='{title_enable}':"
        "x=(w-text_w)/2:y=h*0.18:fontsize=72:"
        "fontcolor=white:borderw=6:bordercolor=black@0.7"
    )
    draw_cta = (
        f"drawtext=fontfile={shlex.quote(font)}:"
        f"textfile={shlex.quote(str(cfile))}:"
        f"enable='{cta_enable}':"
        "x=(w-text_w)/2:y=h*0.83:fontsize=56:"
        "fontcolor=white:borderw=6:bordercolor=black@0.7"
    )

    fcomplex = (
        f"[0:v]{base}[v0];"
        f"[v0]{sub_filter}[v1];"
        f"[v1]{draw_title}[v2];"
        f"[v2]{draw_cta}[v]"
    )

    cmd = [
        "ffmpeg","-nostdin","-y",
        "-i", str(v),
        "-i", str(a),
        "-filter_complex", fcomplex,
        "-map","[v]","-map","1:a:0",
        "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k",
        "-movflags","+faststart",
        "-shortest",
        str(out)
    ]

    print("[render_final] Exécution FFmpeg…")
    print(" ".join(shlex.quote(c) for c in cmd))
    subprocess.run(cmd, check=True)
    print(f"[render_final] OK -> {out}")

if __name__ == "__main__":
    main()