# Pilote reproductible NSFW-Cutter — version 1

Cette infrastructure mesure le pipeline livré ; elle ne change ni les modèles,
ni les prompts, ni les décisions, ni la fusion. Ses tests sont synthétiques :
ils ne constituent **pas** une validation scientifique du détecteur.

## Organisation

- `evaluation/pilot/manifest.py` : contrats Pydantic stricts et identité des fichiers.
- `metrics.py` : métriques hors ligne, sans modèle ni accès aux vidéos.
- `observability.py` : observateurs déléguant aux services existants et cache privé.
- `runner.py` : appel de `AnalysisPipeline.run()`, isolation, provenance, sauvegarde.
- `report.py` : association des résultats aux annotations, agrégations et CSV.
- `__main__.py` : CLI, accessible par `python -m evaluation.pilot`.
- `templates/six_clips.blank.json` : six entrées **à remplir**, toutes en tuning.
- `tests/fixtures/pilot/synthetic.json` : exemple terminé **fictif**, sans vidéo.
- `tests/test_pilot_evaluation.py` : tests exclusivement synthétiques/simulés.

Aucun fichier de production n'est modifié. L'import du contrôleur nécessaire
pour réutiliser sa conversion des paramètres est différé au mode `run`.
Il nécessite les dépendances de l'application, dont Qt. `validate-only`, `schema`
et `score` n'importent pas ce contrôleur et ne nécessitent pas les poids des modèles.

## Schéma du manifeste

Le schéma machine normatif est généré depuis les mêmes classes que le validateur :

```powershell
.venv\Scripts\python.exe -m evaluation.pilot schema
```

Tous les objets structurés refusent les champs inconnus. Les nombres sont finis,
les booléens ne sont pas des temps, les identifiants sont uniques dans leur portée.
Les chemins sont relatifs au dossier du manifeste, ou absolus. Les temps sont en
secondes **locales au clip**, dans des intervalles semi-ouverts `[début, fin)`.
Le temps dans la source vaut `source_offset_seconds + temps_local`.

| Objet/champ | Contrat version 1 |
| --- | --- |
| `schema_version` | `1` |
| `dataset_id` | Identifiant stable, lettres/chiffres/`_.-` |
| `synthetic` | `false` pour les vrais clips ; `true` interdit l'inférence CLI |
| `clips` | Liste non vide ; le modèle fourni contient exactement six clips |
| `clip_id` | Identifiant unique, indépendant du nom du fichier |
| `source_video_id` | Identifiant de la vidéo source ; même source = même split |
| `file_path` | Chemin du clip, pas une URL |
| `source_offset_seconds` | Début du clip dans la source, >= 0 |
| `split` | `tuning` ou `test` |
| `duration_seconds` | Durée > 0, à reprendre précisément des métadonnées média |
| `sha256` | SHA-256 complet des octets, 64 caractères hexadécimaux minuscules |
| `media_metadata` | Objet optionnel libre : codecs, résolution, FPS, origine de la mesure… |
| `annotation_version` | Version non vide ; à incrémenter après révision |
| `exhaustive` | `true` seulement après visionnage/annotation de tout le clip |
| `events` | Liste d'événements ; `[]` signifie négatif seulement si exhaustif |
| `excluded_intervals` | Intervalles explicitement ambigus ou non évaluables |

Un événement contient `event_id`, `start_seconds`, `end_seconds`, `categories`,
`notes` (peut être vide), `uncertainty` (facultatif/null). `categories` est une
liste non vide et sans doublons parmi `nudity`, `sexual_activity`, `sexual_context`.
`uncertain` est une sortie du modèle, **jamais une vérité positive**.
`uncertainty` contient éventuellement `start_tolerance_seconds`,
`end_tolerance_seconds` et `notes`. Ces tolérances documentent l'annotation ; elles
ne modifient pas secrètement l'IoU ou les seuils du score primaire.

Une exclusion contient `exclusion_id`, `start_seconds`, `end_seconds`,
`kind` (`ambiguous` ou `excluded`), et `reason` non vide.
Tous les événements/exclusions doivent vérifier `0 <= début < fin <= durée`.
Les exclusions peuvent se chevaucher : leur union est soustraite une seule fois.

Les champs d'identité/durée du modèle vierge sont `null`, et `exhaustive=false`.
`validate-only --allow-draft` contrôle sa structure mais ne le déclare pas prêt.
Sans cette option, chaque clip doit être exhaustif et tous ces champs renseignés.
Les sources et empreintes communes à tuning et test sont interdites. Le validateur
ne peut pas détecter deux identifiants trompeurs désignant la même source : cela
reste une responsabilité de préparation du corpus.

## Préparer et annoter les six vrais clips

1. Choisir au moins trois sources distinctes, identifiées sans ambiguïté, dont les
   contenus sont utilisables dans le cadre du projet. Garder les médias privés.
2. Réserver les six clips au **tuning/pilote** ; ne pas les réutiliser comme test
   indépendant après avoir inspecté leurs erreurs. Réserver d'autres sources pour
   l'évaluation finale. Le manifeste accepte les deux splits pour cette phase ultérieure.
3. Inclure deux clips sans événement cible, des positifs courts et longs, des
   contextes visuellement difficiles et un cas ambigu explicitement masqué. Ne
   pas annoter artificiellement des catégories qui ne sont pas présentes.
4. Reprendre la durée média précise et l'offset source. Calculer SHA-256 une fois
   les clips définitifs préparés. Le mode de validation ne lit pas ces fichiers.
5. Visionner intégralement, poser début/fin locaux et catégories selon un guide
   écrit avant de regarder les prédictions. Une scène continue constitue un
   événement par catégorie, pas un événement par personne ni par image.
   Des catégories différentes peuvent se chevaucher. Documenter les désaccords.
6. En cas d'ambiguïté non résolue, définir une exclusion motivée plutôt qu'une
   pseudo-vérité `uncertain`. Si possible, faire relire les bornes par une autre personne.
7. Mettre `exhaustive=true` seulement après cette vérification, puis figer le
   manifeste/version. Conserver les changements d'annotation comme nouvelles versions.

Commandes PowerShell de préparation, **sans inférence** (depuis la racine du dépôt) :

```powershell
# Ce dossier est déjà couvert par artifacts/ dans .gitignore.
# ErrorAction Stop évite de remplacer accidentellement une préparation existante.
New-Item -ItemType Directory -Path artifacts/pilot -ErrorAction Stop
Copy-Item evaluation/pilot/templates/six_clips.blank.json artifacts/pilot/manifest.json
.venv\Scripts\python.exe -m evaluation.pilot validate-only artifacts/pilot/manifest.json --allow-draft

# Pour chaque vrai fichier, quand il existe ; copier le résultat dans le manifeste.
(Get-FileHash -LiteralPath 'CHEMIN_DU_CLIP' -Algorithm SHA256).Hash.ToLowerInvariant()

# Après remplissage manuel des six annotations :
.venv\Scripts\python.exe -m evaluation.pilot validate-only artifacts/pilot/manifest.json
```

`validate-only` ne crée ni résultat, ni cache, ne calcule aucune empreinte média,
ne lance ni FFmpeg/ffprobe, ni modèle. Il valide uniquement le JSON et les
annotations déclarées. Le résultat précise `media_identity_verified=false`.
L'exemple de test peut être validé sans fichier vidéo :

```powershell
.venv\Scripts\python.exe -m evaluation.pilot validate-only tests/fixtures/pilot/synthetic.json
```

## Exécuter ultérieurement le pilote

Ces commandes sont à exécuter **uniquement après annotation et décision explicite
de lancer une vraie inférence locale**. Elles n'ont pas été exécutées pour construire
l'infrastructure. Les poids de production et FFmpeg doivent déjà être disponibles.
Le runner interdit le téléchargement par configuration, désactive les traces réseau
LangSmith et n'appelle aucun outil de provisionnement. Ce n'est pas un pare-feu
système : un environnement isolé reste préférable pour les données sensibles.

```powershell
.venv\Scripts\python.exe -m evaluation.pilot run artifacts/pilot/manifest.json --clip pilot_01 --output artifacts/pilot/runs --allow-inference
```

Répéter pour `pilot_02` à `pilot_06`, **un processus par clip**, afin de ne pas
réutiliser implicitement un modèle déjà chargé en mémoire. Vérifier chaque
`summary.json` avant de poursuivre. Le code de retour vaut 0 pour `completed`,
2 pour les autres états. Ctrl+C demande une annulation coopérative ; l'arrêt d'un
calcul GPU en cours peut attendre un point de contrôle du pipeline.

Les paramètres sont ceux du fichier de réglages courant de l'application, ou ses
valeurs par défaut si ce fichier n'existe pas. Aucune création/réparation de ce
fichier n'est effectuée. Un fichier invalide bloque l'exécution. Pour figer une
configuration, fournir une copie privée explicite via `--app-settings`.

```powershell
.venv\Scripts\python.exe -m evaluation.pilot run artifacts/pilot/manifest.json --clip pilot_01 --output artifacts/pilot/runs --app-settings artifacts/pilot/app-settings.json --overrides artifacts/pilot/overrides.json --allow-inference
```

`overrides.json` est un objet JSON de champs `AnalysisSettings`, validé strictement.
Exemple d'une comparaison à un seul paramètre :
`{"prefilter_candidate_threshold": 0.25}`. Ce nombre est un exemple de configuration,
pas un seuil recommandé après expérimentation. Aucun changement d'identité de modèle,
révision épinglée, prompt/schema ou profil versionné n'est autorisé.

Ne pas confondre :

- `prefilter_candidate_threshold` : porte Marqo de Balanced/Thorough ;
- `prefilter_strong_threshold` : porte Marqo de Fast ;
- `visual_confidence_threshold` : filtre des évidences visuelles lors de la fusion.

Le runner reprend exactement `_analysis_settings_from_app_settings` : le seuil
visuel par défaut de l'application est 0,50, alors que celui du contrat seul est
0,55. L'ancien `ai_sample_rate_fps` de l'application n'est pas un override effectif.
Les taux résolus, la porte Marqo effective et les plafonds réels de tokens sont
enregistrés séparément des valeurs demandées. Les autres constantes d'implémentation
sont identifiées par le commit et les empreintes des sources.

La branche texte utilise explicitement `selected_subtitle=None`, donc le chemin
audio/Whisper existant. Ce pilote n'évalue pas la sélection de sous-titres de l'UI.
La revue humaine et l'export ne sont pas exécutés : les prédictions évaluées sont
les suggestions automatiques **avant revue humaine**.

## Sorties, cache et confidentialité

Un appel crée `runs/<horodatage_UTC>_<UUID>/` par création exclusive. Il ne reprend
jamais une tentative précédente, et `force_reanalysis=true`. Les poids locaux sont
réutilisés, mais pas les résultats d'analyse. Le cache OS n'est pas purgé ; il faut
donc parler de cache d'analyse froid, pas de machine entièrement froide.

| Fichier | Schéma et contenu |
| --- | --- |
| `manifest.json` | Copie intégrale du manifeste v1, avec digest canonique |
| `config.json` | v1 : tous les réglages effectifs, valeurs résolues, provenance et overrides |
| `attempt.json` | v1 : identité, clip, split, début UTC, digests, politique de cache, état initial `running` |
| `environment.json` | v1 : commit, état Git, empreintes sources, versions installées, Python, OS/CPU/RAM/GPU si disponibles, FFmpeg et environnement d'exécution |
| `observations.jsonl` | Chaque ligne v1 : `kind`, horloge monotone relative, métadonnées de l'étape |
| `record.json` | **AnalysisRecord de production v2 retourné directement**, pas un résultat rechargé du cache |
| `summary.json` | v1 : état terminal, erreur technique typée, durées, RTF, compteurs de lots, disponibilité et SHA-256 du record |
| `cache/` | Cache d'analyse exclusif à cette tentative, même API que la production |

`attempt.json` est immuable : le résultat terminal est dans `summary.json`. Absence
de summary = interruption/état inconnu, **pas succès ni négatif**. Un échec avant
retour du pipeline ne produit pas un faux `AnalysisRecord`. Une panne disque peut
empêcher toute écriture terminale ; les fichiers incomplets ne sont pas réparés
automatiquement. L'évaluateur signale les incohérences au lieu de les corriger.

Le journal contient les images retenues par l'échantillonneur (horodatages et
origines periodic/scene/refinement), scores Marqo, flags conservateurs, fenêtres et
déclencheurs, plan et identités des lots Qwen, durée/état/type d'erreur/stop_reason,
compteurs structurés et suggestions finales sans justification textuelle.
`model_probability=null` pour un score de secours conservateur ; `decision_score=1`
n'est alors **pas** une probabilité prédite par Marqo. Les pics des fenêtres peuvent
eux aussi refléter ce secours : les interpréter avec les flags des scores.

Pas de pixels, planches-contact, audio brut ou vidéos dupliquées par les observateurs.
Le pipeline produit ses médias **temporaires habituels**, supprimés lors de sa sortie
normale ; un arrêt brutal peut laisser `cache/work`, à traiter comme sensible.
Les sorties VLM brutes/réparées et justifications sont supprimées des copies de
checkpoints. Le cache de record masque aussi les extraits et justifications.
**Le record retourné reste intégral, conformément à l'exigence de conservation** :
`record.json` peut donc contenir des extraits de texte et des raisons. Garder les
tentatives localement, hors Git/partage public, avec accès restreint. Ne publier
que les métriques et des exemples explicitement autorisés et anonymisés.

## Métriques et conventions

Deux évaluations distinctes sont produites :

- **Binaire** : toutes les suggestions, y compris `uncertain`, sont des alertes.
  La vérité terrain est l'union des événements cibles qui se chevauchent/se touchent,
  avant masquage ; aucun petit écart positif n'est fusionné artificiellement.
- **Par catégorie** : seuls les événements/suggestions de la catégorie sont retenus.
  Une fusion de production peut perdre une catégorie : ce score est complémentaire,
  pas le seul jugement du système.

Une exclusion est soustraite à la vérité et aux prédictions. Les morceaux restants
gardent **la même identité** pour l'appariement. Un élément totalement masqué est
ignoré et son ID est listé. La durée évaluée est la durée du clip moins l'union des
exclusions. Les scores temporels prennent l'union des segments, sans double comptage.

IoU temporelle = intersection / union des durées non exclues. Appariement un-à-un
avec seuil inclusif à 0,25 ; **0,50 primaire** ; 0,75. Le graphe biparti maximise
d'abord le nombre de couples, puis leur somme d'IoU. Les coûts rationnels, l'ordre
trié des IDs et l'ordre stable des arêtes rendent les égalités déterministes.
Ce choix est une convention d'évaluation, non un seuil de décision du modèle.

Chaque couple donne un TP. Toute suggestion non associée est FP ; tout événement
non associé est FN. Un doublon ou fragment supplémentaire peut donc être FP.
Une suggestion couvrant deux événements distincts ne compte qu'une fois comme TP.
Il n'existe **pas de TN événementiel** dans ce protocole.

- Précision = TP/(TP+FP), rappel = TP/(TP+FN), F1 = 2TP/(2TP+FP+FN).
- Couverture cible = durée cible couverte / durée cible.
- Précision temporelle = durée cible couverte / durée prédite.
- Durée manquée = durée cible moins durée couverte.
- Excès ordinaire = durée prédite moins durée couverte ; potentiel retrait excessif,
  **pas une mesure d'un export réellement réalisé**.
- Fausses alertes/min = FP / minutes évaluées, pour chaque seuil IoU. Un FP peut être
  un doublon ou une mauvaise localisation, pas nécessairement du contenu ordinaire.
- Même taux sur les clips sans cible dans la région évaluée, avec dénominateur
  limité à ces clips négatifs.
- Erreurs de bornes signées = prédiction moins vérité, uniquement sur les couples
  appariés. Biais et MAE agrégés ; borne touchant une exclusion = indisponible.
- Toute division par zéro donne `null` dans JSON, cellule vide dans CSV, jamais 100 %.

Les agrégats sont **micro** (sommes des comptes et durées), séparés tuning/test,
binaire/catégorie et `completed_only`/`all_available_records`. Les sorties partielles
ou annulées disponibles ne sont jamais présentées comme des exécutions complètes.
Les tentatives sans record/media utilisable ont une qualité indisponible et restent
dans le tableau de fiabilité. Publier ce tableau avec les performances pour éviter
de masquer les échecs techniques. Les clips non sélectionnés sont explicitement listés.

Temps pipeline = `perf_counter()` autour de `AnalysisPipeline.run()` ; il inclut
préflight, chargement des modèles, traitement texte/visuel et persistance de production.
Temps wall = tentative entière, incluant collecte de provenance/vérification SHA.
RTF = temps pipeline / durée vidéo ; débit = durée vidéo / temps pipeline.
Pour une tentative partielle, ce n'est **pas** un débit de traitement complet.

`invalid_responses` est une borne inférieure observée : les réponses réparées et
erreurs structurées sont visibles, mais certains timeouts ne permettent pas de
reconstruire l'étape interne de réparation sans modifier le fournisseur.
`unprocessed_batches` = lots planifiés jamais commencés ; `unfinished_batches` =
commencés sans terminaison observée. Plan indisponible = `null`, pas zéro. Les
agrégats précisent le nombre de tentatives observables/inconnues pour chaque compteur.

## Générer les tableaux hors ligne

Sélectionner explicitement **une tentative par clip** pour une configuration :

```powershell
.venv\Scripts\python.exe -m evaluation.pilot score artifacts/pilot/manifest.json --attempts 'artifacts/pilot/runs/ID_01' 'artifacts/pilot/runs/ID_02' 'artifacts/pilot/runs/ID_03' 'artifacts/pilot/runs/ID_04' 'artifacts/pilot/runs/ID_05' 'artifacts/pilot/runs/ID_06' --output artifacts/pilot/report_v1
```

Le dossier de sortie doit ne pas exister. Le score vérifie les digests du manifeste
et de configuration, l'identité du record et les paramètres. Les annotations doivent
avoir la même durée que les métadonnées du record à 1 microseconde près (tolérance
numérique, pas une tolérance de détection). Résoudre un désaccord plutôt que tronquer
silencieusement des prédictions. Un mélange de configurations/code/dépendances ou
matériel est refusé ; produire des rapports séparés pour comparer.

Sorties v1 : `metrics.json` contient les appariements/erreurs de bornes, métriques
par clip, agrégats, fiabilité et tentatives ; `clips.csv` et `aggregates.csv` sont
des tables longues, une ligne par clip/groupe et seuil IoU. Aucune justification
textuelle sensible n'est incluse. Tableaux/figures à préparer ensuite :

1. Composition du corpus et répartition par source, catégorie, split et durée.
2. TP/FP/FN/précision/rappel/F1 aux trois IoU, avec dénominateurs et fiabilité.
3. Couverture temporelle vs excès de retrait potentiel, par clip/configuration.
4. Distribution des erreurs de bornes et exemples d'échecs annotés.
5. Temps pipeline/RTF et nombre de frames/lots transmis à Qwen.

## Limites et suite

Les horodatages observés sont ceux exposés **après déduplication** par les services.
Ils ne prouvent pas le PTS réel de chaque image décodée, ni les décisions internes
d'une génération annulée. Un échantillonnage interrompu avant retour peut ne fournir
aucune liste. Ces inconnues sont à distinguer d'une scène réellement non échantillonnée.

Les empreintes du code, les révisions épinglées et les versions favorisent la
reproductibilité, sans garantir une exécution GPU bit-à-bit. Les versions des poids
sont celles demandées au fournisseur ; aucun audit cryptographique de chaque tenseur
local n'est effectué. Les informations matérielles indisponibles restent nulles.

Six clips vérifient la chaîne de mesure et révèlent des erreurs, pas la généralisation
du détecteur. Après le pilote : figer le guide d'annotation et les choix de métriques,
préparer environ 25–35 clips au total, comparer au plus deux/trois configurations sur
tuning, choisir une configuration, puis évaluer une fois le test indépendant par source.
Une comparaison de modes est multivariée ; une variation de porte Marqo ou de fréquence
à paramètres constants isole mieux une décision. Ne jamais recycler des résultats
historiques de préfiltre comme scores du pipeline complet.

La validation de revue humaine, découpage FFmpeg, durées exportées, codecs et
synchronisation audio/vidéo reste un protocole distinct, non couvert par ces tests.

Commande de tests synthétiques nouveaux :

```powershell
.venv\Scripts\python.exe -m pytest tests/test_pilot_evaluation.py -q
```
