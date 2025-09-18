# horror-video-pipeline

- Workflow manuel: **Actions > Run workflow > horror_build**
- Secrets requis (Settings > Secrets and variables > Actions):
  - `OPENAI_API_KEY`
  - `ELEVENLABS_API_KEY`
  - `ELEVENLABS_VOICE_ID`

> ⚠️ Les clips 5s ne sont **pas** dans le repo (trop lourds).  
> Par défaut, le job attend `bank_video/Horreur/*.mp4`.  
> Si vous n’avez pas de clips dans le repo, remplacez l’étape “Select clips and merge” par un téléchargement (Drive/S3) ou ajoutez des *proxies* légers.
