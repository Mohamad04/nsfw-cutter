# Smart Cutting MKV H.264 (D2) — 18 octobre 2026

Base Git : `278c2858044e3fe93bbd3793466ecad54bf984d9`. FFmpeg 8.1.1 épinglé. Aucune
inférence IA.

## Cause

FFmpeg recule la cible d'une recherche en entrée (`-ss` avant `-i`) d'environ 0,13 s
(3/23 s). Il le fait pour les démultiplexeurs qui ne savent pas rechercher par PTS,
comme Matroska, lorsqu'un flux comporte des B-frames.

Mesure avec 8.1.1 : `-ss 14` et `-ss 14.1` démarrent la copie au keyframe 12 ;
`-ss 14.13` démarre au keyframe 14. Les morceaux copiés commençaient donc au keyframe
précédent. La vérification par hash les refusait, si bien que tout export MKV était
refusé. En MP4, la recherche se fait par PTS et tombe juste.

## Solution : normalisation sans perte, vérifiée

`services/export/source_normalization_service.py` remuxe le premier flux vidéo et le
premier flux audio du MKV en MP4 (`-c copy`, sans ré-encodage), dans le dossier
temporaire de l'export. Le fichier obtenu n'est utilisé que si :

- chaque paquet vidéo et chaque paquet audio a les mêmes données, dans le même ordre ;
- chaque paquet garde la même position sur la chronologie de la source (PTS relatif au
  début du conteneur), à 0,5 ms près pour la vidéo et à 1,1 ms près pour l'audio. MP4
  recalcule en effet les PTS audio d'après le nombre d'échantillons, alors que Matroska
  les arrondit à la milliseconde.

La correspondance entre le temps d'origine et le temps normalisé est donc l'identité,
et elle est vérifiée. Le reste du traitement (planification, copie au nombre exact
d'images, vérification par hash, ré-encodage des bords, audio aligné sur les images)
s'applique au fichier normalisé. Les sous-titres sont reconstruits depuis le MKV
d'origine. La sortie est un `.mkv`. Le fichier normalisé est supprimé avec le dossier
temporaire, que l'export réussisse, échoue, soit annulé ou dépasse son délai.

Le résultat expose `source_normalization`.

## Deux défauts latents corrigés au passage (visibles avec les MKV, mais aussi possibles en MP4)

1. **Base de temps.** Le démultiplexeur concat ne convertit pas les horodatages entre
   fichiers dont la base de temps diffère. Les morceaux copiés gardent la base de la
   source (1/16000 après normalisation, 1/90000 pour beaucoup de MP4), alors que libx264
   écrivait en 1/12800. Les morceaux ré-encodés étaient donc décalés d'un facteur 0,8.
   Les morceaux reçoivent désormais `-video_track_timescale` de la source.
2. **Délai de réordonnancement.** Pour une source sans B-frames, les morceaux ré-encodés
   (avec B-frames) faisaient reculer le DTS à la jonction, ce qui figeait une image
   pendant 80 ms. Les morceaux ré-encodés reproduisent désormais le délai de la source
   (`has_b_frames` 0 → `-bf 0`, 1 → `-bf 1`).

Une nouvelle vérification de la chronologie compare l'espacement des images de la vidéo
concaténée et du fichier final à la durée d'affichage des images source conservées. Elle
arrête l'export en cas d'écart : c'est elle qui a révélé ces deux défauts.

## Cas refusés explicitement

- MKV à fréquence d'image variable (espacement des images variant de plus de 2,1 ms).
- MKV avec plusieurs pistes audio.
- MKV tronqué ou endommagé (durée déclarée supérieure de plus de 1 s à la dernière image).
- Codecs autres que H.264, ou format de pixels autre que yuv420p (validation inchangée).

Fast Cutting reste refusé sur les MKV.
