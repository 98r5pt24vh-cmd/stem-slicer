# Handoff — Stem Slicer 1.9 macOS Beta

## Baseline canonique

Source macOS 1.9 :

`Source/Stem_Slicer_1.9_macOS`

Cette source dérive de la source de production macOS 1.8.5 et intègre la tab
Generate fonctionnelle avec le dernier layout compact validé.

## Runtime et build

- CPython 3.12.13 arm64.
- PySide6 6.11.1 / Qt 6.11.1.
- PyInstaller 6.18.0.
- Torch 2.5.1, Transformers 4.38.2, scikit-learn 1.9.0.
- Environnement et dossiers PyInstaller créés à neuf pour le build final.
- Signature ad hoc profonde et stricte validée avant et après exécution.

## Generate

- MERT-v1-95M + 64 caractéristiques DSP, vecteur total de 832 valeurs.
- Tête `layer_roles_v1` embarquée, 14 catégories entraînées.
- Checkpoint et code MERT empaquetés pour une classification entièrement hors
  ligne.
- Données d’entraînement séparées de la librairie utilisateur scannée.
- Lecture multicouche synchronisée sans redémarrage du moteur audio lors des
  transformations chaudes.
- Full Loop non affichée mais toujours générée et accessible via Drag All.

## Gates effectués

- `pip check` : OK.
- Suite source : 293 tests, OK.
- Smoke UI packagé : OK.
- Smoke clé/BPM packagé : OK.
- Smoke MIDI packagé : OK, fichier `MThd` valide.
- Worker MERT packagé : handshake 832 dimensions / 14 classes et prédiction
  réelle, OK.
- Aucun cache mutable `.nbi`, `.nbc`, Hugging Face ou Transformers créé dans
  le bundle après exécution.
- ZIP : résultat et SHA-256 consignés dans `Validation_Evidence` après création.

## Défauts et restrictions non résolus

- Waveform Quick Extract : tête de lecture encore difficile à glisser sur les
  cards concernées ; défaut connu de la baseline antérieure, non corrigé ici.
- Ventura : non compatible avec les wheels officielles PySide6 6.11.1 actuelles
  dont les modules essentiels arm64 déclarent `minos 15.0`. Ne pas présenter
  cette build comme compatible macOS 13.
- Licence : le checkpoint MERT est CC BY-NC 4.0 ; build beta non commerciale
  tant que ce modèle est embarqué sous ces conditions.
