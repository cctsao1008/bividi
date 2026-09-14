"""Host facade shared by CLI, MCP, ROS, and future adapters."""

from __future__ import annotations

from collections.abc import Iterable

from .capabilities import SensorCapabilities
from .model import CaptureMode, SourceDescriptor, SourceStatus
from .provider import StereoSourceProvider


class BividiHost:
    """Aggregate one or more source providers behind one host API."""

    def __init__(self, providers: Iterable[StereoSourceProvider] = ()) -> None:
        self._providers = tuple(providers)
        self._source_to_provider: dict[str, StereoSourceProvider] = {}
        self.refresh()

    def refresh(self) -> None:
        source_to_provider: dict[str, StereoSourceProvider] = {}
        for provider in self._providers:
            for source in provider.list_sources():
                if source.source_id in source_to_provider:
                    raise ValueError(f"duplicate source_id: {source.source_id}")
                source_to_provider[source.source_id] = provider
        self._source_to_provider = source_to_provider

    def list_sources(self) -> tuple[SourceDescriptor, ...]:
        sources: list[SourceDescriptor] = []
        for provider in self._providers:
            sources.extend(provider.list_sources())
        return tuple(sources)

    def get_source_status(self, source_id: str) -> SourceStatus:
        return self._provider_for(source_id).get_status(source_id)

    def list_modes(self, source_id: str) -> tuple[CaptureMode, ...]:
        return tuple(self._provider_for(source_id).list_modes(source_id))

    def get_capabilities(self, source_id: str) -> SensorCapabilities:
        return self._provider_for(source_id).get_capabilities(source_id)

    def _provider_for(self, source_id: str) -> StereoSourceProvider:
        try:
            return self._source_to_provider[source_id]
        except KeyError as exc:
            raise KeyError(f"unknown source: {source_id}") from exc
