#!/usr/bin/env python3
import argparse, pathlib, sys, urllib.request, urllib.parse, os, re

def normalize_dropbox(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
        if "dropbox.com" in p.netloc:
            q = dict(urllib.parse.parse_qsl(p.query))
            q["dl"] = "1"
            url = urllib.parse.urlunparse((
                p.scheme, p.netloc, p.path, p.params,
                urllib.parse.urlencode(q), p.fragment
            ))
    except Exception:
        pass
    return url

def safe_name(url: str) -> str:
    p = urllib.parse.urlparse(url)
    name = pathlib.Path(p.path).name or "file"
    root, ext = os.path.splitext(name)
    if not ext:
        ext = ".mp4"
    name = re.sub(r'[^A-Za-z0-9._-]+', '_', root) + ext
    return name

def download(url: str, dest: pathlib.Path):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1024 * 64)
            if not chunk:
                break
            f.write(chunk)

def collect_url_files(args) -> list[pathlib.Path]:
    url_files: list[pathlib.Path] = []
    if args.manifest_file:
        p = pathlib.Path(args.manifest_file)
        if not p.is_file():
            print(f"Manifest file introuvable: {p}", file=sys.stderr)
            sys.exit(1)
        url_files = [p]
    elif args.manifest_dir:
        d = pathlib.Path(args.manifest_dir)
        if not d.exists() or not d.is_dir():
            print(f"Manifest dir introuvable ou non dossier: {d}", file=sys.stderr)
            sys.exit(1)
        url_files = [p for p in sorted(d.iterdir()) if p.is_file()]
        if not url_files:
            print(f"Aucun fichier d’URL trouvé dans {d}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Fournir --manifest-file ou --manifest-dir", file=sys.stderr)
        sys.exit(1)
    return url_files

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest-file", help="Fichier unique contenant des URLs (une par ligne)")
    ap.add_argument("--manifest-dir", help="Dossier contenant un ou plusieurs fichiers d’URLs")
    ap.add_argument("--bank-root", required=True, help="Racine de ta banque (ex: 'Bank Vidéo')")
    ap.add_argument("--theme", default="Horreur", help="Sous-dossier de la banque (ex: Horreur)")
    args = ap.parse_args()

    url_files = collect_url_files(args)

    bank = pathlib.Path(args.bank_root)
    dest_dir = bank / args.theme
    dest_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for fpath in url_files:
        for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
            url = line.strip()
            if not url or url.startswith("#"):
                continue
            url = normalize_dropbox(url)
            name = safe_name(url)
            dest = dest_dir / name
            try:
                print(f"Téléchargement -> {dest}")
                download(url, dest)
                count += 1
            except Exception as e:
                print(f"Échec: {url} -> {e}", file=sys.stderr)

    print(f"OK: {count} fichiers téléchargés dans {dest_dir}")

if __name__ == "__main__":
    main()