"""
AdAiz Domain Contracts & LangGraph State Specification.
Traceability: REQ-ORCH-01, REQ-HITL-01, REQ-ADCP-01, REQ-MMQA-01
Governing Skills:
- spec-driven-development-kit
- langgraph-multi-agent-orchestration
- adcp-and-adtech-protocols
"""

from __future__ import annotations

from operator import add
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict

ChannelType = Literal["display", "video", "ctv", "dooh"]
SensitivityTier = Literal["READ_ONLY", "DRAFT_MUTATION", "LIVE_SPEND"]


class CampaignBrief(BaseModel):
    """Validated client campaign brief input contract."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    campaign_id: str = Field(description="Unique campaign correlation ID")
    tenant_id: str = Field(description="Multi-tenant isolation namespace ID")
    brand_id: str = Field(description="Brand identifier within the tenant")
    brand_name: str = Field(description="Human-readable brand name")
    objective: str = Field(description="Primary campaign objective and product message")
    total_budget_usd: float = Field(gt=0, description="Total campaign media budget in USD")
    target_channels: list[ChannelType] = Field(min_length=1, description="Omnichannel mix")
    target_geos: list[str] = Field(min_length=1, description="ISO country/metro codes")
    audience_segments: list[str] = Field(default_factory=list, description="Target audience segments")
    flight_start: str = Field(default="2026-11-01", description="ISO start date")
    flight_end: str = Field(default="2026-11-30", description="ISO end date")
    simulate_dsp_503_once: bool = Field(
        default=False,
        description="Chaos/Fault-injection toggle: simulates a transient 503 timeout on first SSP/DSP call",
    )


class CreativeAsset(BaseModel):
    """Omnichannel creative asset contract with automated QA & C2PA provenance metadata."""

    asset_id: str
    channel: ChannelType
    format_name: str
    dimensions: str  # e.g., "300x250", "1920x1080", "1080x1920"
    duration_sec: int | None = None
    has_audio: bool = False
    safe_zone_inset_pct: int = 0
    headline: str
    subheadline: str = ""
    cta_text: str = ""
    primary_hex: str = "#4F46E5"
    background_hex: str = "#0F172A"
    contrast_ratio: float = 7.5
    word_count: int = 0
    visual_scene_description: str = ""
    storyboard_beats: list[str] = Field(default_factory=list)
    contextual_triggers: list[str] = Field(default_factory=list)
    dco_variants: list[dict[str, Any]] = Field(default_factory=list)
    disclaimer_text: str = ""
    c2pa_provenance: dict[str, Any] = Field(default_factory=dict)
    spec_valid: bool = True
    spec_errors: list[str] = Field(default_factory=list)
    compliance_passed: bool = False
    compliance_score: float = 0.0
    compliance_notes: str = ""
    cited_rule_ids: list[str] = Field(default_factory=list)


class MediaLineItem(BaseModel):
    """Programmatic media buy package discovered via AdCP / OpenRTB 2.6 PMP deals."""

    line_id: str
    channel: ChannelType
    seller_agent_id: str
    publisher_or_ssp: str
    product_name: str
    deal_id: str
    buying_type: Literal["PMP", "PG", "OpenRTB_2.6"] = "PMP"
    rate_card_cpm_usd: float = 0.0
    allocated_budget_usd: float
    target_cpm_usd: float
    negotiated_savings_pct: float = 0.0
    negotiated_savings_usd: float = 0.0
    bonus_impressions: int = 0
    estimated_impressions: int
    a2a_negotiation_transcript: list[str] = Field(default_factory=list)
    synced_creative_ids: list[str] = Field(default_factory=list)
    adcp_status: Literal["discovered", "creatives_synced", "active", "quarantined"] = "discovered"


class ExecutionTraceEvent(BaseModel):
    """OpenTelemetry GenAI & AgentOps compatible span record."""

    timestamp: str
    node: str
    event_type: Literal[
        "route",
        "tool_call",
        "retry",
        "guardrail",
        "rag_retrieval",
        "hitl",
        "activation",
        "security",
    ]
    summary: str
    duration_ms: float
    cost_usd: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


def merge_creatives_by_channel(
    existing: list[CreativeAsset], new: list[CreativeAsset]
) -> list[CreativeAsset]:
    """
    Parallel-safe reducer for LangGraph Send() workers.
    Deduplicates by channel so revisions cleanly overwrite the previous asset for that channel.
    """
    if not existing:
        existing = []
    by_channel: dict[str, CreativeAsset] = {item.channel: item for item in existing}
    for item in new:
        by_channel[item.channel] = item
    order = ["display", "video", "ctv", "dooh"]
    return sorted(
        by_channel.values(),
        key=lambda x: order.index(x.channel) if x.channel in order else 99,
    )


class AdAizGraphState(TypedDict, total=False):
    """Shared stateful workflow dictionary for the AdAiz LangGraph orchestrator."""

    brief: CampaignBrief
    config_version: str
    brand_guidelines: dict[str, Any]
    retrieved_guideline_chunks: list[dict[str, Any]]
    episodic_learnings: list[str]
    adcp_capabilities: dict[str, Any]
    audience_signals: list[dict[str, Any]]
    negotiation_summary: dict[str, Any]
    content_standards_id: str
    # Parallel fan-in reducer for omnichannel creative workers
    creatives: Annotated[list[CreativeAsset], merge_creatives_by_channel]
    media_plan: list[MediaLineItem]
    budget_math_valid: bool
    spec_all_valid: bool
    compliance_status: Literal["pending", "approved", "rejected"]
    compliance_feedback: str
    revision_count: int
    metacognition: dict[str, Any]
    security_flags: list[str]
    hitl_decision: dict[str, Any] | None
    approval_jwt: str | None
    activation_receipts: list[dict[str, Any]]
    pacing_insights: dict[str, Any]
    workflow_status: Literal[
        "running",
        "awaiting_human_approval",
        "active",
        "revision_requested",
        "blocked_security",
    ]
    trace_events: Annotated[list[ExecutionTraceEvent], add]
