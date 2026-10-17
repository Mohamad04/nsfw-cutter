# Contraintes d'indices Qwen — correction du 17 octobre 2026

Base Git : `6e64197de3df29b92c8eb67229e01af6b98f7867`. Arbre de travail
initialement propre ; correction locale non commitée. Aucun modèle téléchargé,
aucun poids chargé, aucune inférence réelle exécutée.

## Cause et modification

Dans lm-format-enforcer 0.11.3, les bornes numériques minimum/maximum ne
garantissent pas le filtrage des indices. Pydantic et le contrôle de taille du
lot rejettent correctement les indices invalides après génération. Le choix
sémantique de 16/19 par Qwen lors de P04 reste inexpliqué.

`_wire_schema_for_batch()` ajoute une énumération entière `1..len(batch.frames)`
à `first_frame`, `last_frame` et `evidence_frames.items`. Le même schéma est déjà
transmis à la génération initiale et à la réparation. Les validations existantes,
prompts, seuils, poids, échantillonnage, fusion et annotations restent inchangés.
Ni écrêtage, ni conversion implicite d'horodatages, ni suppression d'erreur.

Fichiers concernés :

- `services/analysis/providers/qwen.py` : trois énumérations dans le schéma.
- `services/analysis/contracts.py` : révision du contrat par défaut.
- `tests/test_analysis_structured_output.py` : lots 8/8/4, filtrage réel,
  conversion, réparation, validation et clés de cache.
- `tests/test_pilot_evaluation.py` : sortie invalide, résultat partiel,
  checkpoint échoué et confidentialité, avec services simulés.
- `docs/qwen_frame_index_constraints.md` : présent compte rendu.

## Versions et caches

`AnalysisSettings.prompt_schema_revision` passe de **2 à 3** par défaut.
Ce champ est inclus dans la clé d'analyse et dans les clés de checkpoints des
lots : les nouvelles exécutions utilisant le contrat 3 ne reprennent pas les
checkpoints du contrat 2. Les anciennes versions restent lisibles pour l'audit ;
ne pas forcer la révision historique dans les futures exécutions.

Les formats de stockage restent inchangés : `AnalysisRecord.schema_version=2`,
`AnalysisBatchCheckpoint.schema_version=1`, `settings_version=2` et
`make_batch_key.key_version=1`. Aucune migration des résultats historiques.

## Preuve avec le tokenizer installé

Tokenizer `Qwen2Tokenizer`, 151 665 tokens, snapshot local
`Qwen/Qwen2.5-VL-3B-Instruct` à la révision
`66285546d2b821cf421d4f5eb2576359d3770cd3`.

Chargement par `AutoTokenizer.from_pretrained` depuis un dossier local,
`local_files_only=True`, `trust_remote_code=False`. Aucun processeur visuel ni
modèle chargé. Le test utilise les fonctions de production
`_build_lmfe_tokenizer_data` et `_build_schema_prefix_allowed_tokens_fn`.
Chaque token d'un JSON synthétique est soumis au filtre, avec vérification
d'EOS et exclusion des tokens du prompt.

Pour les lots de 8, 8 et 4 images, tous les indices locaux valides ainsi que les
suggestions vides sont acceptés. Pour le lot de quatre images, 0, 5, 8, 16 et 19
sont rejetés dans chacun des trois champs. Les tests vérifient également le
schéma partagé par les deux passes et le maintien de l'erreur lorsque la sortie
simulée reste invalide après réparation. Le pipeline simulé conserve les preuves
valides, reste partiel et conserve un checkpoint d'échec sans sortie brute.

Les tests du tokenizer local sont explicitement activés par
`NSFW_CUTTER_TEST_QWEN_TOKENIZER`. Sans cette variable, ils sont signalés comme
ignorés ; aucune tentative de téléchargement n'est faite. Lors de cette
validation, ils ont tous été exécutés, sans test ignoré.

## Environnement et résultats

| Dépendance | Version |
|---|---|
| Python | 3.14.6 |
| lm-format-enforcer | 0.11.3 |
| transformers | 5.14.1 |
| tokenizers | 0.22.2 |
| pydantic | 2.12.5 |
| torch | 2.13.0+cu130 |
| huggingface-hub | 1.26.0 |
| pytest | 9.1.1 |

Commandes PowerShell utilisées, depuis la racine du dépôt :

```powershell
$env:NSFW_CUTTER_TEST_QWEN_TOKENIZER='C:/Users/user/AppData/Local/MohamadElHajj/NSFW Cutter/cache/models/models--Qwen--Qwen2.5-VL-3B-Instruct/snapshots/66285546d2b821cf421d4f5eb2576359d3770cd3'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$qwenTestTemp=Join-Path (Get-Location) ('artifacts/qwen-enum-tests-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $qwenTestTemp) { throw 'Test directory must be new' }
.venv/Scripts/python.exe -m pytest tests/test_analysis_structured_output.py tests/test_analysis_checkpoints.py tests/test_pilot_evaluation.py -q -p no:cacheprovider --basetemp $qwenTestTemp

$qwenTestTemp=Join-Path (Get-Location) ('artifacts/qwen-enum-consumers-' + [guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $qwenTestTemp) { throw 'Test directory must be new' }
.venv/Scripts/python.exe -m pytest tests/test_analysis_contracts.py tests/test_analysis_cache.py tests/test_analysis_qwen_provider.py tests/test_analysis_pipeline.py -q -p no:cacheprovider --basetemp $qwenTestTemp
```

- Première commande : **106 tests et 3 sous-tests réussis**, 8,94 s.
- Seconde commande : **29 tests et 28 sous-tests réussis**, 0,72 s.
- Total : **135 tests et 31 sous-tests réussis**, aucun test ignoré.
- Avertissement préexistant : compatibilité Pydantic V1/LangChain avec Python 3.14.
- `git diff --check` : aucune erreur d'espacement ; Git avertit de la
  normalisation LF/CRLF sur Windows.

Une première vérification du fichier de tests structurés seul avait réussi
(47 tests, avant ajout des tests de réparation), avec avertissement d'accès au
cache pytest. Une première exécution des trois suites ciblées avait ensuite
obtenu 88 tests réussis et 18 erreurs de préparation dues au refus d'accès à
`Temp/pytest-of-user`. La relance avec un dossier temporaire neuf dans le
workspace et le cache pytest désactivé a résolu ce problème d'environnement.

## Intégrité et limites

Les SHA-256 des **92 fichiers** présents sous `artifacts/pilot` avant les
modifications sont identiques après les tests. Aucun fichier ajouté ou supprimé
dans ce dossier. P01–P04, y compris leurs caches, restent inchangés ; P05/P06
n'ont pas été exécutés.

L'énumération protège le domaine des indices ; elle ne garantit ni la justesse
de la catégorie ni la localisation sémantique. Les contraintes relationnelles
restent vérifiées après génération. La restriction des tokens disponibles peut
changer la sortie du modèle : une nouvelle inférence doit être identifiée par
la nouvelle révision et ne doit pas être présentée comme strictement identique
aux expériences du contrat 2.

Après autorisation séparée : figer la révision du correctif, revérifier le
manifeste et les entrées, puis exécuter P04 entier avec un nouvel identifiant,
un cache isolé et `force_reanalysis=true`, sans reprise de checkpoints.
Conserver l'ancienne tentative partielle et maintenir l'incertitude humaine sur
`sexual_activity`. Aucune inférence n'est autorisée par le présent changement.
