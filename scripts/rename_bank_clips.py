import os, re, sys
from pathlib import Path

# --- Répertoire local où se trouvent tes vidéos ---
BASE_DIR = r"C:\Users\ARMAND\Desktop\Bank Video"

# --- Préfixes pour chaque thème ---
THEMES = {
    "Horreur": "horreur",
    "IA": "ia",
    "Argent": "argent",
    # "Sport_Bien_etre": "sport"  # <-- tu pourras l'ajouter plus tard
}

# Extensions supportées
EXTS = {".mp4", ".mov", ".m4v"}

# Nombre de chiffres pour la numérotation
ZERO_PAD = 2  # => horreur_01.mp4, horreur_02.mp4

# Mode test (True = juste affichage, False = renomme réellement)
DRY_RUN = False

def nice_sort_key(p: Path):
    """Tri naturel des noms de fichiers pour éviter le désordre."""
    s = p.stem
    nums = re.findall(r"\d+", s)
    return (re.sub(r"\d+", "", s).lower(), int(nums[-1]) if nums else -1, s.lower())

def already_clean(name: str, prefix: str):
    """Vérifie si le nom est déjà correct (ex: horreur_01.mp4)."""
    return re.fullmatch(fr"{prefix}_\d{{{ZERO_PAD}}}\.[a-z0-9]{{3,4}}", name, re.IGNORECASE)

def main():
    base = Path(BASE_DIR)
    if not base.exists():
        print(f"Chemin introuvable : {BASE_DIR}")
        sys.exit(1)

    total_renamed = 0
    for folder, prefix in THEMES.items():
        d = base / folder
        if not d.exists():
            print(f"[!] Dossier manquant (ignoré) : {d}")
            continue

        files = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in EXTS]
        if not files:
            print(f"[-] Aucun clip trouvé dans : {d}")
            continue

        files.sort(key=nice_sort_key)

        counter = 1
        used_targets = set()
        for src in files:
            target_name = f"{prefix}_{counter:0{ZERO_PAD}d}{src.suffix.lower()}"

            # Si déjà propre et correct
            if already_clean(src.name, prefix):
                if src.name != target_name:
                    dst = src.with_name(target_name)
                else:
                    used_targets.add(src.name.lower())
                    counter += 1
                    continue
            else:
                dst = src.with_name(target_name)

            # Gestion des doublons éventuels
            k = 1
            base_target = dst.stem
            while dst.name.lower() in used_targets or dst.exists():
                dst = src.with_name(f"{base_target}_dup{k}{src.suffix.lower()}")
                k += 1

            # Dry-run ou renommage réel
            if DRY_RUN:
                print(f"[DRY] {src.name}  ->  {dst.name}")
            else:
                src.rename(dst)
                print(f"[OK ] {src.name}  ->  {dst.name}")
                total_renamed += 1
                used_targets.add(dst.name.lower())

            counter += 1

        print(f"[{folder}] {len(files)} fichiers traités.\n")

    print(f"Terminé. Fichiers renommés : {total_renamed}")

if __name__ == "__main__":
    main()
    