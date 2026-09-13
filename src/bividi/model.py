"""Hardware-independent host-domain objects for Bividi.

These objects describe source capability and status. They intentionally avoid
OpenCV, UVC, ROS, MCP, NumPy, and device-specific assumptions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class EvidenceKind(str, Enum):
    """How a host-domain object should be interpreted as evidence."""

    SYNTHETIC = "synthetic"
    DECLARED = "declared"
    MEASURED = "measured"


class SourceState(str, Enum):
    """Availability state of a stereo source."""

    AVAILABLE = "available"
    OFFLINE = "offline"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    source_id: str
    name: str
    provider_id: str
    evidence: EvidenceKind
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = self.evidence.value
        return result


@dataclass(frozen=True, slots=True)
class CaptureMode:
    """A provider-advertised stereo capture mode.

    Width and height are the dimensions of each logical eye image at the
    provider boundary, not necessarily the dimensions of a transport payload.
    Transport packing belongs below the provider boundary.
    """

    mode_id: str
    eye_width: int
    eye_height: int
    fps_num: int
    fps_den: int
    pixel_format: str
    evidence: EvidenceKind

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = self.evidence.value
        result["fps"] = self.fps
        return result


@dataclass(frozen=True, slots=True)
class SourceStatus:
    source_id: str
    state: SourceState
    evidence: EvidenceKind
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["state"] = self.state.value
        result["evidence"] = self.evidence.value
        return result
