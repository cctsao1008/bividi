"""Provider contract for host-visible sensor sources."""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from .capabilities import SensorCapabilities
from .model import CaptureMode, SourceDescriptor, SourceStatus


@runtime_checkable
class StereoSourceProvider(Protocol):
    """Compatibility host-provider contract.

    The existing provider API remains stereo-oriented while Issue #11 owns the
    final observation-boundary freeze. Runtime topology is now exposed through
    ``get_capabilities`` so the core does not have to infer mono/stereo/IMU/
    audio configuration from provider names or build flags.
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

    def get_capabilities(self, source_id: str) -> SensorCapabilities:
        ...
