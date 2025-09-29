#!/usr/bin/env python3
import argparse, subprocess, pathlib, sys, shlex, re

FONTFILE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"  # dispo sur ubuntu-latest

def ffprobe_duration(path: pathlib.Path) -> float:
    try:
        out = subprocess.check_output([
            "ffprobe","-v","error",
            "-show_entries","format=duration",
            "-of","default=nk=1:nw=1",
            str(path)
        ]).decode("utf-8","ignore").strip()
        return float(out)
    except Exception:
        return 0.0

def read_title(story_path: pathlib.Path, title_path: pathlib.Path) -> str:
    if title_path.exists() and title_path.stat().st_size:
        return title_path.read_text(encoding="utf-8").strip()
    # fallback: fabriquer un titre court depuis la 1ère phrase du script
    if story_path.exists() and story_path.stat().st_size:
        txt = story_path.read_text(encoding="utf-8", errors="ignore").strip()
        # prendre la 1re phrase
        m = re.split(r"[.!?]\s+", txt)
        head = (m[0] if m else txt).strip()
        # 6–10 mots max
        words = head.split()
        short = " ".join(words[:10])
        return short if short else "Histoire d'horreur"
    return "Histoire d'horreur"

def esc_drawtext_text(s: str) -> str:
    # Échappements sûrs pour drawtext
    s = s.replace("\\", "\\\\")
    s = s.replace(":", r"\:")
    s = s.replace("'", r"\'")
    return s

def esc_filter_arg_path(p: str) -> str:
    # Pour subtitles=filename=... dans le filtergraph
    # (éviter espaces/comma/colon)
    s = p.replace("\\", "\\\\")
    s = s.replace(":", r"\:")
    s = s.replace(",", r"\,")
    return s

def main():
    ap = argparse.ArgumentParser(description="Assemble final TikTok horror video with intro/outro and ASS subtitles")
    ap.add_argument("--video", required=True, help="Chemin de la vidéo fusionnée (merged.mp4)")
    ap.add_argument("--audio", required=True, help="Chemin de l'audio narratif (voice.wav)")
    ap.add_argument("--subs",  required=True, help="Chemin des sous-titres .ass")
    ap.add_argument("--output", required=True, help="Fichier de sortie final")
    # facultatif: story/title pour l’intro
    ap.add_argument("--story", default="story/story.txt")
    ap.add_argument("--title", default="story/title.txt")
    # timings overlays
    ap.add_argument("--intro_dur", type=float, default=1.8)
    ap.add_argument("--outro_dur", type=float, default=2.2)
    # CTA texte (modif facile si besoin)
    ap.add_argument("--cta_text", default="Tu as aimé ? Abonne-toi et partage !")
    args = ap.parse_args()

    video = pathlib.Path(args.video)
    audio = pathlib.Path(args.audio)
    subs  = pathlib.Path(args.subs)
    output = pathlib.Path(args.output)
    story = pathlib.Path(args.story)
    title_file = pathlib.Path(args.title)

    if not video.exists():
        print(f"[render_final] ERREUR: vidéo manquante -> {video}", file=sys.stderr); sys.exit(1)
    if not audio.exists():
        print(f"[render_final] ERREUR: audio manquant -> {audio}", file=sys.stderr); sys.exit(1)
    if not subs.exists():
        print(f"[render_final] ERREUR: sous-titres manquants -> {subs}", file=sys.stderr); sys.exit(1)
    output.parent.mkdir(parents=True, exist_ok=True)

    vdur = ffprobe_duration(video)
    if vdur <= 0:
        print("[render_final] ERREUR: durée vidéo inconnue", file=sys.stderr); sys.exit(1)

    # Lire le titre (depuis title.txt ou fallback)
    title_txt = read_title(story, title_file)
    cta_txt = args.cta_text

    # Échapper pour drawtext
    title_txt_esc = esc_drawtext_text(title_txt)
    cta_txt_esc   = esc_drawtext_text(cta_txt)

    # Timings intro/outro (pas de padding noir — overlays par-dessus la vidéo existante)
    intro_d = max(0.0, min(args.intro_dur, max(0.0, vdur - 0.1)))  # pas dépasser vdur
    outro_d = max(0.0, min(args.outro_dur, max(0.0, vdur - 0.1)))
    outro_st = max(0.0, vdur - outro_d)

    # Fades globaux déjà chiffrés (pas d'expressions 'duration-...')
    fade_in_d  = 0.6
    fade_out_d = 0.6
    fade_out_st = max(0.0, vdur - fade_out_d)

    # Préprocess + léger "shake" via rotate sinus
    base = (
        f"[0:v]setpts=PTS-STARTPTS,"
        f"scale=1200:2133:force_original_aspect_ratio=increase,"
        f"rotate=0.005*sin(2*PI*t):fillcolor=black,"
        f"crop=1080:1920,"
        f"unsharp=5:5:0.5:5:5:0.0,"
        f"eq=contrast=1.05:brightness=0.02,"
        f"fps=30,"
        f"fade=t=in:st=0:d={fade_in_d},"
        f"fade=t=out:st={fade_out_st:.3f}:d={fade_out_d}[base];"
    )

    # Intro title en haut (éviter le centre où tu places tes sous-titres)
    intro = (
        f"[base]drawtext=fontfile={FONTFILE}:"
        f"text='{title_txt_esc}':"
        f"x=(w-text_w)/2:y=120:"
        f"fontsize=72:fontcolor=white:"
        f"box=1:boxcolor=black@0.55:boxborderw=24:"
        f"enable='between(t,0,{intro_d:.2f})'[t1];"
    )

    # Outro CTA proche du haut aussi (pour éviter collision avec subs centrés)
    outro = (
        f"[t1]drawtext=fontfile={FONTFILE}:"
        f"text='{cta_txt_esc}':"
        f"x=(w-text_w)/2:y=220:"
        f"fontsize=64:fontcolor=white:"
        f"box=1:boxcolor=black@0.55:boxborderw=22:"
        f"enable='between(t,{outro_st:.2f},{vdur:.2f})'[v0];"
    )

    # Audio passthrough (juste alignement PTS)
    audiof = "[1:a]asetpts=PTS-STARTPTS[a0];"

    # Sous-titres (chemin absolu + échappement filtre)
    subs_abs = esc_filter_arg_path(str(subs.resolve()))
    subsf = f"[v0]subtitles=filename={subs_abs}[v]"

    filter_complex = base + intro + outro + audiof + subsf

    cmd = [
        "ffmpeg","-nostdin","-y",
        "-i", str(video),
        "-i", str(audio),
        "-filter_complex", filter_complex,
        "-map","[v]","-map","[a0]",
        "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
        "-c:a","aac","-b:a","192k",
        "-movflags","+faststart",
        "-shortest",
        str(output)
    ]

    print("[render_final] Exécution FFmpeg…")
    print(" ".join(shlex.quote(c) for c in cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[render_final] ERREUR FFmpeg: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[render_final] Vidéo finale générée -> {output}")

if __name__ == "__main__":
    main()