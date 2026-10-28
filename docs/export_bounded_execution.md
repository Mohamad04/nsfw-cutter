# Exécution bornée et annulation des exports (D1/D6) — 18 octobre 2026

Base Git : `95b90acac8f7d614615ecd8dbde2d5d8078bb80a`. Aucune inférence IA, aucune
modification du pipeline de détection.

## D1 — cause

Le blocage vient de l'encodeur AAC natif des builds FFmpeg *nightly* : le build fourni
`N-125954-g9862dd83b1-20260804`, et `N-126965` également. L'orchestration des
sous-processus n'est pas en cause. Points établis :

- Reproduction minimale : 1,5 s de silence numérique suivi d'une salve de 1 kHz de
  40 ms débutant entre 0,6 et 0,75 s, en mono 48 kHz, `-c:a aac -b:a 192k`. Le build
  boucle à 100 % CPU, et la sortie reste figée à `time=00:00:00.66`.
- Le blocage persiste avec une entrée WAV déjà décodée (sans filtre ni démultiplexeur),
  et quelle que soit l'entrée standard (`stdin` hérité ou `DEVNULL`).
- Il ne se produit pas en 128k, 160k ni 256k, ni en stéréo, ni avec `-aac_coder fast`,
  ni en sortie PCM.
- Les builds de la branche 8.1 (`n8.1.2-34`, Gyan `8.1.1` release) ne bloquent sur
  aucune variante testée.

## FFmpeg fourni : passage à 8.1.1 stable

`vendor/ffmpeg/` (ignoré par Git, embarqué tel quel par PyInstaller) contient désormais
le build statique Gyan `8.1.1-full_build`, licence GPL v3, sans composant `nonfree`. Ce
build est accompagné de son `LICENSE.txt` et de `README-ffmpeg-build.txt`, qui indique
la référence du code source `239f2c733d`.

| Binaire | SHA-256 |
|---|---|
| ffmpeg.exe | `09948d4cdd0650da6ff5a87577469f2a218dc2615ae379f8f734d24c49de0f73` |
| ffprobe.exe | `a6618e99bb58869ded3c6f37b53aa1a8d701c3591dbb7b5b317d47369c112be2` |

La préparation est épinglée et vérifiée par hash : voir `docs/ffmpeg_distribution.md`.
Le test `test_bundled_aac_encoder_does_not_hang` échoue si un build touché par D1 est de
nouveau embarqué.

## Exécution bornée

`services/infrastructure/ffmpeg/bounded_runner.py` remplace `subprocess.run` pour tous
les appels FFmpeg/ffprobe des exports Smart et Fast.

- **Chien de garde de progression** : FFmpeg est arrêté si sa progression (`time=` sur
  stderr, ou des octets sur stdout pour ffprobe) n'avance plus pendant
  `NSFW_CUTTER_FFMPEG_STALL_TIMEOUT_SECONDS` secondes (180 par défaut). Un export long qui
  progresse n'est jamais interrompu ; une limite absolue optionnelle existe
  (`max_runtime_seconds`, désactivée par défaut).
- **Annulation** : `ExportCancellationToken` termine le processus FFmpeg actif
  (`taskkill /T /F` sous Windows) et refuse les commandes suivantes.
- **Erreurs distinctes** : un dépassement lève `FFmpegTimeoutError`, une annulation
  `ExportCancelledError`.
- **Nettoyage** : après une annulation ou un dépassement, l'export supprime son dossier
  temporaire et sa sortie partielle. Il ne supprime jamais un fichier qu'il n'a pas créé.

## Annulation utilisateur

Le bouton « Cancel » de `ExportActionBar` (visible pendant un export) appelle
`VideoCutController.cancelExport()`. L'annulation suit ensuite ce chemin :

1. les runners appellent `cancel()` sur le worker ;
2. le worker déclenche son jeton d'annulation ;
3. le runner borné termine FFmpeg ;
4. le worker émet `signals.cancelled` ;
5. l'état passe à `cutCancelled`, avec le statut « Video export cancelled » ;
6. le job Fast est enregistré en base avec le statut `cancelled`.

Un second export lancé pendant qu'un export est en cours est refusé.

## Audio en Fast Cutting

Mesure sur échantillons décodés, avec un ton marqueur placé uniquement dans
l'intervalle supprimé : la copie de flux AAC conserve 97 ms de son supprimé pour une
jonction, et 271 ms pour 3 coupes. Fast Cutting refuse donc désormais la suppression
d'intervalles sur une source avec audio (`FastCuttingAudioError`) et oriente vers
Smart Cutting, qui donne 0 ms de résidu.

## Fichiers temporaires de Fast Cutting (D5)

Chaque export Fast copie ses segments dans un dossier qui lui est propre,
`cache/<préfixe>_<uuid>` (ce dossier contient aussi `concat_list.txt`). La sortie finale est
écrite dans le dossier de sortie, jamais dans ce dossier temporaire.

- **Export réussi** : l'export supprime son propre dossier temporaire. Si la suppression
  échoue, le message `Temporary files could not be removed: …` est ajouté à
  l'avertissement du résultat et au journal. La sortie, déjà vérifiée, est conservée.
- **Échec, annulation ou délai dépassé** : l'export supprime son dossier temporaire et les
  sorties qu'il a lui-même créées.
- **Exports simultanés** : un export ne touche jamais aux dossiers des autres exports
  (nom unique), ni à la source, ni aux fichiers qui existaient déjà.
