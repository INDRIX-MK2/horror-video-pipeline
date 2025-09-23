#!/usr/bin/env python3
import pathlib, re

root = pathlib.Path("bank_video/Horreur")
root.mkdir(parents=True, exist_ok=True)
files = sorted(root.glob("*.mp4"))
for i,p in enumerate(files,1):
    new = root / f"clip_{i:03d}.mp4"
    if new != p:
        try:
            p.rename(new)
            print(f"{p.name} -> {new.name}")
        except Exception as e:
            print(f"Skip {p}: {e}")