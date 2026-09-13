"""Provider contract for stereo sources."""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from .model import CaptureMode, SourceDescriptor, SourceStatus


@runtime_checkable
class StereoSourceProvider(Protocol):
    """Minimal host-side source provider contract.

    Implementations may wrap UVC, recorded data, synthetic fixtures, or future
    transports. The contract intentionally exposes logical stereo capability,
    not transport packing details.
    """

    @property
    def provider_id(self) -> str:
        ...

    def list_sources(self) -> Sequence[SourceDescriptor]:
        ...

    def get_status(self, source_id: str) -> SourceStatus:
        ...

    def list_modes(self, source_id: str) -> Sequence[CaptureMode]:
        ...
