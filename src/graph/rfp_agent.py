"""
Sales & Unstructured RFP Intake Agent (Tier-1 Scoped Agent + Deterministic Yield Calculator).
Covers JD requirement: "creative, sales and campaign workflows".

Traceability: REQ-SALES-01
Governing Skills:
- langgraph-multi-agent-orchestration
- product-engineering-and-technical-rfcs
- finops-and-saas-monetization
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from src.graph.state import CampaignBrief, ChannelType
from src.harness.executor import sanitize_untrusted_text
from src.harness.llm_gateway import ModelCascadeGateway


SAMPLE_RFP_EMAILS: list[dict[str, str]] = [
    {
        "rfp_id": "RFP-2026-AURORA-Q4",
        "title": "Aurora EV Motors — Q4 APAC & US West Coast Launch RFP ($125,000)",
        "raw_text": (
            "Subject: RFP — Q4 Omnichannel Launch for Aurora EV Motors\n"
            "Hi Agency Sales Team,\n"
            "We need a full omnichannel proposal for Aurora EV Motors launching our new 380-mile range GT. "
            "Our total budget is $125,000 running from 2026-11-01 to 2026-11-30 across Singapore (SG) and California (US-CA). "
            "Please include Connected TV (CTV), Urban DOOH digital screens, Online Video, and high-impact Display banners "
            "targeting EV Intenders and Luxury Auto Buyers."
        ),
    },
    {
        "rfp_id": "RFP-2026-NOVAPAY-CFO",
        "title": "NovaPay Treasury — B2B Cross-Border Liquidity Pitch ($68,500)",
        "raw_text": (
            "Subject: Media & Creative Pitch Request — NovaPay B2B Treasury\n"
            "Team, NovaPay Treasury is allocating $68,500 for our institutional FX & cross-border liquidity campaign "
            "in Singapore (SG) and Hong Kong (HK). We want Connected TV (CTV), Display banners on financial news, "
            "and CBD DOOH totems targeting Enterprise CFOs and Corporate Treasurers."
        ),
    },
    {
        "rfp_id": "RFP-2026-VERVE-COMMUTE",
        "title": "Verve Nitro Cold Brew — Urban Commuter Blitz ($45,000)",
        "raw_text": (
            "Subject: Urgent Q4 Brief — Verve Nitro Cold Brew\n"
            "We have $45,000 to promote Verve Nitro Cold Brew (0g added sugar, 140mg natural caffeine) "
            "in New York (US-NY) and London (GB-LON). Focus heavily on DOOH commuter screens, vertical Online Video, and CTV."
        ),
    },
]


class SalesRFPIntakeAgent:
    """
    Tier-1 Scoped Agent that parses unstructured client RFP emails/documents into a validated
    `CampaignBrief` and computes a commercial Agency Sales Pitch & Margin Proposal.
    """

    def __init__(self, gateway: ModelCascadeGateway | None = None) -> None:
        self.gateway = gateway or ModelCascadeGateway()

    def parse_rfp_and_build_pitch(self, raw_rfp_text: str) -> dict[str, Any]:
        """
        Extract structured campaign parameters from unstructured RFP text and build
        an executive Sales Pitch Proposal with deterministic yield & margin math.
        """
        clean_text = sanitize_untrusted_text(raw_rfp_text)

        def _deterministic_extractor() -> dict[str, Any]:
            lower = clean_text.lower()

            # 1. Detect brand & tenant
            if "novapay" in lower or "treasury" in lower or "fx" in lower:
                tenant_id = "tenant_nova"
                brand_id = "novapay"
                brand_name = "NovaPay Treasury"
            elif "verve" in lower or "cold brew" in lower or "coffee" in lower:
                tenant_id = "tenant_verve"
                brand_id = "verve_brew"
                brand_name = "Verve Nitro Cold Brew"
            else:
                tenant_id = "tenant_aurora"
                brand_id = "aurora_ev"
                brand_name = "Aurora EV Motors"

            # 2. Extract dollar budget (e.g., $125,000 or 68500)
            budget_usd = 75000.00
            dollar_match = re.search(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{2})?|[0-9]{4,9}(?:\.[0-9]{2})?)", clean_text)
            if dollar_match:
                budget_usd = float(dollar_match.group(1).replace(",", ""))
            else:
                k_match = re.search(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s*k\b", lower)
                if k_match:
                    budget_usd = float(k_match.group(1)) * 1000.0

            # 3. Extract channels
            channels: list[ChannelType] = []
            if any(k in lower for k in ["display", "banner", "iab", "omnichannel"]):
                channels.append("display")
            if any(k in lower for k in ["online video", "vertical video", "olv", "video", "omnichannel"]):
                channels.append("video")
            if any(k in lower for k in ["ctv", "connected tv", "streaming", "omnichannel"]):
                channels.append("ctv")
            if any(k in lower for k in ["dooh", "out-of-home", "billboard", "totem", "screen", "omnichannel"]):
                channels.append("dooh")
            if not channels:
                channels = ["display", "ctv", "dooh"]

            # 4. Extract geos
            geos: list[str] = []
            geo_patterns = {
                "SG": r"\b(sg|singapore)\b",
                "HK": r"\b(hk|hong kong)\b",
                "US-CA": r"\b(us-ca|california)\b",
                "US-NY": r"\b(us-ny|new york)\b",
                "GB-LON": r"\b(gb-lon|london|uk)\b",
            }
            for code, pat in geo_patterns.items():
                if re.search(pat, lower):
                    geos.append(code)
            if not geos:
                geos = ["SG", "US-CA"]

            # 5. Extract clean objective summary
            lines = [
                ln.strip()
                for ln in clean_text.splitlines()
                if ln.strip() and not ln.strip().lower().startswith("subject:")
                and not ln.strip().lower().startswith("hi ")
            ]
            objective = " ".join(lines)[:200] if lines else clean_text[:200]

            rfp_hash = hashlib.md5(clean_text.encode("utf-8")).hexdigest()[:6]
            return {
                "campaign_id": f"rfp_{brand_id}_{rfp_hash}",
                "tenant_id": tenant_id,
                "brand_id": brand_id,
                "brand_name": brand_name,
                "objective": objective,
                "total_budget_usd": round(budget_usd, 2),
                "target_channels": channels,
                "target_geos": geos,
                "audience_segments": ["RFP Target Audience", "High-Intent Decision Makers"],
                "flight_start": "2026-11-01",
                "flight_end": "2026-11-30",
            }

        extracted_dict, provider_used = self.gateway.generate_structured_json(
            task_tier="tier_1_fast_extraction",
            system_prompt="Extract structured advertising CampaignBrief fields from raw RFP text.",
            user_prompt=clean_text,
            fallback_fn=_deterministic_extractor,
        )

        # Ensure extracted dict conforms strictly to CampaignBrief
        try:
            brief = CampaignBrief(**extracted_dict)
        except Exception:
            brief = CampaignBrief(**_deterministic_extractor())

        # Deterministic Sales Yield & Commercial Pitch Calculation
        gross_budget = brief.total_budget_usd
        agency_platform_fee_usd = round(gross_budget * 0.12, 2)  # 12% agency orchestration & managed service margin
        working_media_usd = round(gross_budget - agency_platform_fee_usd, 2)
        blended_est_cpm = 14.80
        estimated_total_impressions = int((gross_budget / blended_est_cpm) * 1000)

        pitch_proposal = {
            "proposal_id": f"PITCH-{brief.campaign_id.upper()}",
            "extraction_provider": provider_used,
            "gross_client_budget_usd": gross_budget,
            "working_media_spend_usd": working_media_usd,
            "agency_platform_margin_usd": agency_platform_fee_usd,
            "agency_margin_pct": 12.0,
            "estimated_impressions": estimated_total_impressions,
            "estimated_blended_cpm_usd": blended_est_cpm,
            "recommended_flight": f"{brief.flight_start} to {brief.flight_end}",
            "executive_pitch_summary": (
                f"Omnichannel proposal for {brief.brand_name} across {', '.join(ch.upper() for ch in brief.target_channels)} "
                f"in {', '.join(brief.target_geos)} delivering ~{estimated_total_impressions:,} impressions via AdCP PMP/PG deals."
            ),
        }

        return {
            "extracted_brief": brief.model_dump(),
            "sales_pitch_proposal": pitch_proposal,
        }
