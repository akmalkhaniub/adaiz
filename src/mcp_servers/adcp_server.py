"""
Ad Context Protocol (AdCP) & Agent-to-Agent (A2A) MCP Server.
Implements official adcontextprotocol/adcp wire tasks:
- get_adcp_capabilities (adagents.json A2A discovery)
- get_products (PMP / PG / OpenRTB 2.6 inventory discovery)
- create_content_standards (IAB brand suitability governance)
- sync_creatives (Creative critical-path registration)
- create_media_buy (LIVE_SPEND campaign activation)
- allocate_media_budget_deterministic (Zero-LLM penny-perfect allocator)

Traceability: REQ-ADCP-01, REQ-HARN-02
Governing Skills:
- adcp-and-adtech-protocols
- mcp-and-a2a-interoperability
- langgraph-multi-agent-orchestration
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from src.graph.state import ChannelType, CreativeAsset, MediaLineItem
from src.harness.executor import TransientDSPTimeoutError


SELLER_AGENT_CARDS: dict[str, dict[str, Any]] = {
    "magnite_ctv_agent": {
        "agent_id": "magnite_ctv_agent",
        "organization": "Magnite ClearLine CTV SSP",
        "adagents_json_uri": "adcp://sellers/magnite/adagents.json",
        "supported_protocols": ["adcp/v1.0", "openrtb/2.6", "vast/4.2"],
        "capabilities": {
            "media_buy": True,
            "creative_sync": True,
            "inline_creative_management": True,
            "supported_channels": ["ctv", "video"],
        },
    },
    "ttd_omnichannel_agent": {
        "agent_id": "ttd_omnichannel_agent",
        "organization": "The Trade Desk Kokai Exchange",
        "adagents_json_uri": "adcp://sellers/thetradedesk/adagents.json",
        "supported_protocols": ["adcp/v1.0", "openrtb/2.6", "prebid/pmp"],
        "capabilities": {
            "media_buy": True,
            "creative_sync": True,
            "inline_creative_management": True,
            "supported_channels": ["display", "video", "ctv"],
        },
    },
    "dv360_publisher_agent": {
        "agent_id": "dv360_publisher_agent",
        "organization": "Google DV360 Marketplace",
        "adagents_json_uri": "adcp://sellers/dv360/adagents.json",
        "supported_protocols": ["adcp/v1.0", "openrtb/2.6"],
        "capabilities": {
            "media_buy": True,
            "creative_sync": True,
            "inline_creative_management": True,
            "supported_channels": ["display", "video"],
        },
    },
    "vistar_dooh_agent": {
        "agent_id": "vistar_dooh_agent",
        "organization": "Vistar Media Global DOOH Exchange",
        "adagents_json_uri": "adcp://sellers/vistar/adagents.json",
        "supported_protocols": ["adcp/v1.0", "openrtb/dooh-2.6"],
        "capabilities": {
            "media_buy": True,
            "creative_sync": True,
            "inline_creative_management": True,
            "supported_channels": ["dooh"],
        },
    },
}


CHANNEL_CATALOG: dict[ChannelType, dict[str, Any]] = {
    "display": {
        "seller_agent_id": "dv360_publisher_agent",
        "publisher_or_ssp": "Google DV360 • Reuters & Bloomberg Finance Network",
        "product_name": "High-Impact IAB Executive Display PMP",
        "deal_prefix": "PMP-DV360-DISP",
        "buying_type": "PMP",
        "default_cpm_usd": 6.80,
        "weight": 0.20,
    },
    "video": {
        "seller_agent_id": "ttd_omnichannel_agent",
        "publisher_or_ssp": "The Trade Desk • Premium Online Video (OLV)",
        "product_name": "Outstream & Instream HD Video VAST 4.2",
        "deal_prefix": "PMP-TTD-OLV",
        "buying_type": "PMP",
        "default_cpm_usd": 14.50,
        "weight": 0.25,
    },
    "ctv": {
        "seller_agent_id": "magnite_ctv_agent",
        "publisher_or_ssp": "Magnite ClearLine • Hulu / Disney+ / Peacock CTV",
        "product_name": "Prime-Time Non-Skippable 15s CTV Pod PG",
        "deal_prefix": "PG-MAG-CTV",
        "buying_type": "PG",
        "default_cpm_usd": 26.00,
        "weight": 0.35,
    },
    "dooh": {
        "seller_agent_id": "vistar_dooh_agent",
        "publisher_or_ssp": "Vistar Media • JCDecaux & ClearChannel Urban Totems",
        "product_name": "Dynamic Commuter & CBD Digital Screens",
        "deal_prefix": "PMP-VIS-DOOH",
        "buying_type": "OpenRTB_2.6",
        "default_cpm_usd": 11.20,
        "weight": 0.20,
    },
}


class AdCPServer:
    """MCP Server implementing AdCP protocol tasks and deterministic media math."""

    def __init__(self) -> None:
        self._fault_injected_campaigns: set[str] = set()

    def get_adcp_capabilities(self, channels: list[ChannelType]) -> dict[str, Any]:
        """Task 1: Query A2A Agent Cards (adagents.json) for requested channels."""
        matched_sellers = []
        for card in SELLER_AGENT_CARDS.values():
            supported = card["capabilities"]["supported_channels"]
            if any(ch in supported for ch in channels):
                matched_sellers.append(card)
        return {
            "protocol_version": "adcp/1.0-mcp-streamable-http",
            "discovered_seller_agents": matched_sellers,
            "seller_count": len(matched_sellers),
        }

    def get_products(
        self,
        campaign_id: str,
        buying_mode: str,
        brief_summary: str,
        channels: list[ChannelType],
        target_geos: list[str],
        simulate_503_once: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Task 2: AdCP get_products discovery across SSPs.
        Supports fault injection (`simulate_503_once`) to verify Agent Harness retry recovery.
        """
        if simulate_503_once and campaign_id not in self._fault_injected_campaigns:
            self._fault_injected_campaigns.add(campaign_id)
            raise TransientDSPTimeoutError(
                "HTTP 503 Service Unavailable: Upstream SSP Inventory Gateway timed out during AdCP get_products."
            )

        geo_tag = "-".join(g.upper() for g in target_geos[:2]) or "GLOBAL"
        products: list[dict[str, Any]] = []
        for ch in channels:
            spec = CHANNEL_CATALOG[ch]
            deal_hash = hashlib.md5(f"{campaign_id}:{ch}:{geo_tag}".encode()).hexdigest()[:6].upper()
            products.append(
                {
                    "channel": ch,
                    "seller_agent_id": spec["seller_agent_id"],
                    "publisher_or_ssp": spec["publisher_or_ssp"],
                    "product_name": f"{spec['product_name']} ({geo_tag})",
                    "deal_id": f"{spec['deal_prefix']}-{geo_tag}-{deal_hash}",
                    "buying_type": spec["buying_type"],
                    "target_cpm_usd": spec["default_cpm_usd"],
                    "weight": spec["weight"],
                }
            )
        return products

    @staticmethod
    def allocate_media_budget_deterministic(
        campaign_id: str,
        total_budget_usd: float,
        discovered_products: list[dict[str, Any]],
    ) -> list[MediaLineItem]:
        """
        Tier 0 Deterministic Engine (Zero LLM freehand math):
        Splits total_budget_usd across discovered products with penny-perfect conservation
        (`sum(allocated) == round(total_budget_usd, 2)`) and exact impression calculation.
        """
        total_budget = round(float(total_budget_usd), 2)
        if not discovered_products:
            return []

        total_weight = sum(float(p.get("weight", 1.0)) for p in discovered_products) or 1.0
        line_items: list[MediaLineItem] = []
        allocated_so_far = 0.0

        for idx, prod in enumerate(discovered_products):
            is_last = idx == len(discovered_products) - 1
            if is_last:
                budget_share = round(total_budget - allocated_so_far, 2)
            else:
                raw_share = total_budget * (float(prod.get("weight", 1.0)) / total_weight)
                budget_share = round(raw_share, 2)
                allocated_so_far = round(allocated_so_far + budget_share, 2)

            cpm = float(prod["target_cpm_usd"])
            est_impressions = int((budget_share / cpm) * 1000)

            line_items.append(
                MediaLineItem(
                    line_id=f"LINE-{idx + 1:02d}-{prod['channel'].upper()}",
                    channel=prod["channel"],
                    seller_agent_id=prod["seller_agent_id"],
                    publisher_or_ssp=prod["publisher_or_ssp"],
                    product_name=prod["product_name"],
                    deal_id=prod["deal_id"],
                    buying_type=prod["buying_type"],
                    allocated_budget_usd=budget_share,
                    target_cpm_usd=cpm,
                    estimated_impressions=est_impressions,
                )
            )
        return line_items

    @staticmethod
    def create_content_standards(
        tenant_id: str,
        brand_id: str,
        excluded_iab_categories: list[str] | None = None,
    ) -> dict[str, Any]:
        """Task 3: AdCP create_content_standards governance registration."""
        exclusions = excluded_iab_categories or ["IAB25-NonStandard", "IAB26-IllegalContent", "FakeNews-MFA"]
        std_id = f"ADCP-GOV-{tenant_id.upper()}-{brand_id.upper()}-2026"
        return {
            "content_standards_id": std_id,
            "excluded_iab_categories": exclusions,
            "brand_safety_tier": "GARM_STRICT_FLOOR",
            "status": "registered",
        }

    @staticmethod
    def sync_creatives(
        media_plan: list[MediaLineItem],
        creatives: list[CreativeAsset],
    ) -> list[MediaLineItem]:
        """
        Task 4: AdCP sync_creatives critical path.
        Registers spec-valid creatives into each seller agent's library and attaches creative_ids.
        """
        creative_by_channel = {c.channel: c for c in creatives if c.spec_valid}
        updated_plan: list[MediaLineItem] = []
        for item in media_plan:
            matched = creative_by_channel.get(item.channel)
            synced_ids = [matched.asset_id] if matched else []
            status = "creatives_synced" if synced_ids else "quarantined"
            updated_plan.append(
                item.model_copy(
                    update={
                        "synced_creative_ids": synced_ids,
                        "adcp_status": status,
                    }
                )
            )
        return updated_plan

    @staticmethod
    def create_media_buy(
        campaign_id: str,
        tenant_id: str,
        content_standards_id: str,
        media_plan: list[MediaLineItem],
        flight_start: str,
        flight_end: str,
    ) -> list[dict[str, Any]]:
        """
        Task 5: AdCP create_media_buy (LIVE_SPEND tier).
        Activates PMP/PG packages across seller SSPs/DSPs.
        """
        receipts: list[dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in media_plan:
            if not item.synced_creative_ids:
                raise ValueError(
                    f"AdCP Critical Path Error: Line item '{item.line_id}' cannot activate without synced creatives."
                )
            order_hash = hashlib.sha256(
                f"{tenant_id}:{campaign_id}:{item.deal_id}".encode()
            ).hexdigest()[:8].upper()
            receipts.append(
                {
                    "order_id": f"ORD-{item.channel.upper()}-{order_hash}",
                    "line_id": item.line_id,
                    "channel": item.channel,
                    "seller_agent_id": item.seller_agent_id,
                    "publisher_or_ssp": item.publisher_or_ssp,
                    "deal_id": item.deal_id,
                    "allocated_budget_usd": item.allocated_budget_usd,
                    "target_cpm_usd": item.target_cpm_usd,
                    "estimated_impressions": item.estimated_impressions,
                    "synced_creative_ids": item.synced_creative_ids,
                    "content_standards_id": content_standards_id,
                    "flight_window": f"{flight_start} -> {flight_end}",
                    "status": "ACTIVE_DELIVERING",
                    "activated_at": now_iso,
                }
            )
        return receipts
