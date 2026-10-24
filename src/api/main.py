"""
AdAiz FastAPI Gateway & Human-in-the-Loop Controller.
Traceability:
- REQ-ORCH-01, REQ-HITL-01, REQ-HARN-01, REQ-MEM-01, REQ-ADCP-01, REQ-EVAL-01
- REQ-SALES-01, REQ-LLM-01, REQ-DB-01, REQ-INSIGHTS-01
Governing Skills:
- fullstack-fastapi-architecture
- modern-fullstack-web-and-api
- security-and-multi-tenant-saas
- database-and-async-persistence
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from evals.run_evals import (
    GOLDEN_EVAL_BRIEFS,
    run_all_evaluation_gates,
    run_candidate_regression_comparison,
)
from src.graph.insights_agent import CampaignInsightsAndSagaAgent
from src.graph.rfp_agent import SAMPLE_RFP_EMAILS, SalesRFPIntakeAgent
from src.graph.state import CampaignBrief, ChannelType, CreativeAsset
from src.graph.workflow import AdAizOrchestrator
from src.harness.executor import (
    SecurityViolationError,
    mint_approval_token,
    verify_operator_role_permission,
)
from src.harness.llm_gateway import ModelCascadeGateway
from src.mcp_servers.creative_server import CreativeMCPServer
from src.memory.brand_vault import TenantAccessViolationError
from src.memory.persistence import SQLitePersistenceManager


class RunCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    campaign_id: str
    tenant_id: str = "tenant_aurora"
    brand_id: str = "aurora_ev"
    brand_name: str = "Aurora EV Motors"
    objective: str
    total_budget_usd: float = Field(gt=0)
    target_channels: list[ChannelType] = Field(min_length=1)
    target_geos: list[str] = Field(default_factory=lambda: ["SG", "US-CA"])
    audience_segments: list[str] = Field(default_factory=lambda: ["Core Audience"])
    flight_start: str = "2026-11-01"
    flight_end: str = "2026-11-30"
    simulate_dsp_503_once: bool = False


class ParseRFPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    raw_rfp_text: str = Field(min_length=10)


class HITLDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    approved: bool
    reviewer: str = "Agency Media Director"
    role: str = "media_director"
    notes: str = ""


class ForkCampaignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    new_budget_usd: float = Field(gt=0)


class CandidateEvalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_version: str = "adaiz-graph-v2.7.0-candidate"
    prompt_persona: str = "High-Conversion Executive Direct Response"
    strict_compliance: bool = True
    model_routing_tier: str = "cascade_hybrid"


class SagaRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = "Operator triggered emergency brand-safety halt & Saga rollback"


class RAGQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str
    brand_id: str
    query: str
    requesting_tenant_id: str | None = None


class BrandRuleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str
    brand_id: str
    custom_rule: str


def _serialize_state(state_values: dict[str, Any]) -> dict[str, Any]:
    """Serialize LangGraph state dictionary with Pydantic models into clean JSON."""
    if not state_values:
        return {}
    brief = state_values.get("brief")
    creatives = state_values.get("creatives", [])
    media_plan = state_values.get("media_plan", [])
    trace_events = state_values.get("trace_events", [])

    campaign_id = (
        brief.campaign_id
        if hasattr(brief, "campaign_id")
        else (brief.get("campaign_id", "") if isinstance(brief, dict) else "")
    )
    return {
        "campaign_id": campaign_id or state_values.get("campaign_id", ""),
        "config_version": state_values.get("config_version", AdAizOrchestrator.CONFIG_VERSION),
        "workflow_status": state_values.get("workflow_status", "running"),
        "brief": brief.model_dump() if hasattr(brief, "model_dump") else brief,
        "brand_guidelines": state_values.get("brand_guidelines", {}),
        "retrieved_guideline_chunks": state_values.get("retrieved_guideline_chunks", []),
        "episodic_learnings": state_values.get("episodic_learnings", []),
        "adcp_capabilities": state_values.get("adcp_capabilities", {}),
        "audience_signals": state_values.get("audience_signals", []),
        "negotiation_summary": state_values.get("negotiation_summary", {}),
        "content_standards_id": state_values.get("content_standards_id", ""),
        "creatives": [c.model_dump() if hasattr(c, "model_dump") else c for c in creatives],
        "media_plan": [m.model_dump() if hasattr(m, "model_dump") else m for m in media_plan],
        "budget_math_valid": state_values.get("budget_math_valid", False),
        "spec_all_valid": state_values.get("spec_all_valid", False),
        "compliance_status": state_values.get("compliance_status", "pending"),
        "compliance_feedback": state_values.get("compliance_feedback", ""),
        "revision_count": state_values.get("revision_count", 0),
        "security_flags": state_values.get("security_flags", []),
        "hitl_decision": state_values.get("hitl_decision"),
        "approval_jwt_present": bool(state_values.get("approval_jwt")),
        "activation_receipts": state_values.get("activation_receipts", []),
        "pacing_insights": state_values.get("pacing_insights", {}),
        "trace_events": [e.model_dump() if hasattr(e, "model_dump") else e for e in trace_events],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.orchestrator = AdAizOrchestrator()
    app.state.db = SQLitePersistenceManager()
    app.state.llm_gateway = ModelCascadeGateway()
    app.state.rfp_agent = SalesRFPIntakeAgent(gateway=app.state.llm_gateway)
    app.state.insights_agent = CampaignInsightsAndSagaAgent()
    app.state.last_eval_report = run_all_evaluation_gates()
    yield


app = FastAPI(
    title="AdAiz — Agentic Advertising Platform",
    version="2.6.0",
    description="Multi-Agent LangGraph Orchestrator with AdCP over MCP, Sales RFP Intake, Agent Harness, SQLite WAL Persistence, Post-Launch Saga Optimizer, and 4-Gate Evaluations.",
    lifespan=lifespan,
)

UI_DIR = Path(__file__).resolve().parent.parent / "ui"


@app.get("/api/v1/health")
async def health_check() -> dict[str, Any]:
    gateway: ModelCascadeGateway = app.state.llm_gateway
    db: SQLitePersistenceManager = app.state.db
    return {
        "status": "healthy",
        "service": "AdAiz Agentic Advertising Platform",
        "config_version": AdAizOrchestrator.CONFIG_VERSION,
        "protocols": ["AdCP/1.0", "MCP/Streamable-HTTP", "OpenRTB/2.6", "A2A/AgentCard", "SSE/Events"],
        "llm_gateway": gateway.get_gateway_status(),
        "persistence": {
            "engine": "SQLite WAL (adaiz_state.db)",
            "stored_campaigns_count": len(db.list_recent_campaigns(limit=100)),
        },
    }


@app.get("/api/v1/presets")
async def get_presets() -> dict[str, Any]:
    """Return golden agency presets and sample unstructured RFP emails."""
    return {
        "presets": GOLDEN_EVAL_BRIEFS,
        "rfp_samples": SAMPLE_RFP_EMAILS,
    }


@app.post("/api/v1/sales/parse-rfp")
async def parse_unstructured_rfp(req: ParseRFPRequest) -> dict[str, Any]:
    """
    REQ-SALES-01: Parse an unstructured client RFP email/brief into a structured CampaignBrief
    and generate an executive Sales Pitch & Agency Margin Proposal.
    """
    rfp_agent: SalesRFPIntakeAgent = app.state.rfp_agent
    return rfp_agent.parse_rfp_and_build_pitch(req.raw_rfp_text)


@app.post("/api/v1/campaigns/run")
async def run_campaign_workflow(req: RunCampaignRequest) -> dict[str, Any]:
    """
    Start or re-run a campaign workflow from brief up to the LangGraph `interrupt()` HITL gate,
    persisting the resulting snapshot and trace spans to SQLite WAL storage.
    """
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    brief = CampaignBrief(**req.model_dump())
    try:
        state_values = orchestrator.run_until_hitl(brief)
        serialized = _serialize_state(state_values)
        db.save_campaign_snapshot(serialized)
        return serialized
    except TenantAccessViolationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/api/v1/campaigns/{campaign_id}/stream")
async def stream_campaign_trace_sse(campaign_id: str):
    """
    Server-Sent Events (SSE) endpoint streaming step-by-step node execution spans
    for real-time progressive visualization in the Operator Console.
    """
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    state_values = orchestrator.get_campaign_state(campaign_id)
    serialized = _serialize_state(state_values) if state_values else db.load_campaign_snapshot(campaign_id)
    if not serialized:
        raise HTTPException(status_code=404, detail=f"Campaign '{campaign_id}' not found.")

    async def event_generator():
        for idx, span in enumerate(serialized.get("trace_events", [])):
            payload = json.dumps({"step": idx + 1, "span": span})
            yield f"event: trace_span\ndata: {payload}\n\n"
            await asyncio.sleep(0.02)
        yield f"event: complete\ndata: {json.dumps({'campaign_id': campaign_id, 'status': serialized.get('workflow_status')})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/v1/campaigns/{campaign_id}/approve")
async def approve_or_revise_campaign(
    campaign_id: str, req: HITLDecisionRequest
) -> dict[str, Any]:
    """
    Resume a paused workflow at `hitl_approval_gate`.
    Enforces RBAC (`REQ-FINOPS-01`): only `media_director` can authorize LIVE_SPEND.
    If approved=True, mints a cryptographic HMAC-SHA256 `approval_jwt` authorizing LIVE_SPEND.
    If approved=False, routes back into parallel creative regeneration with operator feedback.
    """
    try:
        required_tier = "LIVE_SPEND" if req.approved else "DRAFT_MUTATION"
        verify_operator_role_permission(req.role, required_tier)
    except SecurityViolationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    existing = orchestrator.get_campaign_state(campaign_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Campaign '{campaign_id}' not found.")

    brief: CampaignBrief = existing["brief"]
    jwt_token = None
    if req.approved:
        jwt_token = mint_approval_token(
            tenant_id=brief.tenant_id,
            campaign_id=brief.campaign_id,
            total_budget_usd=brief.total_budget_usd,
            reviewer=f"{req.reviewer} ({req.role})",
        )

    updated = orchestrator.resume_from_hitl(
        campaign_id=campaign_id,
        approved=req.approved,
        reviewer=f"{req.reviewer} ({req.role})",
        notes=req.notes,
        approval_jwt=jwt_token,
    )
    serialized = _serialize_state(updated)
    db.save_campaign_snapshot(serialized)
    db.record_flywheel_entry(
        campaign_id=campaign_id,
        tenant_id=brief.tenant_id,
        brand_id=brief.brand_id,
        approved=req.approved,
        reviewer=f"{req.reviewer} ({req.role})",
        notes=req.notes,
    )
    return serialized


@app.get("/api/v1/campaigns/{campaign_id}/ad-tags")
async def export_campaign_ad_tags(campaign_id: str) -> dict[str, Any]:
    """
    REQ-DCO-01: Export standards-compliant IAB VAST 4.2 XML (CTV/Video) and
    HTML5 clickTag Ad Bundles (Display/DOOH) + DCO Variants for all campaign creatives.
    """
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    state_values = orchestrator.get_campaign_state(campaign_id)
    serialized = _serialize_state(state_values) if state_values else db.load_campaign_snapshot(campaign_id)
    if not serialized:
        raise HTTPException(status_code=404, detail=f"Campaign '{campaign_id}' not found.")

    brand_name = serialized.get("brief", {}).get("brand_name", "Brand")
    tags = []
    for raw_c in serialized.get("creatives", []):
        asset = CreativeAsset(**raw_c) if isinstance(raw_c, dict) else raw_c
        tags.append(CreativeMCPServer.export_traffickable_ad_tag(asset, brand_name=brand_name))
    return {"campaign_id": campaign_id, "ad_tags": tags}


@app.get("/api/v1/campaigns/{campaign_id}/checkpoints")
async def get_campaign_checkpoints(campaign_id: str) -> dict[str, Any]:
    """
    REQ-ORCH-02: Return LangGraph state checkpoint timeline for Time-Travel inspection.
    """
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    history = orchestrator.get_checkpoint_history(campaign_id)
    return {"campaign_id": campaign_id, "checkpoints": history}


@app.post("/api/v1/campaigns/{campaign_id}/fork")
async def fork_campaign_checkpoint(
    campaign_id: str, req: ForkCampaignRequest
) -> dict[str, Any]:
    """
    REQ-ORCH-02: Time-Travel / State Forking — clone a campaign from its checkpoint history
    with a modified budget and re-orchestrate in a new forked thread.
    """
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    try:
        forked_state = orchestrator.fork_campaign_with_new_budget(
            source_campaign_id=campaign_id, new_budget_usd=req.new_budget_usd
        )
        serialized = _serialize_state(forked_state)
        db.save_campaign_snapshot(serialized)
        return serialized
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/campaigns/{campaign_id}/optimize-pacing")
async def optimize_active_campaign_pacing(campaign_id: str) -> dict[str, Any]:
    """
    REQ-INSIGHTS-01: Run Post-Launch Autonomous Pacing Optimization & OpenRTB Bid-Shading
    with penny-perfect budget conservation.
    """
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    insights_agent: CampaignInsightsAndSagaAgent = app.state.insights_agent

    state_values = orchestrator.get_campaign_state(campaign_id)
    serialized = _serialize_state(state_values) if state_values else db.load_campaign_snapshot(campaign_id)
    if not serialized:
        raise HTTPException(status_code=404, detail=f"Campaign '{campaign_id}' not found.")

    optimized = insights_agent.optimize_campaign_pacing(serialized)
    db.save_campaign_snapshot(optimized)
    return optimized


@app.post("/api/v1/campaigns/{campaign_id}/saga-rollback")
async def saga_rollback_active_campaign(
    campaign_id: str, req: SagaRollbackRequest
) -> dict[str, Any]:
    """
    REQ-INSIGHTS-01: Execute Saga Compensating Transactions across all active DSP orders,
    releasing media budget holds and returning campaign to quarantine/review.
    """
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    insights_agent: CampaignInsightsAndSagaAgent = app.state.insights_agent

    state_values = orchestrator.get_campaign_state(campaign_id)
    serialized = _serialize_state(state_values) if state_values else db.load_campaign_snapshot(campaign_id)
    if not serialized:
        raise HTTPException(status_code=404, detail=f"Campaign '{campaign_id}' not found.")

    rolled_back = insights_agent.saga_rollback_campaign(serialized, reason=req.reason)
    db.save_campaign_snapshot(rolled_back)
    return rolled_back


@app.get("/api/v1/campaigns")
async def list_persisted_campaigns(tenant_id: str | None = None) -> dict[str, Any]:
    db: SQLitePersistenceManager = app.state.db
    return {"campaigns": db.list_recent_campaigns(tenant_id=tenant_id)}


@app.get("/api/v1/campaigns/{campaign_id}")
async def get_campaign(campaign_id: str) -> dict[str, Any]:
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    state_values = orchestrator.get_campaign_state(campaign_id)
    if state_values:
        return _serialize_state(state_values)
    persisted = db.load_campaign_snapshot(campaign_id)
    if persisted:
        return persisted
    raise HTTPException(status_code=404, detail=f"Campaign '{campaign_id}' not found.")


@app.get("/api/v1/vault/{tenant_id}/{brand_id}")
async def get_brand_vault(
    tenant_id: str, brand_id: str, requesting_tenant_id: str | None = None
) -> dict[str, Any]:
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    try:
        profile = orchestrator.brand_vault.get_brand_profile(
            tenant_id=tenant_id,
            brand_id=brand_id,
            requesting_tenant_id=requesting_tenant_id,
        )
        learnings = orchestrator.episodic_memory.get_learnings(tenant_id, brand_id)
        return {
            "profile": profile,
            "episodic_learnings": learnings,
            "flywheel_entries": [
                e
                for e in orchestrator.episodic_memory.dataset_flywheel
                if e["tenant_id"] == tenant_id
            ],
        }
    except TenantAccessViolationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.delete("/api/v1/vault/{tenant_id}")
async def gdpr_purge_tenant(tenant_id: str) -> dict[str, Any]:
    """
    REQ-DB-01: GDPR / CCPA Right-to-Erasure cascading purge across SQLite tables,
    Hybrid RAG Brand Vault, and Episodic Memory.
    """
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    db: SQLitePersistenceManager = app.state.db
    vault_deleted = orchestrator.brand_vault.purge_tenant_data(tenant_id)
    db_deleted = db.purge_tenant_completely(tenant_id)
    return {
        "tenant_id": tenant_id,
        "status": "GDPR_CASCADING_ERASURE_COMPLETE",
        "brand_vault_profiles_purged": vault_deleted,
        **db_deleted,
    }


@app.post("/api/v1/vault/search")
async def search_brand_vault(req: RAGQueryRequest) -> dict[str, Any]:
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    try:
        orchestrator.brand_vault.get_brand_profile(
            tenant_id=req.tenant_id,
            brand_id=req.brand_id,
            requesting_tenant_id=req.requesting_tenant_id or req.tenant_id,
        )
        chunks = orchestrator.brand_vault.retrieve_hybrid_rrf(
            tenant_id=req.tenant_id,
            brand_id=req.brand_id,
            query=req.query,
            top_k=4,
        )
        return {"results": chunks}
    except TenantAccessViolationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.post("/api/v1/vault/rules")
async def add_brand_rule(req: BrandRuleUpdateRequest) -> dict[str, Any]:
    orchestrator: AdAizOrchestrator = app.state.orchestrator
    profile = orchestrator.brand_vault.update_brand_guidelines(
        tenant_id=req.tenant_id,
        brand_id=req.brand_id,
        custom_rule=req.custom_rule,
    )
    return {"profile": profile}


@app.get("/api/v1/evals/latest")
async def get_latest_evals() -> dict[str, Any]:
    return app.state.last_eval_report


@app.post("/api/v1/evals/run")
async def trigger_eval_suite() -> dict[str, Any]:
    report = run_all_evaluation_gates()
    app.state.last_eval_report = report
    return report


@app.post("/api/v1/evals/compare-candidate")
async def compare_candidate_eval_config(req: CandidateEvalRequest) -> dict[str, Any]:
    """
    REQ-EVAL-02: Run the Interactive Prompt & Config Version Regression Comparator.
    """
    return run_candidate_regression_comparison(
        candidate_version=req.candidate_version,
        prompt_persona=req.prompt_persona,
        strict_compliance=req.strict_compliance,
        model_routing_tier=req.model_routing_tier,
    )


@app.get("/")
async def serve_operator_console():
    return FileResponse(UI_DIR / "index.html")


if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")
