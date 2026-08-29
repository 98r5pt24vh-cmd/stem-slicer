# Third-Party Notices

## OpenKeyScan Analyzer

Stem Slicer includes the OpenKeyScan Analyzer from Rekordcloud, based on
MusicalKeyCNN. It is distributed under the MIT License.

Source: https://github.com/rekordcloud/openkeyscan-analyzer

Copyright (c) 2025 Alexander Sommer

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Spotify Basic Pitch

Stem Slicer uses Spotify Basic Pitch for local audio-to-MIDI transcription.
Basic Pitch is distributed under the Apache License 2.0.

Source: https://github.com/spotify/basic-pitch

Copyright 2022 Spotify AB

Licensed under the Apache License, Version 2.0 (the "License"); you may not use
this file except in compliance with the License. You may obtain a copy of the
License at https://www.apache.org/licenses/LICENSE-2.0

The complete Basic Pitch `LICENSE` and `NOTICE` files are included in the
application under `licenses/basic-pitch`.

## FFmpeg

Stem Slicer includes a separate FFmpeg executable for local audio processing.
The pinned Windows binary reports a GPL version 3-or-later configuration; its
exact configuration is available by running `ffmpeg -version` and `ffmpeg -L`.

Source and license information: https://ffmpeg.org/

Windows binary distribution source:
https://github.com/descriptinc/ffmpeg-ffprobe-static/releases/tag/b6.1.2-rc.1

## Bungee

Stem Slicer uses the open-source Bungee time-stretch and pitch-shift engine
for BPM and key conversion. Bungee is distributed under the Mozilla Public
License 2.0. The complete license is included under
`licenses/Bungee-MPL-2.0.txt`.

Source: https://github.com/kupix/bungee

## MERT-v1-95M

Slicer includes the `m-a-p/MERT-v1-95M` checkpoint and its custom
modeling code for local layer-category feature extraction. The model card
identifies the license as Creative Commons Attribution-NonCommercial 4.0
International (CC BY-NC 4.0).

Model: https://huggingface.co/m-a-p/MERT-v1-95M

License: https://creativecommons.org/licenses/by-nc/4.0/

This license restricts use of the model to non-commercial purposes unless
separate permission is obtained. Consequently, this beta build must not be
commercially distributed with the bundled checkpoint under the current terms.

## PyTorch, Transformers and scikit-learn

Stem Slicer uses PyTorch, Hugging Face Transformers, Hugging Face Hub,
Safetensors, joblib and scikit-learn to run the local Generate classifier.
Their respective project licenses and notices remain available from the
official projects:

- https://github.com/pytorch/pytorch
- https://github.com/huggingface/transformers
- https://github.com/huggingface/huggingface_hub
- https://github.com/huggingface/safetensors
- https://github.com/joblib/joblib
- https://github.com/scikit-learn/scikit-learn
