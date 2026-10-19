# cuBLAS CUDA 12 embarqué pour Whisper : provenance, vérification et licence

## Pourquoi deux versions de CUDA

- **Whisper (faster-whisper 1.2.1).** Il s'appuie sur CTranslate2 4.8.1, compilé pour **CUDA 12**.
  `ctranslate2.dll` intègre le runtime CUDA et le pilote (`nvcuda.dll`). Il charge cuBLAS
  dynamiquement par son nom, `cublas64_12.dll`, qui dépend lui-même de `cublasLt64_12.dll`. Il
  ne fait aucune référence à cuDNN.
- **Qwen et Marqo (PyTorch 2.13.0+cu130).** Ils utilisent **CUDA 13**. PyTorch fournit son propre
  `cublas64_13.dll`, `cublasLt64_13.dll`, son runtime CUDA 13 et cuDNN 9.20.
- **Sans cuBLAS 12.** Le modèle Whisper se charge bien sur CUDA, mais le premier calcul échoue
  avec `Library cublas64_12.dll is not found or cannot be loaded`. L'application revient alors
  sur le CPU (`CUDA Whisper inference failed; using the slow CPU fallback.`).
- **cuDNN pour CUDA 12 n'est pas embarqué.** CTranslate2 4.8.1 n'en a pas besoin, et sa DLL
  `cudnn64_9.dll` porte le même nom que celle de PyTorch.

Les deux versions ne partagent aucun nom de fichier (`…64_12.dll` d'un côté, `…64_13.dll` de
l'autre). PyTorch et ses bibliothèques CUDA 13 ne sont ni modifiés ni déplacés.

## Archive retenue

La seule source de vérité est `scripts/cuda12-cublas-pin.json`.

| Élément | Valeur |
|---|---|
| Version | cuBLAS **12.8.4.1** (redistribuable CUDA 12.8.1) |
| Archive | `https://developer.download.nvidia.com/compute/cuda/redist/libcublas/windows-x86_64/libcublas-windows-x86_64-12.8.4.1-archive.zip` |
| Manifeste NVIDIA | `https://developer.download.nvidia.com/compute/cuda/redist/redistrib_12.8.1.json` |
| SHA-256 de l'archive | `57a470112cec7e112c95253dde8b3c7184d795dbd92b0bde77a4cb7f8c94c8aa` (563 660 944 octets) |
| `cublas64_12.dll` | SHA-256 `9513540e4ec4c51ee9e7304138c2cc255c29a8c181f9e80c38efa25738becd99`, 113 716 224 octets |
| `cublasLt64_12.dll` | SHA-256 `b199d1ff892a81b7fd3d57ba1781549609b41500b36008fef326038393ad46c7`, 674 667 520 octets |
| `LICENSE.txt` | SHA-256 `e2c71babfd18a8e69542dd7e9ca018f9caa438094001a58e6bc4d8c999bf0d07` |

Les deux DLL sont des binaires x64. Elles n'importent que `KERNEL32.dll`, et
`cublasLt64_12.dll` dans le cas de `cublas64_12.dll`.

**Les DLL ne portent pas de signature Authenticode.** Les DLL CUDA 13 de PyTorch, elles, sont
signées. La provenance repose donc sur le téléchargement HTTPS depuis le domaine NVIDIA et sur
les empreintes publiées dans le manifeste.

## Préparation et vérification

`scripts/prepare_cuda12_cublas.ps1` prépare `vendor/cuda12-cublas/`, un dossier ignoré par Git.

```powershell
# Archive déjà téléchargée (recommandé, sans accès réseau) :
.\scripts\prepare_cuda12_cublas.ps1 -ArchivePath C:\chemin\libcublas-windows-x86_64-12.8.4.1-archive.zip
# Ou téléchargement explicite de l'URL épinglée :
.\scripts\prepare_cuda12_cublas.ps1 -AllowDownload
```

Ce que fait le script :

- **Sans argument**, il ne télécharge jamais rien. Il vérifie les fichiers déjà présents et
  échoue avec une procédure de récupération s'ils manquent.
- **L'archive** doit avoir la taille et le SHA-256 épinglés. Le script n'en extrait que les deux
  DLL et `LICENSE`, et vérifie l'empreinte de chacun avant de l'installer. Une archive ou un
  fichier non conforme est refusé sans rien modifier.
- **Les fichiers déjà présents** sont conservés s'ils correspondent au pin, et refusés sans être
  modifiés sinon. L'option `-Replace` les remplace ; les anciens sont alors copiés dans
  `artifacts/`.
- **Aucun effet système.** Le script ne modifie pas le PATH et n'installe rien à l'échelle du
  système.

`scripts/build_windows.ps1` appelle ce script, sans téléchargement, après la préparation de
FFmpeg. Il ajoute ensuite les deux DLL dans `_internal\ctranslate2\`, à côté de
`ctranslate2.dll`. C'est là que `ctranslate2/__init__.py` les trouve : il ajoute son propre
dossier au chemin de recherche des DLL et charge les DLL qu'il contient. Aucun chemin global
n'est ajouté.

Après PyInstaller, le script fait encore deux choses :

- **Doublon supprimé.** L'analyse de dépendances de PyInstaller copie aussi `cublasLt64_12.dll`
  à la racine de `_internal\`, un dossier qui fait partie du chemin de recherche des DLL de tout
  le processus. Le script supprime cette copie, à condition que son empreinte soit exactement
  celle du pin. `--add-data` ne l'évite pas, car PyInstaller reclasse les DLL en binaires.
- **Contrôles finaux.** Le build échoue si une DLL manque, si son empreinte diffère, s'il en
  reste une autre copie dans `_internal\`, ou si la licence (`_internal\vendor\cuda12-cublas\LICENSE.txt`)
  est absente.

`tests/test_cuda12_cublas_pin.py` vérifie le pin, le script de préparation et le script de
build sans télécharger l'archive. Les contrôles de `vendor/` et de `dist/` sont ignorés tant que
ces dossiers n'existent pas localement.

## Construire hors ligne

1. Préparer FFmpeg (`docs/ffmpeg_distribution.md`) et cuBLAS (ci-dessus) à partir de copies
   locales vérifiées.
2. Installer l'environnement Python décrit dans le README : `requirements.txt`, PyTorch cu130,
   et la pile d'analyse locale. Les poids des modèles ne sont jamais embarqués.
3. Lancer `.\scripts\build_windows.ps1`. Les deux scripts de préparation trouvent les fichiers
   déjà vérifiés et n'accèdent pas au réseau.

**Les workflows GitHub `build-windows.yml` et `release.yml` ne préparent pas cuBLAS.** Le build
CI échoue donc à cette étape tant qu'aucune étape de préparation n'est ajoutée, qu'il s'agisse
d'une archive en cache ou de `-AllowDownload`. C'est une décision à prendre, non implémentée.

**Effet du PATH.** Le hook PySide6 de PyInstaller cherche aussi `libssl-3-x64.dll` et
`libcrypto-3-x64.dll` dans le PATH. Un build lancé depuis Git Bash embarque ainsi l'OpenSSL
3.2.1 de Git for Windows ; un build lancé depuis PowerShell ne l'embarque pas. Voir les points
ouverts ci-dessous.

## Taille et ressources

- **Taille.** Le paquet gagne 788 Mo (de 4,43 à 5,22 Go). Le zip gagne environ 0,57 Go (de 2,55
  à environ 3,12 Go, mesuré sur un build intermédiaire).
- **Mémoire mesurée** le 2026-10-19 sur une RTX 3070 8 Go avec 32 Go de RAM :
  - la RAM du processus monte jusqu'à environ 9,9 Go pendant le chargement de Qwen ;
  - la VRAM monte jusqu'à 4,4 Go dans un processus neuf, et jusqu'à 5,06 Go quand Qwen est
    encore chargé d'une analyse précédente et que Whisper tourne sur le GPU (environ 1,6 Go
    étaient déjà occupés par d'autres programmes) ;
  - une carte de 6 Go serait donc juste.
- **Build.** La compression `Compress-Archive` de 5,2 Go a été interrompue une fois, alors que
  la mémoire système était faible.
- **Portabilité.**
  - Windows x64 uniquement.
  - Testé avec un seul GPU (RTX 3070, sm_86) et un seul pilote (610.88). La version minimale du
    pilote requise par CUDA 12.8 est celle des notes de version CUDA ; elle n'a pas été testée
    ici.
  - Sans GPU NVIDIA, ou si l'exécution CUDA échoue, Whisper revient automatiquement sur le CPU.

## Reproduire le test GPU du paquet

Ce test a été fait manuellement sur l'exécutable réel, avec l'interface visible.

1. **Environnement.** PATH réduit à `C:\Windows\System32` (sans FFmpeg).
   `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1` et
   `NSFW_CUTTER_LANGSMITH_TRACING=0`. `NSFW_CUTTER_AI_ALLOW_MODEL_DOWNLOAD` est retiré. Les
   modèles sont déjà présents dans le cache utilisateur.
2. **Données utilisateur.** Sauvegarder `settings.json`, `nsfw_app.db` et `video-cut.log` avec
   leur SHA-256. Vérifier qu'aucun enregistrement d'analyse n'existe pour les vidéos de test.
3. **Médias.** Vidéos de test non sensibles de 40 s (mires et voix de synthèse Windows locale) :
   - **A**, phrases neutres ;
   - **B**, description d'un plan de maison contenant le mot ordinaire « bedroom », qui active
     la branche déclenchée par le texte ;
   - **C**, pour l'annulation.
4. **Pour chaque vidéo :** l'ouvrir, cliquer sur **AI Picks** puis **Analyze video**, et
   surveiller la VRAM (`nvidia-smi`), la RAM, la réactivité de l'interface et les connexions
   sortantes. Pour C, cliquer sur **Cancel analysis** pendant le premier lot Qwen.
5. **Critères de réussite :**
   - aucun avertissement « CUDA Whisper inference failed » dans l'enregistrement ;
   - une seule ligne `faster_whisper Processing audio` par analyse ;
   - `cublas64_12.dll` et `cublasLt64_12.dll` chargées depuis `_internal\ctranslate2\`, et
     `cublas64_13.dll` depuis `_internal\torch\lib\` (liste des modules du processus) ;
   - `provider_diagnostics` indique Qwen en `cuda` / `bitsandbytes-nf4` ;
   - l'enregistrement de C est `cancelled` ;
   - aucune connexion sortante.
6. **Après les tests.** Fermer l'application, supprimer les entrées de cache créées par le test,
   restaurer les fichiers utilisateur, puis vérifier leurs empreintes.

**Résultats du 2026-10-19,** comparés au build précédent qui utilisait le repli CPU, à
processus neuf égal :

| Vidéo | Analyse avant | Analyse après |
|---|---|---|
| A | 46,4 s | 42,4 s |
| B | 27,4 s | 23,6 s |

- Les sorties Marqo et Qwen ainsi que les suggestions sont identiques.
- Sur B, la fin d'un segment Whisper diffère : 11,8 s avec CUDA en float16, 13,0 s sur CPU en
  int8.
- Transcription seule : 0,31 s sur GPU contre 2,87 s sur CPU. Le gain sur l'analyse complète
  reste limité, car le chargement de Qwen domine la durée.

## Revenir au repli CPU

- **Sur un paquet déjà construit :** supprimer `_internal\ctranslate2\cublas64_12.dll` et
  `cublasLt64_12.dll`. L'application revient automatiquement sur le CPU pour Whisper, sans
  changement de code.
- **Dans le dépôt :** annuler le commit qui introduit ce document, puis reconstruire.
- **Build précédent :** le build qui utilisait le repli CPU (HEAD `dd0963e`) a été conservé
  localement dans `artifacts/previous-build-cpu-fallback-dd0963e/`, un dossier ignoré par Git
  et absent des autres machines.

## Obligations de redistribution (à valider juridiquement)

Le contrat de licence CUDA (« CUDA Toolkit EULA », annexe A) range « CUDA BLAS Library :
cublas.dll, cublasLt.dll » parmi les fichiers redistribuables, y compris les variantes dont le
nom porte un numéro de version. Ses conditions comprennent :

- **Fonctionnalité substantielle.** L'application doit apporter une fonctionnalité substantielle
  en plus des bibliothèques.
- **Usage limité.** Les fichiers ne doivent servir qu'à l'application.
- **Fichiers non modifiés.** Les fichiers ne doivent pas être modifiés.
- **Conditions compatibles.** Les conditions de distribution de l'application doivent être
  compatibles avec celles du contrat.
- **Matériel NVIDIA.** L'utilisation doit se faire sur des systèmes équipés d'un GPU NVIDIA.

État actuel :

- **Fait.** Le texte de la licence NVIDIA (`LICENSE.txt` de l'archive) est embarqué et vérifié,
  et les fichiers ne sont pas modifiés (empreintes vérifiées).
- **Non fait.**
  - Aucune revue juridique n'a confirmé que ces conditions sont remplies.
  - Le dépôt n'a pas de licence d'application permettant de juger la compatibilité.
- **Points voisins encore ouverts :**
  - FFmpeg : source correspondante GPL (voir `docs/ffmpeg_distribution.md`) ;
  - OpenSSL : le paquet contient `libssl-3.dll` 3.5.7 de CPython, et parfois `libssl-3-x64.dll`
    3.2.1 de Git for Windows selon le PATH du build, sans texte de licence OpenSSL (Apache-2.0) ;
  - CPython : l'avis de licence n'est pas inclus.

Ces obligations ne sont pas considérées comme remplies.
