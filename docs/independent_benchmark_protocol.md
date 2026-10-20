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
  son propre cuBLAS 12.
  - **Diagnostic du 2026-10-20 (processus neuf, depuis le code source) :**
    - cuBLAS 12 est chargé depuis `vendor\cuda12-cublas`, cuBLAS 13 depuis `torch\lib` ;
    - torch tourne sur CUDA dans le même processus ;
    - Whisper tourne en `cuda` / `float16` : chargement 2,2 s, transcription 0,81 s ;
    - les **3 segments sont identiques à l'exécutable validé**, bornes comprises
      (0–3,4 / 3,4–10,0 / 10,0–11,8 s) ;
    - VRAM de 1 246 à 2 101 Mio, RAM du processus 1,48 Go.

    Preuves : `artifacts/benchmark-runner-20261020/whisper-diag/`.
  - **Différence avec l'exécutable.** Dans le `.venv`, CTranslate2 charge aussi sa cale
    `cudnn64_9.dll`, absente de l'exécutable. Elle porte le même nom que le cuDNN 9.20 de PyTorch.
    Le worker initialise donc CUDA dans torch **avant** CTranslate2, et enregistre les chemins de
    cuDNN et de cuBLAS réellement chargés (`loaded_runtime_libraries`).
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
- **Contrôle anti-fuite obligatoire.** `validate` et `score` exigent `--pilot-manifest`
  (`artifacts/pilot/manifest.json` pour les 6 clips du pilote). Sans ce manifeste, la commande
  s'arrête. La fonction `score()` exige elle aussi `pilot_manifest` : on ne peut pas noter sans ce
  contrôle.
  - **Ce qui est refusé :** tout élément qui partage un SHA-256 avec un clip du pilote, ou dont le
    `group_id` est un `source_video_id` du pilote.
  - **Identité des médias :** la notation exige le SHA-256 de chaque vidéo évaluée, donc le contrôle
    est forcément refait après le téléchargement.
  - **Limite :** une copie recodée ou découpée d'une source du pilote n'est pas détectable par
    empreinte ; l'indépendance repose alors sur la provenance documentée.
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

- **Niveau vidéo** (seulement si la vérification est complète ; sinon, revue des alertes, voir 8 bis) :
  - matrice TP / FP / FN / TN ;
  - précision, rappel, spécificité, F1, exactitude équilibrée ;
  - IC de Wilson à 95 % pour les proportions, chacune avec son dénominateur explicite.
    `false_positive_rate_on_verified_negatives_ci` a pour dénominateur les négatifs de référence
    (TN + FP) d'un jeu **entièrement** vérifié. Ce taux n'existe pas sous une vérification
    partielle.
  - Les étiquettes `uncertain` et `missing` ne sont **jamais** notées, mais sont comptées.
  - Les échecs sont exclus et comptés (politique `exclude`), ou comptés comme erreurs (politique
    `worst_case`). Les deux sont publiées.
- **Niveau événement** (seulement si la vérité temporelle est exhaustive **et** la vérification
  complète ; la part des vidéos évaluables réellement notées est publiée) :
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

## 8 bis. Vérification des étiquettes et interprétation statistique

**Provenance de la revue.** Chaque vidéo porte `review_basis` :

| Valeur | Sens | Étiquette permise |
|---|---|---|
| `unreviewed` | Aucune référence | `missing` uniquement |
| `complete` | Annotation qui couvre **toutes** les vidéos évaluables du split | positive, negative, uncertain |
| `alert_triggered` | Revue parce qu'au moins une configuration a alerté | idem |
| `random_audit` | Revue dans l'échantillon aléatoire pré-déclaré des vidéos non alertées | idem |

Les autres éléments de provenance sont consignés dans `provenance` : relecteurs, date, version du
guide, accord entre relecteurs. Une étiquette `missing` n'est **jamais** traitée comme un négatif.

**Revue complète ou partielle.**
- **Vérification complète** (tous les éléments évaluables en `complete`) : métriques de
  classification, tests appariés et métriques événementielles sont publiés.
- **Dans tous les autres cas, ils sont retenus** (`withheld`). Le sous-ensemble vérifié contient
  toutes les alertes, mais seulement un échantillon des non-alertes. Ce n'est pas un échantillon
  aléatoire de la population : une spécificité ou un taux de faux positifs calculés dessus sans
  pondération seraient biaisés, pessimistes. On ne publie alors que la revue des alertes
  (`alert_review`) :
  - **taux d'alerte non vérifié** : vidéos alertées sur **toutes** les vidéos analysées (runs
    terminés). Ce n'est **pas** un taux de faux positifs ;
  - **fausses alertes confirmées** : un nombre, ventilé par étiquette de référence ;
  - **fausses alertes confirmées par vidéo analysée et par heure analysée** : publiées
    **uniquement** si toutes les alertes ont été revues. C'est alors un décompte exact rapporté à
    toutes les vidéos analysées, pas une spécificité ;
  - **constats de l'audit** : étiquettes et positifs non alertés trouvés dans l'échantillon audité,
    décrits pour cet échantillon seulement.
- **Estimation à l'échelle de la population.** Toute estimation de spécificité ou de taux de faux
  positifs à partir de l'audit exigerait un estimateur pondéré par le plan de sondage, justifié et
  pré-enregistré séparément. Il n'est pas implémenté.

**Protocole d'audit des vidéos non alertées.**
1. Après les exécutions A0, A1 et A2, définir la population des vidéos **non alertées par aucune
   configuration**.
2. Tirer de façon déterministe, avec une graine déclarée avant la revue, au moins 10 % de cette
   population, et au minimum 30 vidéos si possible.
3. Faire revoir l'échantillon par un relecteur, sans connaître la strate.
4. Rapporter les constats tels quels.

Toute vidéo retirée de l'échantillon est comptée.

**Contenu NSFW découvert dans le volet technique.** Une vidéo réellement NSFW trouvée pendant la
revue prend l'étiquette `positive`. Elle est **exclue** (`excluded: true`,
`exclusion_reason: nsfw_discovered`) ; le validateur refuse tout positif non exclu dans ce volet. Le
rapport publie `excluded_by_reason` et `excluded_reference_positives` : la découverte reste
visible, mais la vidéo ne compte ni comme vrai positif ni comme faux positif.

**Limites de Charades comme jeu d'évaluation NSFW.**
- Ce n'est pas un jeu NSFW : aucune étiquette de nudité ou de contenu sexuel, aucun positif de
  référence.
- On ne peut donc pas en tirer de rappel, de F1 ni d'exactitude NSFW. Seuls comptent les faux
  positifs, les coûts et la robustesse.
- Le contenu est du quotidien en intérieur, filmé par des participants recrutés en ligne, d'environ
  30 s, à 480p : la généralisation à des films ou à des contenus professionnels n'est pas
  démontrée.
- Il y a peu de parole, si bien que A1 ≈ A2 est attendu et que l'apport du texte y est presque
  invisible.
- La licence est non commerciale (section 12).

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
2. ~~Vérifier Whisper en CUDA `float16` depuis le code source~~ : **fait le 2026-10-20** (section 1).
3. Autoriser le téléchargement de `Charades.zip` (annotations, déjà lues) et de
   `Charades_v1_480.zip` (16,3 Go). Le téléchargement est vérifié par le SHA-256 consigné, et seul
   le sous-ensemble du manifeste est extrait.
4. ~~Écrire et tester le runner~~ : **implémenté et testé** sur données synthétiques avec un pipeline
   simulé (section 10 bis). Il n'a encore jamais été exécuté avec les vrais modèles.
5. Lancer d'abord le manifeste de 100 vidéos, vérifier les sorties, puis passer à 500 ou 1 000
   (critères en section 10 ter).
6. Faire la revue humaine des alertes et de l'audit, versionner les étiquettes (avec
   `review_basis`), puis lancer
   `python -m evaluation.benchmark score MANIFEST RESULTS --pilot-manifest artifacts/pilot/manifest.json --output DOSSIER_NEUF`.
7. Pour le volet 2 : décision sur les demandes Pornography-2k et NPDI-800, hors contrainte
   « sans autorisation ».

## 10 bis. Runner de campagne (`evaluation/benchmark/runner.py`, `worker.py`)

```powershell
# Inférence (autorisation explicite requise), séquentielle, reprenable :
.venv\Scripts\python.exe -m evaluation.benchmark run MANIFEST --media-root DOSSIER_MEDIAS --campaign artifacts\benchmark\campagne-001 --pilot-manifest artifacts\pilot\manifest.json --allow-inference
# Après examen d'un échec ou d'une annulation :
... run ... --retry-incomplete
# Construction d'un ResultsFile validé (nouveau fichier, jamais écrasé) :
.venv\Scripts\python.exe -m evaluation.benchmark collect MANIFEST --campaign artifacts\benchmark\campagne-001 --pilot-manifest artifacts\pilot\manifest.json --output artifacts\benchmark\campagne-001-results.json
```

- **Une vidéo source à la fois, en ordre fixe.** Le manifeste fixe l'ordre. Pour chaque vidéo :
  1. vérification du SHA-256 ;
  2. préparation de la copie **vidéo seule** vérifiée pour A1 (`inputs/`) ;
  3. exécution de A2 et de A1, **chacune dans un processus neuf** (`cold_process`), dans un ordre
     alterné d'une vidéo à l'autre.

  A0 est déduit après coup des scores Marqo enregistrés par A2.
- **Isolement.** Chaque tentative a son dossier exclusif (`attempts/<UTC>_<item>_<config>_<uuid>/`),
  son cache d'analyse privé et `force_reanalysis`. Le pipeline de production est **inchangé** : les
  observateurs du pilote lui sont seulement ajoutés.
- **Verrou et identité de campagne.** Un verrou système empêche deux exécutions concurrentes.
  `campaign.json` fixe le manifeste, le pilote, la configuration gelée (`3348307d…`), la référence
  `2399e950`, les révisions de modèles, l'empreinte du code d'analyse et des dépendances, les
  limites et le préchargement. Tout changement impose une nouvelle campagne.
- **Contrôle d'identité avant toute exécution.** `services/analysis`, `models` et `core` doivent être
  identiques à `2399e950`, sans fichier non suivi. Les réglages doivent correspondre à
  l'empreinte gelée.
- **Écritures atomiques.** Fichier temporaire, `fsync`, puis renommage, sans jamais écraser un
  fichier existant.
- **Reprise.** Une tentative terminée n'est jamais refaite. Un échec ou une annulation impose une
  reprise **explicite** (`--retry-incomplete`), et l'historique des tentatives est conservé. La
  campagne s'arrête au premier résultat non terminé.
- **Statuts explicites.** `completed`, `partial`, `failed`, `cancelled`, plus `not_run` à la
  collecte. Erreurs typées :
  - `input_sha256_mismatch` ;
  - `whisper_cpu_fallback` ou `whisper_unavailable` (pour A2) ;
  - `a1_text_branch_ran` ;
  - `resource_limit:*`, `timeout` ou `interrupted_by_user` (raison du parent) ;
  - `|killed_after_grace` en suffixe.

  Une sortie sans résumé compte comme un échec.
- **GPU ou repli CPU.** Le worker classe le mode de calcul de Whisper d'après les avertissements de
  production. Un repli sur CPU **fait échouer** A2, et `collect` refuse tout A2 terminé sans
  `cuda_float16`. Les DLL CUDA et cuDNN chargées sont enregistrées.
- **Mesures :**
  - durée de chaque étape d'après les événements de progression, temps du pipeline et temps total ;
  - surveillance chaque seconde par le parent : RAM et CPU de l'arbre de processus du worker,
    mémoire disponible, mémoire virtuelle libre, VRAM et utilisation du GPU (`monitor.jsonl`, pics
    dans `monitor_summary.json`). Le CPU suit la convention psutil : 100 = un cœur logique occupé ;
    la première mesure de chaque processus est exclue, et les pics et moyennes sont publiés avec le
    nombre de cœurs logiques.
  - les processus suivis sont identifiés par leur PID **et** leur date de création, car Windows
    réutilise les PID. Avant cette correction, un objet périmé gardé en cache pour un PID réattribué
    à un nouveau worker faisait échouer toutes les mesures de cette tentative : la campagne
    `charades-track1-100-20261020` n'a aucune mesure RAM/CPU de l'arbre pour 22 tentatives sur 200.
    Ces trous restent signalés comme manquants. Chaque échantillon non mesuré porte désormais sa
    cause (`process_tree_error`), et `monitor_summary.json` les compte
    (`process_tree_monitoring`). Aucune valeur n'est estimée. Les limites de ressources reposent
    toujours sur la mémoire système, la mémoire virtuelle et la VRAM, et leur calcul est inchangé.
- **Entrées canoniques.** Le chemin de chaque entrée est enregistré en absolu, quel que soit le
  dossier de lancement. Un ancien enregistrement à chemin relatif est résolu à côté de son fichier
  d'identité, sans être réécrit.
- **Sonde Whisper (évaluation seulement, A2 seulement).** Dans le processus worker A2, une
  sous-classe de `faster_whisper.WhisperModel` appelle exactement le même constructeur et la même
  `transcribe()`. Elle enregistre :
  - le périphérique et le type de calcul ;
  - les durées de chargement et de transcription ;
  - le nombre de segments ;
  - la langue détectée.

  Elle ne lit jamais le texte, l'audio ni le contenu de la parole. Sans segment, la langue
  détectée n'est pas une observation de langue parlée : elle est rangée dans
  `detected_language_without_speech` (`language_basis: no_speech_segments_unreliable`), et
  `language` reste vide. Une transcription observée hors CUDA, ou un chargement CUDA autre que
  `float16`, fait échouer A2 même sans avertissement de production. A1 n'a pas de piste audio : la
  sonde n'y est pas installée, et `faster_whisper` et CTranslate2 n'y sont pas importés
  (`python_modules_imported` dans `summary.json`). Le préchargement de cuBLAS 12 est inchangé.
- **Sous-ensemble de sensibilité (`score --subset SPEC.json`).** Le fichier de spécification donne
  `subset_id`, `reason`, `exclude_item_ids` et, en option, `selection_rule` (`provenance_flag` et
  `scope`). Avec cette règle, la liste doit correspondre **exactement** :
  - avec `scope: item` (par défaut), aux vidéos évaluables portant ce marqueur de provenance ;
  - avec `scope: subject`, à **toutes** les vidéos des sujets qui ont au moins une vidéo marquée.
    Le sous-ensemble obtenu est disjoint par sujet.
 Le manifeste et les résultats de la campagne ne sont pas modifiés, et le rapport garde
  l'empreinte du manifeste complet. Le bloc `subset` enregistre :
  - les vidéos et sujets exclus et ceux qui restent ;
  - les sujets partagés avec des vidéos exclues ;
  - l'empreinte du manifeste dérivé et le SHA-256 de la spécification.

  Une vidéo exclue retire ses deux configurations, si bien qu'une paire A1/A2 n'est jamais coupée.
- **Incertitude groupée et accord sans étiquette (`score`).** `alert_uncertainty` ajoute à
  l'intervalle de Wilson simple un bootstrap groupé par sujet du taux d'alerte.
  `paired_alert_agreement` compte, vidéo par vidéo, les alertes communes, propres à chaque
  configuration ou absentes, avec un bootstrap groupé de la différence de taux d'alerte. Ces blocs
  n'utilisent aucune étiquette : un accord n'est pas une exactitude, et ces chiffres ne sont ni une
  spécificité ni un taux de faux positifs. Chaque intervalle groupé indique combien de sujets portent
  le signal (`informative_groups`), ainsi que la probabilité qu'un rééchantillonnage n'en contienne
  aucun. Le traitement dépend de ce nombre :
  - **moins de 5 sujets** : l'intervalle reçoit une mise en garde (`caution`) ;
  - **aucun sujet** (aucune alerte, toutes les vidéos alertées, ou aucune paire discordante) :
    l'intervalle, de largeur nulle, est retenu (`interval_withheld`). Il suggérerait une précision
    que les données ne donnent pas.
- **Limites par défaut :** mémoire disponible au moins 2,5 Go ; mémoire virtuelle libre au moins
  1,5 Go ; VRAM sous 7 900 Mio, une alerte n'étant déclenchée qu'après 5 échantillons consécutifs ;
  300 s par tentative. En cas de dépassement : annulation coopérative, puis arrêt forcé après 60 s.
- **Froid et chaud.** Toutes les tentatives démarrent avec des modèles froids (`cold_process`). Le
  cache disque de l'OS n'est pas contrôlé (`os_file_cache: unknown`). Une mesure à processus chaud
  devrait former une campagne distincte, jamais mélangée à celle-ci.
- **Limites des tests.** Le runner a été testé avec un pipeline simulé, de vraies vidéos synthétiques
  et un vrai sous-processus worker (qui refuse une entrée). Il a ensuite tourné avec les vrais
  modèles sur une vidéo Charades (`smoke1`), puis sur cinq (`pilot5`, 2026-10-20 : 10 tentatives
  terminées, Whisper confirmé en CUDA `float16`). Le correctif qui limite la sonde à A2 n'a été
  validé que par des tests synthétiques. Les étiquettes de ces vidéos restent `missing` tant
  qu'aucune revue humaine n'a eu lieu.

## 10 ter. Plan du premier pilote technique Charades (100 vidéos)

- **Licence.** « Non-Commercial Use » : chercheurs académiques, à but non lucratif ou
  gouvernementaux, ou « evaluation purposes » ; ni redistribution ni publication des données, sauf
  de courts extraits si nécessaire. Le cadre du stage doit être **confirmé par écrit** avant le
  téléchargement.
- **Disponibilité (métadonnées seulement).** Requête HEAD du 2026-10-19 : `Charades_v1_480.zip`,
  16 339 546 533 octets, Last-Modified 2021-02-04. L'archive d'annotations a pour SHA-256
  `c616913e…`. La source ne publie aucune empreinte pour l'archive vidéo : il faudra calculer et
  consigner son SHA-256 au premier téléchargement.
- **Stockage.** Environ 17 Go : l'archive entière (16,3 Go), environ 170 Mo de vidéos extraites,
  autant de copies A1, et moins de 1 Go de résultats. L'archive peut être supprimée après
  extraction, une fois son SHA-256 consigné.
- **Manifeste.** `charades_track1_100` (70 sujets, 50 difficiles et 50 ordinaires), groupé par
  sujet. Après extraction : SHA-256 et durées ffprobe, nouvelle version du manifeste, puis
  `validate --pilot-manifest`.
- **Audio, parole et langue.**
  - Présence d'audio : ffprobe.
  - Parole et langue : transcription Whisper de A2 (langue et probabilité dans l'enregistrement).
  - Ces mesures sont rapportées comme **caractéristiques du jeu**, sans jamais servir à choisir les
    vidéos après coup.
- **Arrêt anticipé de la comparaison A1/A2.** Si moins de 10 vidéos sur 100 contiennent une parole
  en anglais détectée, la comparaison A2 − A1 est déclarée **non informative** sur Charades. On
  rapporte alors seulement A0 contre A2. Ce seuil est pré-déclaré ici.
- **Revue humaine.**
  - Toutes les vidéos alertées par l'une des configurations (A0 à 0,15 ou 0,45, A1, A2) sont revues
    par deux relecteurs, avec arbitrage ; leur accord est consigné.
  - Un audit aléatoire porte sur au moins 10 % des autres vidéos, au minimum 30 si possible, avec
    une graine déclarée à l'avance.
  - Aucune capture d'écran.
  - Une vidéo NSFW découverte est exclue (`nsfw_discovered`) et comptée.
  - Aucune vidéo non revue n'est traitée comme un négatif vérifié.
- **Budget.**
  - Environ 0,9 h de temps GPU en hypothèse optimiste, 1,7 h attendue, 3,1 h prudente.
  - Pics d'environ 9,9 Go de RAM et 5,1 Go de VRAM, une exécution à la fois.
  - Commencer par les 5 premières vidéos, relire leurs tentatives, puis poursuivre.
- **Passage à 500, puis à 1 000 vidéos, si :**
  - au moins 95 % des tentatives sont terminées, sans limite de ressources dépassée ni repli de
    Whisper sur CPU ;
  - la revue des alertes est faite et les durées mesurées sont compatibles avec le budget ;
  - aucune anomalie de provenance n'a été relevée.

  Les 1 000 vidéos ne viennent qu'après validation des 500.

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
