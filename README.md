# Horror TikTok Builder (no-heredoc, voice-length-cut)

Pipeline GitHub Actions qui génère un script d'horreur (OpenAI), synthétise la voix (ElevenLabs), construit un fond vidéo vertical 1080x1920 pile à la durée de la voix, crée des sous-titres ASS (karaoké) et rend la vidéo finale. En option, upload Dropbox.

## Secrets requis

- `OPENAI_API_KEY`
- `ELEVENLABS_API_KEY`
- `ELEVENLABS_VOICE_ID`

**Dropbox (au choix)**
- Simple: `DROPBOX_ACCESS_TOKEN`
- Recommandé (stabilité): `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`

## Entrées
- `manifests/horreur.txt` (facultatif) : URLs ou chemins .mp4 (une par ligne)
- `bank_video/Horreur/` (facultatif) : clips .mp4 locaux

## Sorties
- `final_video/final_horror.mp4`
- `subtitles/captions.ass`
- `final_video/dropbox_link.txt` (si upload Dropbox)

## Zéro heredoc
Aucun heredoc dans le workflow ni les scripts. Les commandes ffmpeg sont déclenchées depuis Python.