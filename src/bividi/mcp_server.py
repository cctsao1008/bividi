"""Read-only Model Context Protocol adapter for the Bividi host API.

MCP is used for discovery, control, and selected metadata/resources. It is not
used as a continuous stereo-video transport.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer

from .cli import build_host

mcp = MCPServer("bividi")
_host = build_host()


def _about_payload() -> dict[str, Any]:
    return {
        "project": "bividi",
        "adapter": "mcp",
        "mode": "read-only-development",
        "hardware_provider": False,
        "bulk_media_transport": False,
        "note": "current provider is synthetic; MCP is not the frame streaming plane",
    }


@mcp.tool(name="bividi.about")
def about() -> dict[str, Any]:
    """Describe the current Bividi MCP adapter and its safety boundary."""

    return _about_payload()


@mcp.tool(name="bividi.list_sources")
def list_sources() -> list[dict[str, Any]]:
    """List stereo sources known to the Bividi host."""

    return [source.to_dict() for source in _host.list_sources()]


@mcp.tool(name="bividi.get_source_status")
def get_source_status(source_id: str) -> dict[str, Any]:
    """Return explicit availability/evidence status for one stereo source."""

    return _host.get_source_status(source_id).to_dict()


@mcp.tool(name="bividi.list_modes")
def list_modes(source_id: str) -> list[dict[str, Any]]:
    """List logical per-eye capture modes advertised by one source provider."""

    return [mode.to_dict() for mode in _host.list_modes(source_id)]


@mcp.resource("bividi://host/about", mime_type="application/json")
def about_resource() -> str:
    """Static metadata describing the Bividi MCP host boundary."""

    return json.dumps(_about_payload(), sort_keys=True)


@mcp.resource("bividi://sources", mime_type="application/json")
def sources_resource() -> str:
    """Current stereo-source inventory as a small JSON resource."""

    payload = [source.to_dict() for source in _host.list_sources()]
    return json.dumps(payload, sort_keys=True)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
