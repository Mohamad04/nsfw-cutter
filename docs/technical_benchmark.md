# Benchmark technique indépendant UCF101

Implémentation du 18 octobre 2026. Aucun téléchargement ni aucune inférence réelle effectués.

Validation finale : 88 tests réussis (suite technique + suite pilote), en 5,27 secondes.
La commande validate accepte les 25 clips sans ouvrir les médias ni importer le runtime AI.
Le premier essai pytest avait échoué sur les permissions du dossier TEMP Windows ; les essais
suivants ont utilisé des répertoires temporaires neufs dans artifacts, sans modifier les artefacts du pilote.
La comparaison Git au baseline est vide pour services, core, models, controllers/app, workers et evaluation/pilot.
Les nouveaux fichiers ne sont pas commités ; aucun commit n'était demandé.

## Contrat et périmètre

Le module `evaluation.technical` réutilise l'AnalysisPipeline, le Journal, les observateurs,
le cache privé et l'environnement hors ligne du pilote. Aucun import du calculateur de métriques
annotées. Toutes les catégories NSFW restent inconnues ; aucune annotation négative n'est créée.

La proposition de 25 clips est une liste fermée : son empreinte JSON canonique est
`ff2e84d512bbf095a566ec4187ab7bde2bce0809deae1c6c65ad2565e9dd7b23`.
La validation refuse toute modification, même une modification de métadonnées : une nouvelle
sélection exige une nouvelle version revue du contrat. Les métadonnées résolues sont stockées
dans un autre fichier `prepared.json`, jamais dans la proposition.

`frozen_config.json` copie les réglages effectifs, sans chemins privés ni bloc origin, du fichier
`artifacts/pilot/runs/20261017T185141_5439969c12d04ac98b6d764f5a4f79f9/config.json`.
Empreinte canonique : `3348307d7491fc3406b8bac5aa3cb34fab7434fa316ce71d04d02d84bf85c5db`.
Balanced, batch 8, seuil visuel 0.50, schéma Qwen 3. Les trois révisions de modèles sont conservées.
L'inférence vérifie aussi l'identité du code des services, modèles, core, contrôleur, workers et
infrastructure pilote contre `ca7a6732aa0d4e153b06dada6d54c076a929db27`. Un nouveau commit
contenant uniquement le benchmark est possible : le baseline du détecteur et le HEAD sont distinctement enregistrés.

## Autorisation et conditions d'usage

Un HTTP 200 ne constitue pas une licence. Les conditions UCF101 ne sont pas encore validées.
Aucun fichier d'autorisation utilisable n'a été créé. Après examen réel des conditions, l'utilisateur
fournira un JSON avec exactement ces clés : `dataset` (UCF101), `reviewed_by`, `reviewed_at`,
`terms_source`, `permitted_operations` (liste parmi download, prepare, inference).
Les chaînes doivent être non vides et référencer une vraie validation, pas cet exemple.
Le fichier est une attestation de l'utilisateur, pas une vérification juridique automatique.
Les autorisations CLI sont en outre séparées : aucune opération n'autorise implicitement la suivante.

## Commandes

Depuis la racine du dépôt, PowerShell. Les commandes futures comportent des chemins à remplacer.

Validation sans média et sans modèle :

```powershell
.venv\Scripts\python.exe -m evaluation.technical validate evaluation/proposals/ucf101_technical25.v1.json
.venv\Scripts\python.exe -m evaluation.technical --help
```

Tests synthétiques (répertoire neuf pour éviter les permissions du TEMP Windows) :

```powershell
$testTemp = Join-Path (Get-Location) ('artifacts/technical-tests-' + [guid]::NewGuid().ToString('N'))
.venv\Scripts\python.exe -m pytest tests/test_technical_benchmark.py tests/test_pilot_evaluation.py -q -p no:cacheprovider --basetemp $testTemp
```

Téléchargement futur, uniquement après autorisation et validation d'usage :

```powershell
.venv\Scripts\python.exe -m evaluation.technical download evaluation/proposals/ucf101_technical25.v1.json --output artifacts/technical/downloads --usage-clearance CHEMIN/clearance.json --allow-download
```

Le téléchargement écrit dans un dossier horodaté unique, conserve les fichiers incomplets et refuse
les redirections inattendues ou tailles différentes de celles annoncées. Le reçu SHA-256 final n'est
publié qu'après succès complet. Les sommes calculées ne sont pas des empreintes officielles du fournisseur.

Préparation de vidéos déjà présentes localement, après autorisation :

```powershell
.venv\Scripts\python.exe -m evaluation.technical prepare evaluation/proposals/ucf101_technical25.v1.json --media-root CHEMIN/DOSSIER_DES_AVI --output artifacts/technical/preparations --usage-clearance CHEMIN/clearance.json --allow-prepare
```

Chaque AVI garde son nom officiel. Le reçu de téléchargement, s'il existe, est vérifié.
FFmpeg utilise `-map 0 -c copy -copyts -n` pour le MKV : aucun réencodage ou écrasement.
FFprobe contrôle conteneur, codecs, streams, nombre et empreintes des paquets, timestamps
(tolérance 2 ms) et durée (50 ms). Cette politique est conservatrice : si les codecs ou les
transformations de paquets du muxeur ne permettent pas ce contrôle, la préparation s'arrête,
conserve les fichiers et ne contourne pas la validation. Aucun test réel de remux n'a été exécuté.
Originaux, dérivés, versions FFmpeg/FFprobe et métadonnées sont documentés séparément.

Inférence future, après une autorisation distincte :

```powershell
.venv\Scripts\python.exe -m evaluation.technical run evaluation/proposals/ucf101_technical25.v1.json --prepared CHEMIN/PREPARATION/prepared.json --campaign artifacts/technical/campaign-001 --usage-clearance CHEMIN/clearance.json --allow-inference
```

La même commande reprend les clips non commencés, ignore ceux terminés et vérifie les identités.
Une tentative partielle, échouée, annulée ou interrompue exige en plus `--retry-incomplete`,
uniquement après décision explicite. Une nouvelle tentative et un nouveau cache sont alors créés ;
aucun checkpoint précédent n'est réutilisé. Arrêt de la campagne dès le premier résultat non completed.
Un verrou système interdit deux processus concurrents sur la même campagne et est libéré si le processus meurt.
Une tentative sans identité exploitable reste conservée et demande une inspection manuelle.

Rapport hors ligne, vers un fichier inexistant :

```powershell
.venv\Scripts\python.exe -m evaluation.technical report evaluation/proposals/ucf101_technical25.v1.json --campaign artifacts/technical/campaign-001 --output artifacts/technical/report-001.json
```

## Résultats et confidentialité

Chaque tentative conserve config, environnement, identité média, journal JSONL, cache privé,
AnalysisRecord retourné et résumé. Les données privées restent locales : le record peut contenir
des textes/reasons issus du pipeline et doit bénéficier du même contrôle d'accès que les médias.
Le cache réutilise les garanties de rédaction du pilote. Aucune image ni sortie brute de modèle
n'est affichée par le lanceur ; les exceptions inattendues n'exposent que leur type.

Le taux de succès principal est completed / 25 ; completed / attempted est distinct. Les durées
et fréquences d'alertes agrégées utilisent les derniers résultats completed uniquement.
RTF global = somme des temps pipeline / somme des durées vidéo, pas moyenne des RTF individuels.
Les intervalles superposés sont fusionnés pour la fraction de durée alertée. Les temps connus de
toutes les tentatives sont aussi rapportés ; le temps perdu lors d'une interruption brutale reste inconnu.
Les sorties partielles, avertissements, erreurs, candidats et compteurs Qwen sont disponibles par tentative.
Les compteurs non observables restent null avec un nombre de clips inconnus, pas un zéro supposé.
La précision, le rappel, F1, TP, FP, FN et la couverture de cible ne sont jamais calculés.

## Budget et limites

25 originaux : 12 065 722 octets annoncés. Réserver initialement 1 Go hors modèles pour originaux,
MKV, métadonnées paquets et caches. Prévision d'inférence : 10–30 minutes, non garantie ; mettre
à jour après le probe réel, notamment pour les pistes audio et Whisper. Résolution UCF101 peu
variée ; durées exactes inconnues ; aucune prétention de précision NSFW ou d'indépendance du préentraînement.

Prochaine étape opérationnelle : obtenir une vraie validation des conditions de réutilisation,
puis une autorisation explicite de télécharger les 25 fichiers. La préparation vient ensuite,
puis une nouvelle autorisation d'inférence. Ne pas lancer les commandes futures avec un faux accord.
