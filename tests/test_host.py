import unittest

from bividi.host import BividiHost
from bividi.mock import MockStereoProvider
from bividi.model import EvidenceKind, SourceState


class HostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = BividiHost([MockStereoProvider()])

    def test_lists_synthetic_source(self) -> None:
        sources = self.host.list_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].source_id, "mock:stereo0")
        self.assertEqual(sources[0].evidence, EvidenceKind.SYNTHETIC)

    def test_status_is_explicitly_synthetic(self) -> None:
        status = self.host.get_source_status("mock:stereo0")
        self.assertEqual(status.state, SourceState.AVAILABLE)
        self.assertEqual(status.evidence, EvidenceKind.SYNTHETIC)

    def test_mode_is_logical_per_eye_geometry(self) -> None:
        modes = self.host.list_modes("mock:stereo0")
        self.assertEqual(len(modes), 1)
        self.assertEqual(modes[0].eye_width, 320)
        self.assertEqual(modes[0].eye_height, 240)
        self.assertEqual(modes[0].evidence, EvidenceKind.SYNTHETIC)

    def test_unknown_source_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.host.get_source_status("missing:source")


if __name__ == "__main__":
    unittest.main()
