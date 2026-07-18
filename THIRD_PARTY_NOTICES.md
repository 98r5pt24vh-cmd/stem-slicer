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

## Qt for Python / PySide6

Stem Slicer uses Qt for Python (PySide6). Qt for Python is available under the
GNU Lesser General Public License version 3, the GNU General Public License
version 3, and commercial Qt licenses.

Source and license information: https://doc.qt.io/qtforpython-6/licenses.html

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

## DeepRhythm

Stem Slicer's isolated analyzer uses the open-source DeepRhythm model and
runtime as one input to its Loop-mode BPM decision. DeepRhythm is distributed
under the GNU Affero General Public License version 3. The complete license and
the corresponding analyzer source used by this build are included in this
repository.

Source: https://github.com/bleugreen/deeprhythm

## Bungee

Stem Slicer uses the open-source Bungee time-stretch and pitch-shift engine
for BPM and key conversion. Bungee is distributed under the Mozilla Public
License 2.0. The complete license is included under
`licenses/Bungee-MPL-2.0.txt`.

Source: https://github.com/bungee-audio-stretch/bungee

Pinned source commit: `746833f68a574d997ec50443e7cfd2d37b026302`
