# Validation des médias (D9) et messages d'erreur (D8) — 18 octobre 2026

## D9 — Validation préliminaire à l'ouverture

`services/media/media_validation.py` (`validate_media_file`) est appelé par `VideoImportService`
avant tout enregistrement en base et avant tout changement d'état de l'interface :

1. le fichier existe, n'est pas un dossier, a l'extension `.mp4`/`.mkv`, n'est pas vide et se lit ;
2. ffprobe (build épinglé du projet) lit l'en-tête : le conteneur réel doit correspondre à
   l'extension, avec un flux vidéo utilisable (pas d'audio seul, pas d'image de pochette), un
   codec identifié, une taille d'image et une durée positives ;
3. décodage de la première image vidéo ;
4. lecture (sans décodage) des paquets vidéo des 1,5 dernières secondes : un fichier tronqué
   n'en a aucun, ou FFmpeg signale `partial file` / `File ended prematurely`.

Chaque appel ffprobe a un délai maximal (30 s pour l'en-tête, 60 s pour les contrôles de flux). Les
étapes 3 et 4 tournent en parallèle : le démarrage du ffprobe livré coûte environ 0,5 s sous Windows,
d'où environ 1,1 s pour contrôler une vidéo valide.

**Hors du fil de l'interface.** `AppController` confie le contrôle à `VideoLoadWorker`, dans un
`QThreadPool` dédié : le pool partagé, limité à 2 fils, peut être occupé par une analyse ou un export.
L'enregistrement en base et la mise à jour de l'état se font ensuite sur le fil de l'interface, et
seulement si la demande est toujours la plus récente. Une nouvelle sélection, `cancelVideoLoad`,
`clearVideo` ou `shutdown` (branché sur `aboutToQuit`) annule le contrôle en cours et termine son
ffprobe. Le résultat tardif d'une demande remplacée est ignoré, et une demande identique à celle en
cours n'en lance pas une seconde. La page affiche « Checking … » avec un bouton d'annulation.

**Limite.** C'est un contrôle préliminaire, pas une garantie que chaque image se décode : une
corruption au milieu d'un fichier complet n'est pas détectée et apparaîtra à l'analyse, à la lecture ou
à l'export (avec un message traduit, voir D8). Le listage d'un dossier reste fondé sur l'extension ; le
contrôle a lieu au chargement.

Un fichier refusé ne modifie rien d'autre que le statut et le bandeau `videoLoadError` de la page :
la vidéo déjà chargée le reste, aucune indexation n'est lancée, rien n'est ajouté aux fichiers récents.

## D8 — Messages d'erreur

`services/user_errors.py` (`describe_error`) donne une catégorie et un message pour l'interface ;
`technical_details` garde la commande FFmpeg, le code de retour, la fin de stderr et la chaîne des
causes pour le journal (`logs/video-cut.log`). Il est utilisé par l'ouverture, les workers d'export
(Fast, Smart, lossless, préparation), l'indexation des keyframes et le worker d'analyse.

| Catégorie | Origine |
|---|---|
| `cancelled` | `ExportCancelledError`, même enveloppée |
| `timeout` | `FFmpegTimeoutError` |
| `ffmpeg_unavailable` / `ffmpeg_incompatible` | `FFmpegNotFoundError` / option FFmpeg inconnue |
| `corrupted_media` | `moov atom not found`, `Invalid data…`, `partial file`, `File ended prematurely`… |
| `unsupported_media` | encodeur/décodeur absent, codec non accepté par le conteneur |
| `invalid_output_location` / `output_exists` | `FileExistsError` / `NotADirectoryError` |
| `missing_file`, `access_denied`, `disk_full` | `OSError` (errno / winerror) ou stderr FFmpeg |
| `invalid_request` | refus déjà rédigés pour l'utilisateur (validation, Fast/Smart Cutting) |
| `ffmpeg_failed` | autre échec FFmpeg : code de sortie + renvoi au journal |
| `unexpected` | message d'origine (première ligne, chemins réduits au nom) ; erreur de programmation : type + journal |

Un dossier de sortie qui est un fichier est refusé avant toute commande FFmpeg
(`OutputPreferences.resolve_output_dir`).

## Modes d'export

La fenêtre des réglages ne propose plus les modes clips, qui n'étaient pas branchés : voir
`docs/export_modes.md`.

## Enregistrement en base après validation

`VideoImportService.register_video_file` n'accepte qu'un fichier qui a réussi `validate_video_file`
et n'a pas changé depuis (même taille et même date de modification). Chaque validation n'autorise
qu'un enregistrement. Appeler cette méthode directement ne permet donc pas de sauter la validation D9,
ni d'enregistrer un fichier remplacé entre le contrôle et l'enregistrement.

**Réouverture d'une vidéo.** Avant la correction, chaque chargement réussi ajoutait une ligne `Video`.
Désormais `register_video_file` réutilise la plus ancienne ligne du même utilisateur pour le même
chemin (`repositories/video_repository.find_video_for_path`). La comparaison suit le système de
fichiers (`os.path.normcase` : insensible à la casse sous Windows). Le nom, le chemin, la taille et le
format sont mis à jour, et l'identifiant comme les lignes liées sont conservés.

- Un fichier déplacé reçoit une nouvelle ligne ; l'ancienne reste.
- Un fichier absent ou invalide est refusé avant tout accès à la base.
- Les doublons déjà présents ne sont ni supprimés ni fusionnés.
- Aucun résultat d'analyse, ni aucune tâche de découpe (`CutJob`, rattachée par chemin), n'est
  réécrit.

**Limite.** Il n'y a pas d'index unique, donc pas de migration nécessaire. La réutilisation est garantie
dans un même processus (verrou), mais deux instances de l'application important le même fichier au même
instant pourraient encore créer deux lignes. Une garantie atomique demanderait un index unique,
précédé d'une migration qui rattache les lignes liées des doublons à la ligne conservée.
