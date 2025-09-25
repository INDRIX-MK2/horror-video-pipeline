#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Génère un script d'horreur FR pour TikTok, sans didascalies ni mentions
(type "Scène:", "Voix:", "Narrateur:", "Hook:", "CTA:", etc.).
Le script applique des garde-fous, valide la sortie et regénère si besoin.

Entrées (env) :
  OPENAI_API_KEY   : clé API OpenAI (obligatoire)

Sorties :
  story/story.txt  : texte final validé

Contrainte structure : ne modifie PAS l’arborescence de ton repo.
"""

import os, sys, json, pathlib, re, time
import urllib.request

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
OUT_DIR = pathlib.Path("story")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_FILE = OUT_DIR / "story.txt"

API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
if not API_KEY:
    print("OPENAI_API_KEY manquant", file=sys.stderr)
    sys.exit(1)

# ---------- Paramètres éditables (gardes & style) ----------
TARGET_MIN = 170     # borne basse cible (mots)
TARGET_MAX = 210     # borne haute cible (mots)
MAX_ATTEMPTS = 3     # nb de tentatives de génération
TEMPERATURE  = float(os.environ.get("STORY_TEMPERATURE", "1"))
TOP_P        = float(os.environ.get("STORY_TOP_P", "0.95"))

# Liste des marqueurs/didascalies à bannir explicitement
DISALLOWED_TOKENS = [
    r"\bsc[ée]ne\b",
    r"\bnarrateur\b",
    r"\bvoix\b",
    r"\bhook\b",
    r"\bcta\b",
    r"\bintro\b",
    r"\bd[ée]veloppement\b",
    r"\bconclusion\b",
    r"\bgros plan\b",
    r"\bcadre\b",
    r"\bplan\b",
    r"\bcut\b",
]

DISALLOWED_RE = re.compile("(" + "|".join(DISALLOWED_TOKENS) + ")", re.IGNORECASE)

# Nettoyage léger de toute parenthèse/crochet (didascalies)
PARENS_RE = re.compile(r"[\(\[].*?[\)\]]", re.DOTALL)

def count_words(txt: str) -> int:
    return len(re.findall(r"\b\w+\b", txt, flags=re.UNICODE))

def looks_clean(txt: str) -> bool:
    if DISALLOWED_RE.search(txt):
        return False
    return True

def soft_clean(txt: str) -> str:
    # Supprime entre crochets/parenthèses et éventuels labels en début de ligne
    t = PARENS_RE.sub("", txt)
    t = re.sub(r"^\s*(?:Scène|Voix|Narrateur|Hook|CTA)\s*:\s*", "", t, flags=re.IGNORECASE|re.MULTILINE)
    # Compacte les espaces
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s*\n\s*\n\s*", "\n\n", t).strip()
    return t

def within_target_range(n: int) -> bool:
    return TARGET_MIN <= n <= TARGET_MAX

def build_messages() -> list:
    system_prompt = (
        "Tu es un auteur pro de récits d'horreur courts en FR pour TikTok. "
        "Règles STRICTES :\n"
        "- Ne mets AUCUNE didascalie ni label (pas de 'Scène:', 'Voix:', 'Narrateur:', 'Hook:', 'CTA:').\n"
        "- Raconte UNIQUEMENT l'histoire, en 'je', phrases courtes, immersives, sans vulgarité.\n"
        "- Atmosphère : manoir ancien, pluie, échos métalliques, tension progressive.\n"
        "- Pas de mentions de caméra, plan, cadrage, ni directions scéniques.\n"
        "- Vise ~180–200 mots. Si tu dépasses légèrement, garde la cohérence.\n"
        "- Finir par une phrase qui donne un frisson, pas un appel à s’abonner.\n"
    )
    user_prompt = (
        "Écris une histoire d'horreur immersive (FR), 180–200 mots environ. "
        "Thème : manoir sous la pluie, bruits métalliques, solitude, souffle court. "
        "Style : phrases brèves, vocabulaire concret, sensoriel, sans gore explicite. "
        "Interdits : tout label didascalie (Scène, Voix, Narrateur, Hook, CTA), "
        "tout méta-texte (gros plan, plan, cut), tout appel à l’action. "
        "Sortie : texte brut uniquement."
    )
    return [
        {"role":"system","content": system_prompt},
        {"role":"user","content": user_prompt},
    ]

def openai_chat(messages: list) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": MODEL,
        "temperature": TEMPERATURE,
        "top_p": TOP_P,
        "max_tokens": 800,
        "messages": messages,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {API_KEY}")
    with urllib.request.urlopen(req, timeout=90) as resp:
        obj = json.loads(resp.read().decode("utf-8", "ignore"))
    return obj["choices"][0]["message"]["content"].strip()

def main():
    messages = build_messages()
    final_text = ""
    for attempt in range(1, MAX_ATTEMPTS+1):
        try:
            raw = openai_chat(messages)
        except Exception as e:
            if attempt == MAX_ATTEMPTS:
                print(f"[generate_story] Erreur API: {e}", file=sys.stderr)
                sys.exit(1)
            time.sleep(1.2)
            continue

        txt = soft_clean(raw)
        w = count_words(txt)

        # Validation stricte
        ok = looks_clean(txt) and w >= 120  # on exige un minimum raisonnable
        # Si longueur hors plage, on laisse une chance au post-traitement ; sinon on regénère
        if not ok or not within_target_range(w):
            # Prévention : si présence de didascalies, on renforce l’instruction et on regénère
            if not looks_clean(txt):
                messages.append({
                    "role":"system",
                    "content":"RAPPEL STRICT : aucun label/didascalie (Scène, Voix, Narrateur, Hook, CTA). Recommence en respectant exactement les règles."
                })
                continue
            # Si juste trop court/long, on demande une variation de longueur
            if w < TARGET_MIN:
                messages.append({"role":"user","content":"Refais une version un peu plus longue (~190 mots), mêmes règles strictes."})
                continue
            if w > TARGET_MAX:
                # On essaye d’abréger en conservant la cohérence
                messages.append({"role":"user","content":"Fais une version légèrement plus concise (~190 mots), mêmes règles strictes."})
                continue

        final_text = txt
        break

    if not final_text:
        # filet de sécurité : on prend la dernière version nettoyée
        final_text = soft_clean(raw)

    OUT_FILE.write_text(final_text, encoding="utf-8")
    print(f"[generate_story] OK -> {OUT_FILE} ({count_words(final_text)} mots)")

if __name__ == "__main__":
    main()