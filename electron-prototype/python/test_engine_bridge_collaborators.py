from pathlib import Path
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sqlite3
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_bridge as bridge
from generation_policy import GenerationRequest, LayerCandidate, select_generation


class CollaboratorGenerationTests(unittest.TestCase):
    def test_windows_helper_processes_never_open_a_console(self) -> None:
        with (
            patch.object(bridge.os, "name", "nt"),
            patch.object(bridge.subprocess, "STARTUPINFO", return_value=SimpleNamespace(dwFlags=0, wShowWindow=None), create=True),
            patch.object(bridge.subprocess, "STARTF_USESHOWWINDOW", 1, create=True),
            patch.object(bridge.subprocess, "SW_HIDE", 0, create=True),
            patch.object(bridge.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True),
        ):
            options = bridge._hidden_process_kwargs()

        self.assertEqual(options["creationflags"], 0x08000000)
        self.assertEqual(options["startupinfo"].dwFlags, 1)
        self.assertEqual(options["startupinfo"].wShowWindow, 0)

    def test_source_pool_can_exclude_every_local_candidate(self) -> None:
        local = [{"identity": "local"}]
        cloud = [{"identity": "cloud"}]

        self.assertEqual(
            bridge._records_for_source_pool(local, cloud, "cloud-only"),
            (cloud, cloud),
        )
        self.assertEqual(
            bridge._records_for_source_pool(local, cloud, "local-only"),
            (local, []),
        )
        self.assertEqual(
            bridge._records_for_source_pool(local, cloud, "mixed"),
            ([*local, *cloud], cloud),
        )

    def candidate(self, category: str, producer: str | None, index: int) -> LayerCandidate:
        credits = f"+NRGY {producer}" if producer else "+NRGY"
        return LayerCandidate(
            identity=f"{category}-{producer or 'solo'}-{index}",
            path=Path(f"Fm TEST 140 {credits}_L{index}.mp3"),
            source_loop_id=f"loop-{category}-{producer or 'solo'}-{index}",
            source_bpm=140,
            source_key="F",
            source_mode="minor",
            manual_label=category,
        )

    def test_allowed_pool_keeps_solo_material(self) -> None:
        records = [
            {"filename": "Fm SOLO 140 +NRGY_L1.mp3"},
            {"filename": "Fm DUO 140 +NRGY FROFFSY_L1.mp3"},
            {"filename": "Fm OTHER 140 +NRGY SHARKBOY_L1.mp3"},
        ]

        filtered = bridge._filter_records_by_allowed_producers(
            records,
            allowed_producers=["+NRGY", "FROFFSY"],
        )

        self.assertEqual(
            [record["filename"] for record in filtered],
            [record["filename"] for record in records[:2]],
        )

    def test_cloud_record_uses_explicit_producer_credits(self) -> None:
        record = {
            "filename": "Loop without credits_L1.mp3",
            "producers": ["XT"],
        }

        self.assertEqual(bridge._record_producers(record), ["XT"])
        self.assertEqual(
            bridge._filter_records_by_allowed_producers([record], allowed_producers=["+NRGY"]),
            [],
        )

    def test_candidate_override_drives_cloud_collaborator_group(self) -> None:
        candidate = self.candidate("Bass", None, 1)
        overrides = {candidate.identity: ["XT"]}

        self.assertEqual(
            bridge._candidate_external_producer_keys(candidate, overrides),
            frozenset({"xt"}),
        )

    def test_required_share_is_enforced_without_dropping_solo_candidates(self) -> None:
        categories = ("Bass", "Chords", "Lead", "Counter", "Pluck")
        candidates = tuple(
            self.candidate(category, producer, index)
            for index, category in enumerate(categories, start=1)
            for producer in (None, "FROFFSY")
        )
        request = GenerationRequest(
            categories=categories,
            target_bpm=140,
            target_key="F minor",
            seed=17,
        )
        specs = bridge._collaborator_pool_specs(
            candidates,
            allowed_credit_counts=[1, 2],
            required_producers=["FROFFSY"],
            locked_identities=request.locked_identities_by_slot,
            seed=request.seed,
        )
        _, group, pool, required, _ = specs[0]

        plan = bridge._select_constrained_collaborator_plan(
            pool,
            request,
            target_external_keys=group,
            required_keys=required,
            required_contribution_percent=50,
            select_generation=select_generation,
        )
        present, required_layer_count = bridge._selection_collaborator_state(
            plan,
            required,
        )

        self.assertEqual(present, {"froffsy"})
        self.assertEqual(required_layer_count, 3)
        self.assertEqual(len(plan.selections), 5)

    def test_two_required_collaborators_can_fill_a_three_person_loop(self) -> None:
        categories = ("Bass", "Chords", "Lead", "Counter", "Pluck")
        candidates = tuple(
            self.candidate(category, producer, index)
            for index, category in enumerate(categories, start=1)
            for producer in (None, "CURESFUL", "RP")
        )
        request = GenerationRequest(
            categories=categories,
            target_bpm=140,
            target_key="D major",
            seed=28,
        )

        specs = bridge._collaborator_pool_specs(
            candidates,
            allowed_credit_counts=[3],
            required_producers=["CURESFUL", "RP"],
            locked_identities=request.locked_identities_by_slot,
            seed=request.seed,
        )

        self.assertEqual(len(specs), 1)
        _, group, pool, required, _ = specs[0]
        self.assertEqual(group, frozenset({"curesful", "rp"}))

        plan = bridge._select_constrained_collaborator_plan(
            pool,
            request,
            target_external_keys=group,
            required_keys=required,
            required_contribution_percent=50,
            select_generation=select_generation,
        )
        present, required_layer_count = bridge._selection_collaborator_state(plan, required)

        self.assertEqual(present, {"curesful", "rp"})
        self.assertEqual(required_layer_count, 3)
        self.assertEqual(len(plan.selections), 5)

    def test_any_credit_count_keeps_the_full_allowed_pool(self) -> None:
        categories = ("Bass", "Chords", "Lead", "Counter", "Pluck")
        candidates = tuple(
            self.candidate(category, producer, index)
            for index, category in enumerate(categories, start=1)
            for producer in (None, "FROFFSY", "SHARKBOY")
        )
        request = GenerationRequest(
            categories=categories,
            target_bpm=140,
            target_key="F minor",
            seed=12,
        )

        specs = bridge._collaborator_pool_specs(
            candidates,
            allowed_credit_counts=[0],
            required_producers=["FROFFSY"],
            locked_identities=request.locked_identities_by_slot,
            seed=request.seed,
        )

        self.assertEqual(len(specs), 1)
        credit_count, target, pool, required, _ = specs[0]
        self.assertEqual(credit_count, 0)
        self.assertEqual(target, frozenset({"froffsy"}))
        self.assertEqual(required, frozenset({"froffsy"}))
        self.assertEqual(pool, candidates)

        plan = bridge._select_constrained_collaborator_plan(
            pool,
            request,
            target_external_keys=target,
            required_keys=required,
            required_contribution_percent=20,
            select_generation=select_generation,
        )
        present, required_layer_count = bridge._selection_collaborator_state(plan, required)
        self.assertIn("froffsy", present)
        self.assertEqual(required_layer_count, 1)
        self.assertEqual(len(plan.selections), 5)

    def test_zero_credit_count_is_the_any_sentinel(self) -> None:
        self.assertEqual(
            bridge._normalise_allowed_credit_counts({"allowedCreditCounts": [0, 2, 3]}),
            [0],
        )


class GenerationCatalogCacheTests(unittest.TestCase):
    class FakeCandidate:
        @classmethod
        def from_record(cls, record):
            return SimpleNamespace(path=Path(record["path"]), identity=record["path"])

    def test_catalog_reuses_unchanged_snapshot_and_invalidates_after_write(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            database = root_path / "library.sqlite3"
            first_audio = root_path / "first.mp3"
            first_audio.write_bytes(b"audio")
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE layer_cache (path TEXT, library_root TEXT, manual_excluded INTEGER)"
                )
                connection.execute(
                    "INSERT INTO layer_cache VALUES (?, ?, 0)",
                    (str(first_audio), str(root_path)),
                )

            bridge._invalidate_generation_catalog(database)
            first, first_cached = bridge._load_generation_catalog(
                database,
                [str(root_path)],
                self.FakeCandidate,
            )
            second, second_cached = bridge._load_generation_catalog(
                database,
                [str(root_path)],
                self.FakeCandidate,
            )

            self.assertFalse(first_cached)
            self.assertTrue(second_cached)
            self.assertIs(first, second)

            second_audio = root_path / "second.mp3"
            second_audio.write_bytes(b"audio")
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "INSERT INTO layer_cache VALUES (?, ?, 0)",
                    (str(second_audio), str(root_path)),
                )

            refreshed, refreshed_cached = bridge._load_generation_catalog(
                database,
                [str(root_path)],
                self.FakeCandidate,
            )
            self.assertFalse(refreshed_cached)
            self.assertEqual(len(refreshed["candidates_by_path"]), 2)
            bridge._invalidate_generation_catalog(database)


class CloudLayerMaterializationTests(unittest.TestCase):
    def test_source_origin_distinguishes_cloud_metadata_from_local_credits(self) -> None:
        self.assertEqual(
            bridge._source_origin({"library_root": "/local/library", "producers": ["XT"]}),
            "local",
        )
        self.assertEqual(
            bridge._source_origin({"library_root": "cloud://owner/library", "producers": ["XT"]}),
            "cloud",
        )
        self.assertEqual(
            bridge._source_origin({"cloud_object_path": "owner/library/layer.wav"}),
            "cloud",
        )

    def test_downloads_selected_layer_once_then_reuses_verified_cache(self) -> None:
        content = b"synthetic-cloud-layer"
        expected_sha256 = hashlib.sha256(content).hexdigest()
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization"), self.headers.get("apikey")))
                self.send_response(200)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as root:
                destination = Path(root) / "cache" / "layer.mp3"
                candidate = SimpleNamespace(path=destination, identity="cloud:layer")
                selection = SimpleNamespace(candidate=candidate)
                metadata = {
                    str(destination.resolve()): {
                        "filename": "layer.mp3",
                        "cloud_object_path": "owner/library/layer.mp3",
                        "sha256": expected_sha256,
                        "byte_size": len(content),
                    }
                }
                auth = {
                    "projectUrl": f"http://127.0.0.1:{server.server_port}",
                    "publishableKey": "publishable-test",
                    "accessToken": "access-test",
                    "bucket": "cloud-layers",
                }
                with patch.object(bridge, "progress_percent"):
                    bridge._materialize_cloud_selections("job", [selection], metadata, auth)
                    bridge._materialize_cloud_selections("job", [selection], metadata, auth)

                self.assertEqual(destination.read_bytes(), content)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0][1], "Bearer access-test")
                self.assertEqual(requests[0][2], "publishable-test")
                self.assertIn("/cloud-layers/owner/library/layer.mp3", requests[0][0])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
