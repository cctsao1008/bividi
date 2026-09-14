"""Bividi reference host API.

The package exposes platform-independent host-domain types plus narrow
platform-backend and device-adapter interfaces. OS and vendor transport details
remain outside the core model.
"""

from .backend import BackendDevice, PlatformBackend
from .capabilities import (
    CameraEncoding,
    CameraModality,
    CameraStreamCapability,
    SensorCapabilities,
    TriggerMode,
)
from .device import DeviceAdapter
from .host import BividiHost
from .model import CaptureMode, EvidenceKind, SourceDescriptor, SourceState, SourceStatus
from .provider import StereoSourceProvider

__all__ = [
    "BackendDevice",
    "BividiHost",
    "CameraEncoding",
    "CameraModality",
    "CameraStreamCapability",
    "CaptureMode",
    "DeviceAdapter",
    "EvidenceKind",
    "PlatformBackend",
    "SensorCapabilities",
    "SourceDescriptor",
    "SourceState",
    "SourceStatus",
    "StereoSourceProvider",
    "TriggerMode",
]

__version__ = "0.0.0"
