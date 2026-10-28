# Modes d'export — 18 octobre 2026

## Ce que l'application propose aujourd'hui

L'interface active (`CleanShellPage`) n'a qu'une action : **Export Clean Video**. La liste de coupes
contient des intervalles **à supprimer** (« Total Removed », « Video After Cuts ») et l'export envoie
toujours `export_mode = "remove_intervals"`, en Smart Cutting ou en Fast Cutting.

La fenêtre des réglages ne propose plus de mode d'export. Elle affichait « Remove intervals / Export clips
separately / Export merged clips », mais ce choix n'était relu nulle part. À la place, elle explique
désormais que l'export supprime les coupes de la liste.

## Valeur `last_export_mode` déjà enregistrée

`settings.json` peut contenir `export_clips_separate` ou `export_clips_merged`, écrits par une ancienne
version. Ces valeurs restent valides pour `AppSettings`, ne sont pas réécrites et **ne sont lues par
aucun export** : elles ne peuvent déclencher aucun export inattendu. `OutputPreferences.remember` y
enregistre seulement le mode réellement utilisé (`remove_intervals`).

## Ce qui reste disponible dans le backend

`export_clips_separate` et `export_clips_merged` (`CutExecutionService`) sont conservés et testés
(`tests/test_fast_separate_clips.py`, `tests/test_fast_merged_clips.py`). Ils attendent des intervalles
**à garder** et n'existent qu'en Fast Cutting. Ils refusent les sources avec son et les bornes qui ne
tombent pas sur une image clé utilisable.

## Pour un futur flux « garder des clips »

Il ne faut pas réinterpréter la liste de coupes actuelle. Il faut :

1. **Un choix explicite au moment de l'export**, à côté de Smart/Fast, et non un réglage global
   (par exemple « Supprimer les coupes » / « Garder les clips : un fichier par clip » / « Garder les
   clips : un seul fichier »).
2. **Un vocabulaire distinct en mode clips** : « Clips à garder », « Durée conservée », et la liste des
   fichiers qui seront produits. La même liste ne peut pas signifier « supprimer » et « garder » sans
   que l'utilisateur le voie.
3. **Des préconditions visibles** : en mode clips, Smart Cutting est indisponible (il n'accepte que
   `remove_intervals`), une source avec son est refusée et les bornes doivent tomber sur des images
   clés (sélection « safe »). L'option doit être désactivée, avec la raison affichée, quand ces
   conditions ne sont pas remplies.
4. **Un enregistrement fidèle** : ne mémoriser le mode qu'à partir de ce choix explicite.
5. **Des tests** sur la page et le contrôleur pour chaque mode : demande envoyée au backend,
   refus attendus (son, images clés), fichiers produits, et aucun export lancé en mode clips à partir
   d'une liste de suppressions.
