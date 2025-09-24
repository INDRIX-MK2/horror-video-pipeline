#!/usr/bin/env python3
import os, json, pathlib, re, sys, time
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
STORY_DIR = ROOT / "story"
STORY_DIR.mkdir(parents=True, exist_ok=True)
OUT = STORY_DIR / "story.txt"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "").strip()
USER_PROMPT = os.environ.get("USER_PROMPT", "").strip()

if not OPENAI_API_KEY:
    print("OPENAI_API_KEY manquant", file=sys.stderr)
    sys.exit(1)

if not SYSTEM_PROMPT or not USER_PROMPT:
    print("Prompts manquants (SYSTEM_PROMPT/USER_PROMPT)", file=sys.stderr)
    sys.exit(1)

def remove_stage_directions(text: str) -> str:
    t = text
    # Supprimer lignes avec didascalies typiques
    patterns = [
        r'^\s*(intro|hook|scène|scene|narrateur|développement|conclusion|cta)\s*[:\-–].*$',
        r'^\s*\(.*?\)\s*$',
        r'^\s*\[.*?\]\s*$',
    ]
    for pat in patterns:
        t = re.sub(pat, "", t, flags=re.IGNORECASE | re.MULTILINE)

    # Enlever mentions inline type "Narrateur:" au début de phrases
    t = re.sub(r'(?im)^(?:narrateur|voix off|locuteur)\s*:\s*', '', t)

    # Nettoyages divers
    t = t.replace('“', '"').replace('”', '"')
    t = t.replace('«', '').replace('»', '')
    t = re.sub(r'^\s*["\']\s*', '', t)
    t = re.sub(r'\s*["\']\s*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def ask_openai(system_msg: str, user_msg: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o",
        "temperature": 1.0,
        "messages": [
            {"role":"system","content":system_msg},
            {"role":"user","content":user_msg}
        ]
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    if r.status_code != 200:
        print(f"OpenAI HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)
        sys.exit(1)
    data = r.json()
    txt = data["choices"][0]["message"]["content"]
    return txt

raw = ask_openai(SYSTEM_PROMPT, USER_PROMPT)
clean = remove_stage_directions(raw)

# garde bornes ~180-200 mots (on n’échoue pas si >, on normalise un peu)
words = clean.split()
if len(words) > 230:
    clean = " ".join(words[:230]).rstrip(" ,;:-") + "."

OUT.write_text(clean, encoding="utf-8")
print(f"Story saved to {OUT} ({len(clean.split())} mots)")