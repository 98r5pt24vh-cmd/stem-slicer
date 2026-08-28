# Stem Slicer 1.9B — Project Status

Date: 2026-08-10

Ce document est le contexte court à fournir au début d'une nouvelle tâche. Il
décrit la baseline courante, les fonctions déjà validées et les priorités de
développement. Pour les détails de release et de rebuild, lire ensuite le
handoff et les documents `docs/build`.

## Baseline actuelle

- Version acceptée: **Stem Slicer 1.9B** sur macOS et Windows.
- Source canonique: `/Users/nrgy/Documents/Stem Slicer Repository`.
- Branche courante: `codex/windows-1.9b`.
- Handoff complet: `docs/HANDOFF_ETAT_COURANT_1.9B_2026-08-10.md`.
- Les anciennes applications, builds et caches reproductibles ont été retirés
  du projet actif. Ne jamais reconstruire depuis une ancienne application,
  archive, extraction, `build`, `dist` ou environnement virtuel.
- Toute suppression doit passer par la Corbeille.

## Fonctions actuelles

### Stem Slicer

- Extraction batch de loops MP3 en layers.
- Chemins de détection **Space** et **NoSpace**.
- Analyse de clé et BPM.
- Conversion de BPM et de clé avec Bungee.
- Nommage et sorties prêts pour un usage dans un DAW.

### Quick Tools

- Quick Extract sous forme de cards incrémentales.
- Lecture, waveform, métadonnées et drag audio individuel.
- Conversion BPM/clé optionnelle.
- MIDI Basic Pitch calculé en parallèle et draggable par card.
- Drag All, Quick Scan, Quick Convert et historiques Manage persistants.

### Generate

- Scan incrémental d'une bibliothèque de layers avec cache SQLite persistant.
- Classification locale MERT-v1-95M (moyenne + dispersion temporelle) + 64
  caractéristiques DSP, soit 1 600 valeurs par layer.
- Tête V3 entraînée sur 849 vérités issues de 641 loops sources, plus 323
  exemples auxiliaires Vocal Chop.
- Taxonomie V3 à 14 classes: Arp, Bass, Bells, Chords, Counter,
  Guitar Chords, Keys, Lead, Pad, Piano, Pluck, Strings, Texture et Vocal Chop.
  Rhythmic Pluck est fusionné dans Pluck.
- Taxonomie UI additionnelle lorsque des vérités explicites existent:
  Guitar Lead, Vocal, Brass, Accent et Percussion.
- Recette directement composée avec les cards: ajout, suppression, catégorie,
  Keep, Previous Seed et Generate.
- BPM cible et famille clé majeure/relative mineure.
- Lecture solo et preview multicouche synchronisée avec pause/reprise de layers.
- Volume, octave -1/0/+1, Alt Key, audio et MIDI draggables par card.
- Drag All exporte un MP3 contenant la full loop puis les stems espacés.
- Historique Generate persistant avec lecture, ouverture, drag et Corbeille.

## Moteurs principaux

- UI: PySide6 / Qt 6.11.1.
- Catégories: MERT-v1-95M moyenne/dispersion + DSP64 + tête
  `layer_roles_v3`.
- Clé: OpenKeyScan / MusicalKeyCNN.
- BPM: DeepRhythm, onset et structure.
- Audio: FFmpeg et moteurs structure/grid.
- Stretch/transposition: Bungee.
- MIDI: Basic Pitch ONNX.

## Données à préserver

- Corpus et vérités: dossier propre
  `Stem Slicer 1.9B - Current - 2026-08-10/02_Corpus`.
- Audio d'entraînement des rôles: `03_Research/research/` dans ce même dossier.
- Cache Generate actif: `~/Library/Caches/Stem Slicer/1.9`.
- Le corpus d'entraînement du classificateur doit rester séparé de la
  bibliothèque utilisateur scannée par Generate.

## Faiblesses actuelles vérifiées

1. **Catégories inégalement fiables.** Bass, Chords, Counter, Lead, Pad, Pluck
   et Vocal Chop disposent de davantage de matière. Les classes rares comme
   Bells, Strings, Texture, Guitar, Vocal, Arp, Brass, Accent et Percussion
   demandent encore des vérités et une évaluation plus solide.
2. **Erreurs de clé encore perceptibles.** L'utilisateur a observé des
   générations contenant occasionnellement un layer off-key. Le seuil basé sur
   l'écart Top-1/Top-2 protège une partie des cas, mais retire aussi des layers
   de la loterie. Il faut mesurer précisément le compromis avant de modifier le
   seuil.
3. **Premier scan trop lent.** Le cache rend les scans suivants incrémentaux,
   mais un premier scan de plusieurs milliers de layers reste trop long. Il faut
   profiler séparément décodage/hash, clé/BPM, MERT, DSP et écritures SQLite.
4. **UX Generate perfectible sans urgence.** L'interface 1.9B est validée. Les
   pistes restantes concernent surtout la compréhension de Drag All, le contrôle
   de la preview synchronisée et une éventuelle réorganisation future; éviter
   toute refonte non demandée.

## Priorités de développement

### Priorité 1 — Affiner les catégories

- Geler un benchmark de vérité sans fuite entre layers issus d'une même loop.
- Mesurer précision, rappel et matrice de confusion par catégorie.
- Vérifier les erreurs réelles avant d'ajouter de nouvelles règles.
- Enrichir en priorité les catégories faibles et les négatifs difficiles.
- Comparer proprement DSP seul, MERT seul et MERT+DSP.
- Conserver une catégorie finale obligatoire dans l'UI: pas de catégorie
  utilisateur `Unknown` ou `Uncertain`.

### Priorité 2 — Réévaluer la détection de clé

- Rejouer l'évaluation Top-1/Top-2 sur le corpus de vérité.
- Calibrer le seuil de marge au lieu de l'augmenter arbitrairement.
- Distinguer erreur de détection, relation majeure/mineure et erreur de
  transposition.
- Préserver Alt Key comme solution utilisateur, sans en faire un substitut à
  une meilleure détection.

### Priorité 3 — Accélérer le premier scan Generate

- Instrumenter le temps de chaque phase par layer et sur le batch complet.
- Éviter tout calcul répété et confirmer que les fichiers inchangés utilisent
  toujours le cache.
- Évaluer batch MERT, parallélisme borné, décodage partagé et écritures SQLite
  groupées sans sacrifier la stabilité audio ou l'exactitude.

### Priorité 4 — Rework UI éventuel

- Ne commencer qu'après les mesures catégories/clé/vitesse.
- Prototyper les changements d'interface séparément avant de reconstruire les
  applications finales.
- Conserver le design et les comportements acceptés de 1.9B sauf demande
  explicite.

## Contraintes importantes

- MERT-v1-95M est sous CC BY-NC 4.0: la distribution commerciale exige une
  résolution de licence ou un remplacement.
- La build macOS 1.9B actuelle n'est pas validée pour Ventura/macOS 13.
- La détection de clé, la catégorisation et l'audio-to-MIDI restent
  probabilistes; ne jamais annoncer une précision parfaite sans benchmark.
- Avant tout futur build, lire `docs/build/BUILD_INVARIANTS.md` puis
  `docs/build/CLEAN_REBUILD_RUNBOOK.md`.

## Point de départ recommandé pour la prochaine tâche

Commencer par une étude mesurée, sans rebuild et sans modifier l'interface:

1. inventorier les vérités disponibles par catégorie;
2. reconstruire l'évaluation aveugle reproductible de MERT+DSP;
3. produire les métriques par classe et les principales confusions;
4. profiler un scan représentatif;
5. proposer ensuite une seule passe expérimentale clairement mesurable.
