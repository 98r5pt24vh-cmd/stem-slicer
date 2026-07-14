import os
import re
import sys
import time


BPM_PATTERN = re.compile(r"(?<!\d)(\d{2,3})(?!\d)")
ONSET_THRESHOLD = 0.50
FRAME_THRESHOLD = 0.30
MINIMUM_NOTE_LENGTH_MS = 45.0


def bpm_from_filename(path):
    values = [int(value) for value in BPM_PATTERN.findall(os.path.splitext(os.path.basename(path))[0])]
    plausible = [value for value in values if 40 <= value <= 300]
    if len(plausible) != 1:
        raise ValueError("The layer filename must contain exactly one BPM value.")
    return plausible[0]


def _snap(value, step):
    return round(value / step) * step


def clean_note_events(note_events, bpm):
    """Apply the user-validated Clean Lab V1 post-processing pass."""
    step = 60.0 / bpm / 8.0  # 1/32-note grid
    minimum_duration = step * 0.45
    merge_gap = step * 0.35
    notes = []
    for start, end, pitch, amplitude, _pitch_bend in note_events:
        quantized_start = max(0.0, _snap(start, step))
        quantized_end = max(quantized_start + step, _snap(end, step))
        if quantized_end - quantized_start < minimum_duration:
            continue
        notes.append([
            quantized_start,
            quantized_end,
            int(pitch),
            int(round(35 + 92 * amplitude)),
        ])

    merged = []
    for note in sorted(notes, key=lambda item: (item[2], item[0], item[1])):
        if merged and merged[-1][2] == note[2] and note[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], note[1])
            merged[-1][3] = max(merged[-1][3], note[3])
        else:
            merged.append(note)
    return sorted(merged, key=lambda item: (item[0], item[2], item[1]))


class MidiConverter:
    def __init__(self):
        # Stem Slicer deliberately uses Basic Pitch's compact ONNX model.
        # Avoid probing optional Core ML before selecting that model.
        sys.modules.setdefault("coremltools", None)
        from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
        from basic_pitch.inference import Model
        import numpy as np

        model_path = build_icassp_2022_model_path(FilenameSuffix.onnx)
        self.model = Model(model_path)
        # Warm ONNX after the key engine is ready, not during the user's first
        # Quick Extract conversion.
        self.model.predict(np.zeros((1, 43844, 1), dtype=np.float32))

    def convert(self, audio_path, midi_path, bpm=None):
        import pretty_midi
        from basic_pitch.inference import predict

        started = time.perf_counter()
        bpm = int(bpm) if bpm is not None else bpm_from_filename(audio_path)
        _model_output, _raw_midi, events = predict(
            audio_path,
            self.model,
            onset_threshold=ONSET_THRESHOLD,
            frame_threshold=FRAME_THRESHOLD,
            minimum_note_length=MINIMUM_NOTE_LENGTH_MS,
            midi_tempo=bpm,
        )
        cleaned = clean_note_events(events, bpm)
        midi = pretty_midi.PrettyMIDI(initial_tempo=bpm, resolution=960)
        instrument = pretty_midi.Instrument(program=0, name="Stem Slicer MIDI")
        for start, end, pitch, velocity in cleaned:
            instrument.notes.append(pretty_midi.Note(
                velocity=max(1, min(127, velocity)),
                pitch=pitch,
                start=start,
                end=end,
            ))
        midi.instruments.append(instrument)
        os.makedirs(os.path.dirname(midi_path), exist_ok=True)
        midi.write(midi_path)
        return {"bpm": bpm, "notes": len(cleaned), "elapsed": time.perf_counter() - started}
