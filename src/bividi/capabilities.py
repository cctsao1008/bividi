"""Platform-independent runtime capability model for Bividi sensor rigs.

The model describes what a connected rig exposes after backend/device probing.
It intentionally contains no operating-system, vendor-SDK, or transport-packing
types.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CameraEncoding(str, Enum):
    """Logical image representation exposed by a camera stream."""

    UNKNOWN = "unknown"
    RGB = "rgb"
    MONO = "mono"
    RAW = "raw"


class CameraModality(str, Enum):
    """Physical sensing modality when it is known."""

    UNKNOWN = "unknown"
    VISIBLE = "visible"
    INFRARED = "infrared"


class TriggerMode(str, Enum):
    """Trigger capabilities normalized across device families."""

    SOFTWARE = "software"
    HARDWARE = "hardware"
    COMMAND = "command"


@dataclass(frozen=True, slots=True)
class CameraStreamCapability:
    """One logical camera stream in a runtime-discovered sensor rig."""

    stream_id: str
    role: str = "primary"
    encoding: CameraEncoding = CameraEncoding.UNKNOWN
    modality: CameraModality = CameraModality.UNKNOWN

    def __post_init__(self) -> None:
        if not self.stream_id:
            raise ValueError("camera stream_id must not be empty")
        if not self.role:
            raise ValueError("camera role must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "role": self.role,
            "encoding": self.encoding.value,
            "modality": self.modality.value,
        }


@dataclass(frozen=True, slots=True)
class SensorCapabilities:
    """Runtime-discovered topology and durable sensor capabilities.

    Build/install choices determine which backends are available. This object
    describes the rig that is actually present at runtime.
    """

    cameras: tuple[CameraStreamCapability, ...] = ()
    stereo_pairs: tuple[tuple[str, str], ...] = ()
    imu: bool = False
    audio: bool = False
    device_timestamp: bool = False
    exposure_timestamp: bool = False
    hardware_sync: bool = False
    trigger_modes: tuple[TriggerMode, ...] = ()

    def __post_init__(self) -> None:
        cameras = tuple(self.cameras)
        stereo_pairs = tuple(tuple(pair) for pair in self.stereo_pairs)
        trigger_modes = tuple(self.trigger_modes)
        stream_ids = {camera.stream_id for camera in cameras}
        if len(stream_ids) != len(cameras):
            raise ValueError("camera stream_id values must be unique")
        for pair in stereo_pairs:
            if len(pair) != 2 or pair[0] == pair[1]:
                raise ValueError("each stereo pair must name two distinct camera streams")
            if pair[0] not in stream_ids or pair[1] not in stream_ids:
                raise ValueError("stereo pair references an unknown camera stream")
        object.__setattr__(self, "cameras", cameras)
        object.__setattr__(self, "stereo_pairs", stereo_pairs)
        object.__setattr__(self, "trigger_modes", trigger_modes)

    @property
    def camera_count(self) -> int:
        return len(self.cameras)

    @property
    def stereo_pair_count(self) -> int:
        return len(self.stereo_pairs)

    @property
    def has_stereo(self) -> bool:
        return bool(self.stereo_pairs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cameras": [camera.to_dict() for camera in self.cameras],
            "camera_count": self.camera_count,
            "stereo_pairs": [list(pair) for pair in self.stereo_pairs],
            "stereo_pair_count": self.stereo_pair_count,
            "imu": self.imu,
            "audio": self.audio,
            "device_timestamp": self.device_timestamp,
            "exposure_timestamp": self.exposure_timestamp,
            "hardware_sync": self.hardware_sync,
            "trigger_modes": [mode.value for mode in self.trigger_modes],
        }
