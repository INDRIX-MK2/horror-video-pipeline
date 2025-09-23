#!/usr/bin/env python3
import argparse, pathlib, sys, random

ap = argparse.ArgumentParser()
ap.add_argument("--bank-root", default="BanqueVideo", help="BanqueVideo ou bank_video")
ap.add_argument("--theme", default="Horreur", help="Argent|Horreur|IA")
ap.add_argument("--out", default="selected_media/manifest.txt")
ap.add_argument("--shuffle", action="store_true")
args = ap.parse_args()

bank = pathlib.Path(args.bank_root)
if not bank.exists():
    bank = pathlib.Path("bank_video")

src = bank / args.theme
if not src.exists():
    print(f"Dossier introuvable: {src}", file=sys.stderr); sys.exit(1)

files = [p.resolve().as_posix() for p in sorted(src.glob("*.mp4"))]
if not files:
    print(f"Aucun .mp4 dans {src}", file=sys.stderr); sys.exit(1)

if args.shuffle:
    random.shuffle(files)

outf = pathlib.Path(args.out)
outf.parent.mkdir(parents=True, exist_ok=True)
outf.write_text("\n".join(files), encoding="utf-8")
print(f"Manifest écrit: {outf} ({len(files)} lignes)")