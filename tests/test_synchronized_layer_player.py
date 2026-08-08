import unittest
from unittest.mock import patch

import numpy as np

from synchronized_layer_player import LayerMixDevice, SynchronizedLayerPlayer


class LayerMixDeviceTests(unittest.TestCase):
    def test_layers_join_and_leave_one_sample_clock_without_restarting(self):
        bass = np.full((8, 2), 0.2, dtype=np.float32)
        chords = np.full((8, 2), 0.3, dtype=np.float32)
        device = LayerMixDevice({"bass": bass, "chords": chords})

        self.assertTrue(device.setActive("bass", True))
        first = np.frombuffer(device.readData(8), dtype="<f4")
        self.assertTrue(np.allclose(first, 0.2))
        self.assertAlmostEqual(device.positionRatio(), 1 / 8)

        self.assertTrue(device.setActive("chords", True))
        together = np.frombuffer(device.readData(8), dtype="<f4")
        self.assertTrue(np.allclose(together, 0.5))
        self.assertAlmostEqual(device.positionRatio(), 2 / 8)

        self.assertTrue(device.setActive("bass", False))
        chords_only = np.frombuffer(device.readData(8), dtype="<f4")
        self.assertTrue(np.allclose(chords_only, 0.3))
        self.assertAlmostEqual(device.positionRatio(), 3 / 8)

    def test_solo_always_restarts_from_the_first_sample(self):
        player = SynchronizedLayerPlayer()
        layer = np.full((8, 2), 0.2, dtype=np.float32)
        player._device = LayerMixDevice({"bass": layer}, player)
        player._device.setPositionRatio(0.75)

        with patch.object(player, "_start"):
            self.assertTrue(player.playSolo("bass"))

        self.assertEqual(player.activePaths(), ("bass",))
        self.assertEqual(player.positionRatio(), 0.0)

    def test_first_mix_layer_restarts_but_following_layers_keep_the_clock(self):
        player = SynchronizedLayerPlayer()
        layer = np.full((8, 2), 0.2, dtype=np.float32)
        player._device = LayerMixDevice(
            {"bass": layer, "chords": layer},
            player,
        )
        player._device.setPositionRatio(0.75)

        with patch.object(player, "_start"):
            self.assertTrue(player.playPaths(("bass",), restart=True))
            self.assertEqual(player.positionRatio(), 0.0)
            player.seek(0.5)
            self.assertTrue(player.playPaths(("bass", "chords")))

        self.assertEqual(set(player.activePaths()), {"bass", "chords"})
        self.assertEqual(player.positionRatio(), 0.5)

    def test_seek_and_loop_are_shared_by_every_active_layer(self):
        ramp = np.arange(8, dtype=np.float32)[:, None]
        ramp = np.repeat(ramp, 2, axis=1) / 10.0
        device = LayerMixDevice({"one": ramp})
        device.setActive("one", True)
        device.setPositionRatio(0.75)

        samples = np.frombuffer(device.readData(24), dtype="<f4").reshape(-1, 2)
        self.assertTrue(np.allclose(samples[:, 0], [0.6, 0.7, 0.0]))
        self.assertAlmostEqual(device.positionRatio(), 1 / 8)

    def test_hot_replacement_crossfades_without_resetting_the_clock(self):
        old = np.full((8, 2), 0.2, dtype=np.float32)
        new = np.full((8, 2), 0.6, dtype=np.float32)
        device = LayerMixDevice({"lead": old})
        device.setActive("lead", True)
        device.readData(8)
        position_before = device.positionRatio()

        self.assertTrue(device.replaceLayer("lead", new, crossfade_frames=2))
        transition = np.frombuffer(device.readData(16), dtype="<f4").reshape(-1, 2)

        self.assertAlmostEqual(position_before, 1 / 8)
        self.assertTrue(np.allclose(transition[:, 0], [0.4, 0.6]))
        self.assertAlmostEqual(device.positionRatio(), 3 / 8)

    def test_per_layer_volume_changes_mix_without_moving_the_clock(self):
        bass = np.full((8, 2), 0.2, dtype=np.float32)
        chords = np.full((8, 2), 0.4, dtype=np.float32)
        device = LayerMixDevice({"bass": bass, "chords": chords})
        device.setActivePaths(("bass", "chords"))

        self.assertTrue(device.setVolume("chords", 0.25))
        before = device.positionRatio()
        mixed = np.frombuffer(device.readData(8), dtype="<f4")

        self.assertTrue(np.allclose(mixed, 0.3))
        self.assertEqual(before, 0.0)
        self.assertAlmostEqual(device.positionRatio(), 1 / 8)

if __name__ == "__main__":
    unittest.main()
