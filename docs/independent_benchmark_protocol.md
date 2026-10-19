# Benchmark indépendant NSFW-Cutter — protocole (v1, proposé le 2026-10-19)

Statut : **proposition**. Aucune vidéo n'a été téléchargée et aucune inférence n'a été lancée. Le
pipeline gelé n'a pas été modifié. Ce document distingue partout les **faits vérifiés**, les
**estimations** et les **questions ouvertes**.

## 1. Version évaluée (gel expérimental)

- Commit `2399e950aeb33dd7925690c78d3f5f25d50d07cb`.
- Exécutable `f61826a17fa7643745653f8f1981a84dd2e4253567ae3d85b42e2534ea57ced0`.
- Zip `3a869298c212fa2b6acc84dc9d28f1040697a87e0dde5ba03800aa2f9c229aca`.
- Empreintes revérifiées le 2026-10-19.

Le manifeste complet se trouve dans `artifacts/experimental-freeze-2399e95/` (Python, versions,
révisions de modèles, réglages, matériel).

- **Code d'analyse.** `services/analysis`, `models` et `core` sont identiques octet pour octet au
  commit du pilote (`ca7a6732`).
- **Réglages.** Balanced ; porte Marqo 0,15 (forte : 0,45) ; échantillonnage 0,2 puis 1 image/s ;
  lots Qwen de 8 ; schéma de prompt 3 ; décodage glouton ; seuils de fusion 0,50 (visuel) et 0,35
  (texte).
- **Whisper en CUDA `float16`, comme l'exécutable validé.** Lancé depuis le code source, le runner
  doit appeler `evaluation.benchmark.media.enable_whisper_cuda12_cublas()` avant le premier calcul
  de Whisper, puis enregistrer les chemins des DLL chargées. Le préchargement vérifie les empreintes
  épinglées, puis charge `cublasLt64_12.dll` et `cublas64_12.dll` **dans le processus d'évaluation
  seulement**. Aucun module de production n'importe `evaluation/`, et l'exécutable embarque déjà
  son propre cuBLAS 12. *Ce préchargement n'a pas encore été vérifié par une inférence* : c'est la
  première vérification à faire (étape 10.2).
- **Pilote de 6 clips.** Ses données sont des données de **tuning**, sans valeur de test. Ses
  sources ne doivent jamais apparaître dans le benchmark.

## 2. Objectifs et hypothèses

- **Objectif.** Mesurer, sur des données indépendantes :
  - l'efficacité du pipeline complet (A2) ;
  - l'apport de Qwen par rapport à Marqo seul (A1 contre A0) ;
  - l'apport de la branche audio et texte (A2 contre A1) ;
  - le compromis entre exactitude et temps de calcul ;
  - les erreurs dominantes.
- **H1.** Sur des vidéos réelles présumées négatives, y compris difficiles, A2 produit moins
  d'alertes que A0 à τ = 0,15 : Qwen écarte des alertes de la porte Marqo. Les deux taux sont
  mesurés sur les mêmes vidéos. Une alerte écartée n'est « correcte » qu'après revue, et la
  spécificité n'est déclarée qu'après une vérification complète.
- **H2.** A2 − A1 : le rappel ne peut augmenter que sur les vidéos parlées **en anglais**, puisque
  le lexique est en anglais ; ailleurs, on attend A1 ≡ A2.
- **H3.** Les durées sont dominées par le chargement de Qwen, pas par Whisper sur GPU.
- **Critères pré-déclarés.**
  - Volet 1 : fausses alertes confirmées de A2, par vidéo (IC de Wilson à 95 %) et par heure, avec
    le taux d'alerte non vérifié publié à côté. La spécificité n'est rapportée qu'après une
    vérification complète.
  - Volet 2, s'il devient réalisable : F1 vidéo de A2, avec IC par bootstrap par source.
  - Comparaisons secondaires : McNemar exact avec correction de Holm, et ΔF1 ou Δ spécificité par
    bootstrap apparié.
  - **Aucune affirmation de significativité** en dehors de ces comparaisons pré-déclarées.

## 3. Jeux de données : recherche et décision

Critères imposés :

- téléchargement **sans approbation** ;
- droits explicites ;
- **vraies vidéos** ;
- étiquettes NSFW fiables ;
- âge et consentement sans ambiguïté.

Les faits ci-dessous viennent de la documentation officielle et des métadonnées, consultées le
2026-10-19. Aucun média n'a été ouvert.

| Jeu | Accès | Licence et preuve | Vidéos téléchargeables | Étiquettes | Âge et provenance | Verdict |
|---|---|---|---|---|---|---|
| **Charades v1** (AI2) | **Sans restriction**, URL S3 officielle ; HEAD 200 sur `Charades_v1_480.zip`, 16 339 546 533 octets | **Non commerciale**, « may also be used for evaluation purposes » ; aucune redistribution. Texte lu dans `license.txt` de `Charades.zip` (3 519 822 octets) | Oui, zip monolithique | **Actions** (157 classes, intervalles temporels), **aucune étiquette NSFW** | Acteurs recrutés en ligne qui se filment ; aucune déclaration de consentement explicite | **Adapté au volet 1** (faux positifs et coûts) ; inadapté au volet 2 |
| VHD11K (NYCU, NeurIPS 2024) | Sans restriction sur Hugging Face | CC BY-NC-SA 4.0 selon l'article, aucun champ de licence sur la carte | Oui, `harmful_videos_1000.zip` | 1 000 vidéos, moitié nocives ; 10 catégories dont « Explicit and Sexual Content » ; étiquettes par **débat entre GPT-4V** (vidéo : TPR 75,7 %, TNR 88,1 % contre des humains) | Moitié YouTube/Pexels (droits non établis), moitié générée ; la même archive contient « Child Endangerment » | **Non adapté** (étiquettes de modèles, archive à risque, sous-ensemble sexuel non chiffré) |
| SafeWatch-Bench (Virtue-AI) | `gated: manual` | apache-2.0 sur la carte ; recherche seulement | Environ 1 400 visibles après approbation ; le corpus « 2M+ » est fourni sous forme de **liens** | 6 catégories (C1 sexuel, C2 abus…), étiquettes multi-agents | Réel et généré | **Exclu** (approbation manuelle) |
| EchoRaven/safewatch-genai | Sans restriction | « MIT » déclaré par un **miroir** de SafeWatch, qui ne peut pas accorder ces droits | Oui, 2 040 fichiers | Catégories C1–C6, aucune définition, origine des étiquettes non indiquée | Mêmes risques que SafeWatch, dont C2 « Abuse » | **Non adapté** (droits non établis) |
| HateClipSeg (ACM MM 2025) | Accès restreint | Aucune licence pour les données | **Non** : identifiants YouTube/BitChute seulement | Segments (« Sexual » : 69 vidéos, 372 segments) | Non documentés | **Exclu** |
| MetaHarm (ICWSM 2025) | Zenodo **restreint** | Non indiquée | **Non** : métadonnées et images | Niveau vidéo, dont « Sexual » | Non documentés | **Exclu** |
| 110K Sensitive Video (PUC-Rio) | IEEE DataPort | Licence vide | **Non** : *embeddings* | Binaire, sensible ou non | — | **Exclu** |
| T2VSafetyBench | — | — | **Non** : invites texte | — | — | **Exclu** |
| VidHarm (LiU) | SharePoint, mot de passe publié | Aucune licence, « openly for research » | Oui | **Classes d'âge** (BT/7/11/15), pas NSFW | Bandes-annonces sous droit d'auteur | **Non adapté** |
| Wikimedia Commons | Sans restriction | Licence claire par fichier | Oui | Catégories communautaires, pas de vérité de référence | La politique « Sexual content » a été **rejetée** : âge et consentement ne sont pas vérifiés | **Non adapté pour le contenu sexuel** ; utilisable pour des négatifs |
| Pornography-2k, NPDI-800, LSPD | Accord signé ou demande | Recherche | Oui, après accord | 2k : annotations image par image ; NPDI : niveau vidéo | Web ; à vérifier dans les accords | **Hors contrainte** (autorisation nécessaire), mais seule voie crédible pour le volet 2 |

**Conclusion.** Aucun jeu **public, à licence explicite, téléchargeable sans approbation, avec de vraies
vidéos, des étiquettes NSFW fiables et un âge et un consentement établis** n'a été trouvé. Une
évaluation légitime de l'**exactitude NSFW sur 1 000 vidéos n'est donc pas réalisable** dans ces
contraintes. Ce n'est pas une preuve d'inexistence : la recherche est bornée.

## 4. Deux volets, jamais confondus

### Volet 1 — robustesse technique et faux positifs (Charades), réalisable

- **Population.** Charades v1, 9 848 vidéos, 267 sujets, environ 81 h (vérifié dans les CSV).
  L'**unité d'indépendance est le sujet**, puisqu'un même acteur filme plusieurs vidéos.
- **Échantillonnage.** `evaluation/benchmark/charades.py` trie de façon déterministe par
  `sha256(graine | identifiant)` et sépare deux strates à 50 % chacune :
  - « difficile » : chambre ou salle de bain, ou action liée aux vêtements, serviettes, lit,
    couverture, miroir, ou au fait de s'allonger ;
  - « ordinaire ».

  Un plafond limite le nombre de vidéos par sujet. Les manifestes générés, à partir des
  annotations seulement, se trouvent dans `artifacts/benchmark-design-20261019/` :

  | Effectif | Plafond par sujet | Sujets | Heures (durée annotée) | Difficiles | Chambre | Salle de bain |
  |---:|---:|---:|---:|---:|---:|---:|
  | 100 | 2 | 70 | 0,83 | 50 | 11 | 7 |
  | 200 | 2 | 125 | 1,64 | 100 | 30 | 11 |
  | 500 | 3 | 207 | 4,11 | 250 | 62 | 37 |
  | 1 000 | 7 | 220 | 8,26 | 500 | 116 | 62 |

  Ce qui a été mesuré : avec 50 % de difficiles, un plafond de 5 ne fournit que 318 vidéos
  ordinaires. **1 000 vidéos exigent un plafond de 7.**
- **Étiquettes.** Toutes valent `missing` (négatif *présumé*), avec `review_basis: unreviewed`,
  car Charades n'annote pas la nudité. **Un négatif non vérifié n'est jamais compté comme un vrai
  négatif.** Une vidéo ne reçoit une étiquette qu'après revue par le projet, et le manifeste
  enregistre la base de cette revue :
  - `alert_triggered` : **toutes** les vidéos alertées par A0, A1 ou A2 ;
  - `random_audit` : un échantillon aléatoire pré-déclaré d'au moins 10 % des autres.

  Toute vidéo réellement NSFW découverte est **exclue et comptée**, avec le motif
  `nsfw_discovered`, puisque le volet technique refuse les positifs. Elle est signalée dans le
  rapport.
- **Revue partielle, revue complète.** Revoir les alertes et un échantillon ne vérifie **pas** le jeu
  entier, et le sous-ensemble vérifié n'est pas aléatoire : les vidéos alertées y sont
  surreprésentées. Le scoreur **retient** donc spécificité, rappel, F1 et tests appariés tant que
  tous les éléments évaluables ne sont pas en `review_basis: complete`. Il ne publie que la revue
  des alertes (`alert_review`), qui sépare :
  - le **taux d'alerte non vérifié** sur toutes les vidéos analysées, qui n'est **pas** un taux de
    faux positifs ;
  - les **fausses alertes confirmées** : leur nombre, et leur taux par vidéo et par heure, publiés
    uniquement si toutes les alertes ont été revues ;
  - les vidéos positives trouvées par l'audit sans alerte.
- **Mesures.**
  - Taux d'alerte non vérifié de A0, A1 et A2, par strate.
  - Fausses alertes confirmées, par vidéo et par heure.
  - Typologie des faux positifs.
  - Temps de calcul, RTF, RAM et VRAM.
  - La spécificité n'est rapportée que si la vérification devient complète (voir ci-dessus).
- **Avertissement imposé par le code** (`scope_warning`) : un volet sans positif **n'est pas** une
  évaluation complète de l'exactitude NSFW. On n'y rapporte ni sensibilité ni F1.

### Volet 2 — exactitude de détection, bloqué dans les contraintes actuelles

Il exige des positifs et des négatifs annotés de façon indépendante. Trois voies, toutes soumises
à une décision qui dépasse ce document :

- **Accords Pornography-2k et NPDI-800.** Pornography-2k a des annotations temporelles, donc
  l'appariement d'événements à IoU 0,5 devient possible. Les e-mails sont déjà rédigés
  (`docs/independent_evaluation_access_20261017.md`).
- **Corpus construit par le projet.** Vidéos de stock sous licence, avec autorisations des modèles,
  et double annotation. L'achat est exclu à ce stade.
- **Pilote révisé.** Il reste du **tuning** et ne peut pas servir.

Sans l'une de ces voies, le rapport présentera le volet 1 et le pilote, explicitement étiqueté
« tuning », **sans aucun chiffre d'exactitude présenté comme indépendant**.

## 5. Critères d'éligibilité et d'exclusion

- **Inclusion :**
  - licence et usage vérifiés et consignés dans le manifeste (`dataset.license_evidence`) ;
  - média intact, avec SHA-256 calculé après le téléchargement autorisé ;
  - durée mesurée par ffprobe, pas reprise des CSV.
- **Exclusion, comptée et motivée** (`excluded` et `exclusion_reason`) :
  - média illisible, ou impossible à préparer en A1 (paquets vidéo modifiés) ;
  - tout doute sur l'âge en présence de nudité ou de contenu sexuel ;
  - contenu illicite ;
  - doublon (SHA-256 identique, refusé par le validateur).
- **Aucun remplacement** d'une vidéo exclue après avoir vu les prédictions.

## 6. Indépendance et prévention des fuites

- **Sources disjointes.** Aucune vidéo Charades ne figure dans le pilote. Un même groupe (sujet ou
  source) ne peut pas être à la fois en tuning et en test : le validateur le refuse.
  `python -m evaluation.benchmark validate MANIFEST --pilot-manifest artifacts/pilot/manifest.json`
  refuse aussi tout élément qui partage un SHA-256 ou une source avec le pilote. Il faut le relancer
  une fois les SHA-256 des médias renseignés.
- **Rien n'est ajusté sur le test.** Les seuils A0 (0,15 et 0,45), les règles de décision et les
  critères sont fixés ci-dessus, avant toute exécution.
- **Configuration gelée par empreinte.** `manifest_digest` est vérifié par le scoreur, et les
  résultats d'une autre version du manifeste sont refusés.
- **Biais de contrôle.** La revue des négatifs ne voit les prédictions que pour choisir *quoi*
  revoir (toutes les alertes, plus un échantillon). Ce biais est documenté.

## 7. Plan d'ablation A0 / A1 / A2

| Config | Entrée | Code | Décision vidéo (pré-enregistrée) | Niveau événement |
|---|---|---|---|---|
| A0 | Scores Marqo des images grossières de la **même** exécution A2 | Aucun calcul supplémentaire | Alerte si une probabilité Marqo est ≥ τ (τ = 0,15 et 0,45) ; scores de secours ignorés et comptés | **Non** : aucune conversion temporelle validée |
| A1 | Copie **vidéo seule** (`-map 0:v -c copy -copyts`) ; nombre de paquets, empreintes et PTS (±2 ms) **identiques** (`media.prepare_video_only_copy`) | Pipeline gelé ; sans audio, la branche texte est déclarée non applicable | Alerte si au moins une suggestion finale existe | Oui, si la vérité temporelle est exhaustive |
| A2 | Original | Pipeline gelé complet | Idem | Idem |

Limites de l'attribution des écarts :

- **A2 − A1 ne mesure que la branche texte.** Le texte ajoute des fenêtres examinées par Qwen et
  augmente la confiance ; il ne crée aucune suggestion.
- **A1 − A0 n'est pas l'effet de Qwen seul.** L'écart mélange Qwen, l'échantillonnage dense,
  le regroupement en fenêtres et la fusion. Le rapport ne doit pas l'attribuer à Qwen seul.
- **Stratification par langue.** L'apport du texte est stratifié par présence d'audio et par langue
  de la parole. Charades est majoritairement muet ou peu parlé : A1 ≈ A2 y est attendu.

## 8. Métriques

Elles sont implémentées dans `evaluation/benchmark` et testées sur données synthétiques.

- **Niveau vidéo** (seulement si la vérification est complète ; sinon, revue des alertes) :
  - matrice TP / FP / FN / TN ;
  - précision, rappel, spécificité, F1, exactitude équilibrée ;
  - IC de Wilson à 95 % pour les proportions.
  - Les étiquettes `uncertain` et `missing` ne sont **jamais** notées, mais sont comptées.
  - Les échecs sont exclus et comptés (politique `exclude`), ou comptés comme erreurs (politique
    `worst_case`). Les deux sont publiées.
- **Niveau événement** (seulement si la vérité temporelle est exhaustive) :
  - appariement un-à-un à IoU 0,25, **0,50** et 0,75, avec l'appariement du pilote ;
  - P, R et F1 ;
  - couverture, erreurs de bornes ;
  - **fausses alertes par heure**.
  - Masques par catégorie : une catégorie `unknown` n'est jamais notée.
  - Calcul **refusé** (`TemporalAnnotationsUnavailable`) pour un jeu qui n'a que des étiquettes
    vidéo.
- **Incertitude :**
  - bootstrap percentile **par groupe indépendant**, 5 000 rééchantillonnages, graine fixe ; les
    rééchantillonnages où la statistique n'est pas définie sont comptés ;
  - McNemar exact sur les paires discordantes ;
  - bootstrap apparié de ΔF1 et de Δ exactitude équilibrée ;
  - correction de Holm ;
  - effectifs rapportés par classe et par groupe.
- **Coûts :**
  - temps du pipeline, RTF global (somme des temps / somme des durées) ;
  - pics de RAM et de VRAM ;
  - démarrage à froid ou à chaud, et état du cache disque, séparés.

## 9. Coûts estimés

**Mesures existantes :**
- **Fenêtre de 40 s :** l'analyse prend 23,6 à 46,6 s en processus neuf.
- **Premier lot Qwen :** 29 s avec le cache disque froid, 8,8 s avec le cache chaud.
- **Lots suivants :** 0,63 à 0,69 s chacun.
- **Processus déjà chaud :** 17,5 s.
- **Sans fenêtre candidate :** 7,8 s au pilote (P06) ; Qwen n'est pas chargé.
- **Pics :** environ 9,9 Go de RAM et 4,1 à 5,1 Go de VRAM.

**Hypothèses :**
- vidéos Charades d'environ 30 s ;
- un processus par vidéo et par configuration ;
- A1 coûte à peu près autant que A2 ;
- 10 % de reprises ou d'exclusions ;
- **ce n'est pas une extrapolation linéaire validée.**

Le coût dépend d'abord du nombre de fenêtres candidates, inconnu sur Charades.

| Vidéos | Optimiste (≈ 30 s par paire A1+A2) | Attendue (≈ 55 s) | Prudente (≈ 100 s, cache disque froid) |
|---:|---:|---:|---:|
| 100 | 0,9 h | 1,7 h | 3,1 h |
| 200 | 1,8 h | 3,4 h | 6,1 h |
| 500 | 4,6 h | 8,4 h | 15,3 h |
| 1 000 | 9,2 h | 16,8 h | 30,6 h |

A0 ne coûte aucun calcul. Les durées mesurent l'occupation séquentielle de la RTX 3070 : un seul
run à la fois, à cause des 5,1 Go de VRAM et des 9,9 Go de RAM.

- **Stockage :** l'archive 480p de 16,3 Go est obligatoire, car il n'existe pas d'accès par fichier.
  Il faut y ajouter environ 1,7 Go pour 1 000 vidéos extraites, une estimation calculée à partir de
  la taille de l'archive (environ 1,66 Mo par vidéo), autant pour les copies A1, et moins de 1 Go
  de résultats. Prévoir **25 Go**.
- **Revue humaine (volet 1) :** environ 1 min par vidéo et par relecteur, pour toutes les alertes
  plus 10 % d'audit. Le taux d'alerte sur Charades est **inconnu**. Hypothèse de 10 à 20 % : 200 à
  300 revues, soit environ 4 à 5 h par relecteur.
- **Préparation :** vérification SHA-256, ffprobe et copie A1 en environ 1 à 3 s par vidéo
  (estimation).

## 10. Étapes avant d'autoriser le benchmark réel

1. Confirmer que le cadre du stage est **académique et non commercial**, condition de la licence
   Charades. Accepter le volet 1 comme seul volet réalisable sans autorisation.
2. Autoriser une **vérification d'inférence** d'une vidéo synthétique non sensible, dans un processus
   neuf. Elle doit prouver Whisper en CUDA `float16` via `enable_whisper_cuda12_cublas` : DLL
   chargées depuis `vendor/cuda12-cublas`, transcription correcte.
3. Autoriser le téléchargement de `Charades.zip` (annotations, déjà lues) et de
   `Charades_v1_480.zip` (16,3 Go). Le téléchargement est vérifié par le SHA-256 consigné, et seul
   le sous-ensemble du manifeste est extrait.
4. Écrire et tester un **runner** mince (code d'évaluation seulement). Il doit :
   - lancer un processus par vidéo et par configuration, avec un cache privé ;
   - échantillonner RAM et VRAM ;
   - produire le schéma `ResultsFile` ;
   - extraire les scores Marqo du journal.
5. Lancer d'abord le manifeste de 100 vidéos, vérifier les sorties, puis passer à 500 ou 1 000.
6. Faire la revue humaine des alertes et de l'audit, versionner les étiquettes, puis lancer
   `python -m evaluation.benchmark score`.
7. Pour le volet 2 : décision sur les demandes Pornography-2k et NPDI-800, hors contrainte
   « sans autorisation ».

## 11. Tableaux et figures pour le rapport de stage

1. Tableau de reproductibilité : commit, empreintes, révisions de modèles, matériel, mode de calcul
   de Whisper.
2. Tableau de sélection des jeux de données (section 3) et diagramme d'éligibilité : candidats,
   exclus, motifs.
3. Composition du volet 1 : strates, scènes, sujets, heures ; exclusions comptées.
4. Taux d'alerte A0 (0,15 et 0,45), A1 et A2 par strate, avec IC de Wilson (barres).
5. Graphique en forêt des comparaisons appariées (Δ spécificité, IC par bootstrap par sujet ;
   McNemar avec Holm).
6. Typologie des faux positifs (barres empilées par configuration).
7. Durées : boîtes à moustaches par configuration, barres empilées par étape, froid contre chaud ;
   RTF global.
8. Ressources : profil de RAM et VRAM d'une exécution type ; pics maximaux.
9. Encadré « pilote de tuning » (6 clips) séparé, avec ses limites.
10. Si le volet 2 devient possible : matrices de confusion, F1 vidéo et F1 événementiel à IoU 0,5
    avec IC.

## 12. Limites éthiques et juridiques

- **Charades, non commerciale :** pas de redistribution, publication limitée à de courts extraits.
  Les sujets doivent être traités avec respect.
- **Toute découverte de nudité** dans Charades est traitée comme sensible : revue minimale, pas de
  capture, exclusion si l'âge est douteux.
- **Médias, enregistrements et journaux :** stockage local à accès restreint, hors Git. Seuls les
  chiffres agrégés sont publiés.
- **Aucun chiffre d'exactitude NSFW** ne peut être revendiqué à partir du volet 1.
