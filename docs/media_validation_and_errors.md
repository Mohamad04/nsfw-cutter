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
d'où environ 1,5 s pour ouvrir une vidéo valide.

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

## Option « Export clips separately » (non modifiée)

- `SettingsDialog.qml` écrit `last_export_mode` via `settingsController.setLastExportMode`.
- Rien ne relit ce réglage : `CleanShellPage.exportCleanVideo` envoie toujours `"remove_intervals"`.
- Chaque export appelle `OutputPreferences.remember(..., export_mode)`, qui réécrit
  `last_export_mode` avec le mode utilisé : le choix fait dans les réglages est écrasé au premier export.
- Pour le brancher : lire `settingsController.getLastExportMode()` dans `exportCleanVideo`. Il faut
  aussi présenter les coupes comme des plages **à garder** dans les modes clips (elles sont des plages
  **à supprimer** dans l'interface actuelle). Enfin, Smart Cutting n'accepte que `remove_intervals` :
  les modes clips n'existent qu'en Fast Cutting, sans audio et avec des bornes sur des keyframes.
