from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audio_convert import ConversionRequest, convert_audio, expanded_key_name, shortest_semitone_shift


class PitchMappingTests(unittest.TestCase):
    def test_minor_source_uses_relative_minor_target(self):
        self.assertEqual(shortest_semitone_shift("C# minor", "C major / A minor"), -4)

    def test_major_source_uses_major_target(self):
        self.assertEqual(shortest_semitone_shift("C# major", "C major / A minor"), -1)

    def test_shortest_path_is_bounded_to_six_semitones(self):
        for source in ("C minor", "F# minor", "B major"):
            shift = shortest_semitone_shift(source, "D major / B minor")
            self.assertLessEqual(abs(shift), 6)

    def test_compact_minor_key_from_openkeyscan_is_supported(self):
        self.assertEqual(expanded_key_name("G#m"), "G# minor")
        self.assertEqual(shortest_semitone_shift("G#m", "C major / A minor"), 1)

    def test_key_only_conversion_keeps_source_bpm(self):
        commands = []
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, "Loop.mp3")
            source.write_bytes(b"audio")
            destination = Path(root, "output", "Loop.mp3")
            request = ConversionRequest(
                source=source,
                destination=destination,
                source_bpm=148,
                target_bpm=None,
                source_key="C minor",
                target_key="D major / B minor",
            )

            with patch("audio_convert.find_ffmpeg", return_value="ffmpeg"), \
                 patch("audio_convert._find_bungee", return_value="bungee"), \
                 patch("audio_convert._peak_db", return_value=-1.0), \
                 patch("audio_convert._run", side_effect=lambda command, **kwargs: commands.append(command)):
                result = convert_audio(request)

        bungee_command = next(command for command in commands if command[0] == "bungee")
        self.assertEqual(bungee_command[bungee_command.index("--speed") + 1], "1")
        self.assertEqual(bungee_command[bungee_command.index("--pitch") + 1], "-1")
        self.assertEqual(result.speed_ratio, 1.0)
        self.assertEqual(result.output, destination)


if __name__ == "__main__":
    unittest.main()
