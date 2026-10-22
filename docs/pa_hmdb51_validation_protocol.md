# PA-HMDB51 : protocole de validation humaine indépendante des prédictions

Statut : **pré-déclaré le 2026-10-22, avant toute revue**. Ce protocole complète
`docs/nsfw_annotation_guide.md` (définitions des catégories, sections 4 à 7), qu'il ne modifie pas.

## 1. Pourquoi une validation humaine

PA-HMDB51 annote des **attributs de confidentialité**, pas des catégories NSFW. Son attribut
`nudity` est une échelle d'exposition vestimentaire (Wu et al., TPAMI 2020, tableau 1) :

| Valeur PA-HMDB51 | Sens officiel | Relation avec les catégories du projet |
|---|---|---|
| 0 | manches longues et pantalon | `nudity` présumée absente, **non vérifiée** |
| 1 | manches courtes, jupe ou short | `nudity` absente selon le guide 4.1, **non vérifiée** |
| 2 | « semi-nudité », corps à moitié nu | **indéterminé** : torse masculin nu, maillot ou sous-vêtements donnent `absent` ; aréole féminine ou fesses nues visibles donnent `present` |

Aucune valeur ne décrit `sexual_activity` ni `sexual_context`. **Le niveau 2 n'est jamais une
étiquette positive.** Il sert uniquement à choisir quelles vidéos revoir.

## 2. Aveugle

- `manual_review.csv` ne contient **que** `review_id`, le lot, le fichier à visionner et la durée.
  Il ne contient aucune prédiction, aucun score, aucune catégorie prédite et aucun attribut
  PA-HMDB51.
- L'ordre est aléatoire, avec une graine fixée avant la revue (`nsfw-cutter/pa-hmdb51/review/v1`).
- Le **lot 1** mélange des vidéos impossibles à distinguer pour le relecteur :
  - toutes les alertes A2 ;
  - toutes les alertes A0 à 0,45 ;
  - toutes les vidéos annotées par PA-HMDB51 ;
  - un audit aléatoire des autres vidéos (20 %, au moins 30).
- Le **lot 2** contient le reste. Revoir les deux lots rend la revue **complète**.
- `manual_review_key.csv` relie `review_id` à la vidéo et à son motif de sélection. **Il ne doit pas
  être ouvert avant le verrouillage** (section 4), pas plus que `predictions.csv`, `per_video.csv`,
  `metrics.json` ou `annotation_mapping.csv`.
- **Limite de l'aveugle.** Le relecteur sait que le corpus contient des alertes, et le responsable
  du projet a vu les métriques agrégées. Si le relecteur est aussi celui qui a lancé la campagne,
  l'aveugle reste partiel : il faut le déclarer dans le rapport.

## 3. Visionnage et saisie

- Relecteur **majeur**, qui a lu le guide (sections 2 à 7). Visionnage local uniquement, sans
  capture d'écran, sans téléversement et sans copie des médias hors du poste.
- Visionner le fichier indiqué (`file_to_watch`, l'AVI original) **en entier**, avec un lecteur
  qui permet d'avancer image par image (VLC, par exemple). Le MKV évalué a des images décodées
  identiques, vérifiées par MD5.
- Colonnes à remplir, selon le vocabulaire du guide :

  | Colonne | Valeurs |
  |---|---|
  | `reviewer_id` | pseudonyme |
  | `review_date` | AAAA-MM-JJ |
  | `watched_in_full` | `yes` ou `no` |
  | `nudity`, `sexual_activity`, `sexual_context` | `present`, `absent` ou `uncertain` |
  | `nudity_context` | `nonsexual_everyday`, `nonsexual_medical`, `nonsexual_artistic`, `nonsexual_educational`, `sexual`, `unclear` ou vide |
  | `video_label` | `positive`, `negative`, `uncertain` ou `excluded` |
  | `events` | `début-fin:catégorie` séparés par `;`, en secondes, à 0,5 s près (par exemple `1.0-2.5:nudity`), pour toute catégorie `present` ou `uncertain` |
  | `escalation` | `age_uncertain`, `consent_uncertain`, `other_sensitive` ou vide |
  | `exclusion_reason`, `notes` | texte libre |

- **Cas fréquents dans ce corpus :**
  - Baiser ou étreinte : `sexual_activity` et `sexual_context` valent `absent` (guide 4.2 et 4.3).
  - Torse masculin nu, maillot de bain, plongeon : `nudity` vaut `absent` (guide 4.1).
  - Zone trop petite ou floue à 240p : `uncertain`, jamais `present` par déduction.
- **Escalade (guide 7).** En cas de doute sur l'âge ou le consentement, arrêter le visionnage,
  noter `excluded` avec le motif, et ne pas revisionner.

## 4. Verrouillage et levée de l'aveugle

1. Le lot 1 est rempli entièrement, puis le lot 2 si possible.
2. Calculer le SHA-256 du fichier rempli et le consigner (date et pseudonyme) **avant** d'ouvrir la
   clé : `Get-FileHash manual_review_filled.csv -Algorithm SHA256`.
3. Aucune modification après la levée de l'aveugle. Une correction devient un nouveau fichier
   (`manual_review_filled_v2.csv`), avec sa justification, et les deux versions sont conservées.
4. Notation :
   `python -m evaluation.pa_hmdb51 score-review manual_review_filled.csv --analysis <dossier d'analyse> --output review_scores.json`.

## 5. Ce que la notation publie

Elle refuse les lignes incohérentes avec le guide (par exemple `negative` sans visionnage
complet, ou une catégorie `present` avec une étiquette autre que `positive`). Ces lignes sont
listées et non notées.

| Plan de revue | Publié | Retenu |
|---|---|---|
| Partiel (lot 1 seul) | Alertes confirmées et fausses alertes confirmées (comptes) ; précision des alertes si **toutes** les alertes sont revues ; erreurs de catégorie et localisation sur les vrais positifs revus | Rappel, spécificité, F1, taux de fausses alertes par heure au niveau événement |
| Complet (lots 1 et 2) | Matrice TP/FP/FN/TN, précision, rappel, spécificité et F1 avec IC de Wilson ; confusion par catégorie ; événements à IoU 0,25, 0,50 et 0,75 ; erreurs de bornes | — |

Sans aucun positif de référence, le rappel et le F1 sont **indéfinis** (`null`) et le rapport le
signale. Un test sur des vidéos négatives ne mesure jamais à lui seul la qualité du détecteur.

## 6. Accord inter-annotateurs

Avec un seul relecteur, la notation ajoute `annotation_warning` et les étiquettes restent
provisoires. Le protocole cible prévoit deux relecteurs indépendants, chacun avec sa propre
feuille, puis une adjudication à l'aveugle (guide, section 8). Le calcul de l'accord (kappa de
Cohen par catégorie) n'est pas encore implémenté. C'est une étape à venir.

## 7. Alternative outillée

L'outil hors ligne `python -m evaluation.annotation` (guide, section 11) apporte le verrouillage
définitif, le journal d'audit et l'export lié à l'empreinte du manifeste. Il accepte les manifestes
de référence produits ici, mais il **n'a pas encore été essayé sur ce corpus**.
