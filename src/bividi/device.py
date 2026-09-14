"""Device-adapter boundary for protocol/profile-specific behavior."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .backend import BackendDevice
from .capabilities import SensorCapabilities


@runtime_checkable
class DeviceAdapter(Protocol):
    """Interpret one device family without owning operating-system mechanics."""

    @property
    def adapter_id(self) -> str:
        ...

    def supports(self, device: BackendDevice) -> bool:
        ...

    def discover_capabilities(self, device: BackendDevice) -> SensorCapabilities:
        ...
