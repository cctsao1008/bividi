"""Platform-backend discovery boundary.

Backends own operating-system/API mechanics. Device protocol interpretation
belongs to device adapters; normalized sensor semantics belong to Bividi core.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


@dataclass(frozen=True, slots=True)
class BackendDevice:
    """A device as discovered by one platform backend."""

    backend_device_id: str
    name: str
    transport: str = ""

    def __post_init__(self) -> None:
        if not self.backend_device_id:
            raise ValueError("backend_device_id must not be empty")


@runtime_checkable
class PlatformBackend(Protocol):
    """Minimal OS/API-specific device-discovery contract."""

    @property
    def backend_id(self) -> str:
        ...

    @property
    def platform_name(self) -> str:
        ...

    def list_devices(self) -> Sequence[BackendDevice]:
        ...
