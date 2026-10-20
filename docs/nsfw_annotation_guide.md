# Guide d'annotation NSFW — version 2 proposée (2026-10-20)

> **PROPOSED / NOT YET HUMAN-APPROVED — Statut : proposition, non approuvée.** Ce guide n'a été
> validé par aucun responsable humain. Il remplace la version 1 du kit (`blinded/PROTOCOLE.md`)
> **seulement après approbation écrite**, consignée dans le journal d'audit. Il doit ensuite rester
> figé pour toutes les vidéos d'une même campagne.

Ce guide sert à établir des étiquettes de référence humaines pour le benchmark indépendant
(`docs/independent_benchmark_protocol.md`, sections 8 bis et 10 ter). Il reprend les trois
catégories du pipeline gelé : `nudity`, `sexual_activity` et `sexual_context`. Les définitions
ci-dessous ont été rédigées pour l'annotation humaine. Elles ne reprennent pas le prompt du modèle
et ne modifient ni ce prompt ni les catégories du pipeline.

## 1. Principes

1. **Aveugle.** Les relecteurs ne voient aucune prédiction (A0, A1 ou A2), aucun score Marqo,
   aucune fenêtre candidate, aucune étiquette d'activité Charades, aucun script, aucune strate de
   sélection et aucun marqueur « pilote ». Ils n'ouvrent aucun dossier
   `artifacts/benchmark-runs/`, `artifacts/benchmark-analysis-*` ou `score/`.
2. **Indépendance.** Chacun des deux relecteurs remplit sa propre fiche, dans son propre ordre
   aléatoire. Ils ne se consultent pas avant que les deux fiches soient verrouillées.
3. **Trois états, jamais deux.** Une catégorie est `absent`, `present` ou `uncertain`. L'absence
   d'information n'est jamais une absence de contenu. `uncertain` n'est jamais converti en
   `absent`.
4. **Rien n'est pré-rempli.** Aucune étiquette n'est déduite d'un modèle, des annotations Charades
   ou d'un autre relecteur.
5. **Une étiquette décrit ce qui est visible ou audible**, pas une intention supposée.

## 2. Relecteurs

- Deux relecteurs **adultes** (18 ans ou plus). Ils sont informés à l'avance que les vidéos
  peuvent, rarement, contenir de la nudité ou des contenus sexuels. Ils ont accepté de les
  visionner et peuvent arrêter à tout moment sans justification.
- De préférence, ils n'ont pas participé au réglage du pipeline ni à l'analyse de la campagne.
- Ils reçoivent ce guide approuvé, une séance d'entraînement sur des **exemples non sensibles** (par
  exemple des vidéos quotidiennes avec des cas limites décrits par écrit), et le contact du
  responsable pour l'escalade.
- Leurs identifiants (`reviewer_id`) sont des pseudonymes, attribués par le responsable.

## 3. Visionnage

1. Vérifier le SHA-256 du fichier avant de le visionner (`Get-FileHash -Algorithm SHA256`) et noter
   toute différence au lieu de visionner.
2. Regarder **chaque vidéo en entier**, avec le son si elle en a. Les retours en arrière et le
   ralenti sont permis.
3. Pas de capture d'écran, d'enregistrement, d'extrait ni de partage. Les médias restent sur le
   poste prévu.
4. Noter `watched_in_full`, `audio_listened`, `minutes_spent`, `reviewer_id` et `review_date`.

**Outil de revue hors ligne** (`python -m evaluation.annotation review`, section 11). Avec l'outil,
les étapes 1 et 4 sont automatiques :
- le SHA-256 est vérifié avant le chargement ;
- l'identifiant du relecteur, les horodatages et le temps passé sont enregistrés.

L'outil enregistre aussi les **intervalles réellement lus**. Une avancée de lecture n'est comptée
que si elle est cohérente avec le temps réel écoulé et la vitesse choisie (0,5× à 2×). Un saut, une
avance rapide, une pause ou un changement de vitesse ne comptent jamais comme visionnés, et un
passage revu n'est compté qu'une fois.

La case « vu en entier » ne peut être cochée que lorsque **toute** la vidéo a été lue. Une
tolérance de 0,5 s au total couvre la granularité des positions du lecteur et l'écart de fin de
flux. Le compteur « non lu » indique ce qui manque. Une vidéo n'est `negative` que si trois
conditions sont remplies : les trois catégories sont choisies `absent`, la case « vu en entier »
est cochée, et la case « audio écouté » l'est aussi quand la vidéo a une piste audio. Le
verrouillage demande une dernière confirmation, qui affiche l'étiquette. Rien n'est jamais déduit
par défaut.

## 4. Catégories

### 4.1 `nudity` — présence anatomique visible

**`present`** quand au moins une des zones suivantes est **directement visible et identifiable**
sur au moins une image :
- organes génitaux (quel que soit le sexe) ;
- anus ;
- fesses nues (sans vêtement ni sous-vêtement couvrant le sillon interfessier) ;
- mamelon ou aréole d'une poitrine féminine.

Critères de visibilité :
- La zone doit être **à découvert**. Un tissu fin mais opaque, un maillot, des sous-vêtements, une
  serviette ou un drap qui couvrent la zone donnent `absent`.
- **Transparence** : un vêtement transparent qui laisse voir clairement une zone listée donne
  `present`. Si la zone est devinée sans être identifiable, la réponse est `uncertain`.
- **Flou, pixellisation, faible résolution, contre-jour, mouvement rapide** : `present` seulement
  si la zone reste identifiable sans interprétation. Sinon `uncertain`.
- **Silhouettes, ombres, reflets** sans détail anatomique : `absent`. Avec un détail anatomique
  identifiable : `present`.
- **Image dans l'image** (affiche, écran, photo, tableau visible dans la scène) : même règle,
  avec une mention dans `notes`.
- Un torse masculin nu, un dos nu, des jambes, un ventre nu, une épaule ou un décolleté sans
  aréole visible donnent `absent`.
- Aucune durée minimale : une image identifiable suffit. L'intervalle reporté couvre la visibilité
  réelle.

**La nudité n'implique pas une intention sexuelle.** `nudity` constate une présence anatomique. Le
contexte est noté **séparément** dans la colonne proposée `nudity_context`, quand `nudity` vaut
`present` ou `uncertain` :

| Valeur | Exemples |
|---|---|
| `nonsexual_everyday` | se changer, se laver, sortir de la douche, sans mise en scène sexuelle |
| `nonsexual_medical` | examen, soin, allaitement, démonstration médicale |
| `nonsexual_artistic` | œuvre d'art, sculpture, peinture, performance non sexuelle |
| `nonsexual_educational` | contenu explicatif, anatomie, prévention |
| `sexual` | nudité dans un acte sexuel ou dans une mise en scène sexuelle (4.2 ou 4.3) |
| `unclear` | le contexte ne permet pas de trancher |

`nudity_context` ne change pas l'étiquette `nudity`. Une nudité médicale reste `nudity: present`.
Une vidéo dont la seule nudité est `nonsexual_*` reste donc `positive` au sens du benchmark (au
moins une catégorie `present`). Le contexte permet ensuite de rapporter ces cas à part, sans les
faire disparaître.

### 4.2 `sexual_activity` — acte sexuel, réel ou simulé

**`present`** quand on voit au moins l'un des éléments suivants :
- un rapport sexuel (pénétration ou mouvements de rapport), réel ou simulé, **même habillé** ;
- un acte bucco-génital ;
- une masturbation ;
- un attouchement sexuel des organes génitaux, de la poitrine ou des fesses, par-dessus ou sous les
  vêtements, avec un caractère sexuel manifeste.

**`absent`** pour :
- un baiser, une étreinte, un câlin, une caresse non sexuelle (visage, bras, dos, cheveux) ;
- deux personnes allongées ou endormies dans un lit, sans geste sexuel ;
- un contact accidentel ou fonctionnel (aider à s'habiller, soigner, porter un enfant, sport).

**`uncertain`** quand un geste pourrait être sexuel mais que le cadrage, l'éclairage ou une
occlusion empêchent de le voir clairement, ou quand des mouvements ressemblant à un rapport sont
ambigus. Expliquer le doute dans `notes`.

### 4.3 `sexual_context` — contexte sexuel sans acte ni nudité nécessaires

**`present`** seulement en présence d'une **preuve contextuelle réelle** :
- un geste ou une pose **explicitement sexuels**, par exemple un mime d'acte sexuel, des
  mouvements de bassin dirigés de façon sexuelle, ou une pose sexuelle adressée à la caméra ou à
  une autre personne ;
- un strip-tease, ou des sous-vêtements ou de la lingerie **exhibés dans un but sexuel** (mise en
  scène, insistance de la caméra, pose de séduction explicite) ;
- un objet sexuel **clairement identifiable** (jouet sexuel, préservatif en contexte sexuel)
  utilisé ou mis en avant ;
- des paroles ou des sons sexuels **explicites** (description d'un acte sexuel, gémissements
  sexuels sans ambiguïté), notés `audio` dans `notes`. Le guide ne demande jamais de transcrire
  ces paroles.

**Ne suffisent jamais, à eux seuls** :
- les vêtements ordinaires, moulants, courts, un pyjama, un maillot de bain, une serviette ou des
  sous-vêtements dans un contexte quotidien (s'habiller, se changer, dormir, faire sa toilette) ;
- les objets du quotidien (lit, canapé, douche, miroir, oreiller, banane, etc.), quelle que soit
  leur forme ;
- les poses ordinaires : allongé, penché, assis jambes écartées, s'étirer, faire de l'exercice,
  ramasser un objet ;
- un regard, un sourire, un clin d'œil, une danse non sexuelle ;
- un baiser ou une étreinte romantique sans geste sexuel.

**`uncertain`** quand un indice existe mais que son caractère sexuel n'est pas établi (objet non
identifiable, geste équivoque). Ne jamais déduire un contexte sexuel d'un simple rapprochement
d'objets ou de vêtements.

### 4.4 Cas ambigus fréquents

| Situation | nudity | sexual_activity | sexual_context |
|---|---|---|---|
| Se changer en sous-vêtements, rien de découvert | absent | absent | absent |
| Se changer, fesses nues visibles 1 s | present (`nonsexual_everyday`) | absent | absent |
| Torse masculin nu, en sport ou en lit | absent | absent | absent |
| Couple qui s'embrasse sur un canapé | absent | absent | absent |
| Couple sous un drap, mouvements de rapport visibles | selon la visibilité | present | — |
| Couple sous un drap, mouvements indistincts | selon la visibilité | uncertain | uncertain |
| Pose en lingerie face caméra, mise en scène de séduction | absent (si couvert) | absent | present |
| Serviette nouée après la douche | absent | absent | absent |
| Affiche montrant une nudité, visible dans la scène | present (avec une note) | absent | selon la scène |
| Allaitement, aréole visible | present (`nonsexual_medical`) | absent | absent |
| Zone floue ou trop petite pour être identifiée | uncertain | — | — |

`—` signifie que la catégorie se juge selon les autres éléments de la vidéo.

## 5. Étiquette de la vidéo

- `positive` : au moins une catégorie `present`.
- `negative` : les trois catégories `absent`, **après un visionnage complet**
  (`watched_in_full = yes`) et l'écoute de l'audio quand il existe. Une vidéo non vue en entier ne
  peut pas être `negative`.
- `uncertain` : aucune catégorie `present` et au moins une `uncertain`, ou un visionnage incomplet
  sans motif d'exclusion.
- `excluded` : visionnage arrêté pour une escalade (section 7), ou média illisible ou
  non conforme au SHA-256 (motif dans `exclusion_reason`).

Les étiquettes `uncertain` et `excluded` ne sont **jamais** comptées comme négatives. Elles restent
dans les fiches, dans l'adjudication et dans le rapport.

## 6. Événements temporels

- Pour toute catégorie `present` ou `uncertain`, reporter un ou plusieurs intervalles
  `début-fin:catégorie`, en secondes, à 0,5 s près, par exemple `12.0-18.5:nudity`.
- Deux apparitions séparées de moins de 2 s forment un seul intervalle.
- Une vidéo `negative` n'a aucun intervalle.
- Ces intervalles ne sont exhaustifs que si le relecteur a vu la vidéo en entier. Dans le cas
  contraire, ils ne servent pas à des mesures temporelles.

## 7. Escalade et exclusion

- **Doute sur l'âge** d'une personne dans un contenu sexualisé ou dénudé, ou **doute sur le
  consentement** : arrêter immédiatement le visionnage et ne pas le reprendre. Noter
  `age_uncertain` ou `consent_uncertain` dans `escalation`, `excluded` dans `video_label`, et
  prévenir le responsable. La vidéo est retirée de l'évaluation, **mais reste comptée et tracée**
  dans le journal d'audit et dans le rapport. Elle n'est jamais revisionnée pour « vérifier ».
- Autre contenu choquant inattendu (violence grave, par exemple) : `other_sensitive`, avec la même
  procédure.
- **Contenu NSFW découvert** sans doute sur l'âge ni le consentement : annoter normalement
  (`positive`). La vidéo n'est jamais supprimée en silence ni requalifiée en négative. Le
  responsable l'exclut ensuite du volet technique (`exclusion_reason: nsfw_discovered`), et elle
  reste visible dans `excluded_reference_positives`.

## 8. Verrouillage, adjudication et traçabilité

1. **Verrouillage.** Chaque relecteur enregistre sa fiche, calcule son SHA-256 et ajoute une ligne
   `sheet_locked` (horodatage UTC, identifiant, empreinte) dans `audit_log.csv`. La fiche n'est
   plus modifiée ensuite. Toute correction devient une nouvelle ligne `note` du journal d'audit,
   jamais une réécriture.
2. **Accord inter-relecteurs.** Il est calculé seulement après le verrouillage des deux fiches :
   - accord brut et kappa de Cohen sur `video_label` et sur chaque catégorie ;
   - nombre de vidéos `uncertain` et `excluded` par relecteur.
3. **Adjudication.** Elle porte sur tout désaccord sur `video_label` ou sur une catégorie. Elle est
   faite par une troisième personne adulte, ou par les deux relecteurs ensemble après verrouillage,
   **toujours sans les prédictions des modèles**. `adjudication.csv` reçoit les deux étiquettes,
   les catégories en litige, la décision finale et sa justification. Une adjudication sans accord
   aboutit à `uncertain`.
4. **Levée de l'aveugle.** La fiche de comparaison avec les prédictions (A0, A1 et A2) n'est
   générée **qu'après** le verrouillage de l'adjudication. L'événement `unblinded` est noté dans le
   journal d'audit.
5. **Report dans le manifeste.**
   - `video_label` adjudiqué ;
   - `review_basis: complete` si les 100 vidéos ont été revues ; sinon `alert_triggered` ou
     `random_audit`, selon le plan approuvé ;
   - `category_labels` : `present` reste `present`, `absent` reste `absent`, et `uncertain`
     devient `unknown`, jamais `absent`.

   Les étiquettes Charades d'activité ne sont jamais converties en étiquettes NSFW.

## 9. Un seul relecteur

Avec un seul relecteur, la revue est **exploratoire**. Aucun accord inter-annotateurs n'est calculé
ni revendiqué, et la fiche du second relecteur reste vide.

Conséquences à déclarer dans tout rapport :
- **Fiabilité.** Les étiquettes reflètent le jugement d'une seule personne. Ses erreurs et ses biais
  d'interprétation ne sont ni détectés ni corrigés par un second avis. Il n'y a pas d'adjudication.
- **Aveugle imparfait.** Si le relecteur unique est aussi l'auteur du projet, il a pu voir des
  résultats de la campagne (par exemple les identifiants des vidéos alertées). L'outil n'affiche
  ni identifiant, ni nom de fichier, ni prédiction, ni indice Charades, et suit un ordre aléatoire.
  Il limite donc ce biais sans pouvoir l'exclure.
- **Métriques.** Toute métrique calculée sur ces étiquettes (spécificité, taux de fausses alertes)
  doit porter la mention « référence à un seul relecteur ». `score` ajoute automatiquement
  l'avertissement `annotation_warning`.
- **Cohérence intra-relecteur (option, à pré-déclarer).** Le relecteur peut revoir un échantillon
  aléatoire tiré **avant** le début de la revue (par exemple 10 vidéos), au moins 7 jours plus
  tard, sans consulter ses premières réponses. Cela mesure seulement la stabilité d'un même
  jugement, pas l'accord entre personnes.

## 10. À approuver avant la première revue (responsable du projet)

1. Les définitions des sections 4 à 6, y compris la colonne `nudity_context`. Les fiches à l'aveugle
   devront être régénérées avec cette colonne, vides, sans aucune étiquette.
2. Les deux relecteurs (pseudonymes), leur information préalable et l'adjudicateur.
3. Le plan de revue : revue complète des 100 vidéos (recommandée) ou revue des alertes avec un
   audit aléatoire pré-déclaré.
4. L'ordre des opérations : fiches, verrouillage, accord, adjudication, levée de l'aveugle.
5. Le stockage : poste local, accès restreint, sans copie des médias.

## 11. Outil de revue hors ligne

```powershell
.venv\Scripts\python.exe -m evaluation.annotation review --session <dossier local> --manifest <manifeste> --media-root <dossier des vidéos> --reviewer-id <pseudonyme>
.venv\Scripts\python.exe -m evaluation.annotation status --session ... --manifest ... --media-root ...
.venv\Scripts\python.exe -m evaluation.annotation export --session ... --manifest ... --media-root ... --output <labels.json>
```

- **Une vidéo à la fois**, dans l'ordre aléatoire de la graine 1001 : c'est le même ordre que
  `reviewer_1.csv` du kit.
- **Brouillons :** enregistrés automatiquement, la reprise est possible à tout moment.
- **Verrouillage :** il est définitif. Une correction devient une nouvelle version motivée
  (`locked/<vidéo>/v002.json`), sans écraser la précédente. Chaque événement est inscrit dans
  `audit.jsonl`.
- **Escalade :** le bouton « Arrêter immédiatement » décharge la vidéo.
- **Export :** il n'est possible qu'une fois toutes les vidéos verrouillées. Il produit un fichier
  d'étiquettes lié à l'empreinte du manifeste d'origine, que
  `python -m evaluation.benchmark score ... --labels <labels.json>` applique sans modifier ni le
  manifeste ni les résultats.
- **Isolement :** l'outil ne charge aucun modèle et ne lit aucun dossier de campagne ni de
  résultats. Les sessions et exports restent locaux (`artifacts/`, hors Git).

## Changements par rapport à la version 1

- `nudity` : critères de visibilité détaillés (couverture, transparence, flou, silhouettes, image
  dans l'image) et contexte non sexuel noté à part (`nudity_context`), sans changer l'étiquette.
- `sexual_activity` : actes simulés et habillés inclus ; baisers, étreintes et contacts
  fonctionnels exclus ; cas `uncertain` explicités.
- `sexual_context` : exige une preuve contextuelle réelle. Les vêtements, objets du quotidien et
  poses ordinaires ne suffisent jamais. Les paroles sexuelles explicites sont prises en compte sans
  transcription.
- Ajouts :
  - un tableau des cas ambigus ;
  - des règles sur les intervalles temporels ;
  - des règles d'adjudication à l'aveugle ;
  - la levée de l'aveugle seulement après l'adjudication ;
  - la correspondance avec le manifeste (`uncertain` devient `unknown`) ;
  - les conditions sur les relecteurs adultes.
