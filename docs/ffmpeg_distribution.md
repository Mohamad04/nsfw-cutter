# FFmpeg embarqué : provenance, vérification et licence

## Build retenu

La seule source de vérité est `scripts/ffmpeg-pin.json`.

| Élément | Valeur |
|---|---|
| Version | `8.1.1-full_build-www.gyan.dev`, build statique win64 de https://www.gyan.dev/ffmpeg/builds/ |
| Code source FFmpeg | commit `239f2c733d` (https://github.com/FFmpeg/FFmpeg/commit/239f2c733d) |
| `ffmpeg.exe` | SHA-256 `09948d4cdd0650da6ff5a87577469f2a218dc2615ae379f8f734d24c49de0f73` |
| `ffprobe.exe` | SHA-256 `a6618e99bb58869ded3c6f37b53aa1a8d701c3591dbb7b5b317d47369c112be2` |
| Licence | GPL v3 (`--enable-gpl --enable-version3`, sans `--enable-nonfree`), avec libx264 lié statiquement |

Build rejeté : `N-125954-g9862dd83b1-20260804` (nightly master de BtbN). Son encodeur
AAC natif se bloque (défaut D1). Voir `docs/export_bounded_execution.md`.

## Préparation et vérification

`scripts/prepare_ffmpeg.ps1` prépare `vendor/ffmpeg/`, qui est ignoré par Git et
embarqué tel quel par PyInstaller.

- **Binaires existants.** Ils sont conservés s'ils correspondent au build épinglé, et
  refusés sans être modifiés sinon. L'option `-Replace` les remplace ; les anciens
  binaires sont alors copiés dans `artifacts/`.
- **Sources acceptées.** Le script accepte uniquement :
  - un dossier local passé avec `-SourceDir` ;
  - une archive locale passée avec `-ArchivePath` ;
  - le paquet WinGet `Gyan.FFmpeg` 8.1.1 de l'utilisateur ;
  - l'URL épinglée, seulement avec `-AllowDownload`.

  Il n'utilise jamais une release « latest ».
- **Contrôles avant installation.** `ffmpeg.exe` et `ffprobe.exe` doivent tous deux
  correspondre aux SHA-256 épinglés et annoncer la version épinglée. Cela garantit qu'ils
  proviennent du même build. Une copie corrompue est refusée sans rien modifier.
- **Documents copiés.** Le script vérifie puis copie `LICENSE.txt` (texte de la GPL v3)
  et `README-ffmpeg-build.txt` (configuration de compilation, versions des bibliothèques,
  référence des sources), ainsi que `BUILD-PIN.json`.
- **Sans effet système.** Le script ne modifie jamais le PATH et n'installe rien à
  l'échelle du système.

En cas d'échec, le message indique la procédure de récupération : `-SourceDir`,
`-ArchivePath`, `winget install --id Gyan.FFmpeg --version 8.1.1` ou `-AllowDownload`.

`scripts/build_windows.ps1` appelle ce script, puis refuse le paquet si les binaires
copiés par PyInstaller ne correspondent pas au pin, ou si le texte de licence manque.

`scripts/install_ffmpeg.ps1` est l'installateur optionnel par utilisateur. Il installe
le même build épinglé ; ses hashes intégrés sont vérifiés par `tests/test_ffmpeg_pin.py`.

À l'exécution, si `vendor/ffmpeg/bin` est absent, l'application utilise FFmpeg depuis le
PATH et le signale par un avertissement dans le journal. Le test
`test_bundled_aac_encoder_does_not_hang` détecte un build touché par D1.

## Obligations GPL (à valider juridiquement)

Distribuer `ffmpeg.exe` et `ffprobe.exe` revient à distribuer des binaires sous GPL v3.
L'application doit :

1. **Joindre le texte de la licence.** C'est fait : `vendor/ffmpeg/LICENSE.txt` est
   embarqué et vérifié.
2. **Rendre disponible la « source correspondante » du build.** Il s'agit des sources
   FFmpeg au commit `239f2c733d`, des sources des bibliothèques liées statiquement
   (versions listées dans `README-ffmpeg-build.txt`) et des scripts de compilation.
   L'utilisateur doit pouvoir la récupérer : soit livrée avec le paquet, soit via une
   offre écrite, soit via un serveur tiers dont la disponibilité continue est assurée
   (GPL v3, §6).
3. **Indiquer** que FFmpeg est un programme distinct, invoqué par ligne de commande, et
   identifier sa version.

Questions ouvertes :

- **Source correspondante.** Elle n'est pas encore archivée par le projet ;
  gyan.dev indique les sources, mais leur disponibilité dans la durée n'est pas garantie.
- **Licence de l'application.** NSFW-Cutter n'a pas de fichier de licence dans le dépôt.
  Le statut d'« agrégat » (programme séparé appelé par sous-processus) est l'interprétation
  courante, mais elle doit être confirmée.
- **Portée du build.** Le build « full » embarque de nombreuses bibliothèques inutiles à
  l'application. Un build « essentials » ou un build sur mesure réduirait la taille et
  l'ensemble des sources à fournir ; il devra être validé avec la même matrice de tests.
