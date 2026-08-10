# Handoff canonique — Stem Slicer 1.9B

Date: 2026-08-10

## État accepté

Stem Slicer 1.9B est la baseline courante validée par l'utilisateur sur macOS
et par un bêta-testeur sur Windows, avec le dernier hotfix Windows automatisé
et empaqueté le 2026-08-09.

La source canonique est exclusivement le dépôt Git:

`/Users/nrgy/Documents/Stem Slicer Repository`

Branche actuelle: `codex/windows-1.9b`

Révision finale testée Windows:
`c0340675a51229c9634f24458f295e840ccd00f7`

Ne pas repartir d'un ancien dossier de build ou d'une ancienne application.

## Releases conservées

Racine propre:

`/Users/nrgy/Documents/Codex Project/Stem Slicer Project/Stem Slicer 1.9B - Current - 2026-08-10`

macOS:

- `01_Releases/macOS/Stem Slicer 1.9B.app`
- `01_Releases/macOS/Stem-Slicer-1.9B-macOS.zip`
- ZIP: 672653738 octets, SHA-256
  `dfb4bf375c95509a1b865685a45fbccf6945bd094284e88b997346b7ff86919b`
- Source de l'artefact: `5e2e790a747a5ded488f221da79c5704ba859683`

Windows:

- `01_Releases/Windows/Stem-Slicer-1.9B-Windows.zip`
- ZIP: 871766348 octets, SHA-256
  `b284f144de49d2654f5bdbd087279dec73b84e4cd5c36ff3cdd2517aff932ab9`
- Source de l'artefact: `c0340675a51229c9634f24458f295e840ccd00f7`
- CI: <https://github.com/98r5pt24vh-cmd/stem-slicer/actions/runs/31313639704>

Filet de sécurité historique conservé:

- `01_Releases/Previous_Stable_1.8.2B`: ZIP macOS et Windows de la dernière
  baseline validée avant 1.9B;
- `05_Legacy_Source_History/Windows_Port_1.6B_Git`: dépôt Windows historique
  de 50 commits absent de l'historique Git 1.9B;
- `05_Legacy_Source_History/Source_Snapshots`: sources 1.8.2B et 1.8.5
  allégées, sans environnements, builds ni dépendances lourdes.

Ces éléments servent uniquement au rollback et à l'analyse de régression. Ils
ne remplacent jamais la source Git canonique actuelle.

## Fonctions validées

### Stem Slicer

- Batch de loops MP3.
- Extraction de layers Space et chemin NoSpace intégré.
- Analyse de clé et BPM.
- Conversion BPM et clé avec Bungee.
- Opérations combinables, conventions de nommage et destinations de sortie.
- Le support NoSpace reste borné par le corpus conservé; ne pas généraliser sa
  précision à tout type de fichier sans nouvelles vérités.

### Quick Tools

- Quick Extract avec cards incrémentales.
- Lecture, waveform, métadonnées et drag audio individuel.
- Conversion BPM/clé optionnelle.
- MIDI Basic Pitch par card, calculé parallèlement et draggable.
- DRAG ALL ordonné.
- Quick Scan et Quick Convert.
- Historiques persistants et fenêtres Manage.

### Generate

- Scan incrémental d'une librairie de layers et cache SQLite persistant.
- Classification hors ligne MERT-v1-95M (768 valeurs) + DSP (64 valeurs), soit
  832 valeurs par layer.
- Tête entraînée sur 14 classes: Arp, Bass, Bells, Chords, Counter,
  Guitar Chords, Keys, Lead, Pad, Pluck, Rhythmic Pluck, Strings, Texture et
  Vocal Chop.
- Taxonomie UI étendue conservant aussi Guitar Lead, Vocal, Brass, Accent et
  Percussion lorsque des vérités explicites existent.
- Cards servant directement de recette: ajout, suppression et changement de
  catégorie.
- Keep, Previous Seed, Generate, target BPM et familles clé majeure/relative
  mineure.
- Lecture solo et lecture multicouche synchronisée; pause/reprise de layers
  dans le mix synchronisé.
- Volume, octave -1/0/+1, Alt Key, audio draggable et MIDI draggable par card.
- Master MP3 avec full loop puis stems espacés toujours généré et accessible
  via Drag All, même sans card Full Loop affichée.
- Historique Generate avec lecture, ouverture, drag et déplacement vers la
  Corbeille.

## Moteurs et runtime

- Interface: PySide6/Qt 6.11.1.
- Extraction/décodage/encodage: FFmpeg et moteur structure/grid courant.
- Clé: OpenKeyScan/MusicalKeyCNN.
- BPM: DeepRhythm/onset/structure.
- Transposition/stretch: Bungee.
- MIDI: Basic Pitch ONNX.
- Catégories Generate: MERT-v1-95M + DSP64 + tête
  `layer_roles_v1`.
- macOS: CPython 3.12.13 arm64, PyInstaller 6.18.0.
- Windows: CPython officiel 3.12.10 x64, PyInstaller piloté par la CI.

## Corpus conservés

Les corpus de validation utilisateur sont sous `02_Corpus` dans la racine
propre; l'audio d'entraînement du classificateur est conservé séparément sous
`03_Research`.

- `Extraction_Space_NoSpace/Corpus Loops Test`: corpus audio de découpe actuel,
  y compris `No space` et les perturbations synthétiques.
- `Legacy_Loop_Tests/02_Loop_Tests`: corpus audio historique complet gardé par
  sécurité.
- `Legacy_Truth_Data/03_Truth_Data`: vérités extraction, séquence et clés.
- `NoSpace_Extracted_Evidence/real_nospace_exports_17`: exports réels NoSpace
  retenus pour comparaison.
- `Generate_Reference_Truth/Reference Corpus`: vérités CSV de catégories.
- `Vocal_Chop_Verification`: vocal chops, négatifs triés et exemples
  d'entraînement auxiliaires.
- `03_Research/research/layer_role_model_v1_2026-08-02/training_audio`:
  audios d'entraînement du modèle de rôles.

La loop `Too Slimy` d'Igor est la seule source explicitement signalée comme
manquante par l'utilisateur; elle n'a pas été retrouvée pendant le cleanup.

## Cache actif à ne pas supprimer

Le libellé produit est 1.9B mais `RUNTIME_DATA_VERSION` vaut `1.9`.

Le cache de librairie Generate actif se trouve donc sous:

`~/Library/Caches/Stem Slicer/1.9`

Le supprimer force un scan complet de la librairie. Les caches 1.9 et 1.9B ont
été conservés pendant le cleanup du 2026-08-10.

## Validations de référence

macOS scan hotfix:

- 313 tests source;
- runtime packagé Python 3.12.13 arm64 / PySide6 6.11.1;
- UI, clé/BPM, MIDI et MERT+DSP réels;
- signature ad hoc profonde et stricte avant/après extraction;
- ZIP intègre et application extraite testée.

Windows final:

- 315 tests source;
- gate MIDI complet en 13.153 s sous limite stricte de 30 s;
- regressions drag/drop, Browse, dialog parent natif et card removal;
- bundle audité;
- ZIP créé, extrait et payload extrait smoke-testé.

## Limites connues

- MERT est sous CC BY-NC 4.0: la beta qui l'embarque n'est pas une base de
  distribution commerciale sans résolution de licence ou remplacement.
- La build macOS courante n'est pas validée pour Ventura/macOS 13.
- La détection de clé et l'audio-to-MIDI restent probabilistes.
- Les catégories avec peu de vérités restent moins fiables que Bass, Chords,
  Counter, Lead, Pad, Pluck et Vocal Chop.
- Toute évolution cloud/comptes/partage de librairies est une piste future,
  non implémentée dans 1.9B.

## Rebuild

Lire obligatoirement, dans cet ordre:

1. `docs/build/BUILD_INVARIANTS.md`
2. `docs/build/CLEAN_REBUILD_RUNBOOK.md`

Le runbook Windows repose sur `.github/workflows/build-windows.yml`. Le runbook
macOS impose une construction locale neuve et la double vérification stricte de
signature. Aucun ancien build ne doit servir de dépendance ou de source.
