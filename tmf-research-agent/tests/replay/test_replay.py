from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from tmf_research.paper.replay import (
    ReplayArchive,
    ReplayIdentityError,
    ReplayRecorder,
)

from tests.replay.replay_support import manifest, run_recorded_scenario


class ReplayManifestTests(unittest.TestCase):
    def test_manifest_fixes_every_canonical_input_and_nothing_volatile(self) -> None:
        value = manifest()

        self.assertEqual(
            tuple(item.name for item in fields(value)),
            (
                "raw_checksum", "dataset_version", "feature_version",
                "label_version", "model_version", "experiment_id",
                "code_commit", "seed", "calendar_version",
                "cost_policy_version",
            ),
        )
        self.assertEqual(len(value.content_hash), 64)

    def test_manifest_requires_complete_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "raw checksum"):
            replace(manifest(), raw_checksum="not-a-hash")
        with self.assertRaisesRegex(ValueError, "required"):
            replace(manifest(), dataset_version=" ")
        with self.assertRaisesRegex(ValueError, "seed"):
            replace(manifest(), seed=-1)

    def test_manifest_is_immutable_with_deterministic_identity(self) -> None:
        first = manifest()
        second = manifest()

        self.assertEqual(first.content_hash, second.content_hash)
        self.assertNotEqual(first.content_hash, manifest(seed=8).content_hash)
        with self.assertRaises(FrozenInstanceError):
            first.seed = 9  # type: ignore[misc]


class ReplayRecorderTests(unittest.TestCase):
    def test_recorder_normalizes_and_checksums_deterministically(self) -> None:
        first = ReplayRecorder(manifest())
        second = ReplayRecorder(manifest())
        for recorder in (first, second):
            recorder.record("PREDICTION", '{"signal":"NO_TRADE"}')
            recorder.record("LEDGER", "a" * 64)

        self.assertEqual(first.lines, second.lines)
        self.assertEqual(first.final_checksum(), second.final_checksum())

    def test_recorder_rejects_unknown_kinds_and_is_append_only(self) -> None:
        recorder = ReplayRecorder(manifest())

        with self.assertRaisesRegex(ValueError, "kind"):
            recorder.record("WALL_CLOCK", "{}")
        self.assertFalse(hasattr(recorder, "remove"))
        self.assertFalse(hasattr(recorder, "clear"))

    def test_different_content_changes_the_final_checksum(self) -> None:
        first = ReplayRecorder(manifest())
        second = ReplayRecorder(manifest())
        first.record("PREDICTION", '{"signal":"NO_TRADE"}')
        second.record("PREDICTION", '{"signal":"LONG"}')

        self.assertNotEqual(first.final_checksum(), second.final_checksum())


class ReplayArchiveTests(unittest.TestCase):
    def test_replay_identity_cannot_be_overwritten(self) -> None:
        archive = ReplayArchive()
        recorder = ReplayRecorder(manifest())
        recorder.record("PREDICTION", '{"signal":"NO_TRADE"}')
        archive.publish(recorder)

        with self.assertRaises(ReplayIdentityError):
            archive.publish(recorder)

    def test_version_or_seed_change_creates_a_new_identity(self) -> None:
        archive = ReplayArchive()
        first = ReplayRecorder(manifest())
        second = ReplayRecorder(manifest(seed=8))
        third = ReplayRecorder(manifest(model_version="v2"))
        for recorder in (first, second, third):
            recorder.record("PREDICTION", '{"signal":"NO_TRADE"}')
            archive.publish(recorder)

        self.assertEqual(len(archive.entries), 3)


class SharedInterfaceReplayTests(unittest.TestCase):
    def test_replaying_the_same_events_is_byte_identical_in_process(self) -> None:
        with TemporaryDirectory() as first_root, TemporaryDirectory() as second_root:
            first_checksum, first_lines = run_recorded_scenario(Path(first_root))
            second_checksum, second_lines = run_recorded_scenario(Path(second_root))

        self.assertEqual(first_lines, second_lines)
        self.assertEqual(first_checksum, second_checksum)


if __name__ == "__main__":
    unittest.main()
