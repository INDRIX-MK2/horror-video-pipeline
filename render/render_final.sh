#!/usr/bin/env bash
set -euo pipefail

OUT_NAME="${OUT_NAME:-final_horror.mp4}"

voice="audio/voice.mp3"
subs="subtitles/captions.ass"
merged="selected_media/merged.mp4"
final_dir="final_video"
mkdir -p "$final_dir"

if [ ! -s "$voice" ] || [ ! -s "$subs" ] || [ ! -s "$merged" ]; then
  echo "Entrées manquantes (voice/subs/merged)"; exit 1
fi

# Durées
Vdur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$voice")
Mdur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$merged")

# Si merged < voix, on boucle la vidéo le temps nécessaire
# (boucle approximative sans transition pour rester robuste)
need_loop=0
awk "BEGIN{print ($Mdur < $Vdur) ? 0 : 1}" >/dev/null 2>&1 || true
# shellcheck disable=SC2003
if [ "$(awk "BEGIN{print ($Mdur < $Vdur)?1:0}")" = "1" ]; then
  need_loop=1
fi

src="$merged"
if [ "$need_loop" = "1" ]; then
  # Nombre de boucles approximatif pour couvrir Vdur
  # shellcheck disable=SC2003
  loops=$(awk "BEGIN{print int(($Vdur/$Mdur)+1)}")
  # on veille à ne pas dépasser 30 boucles
  [ "$loops" -gt 30 ] && loops=30
  ffmpeg -nostdin -y -stream_loop "$loops" -i "$merged" -t "$Vdur" -r 30 -c:v libx264 -crf 18 -pix_fmt yuv420p -an "selected_media/looped.mp4"
  src="selected_media/looped.mp4"
fi

# Rendu final aligné à la durée voix
ffmpeg -nostdin -y \
  -i "$src" -i "$voice" \
  -vf "subtitles=${subs}" \
  -map 0:v:0 -map 1:a:0 \
  -t "$Vdur" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -shortest \
  "${final_dir}/${OUT_NAME}"

echo "OK: ${final_dir}/${OUT_NAME}"