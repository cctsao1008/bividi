"""Bividi reference host API.

The package exposes hardware-independent host-domain types and provider
interfaces. Device-specific transport code belongs in adapters/providers.
"""

from .host import BividiHost
from .model import CaptureMode, EvidenceKind, SourceDescriptor, SourceState, SourceStatus
from .provider import StereoSourceProvider

__all__ = [
    "BividiHost",
    "CaptureMode",
    "EvidenceKind",
    "SourceDescriptor",
    "SourceState",
    "SourceStatus",
    "StereoSourceProvider",
]

__version__ = "0.0.0"
