# Exactitude image par image des exports (D3/D4) — 18 octobre 2026

Base Git : `cb46a427e42e1e8fdf4cfebb72cad4af6df8a8ca`. Aucune inférence IA,
aucune modification du pipeline de détection.

## Invariant

Aucune image source dont le PTS appartient à un intervalle supprimé `[début, fin)`
ne doit apparaître dans la vidéo exportée. Chaque image conservée apparaît une fois,
dans l'ordre.

## Causes corrigées

- `-to` / `-t` en copie de flux s'arrêtent sur les DTS : avec des B-frames, le
  keyframe du GOP suivant (et le P qui le suit) étaient copiés. Smart Cutting
  laissait fuir ou dupliquait 2 images par jonction ; Fast Cutting aussi, même
  sur des coupes alignées.
- Fast Cutting démarrait la copie au keyframe précédant une borne non alignée,
  sans contrôle ni refus.
- Smart Cutting découpait l'audio au temps exact et la vidéo au pas d'image, ce qui
  créait une dérive A/V cumulative.

## Comportement

- `services/export/video_packet_index.py` indexe les paquets vidéo (PTS, keyframe,
  hash). Une copie de `[a, b)` n'est tentée que si `a` et `b` sont des points de
  coupe propres ; elle est limitée par `-frames:v N`, puis vérifiée par hash.
- Smart Cutting : si un segment n'est pas copiable proprement (open-GOP), il est
  ré-encodé et signalé dans `video_fallbacks`. Le nombre d'images de chaque morceau
  ré-encodé, la vidéo concaténée et le fichier final sont vérifiés ; en cas d'échec,
  l'export est arrêté et la sortie supprimée. L'audio commence à la première image
  conservée et est complété par du silence jusqu'à l'image suivante (`apad`).
- Fast Cutting (`remove_intervals`) refuse, avant toute commande FFmpeg, toute borne
  qui n'est pas un keyframe de GOP fermé. Le message de refus liste les keyframes
  voisins. Aucune extension silencieuse, aucune bascule vers Smart Cutting.

## Vérification

- `python -m pytest tests/test_export_frame_accuracy.py` : FFmpeg réel, fixtures
  synthétiques à images identifiables, timeout sur chaque sous-processus.
- `python scripts/evaluate_export_frame_accuracy.py --output-dir artifacts/<run> --label <nom>` :
  matrice de 23 cas, résultats JSON (option `--remeasure`).

## Limites connues (non corrigées ici)

- D1 : blocage de l'encodeur AAC sur certaines plages (cas S06).
- D2 : MKV H.264 refusé, car FFmpeg démarre la copie au keyframe précédent.
- D10 : trou d'horodatage de 80 à 96 ms à chaque jonction Fast.
- Fast Cutting : l'audio est copié par trames AAC entières, et peut donc contenir du
  son de l'intervalle supprimé au voisinage des bornes.
