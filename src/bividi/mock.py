"""Synthetic provider used to develop the host and adapters without hardware."""

from __future__ import annotations

from .model import CaptureMode, EvidenceKind, SourceDescriptor, SourceState, SourceStatus


class MockStereoProvider:
    """A deliberately synthetic provider.

    Values returned here are test fixtures only. They are not claims about the
    Waveshare AR0144 camera or any physical device.
    """

    provider_id = "mock"
    source_id = "mock:stereo0"

    def list_sources(self) -> tuple[SourceDescriptor, ...]:
        return (
            SourceDescriptor(
                source_id=self.source_id,
                name="Synthetic stereo source",
                provider_id=self.provider_id,
                evidence=EvidenceKind.SYNTHETIC,
                description="Hardware-independent Bividi development fixture",
            ),
        )

    def get_status(self, source_id: str) -> SourceStatus:
        self._require_source(source_id)
        return SourceStatus(
            source_id=source_id,
            state=SourceState.AVAILABLE,
            evidence=EvidenceKind.SYNTHETIC,
            message="synthetic fixture; no physical camera involved",
        )

    def list_modes(self, source_id: str) -> tuple[CaptureMode, ...]:
        self._require_source(source_id)
        return (
            CaptureMode(
                mode_id="mock-gray8-320x240-10",
                eye_width=320,
                eye_height=240,
                fps_num=10,
                fps_den=1,
                pixel_format="gray8",
                evidence=EvidenceKind.SYNTHETIC,
            ),
        )

    def _require_source(self, source_id: str) -> None:
        if source_id != self.source_id:
            raise KeyError(f"unknown mock source: {source_id}")
