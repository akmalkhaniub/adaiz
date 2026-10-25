"""
Protocol-Level FastMCP Server Adapter (`REQ-MCP-02`).
Exposes AdAiz AdCP Media Buying & Omnichannel Creative tools, Brand Vault resources,
and RFP Intake prompts over wire-protocol JSON-RPC (STDIO and SSE transports).

Reference:
- Micheal Lanham, AI Agents in Action 2E (Chapters 3 & 4)
- Bojie Li, Building AI Agents (Chapter 4)
Governing Skills:
- mcp-and-a2a-interoperability
- adcp-and-adtech-protocols
"""

from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # Graceful fallback shim if mcp package is initializing

    class FastMCP:  # type: ignore[no-redef]
        def __init__(self, name: str, **kwargs: Any) -> None:
            self.name = name
            self._tools: dict[str, Any] = {}
            self._resources: dict[str, Any] = {}
            self._prompts: dict[str, Any] = {}

        def tool(self, name: str | None = None, description: str | None = None):
            def decorator(fn):
                t_name = name or fn.__name__
                self._tools[t_name] = fn
                return fn

            return decorator

        def resource(self, uri: str, name: str | None = None, description: str | None = None):
            def decorator(fn):
                self._resources[uri] = fn
                return fn

            return decorator

        def prompt(self, name: str | None = None, description: str | None = None):
            def decorator(fn):
                p_name = name or fn.__name__
                self._prompts[p_name] = fn
                return fn

            return decorator

        def run(self, transport: str = "stdio") -> None:
            print(f"[{self.name}] Running FastMCP server on transport={transport}")


from src.graph.state import CampaignBrief, ChannelType, CreativeAsset
from src.mcp_servers.adcp_server import AdCPServer
from src.mcp_servers.creative_server import CreativeMCPServer
from src.memory.brand_vault import HybridBrandVault

mcp = FastMCP("AdAiz-Advertising-Protocol")

_adcp_server = AdCPServer()
_creative_server = CreativeMCPServer()
_brand_vault = HybridBrandVault()

REGISTERED_TOOLS: dict[str, Any] = {}
REGISTERED_RESOURCES: dict[str, Any] = {}
REGISTERED_PROMPTS: dict[str, Any] = {}


def _register_tool(fn):
    REGISTERED_TOOLS[fn.__name__] = fn
    return mcp.tool()(fn)


def _register_resource(uri: str):
    def _wrap(fn):
        REGISTERED_RESOURCES[uri] = fn
        return mcp.resource(uri)(fn)

    return _wrap


def _register_prompt(name: str):
    def _wrap(fn):
        REGISTERED_PROMPTS[name] = fn
        return mcp.prompt(name=name)(fn)

    return _wrap


@_register_tool
def adcp_get_capabilities(channels: list[ChannelType]) -> dict[str, Any]:
    """Query A2A Agent Cards (adagents.json) and AdCP capabilities for target channels."""
    return _adcp_server.get_adcp_capabilities(channels=channels)


@_register_tool
def adcp_get_products(
    campaign_id: str,
    brief_summary: str,
    channels: list[ChannelType],
    target_geos: list[str],
    buying_mode: str = "brief",
) -> list[dict[str, Any]]:
    """Discover PMP, PG, and OpenRTB 2.6 inventory packages across SSP seller agents."""
    return _adcp_server.get_products(
        campaign_id=campaign_id,
        buying_mode=buying_mode,
        brief_summary=brief_summary,
        channels=channels,
        target_geos=target_geos,
        simulate_503_once=False,
    )


@_register_tool
def adcp_allocate_budget(
    campaign_id: str,
    total_budget_usd: float,
    discovered_products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute Tier-0 penny-perfect deterministic budget allocation across discovered AdCP products."""
    items = _adcp_server.allocate_media_budget_deterministic(
        campaign_id=campaign_id,
        total_budget_usd=total_budget_usd,
        discovered_products=discovered_products,
    )
    return [item.model_dump() for item in items]


@_register_tool
def creative_generate_omnichannel(
    campaign_id: str,
    tenant_id: str,
    brand_id: str,
    brand_name: str,
    objective: str,
    total_budget_usd: float,
    channel: ChannelType,
    target_geos: list[str] | None = None,
) -> dict[str, Any]:
    """Generate and spec-validate an omnichannel creative asset (Display, Video, CTV, DOOH)."""
    brief = CampaignBrief(
        campaign_id=campaign_id,
        tenant_id=tenant_id,
        brand_id=brand_id,
        brand_name=brand_name,
        objective=objective,
        total_budget_usd=total_budget_usd,
        target_channels=[channel],
        target_geos=target_geos or ["SG"],
    )
    guidelines = _brand_vault.get_brand_profile(tenant_id=tenant_id, brand_id=brand_id)
    learnings = []
    asset = _creative_server.generate_channel_creative(
        brief=brief,
        channel=channel,
        brand_guidelines=guidelines,
        episodic_learnings=learnings,
        revision_count=0,
    )
    return asset.model_dump()


@_register_tool
def creative_validate_compliance(
    creatives: list[dict[str, Any]],
    tenant_id: str,
    brand_id: str,
) -> dict[str, Any]:
    """Audit creative assets against Brand Vault prohibited claims, disclaimers, and IAB technical specs."""
    parsed_creatives = [CreativeAsset(**c) for c in creatives]
    guidelines = _brand_vault.get_brand_profile(tenant_id=tenant_id, brand_id=brand_id)
    chunks = _brand_vault.retrieve_hybrid_rrf(
        tenant_id=tenant_id,
        brand_id=brand_id,
        query="prohibited claims compliance rules",
        top_k=4,
    )
    passed, feedback, audited = _creative_server.evaluate_brand_compliance(
        creatives=parsed_creatives,
        brand_guidelines=guidelines,
        retrieved_chunks=chunks,
    )
    return {
        "compliance_passed": passed,
        "feedback": feedback,
        "audited_creatives": [a.model_dump() for a in audited],
    }


@_register_resource("adcp://brands/{tenant_id}/{brand_id}")
def get_brand_vault_resource(tenant_id: str, brand_id: str) -> str:
    """MCP Resource returning the JSON-serialized Brand Vault profile for (tenant_id, brand_id)."""
    profile = _brand_vault.get_brand_profile(tenant_id=tenant_id, brand_id=brand_id)
    return json.dumps(profile, indent=2)


@_register_prompt("campaign_brief_template")
def campaign_brief_template(
    brand_name: str = "Aurora EV Motors",
    budget_usd: float = 75000.0,
    channels: str = "display, ctv, dooh",
) -> str:
    """Standardized MCP Prompt template for agency RFP intake and omnichannel planning."""
    return (
        f"You are the AdAiz Campaign Orchestrator planning a ${budget_usd:,.2f} omnichannel campaign "
        f"for {brand_name} across [{channels}]. Enforce 100% penny-perfect budget conservation, "
        f"IAB creative specifications, CTV 10% overscan safe-zones, DOOH <=8-word headlines, "
        f"and pause at the Human-in-the-Loop interrupt() gate before any LIVE_SPEND activation."
    )


def get_fastmcp_manifest() -> dict[str, Any]:
    """Return exported FastMCP schema manifest for programmatic inspection and testing."""
    return {
        "server_name": "AdAiz-Advertising-Protocol",
        "supported_transports": ["stdio", "sse"],
        "tools": list(REGISTERED_TOOLS.keys()),
        "resources": list(REGISTERED_RESOURCES.keys()),
        "prompts": list(REGISTERED_PROMPTS.keys()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AdAiz FastMCP Protocol Server Runner")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport protocol (stdio or sse)",
    )
    parser.add_argument("--port", type=int, default=8001, help="Port for SSE transport")
    parser.add_argument(
        "--dump-manifest",
        action="store_true",
        help="Print registered FastMCP tools, resources, and prompts JSON and exit",
    )
    args = parser.parse_args()

    if args.dump_manifest:
        print(json.dumps(get_fastmcp_manifest(), indent=2))
        return

    if args.transport == "sse":
        try:
            mcp.settings.port = args.port  # type: ignore[attr-defined]
        except Exception:
            pass
    mcp.run(transport=args.transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
