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

### Traduction des messages (19 octobre 2026)

Les messages affichés sont traduits à partir d'un **code stable**, jamais en comparant des textes.
`services/user_messages.py` associe chaque code (`media.damaged`, `fast.keyframes_remove`,
`export.output_not_a_folder`, `errors.disk_full`…) à son texte anglais, marqué `QT_TRANSLATE_NOOP`
dans le contexte Qt `UserMessages`. `pyside6-lupdate` l'extrait dans `resources/i18n/app_*.ts`, avec les
traductions de l'interface QML.

- Une erreur codée (`MediaValidationError`, refus Fast, dossier de sortie invalide) porte
  `message_code` et `message_params`. Son `str()` reste le texte anglais.
- `localized_text` / `describe_error` rendent le message dans la langue courante, celle du
  `QTranslator` installé par `TranslationService`. Un paramètre lui-même codé est traduit d'abord : par
  exemple, la liste des limites hors image clé d'un refus Fast.
- Le journal (`technical_details`, `logger`) reste en anglais.

Limites :
- Un message déjà affiché reste dans la langue du moment de l'erreur ; il n'est pas retraduit si
  la langue change ensuite.
- Les erreurs non codées (refus internes rares de Smart Cutting, messages de l'analyse IA) restent en
  anglais.
- En arabe, le texte est aligné et rendu de droite à gauche, mais la disposition de la fenêtre n'est
  pas inversée. Les libellés de section (par exemple « مجلد التصدير ») restent placés à gauche. Le QML
  positionne de nombreux éléments par coordonnées, notamment les barres de temps : une inversion globale
  (`LayoutMirroring`) n'est pas une modification sûre et limitée, et elle demanderait une revue de
  chaque composant.
- Les messages arabes commencent par un mot arabe (« الملف «x» … », « برنامج FFmpeg … ») : Qt déduit le sens
  du paragraphe de son premier caractère fort, et un nom de fichier latin en tête l'affichait de gauche à
  droite. `tests/test_localized_errors.py` le vérifie.
- Textes de l'interface encore non traduits au 19 octobre 2026 : 61 par langue, en FR comme en AR.
  - 44 dans le panneau AI Picks : états de l'installation et du téléchargement des modèles, états de
    l'analyse, libellés des suggestions, « Accept » et « Reject ».
  - 16 dans les réglages IA et mises à jour : « Analysis mode », « Balanced », « Check for updates »…
  - « Medium » dans `CompactAppHeader`.

  Le contenu technique des « Détails » d'un export (mode, durées, commande FFmpeg) reste en anglais.
  Les traductions arabes n'ont pas été relues par un locuteur natif.

### Problème connu (non reproduit) : MKV valide refusé comme incomplet sous forte charge disque

Le 19 octobre 2026, `test_valid_mp4_and_mkv_load_in_the_background` a échoué une fois. Il tournait pendant
un build PyInstaller, très chargé en disque. Le contrôle de fin a rejeté un MKV valide comme
« incomplete », avec le détail `tail packets=2 last_end=4.2 video_duration=6.0` : ffprobe n'avait lu que
deux paquets de la fin.

Le cas n'a pas été reproduit : le même fichier de test, relancé seul trois fois, et la suite complète (870
tests) passent. La logique du contrôle n'a pas changé. À surveiller : si un utilisateur signale un « fichier
incomplet » sur une vidéo qui se lit ailleurs, regarder ce détail dans le journal (`tail packets=…`).

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
