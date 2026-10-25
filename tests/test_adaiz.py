"""
Automated Pytest Verification Suite for AdAiz.
Covers all Specification Requirement IDs (REQ-ORCH-01, REQ-HITL-01, REQ-HARN-01,
REQ-MEM-01, REQ-ADCP-01, REQ-MMQA-01, REQ-EVAL-01).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from evals.run_evals import run_all_evaluation_gates
from src.api.main import app
from src.graph.state import CampaignBrief
from src.graph.workflow import AdAizOrchestrator
from src.harness.executor import (
    AgentHarness,
    BudgetCircuitBreakerError,
    SecurityViolationError,
    mint_approval_token,
    verify_approval_token,
)
from src.mcp_servers.adcp_server import AdCPServer
from src.memory.brand_vault import HybridBrandVault, TenantAccessViolationError


def test_req_adcp_01_penny_perfect_budget_conservation() -> None:
    """REQ-ADCP-01: Verify zero budget drift across arbitrary odd dollar amounts."""
    adcp = AdCPServer()
    for budget in [100.01, 13579.97, 87543.29, 250000.03]:
        products = adcp.get_products(
            campaign_id="test_math",
            buying_mode="brief",
            brief_summary="Omnichannel test",
            channels=["display", "video", "ctv", "dooh"],
            target_geos=["SG"],
        )
        plan = adcp.allocate_media_budget_deterministic("test_math", budget, products)
        assert len(plan) == 4
        assert round(sum(p.allocated_budget_usd for p in plan), 2) == budget
        assert all(p.estimated_impressions > 0 for p in plan)


def test_req_mem_01_hybrid_rag_and_multi_tenant_isolation() -> None:
    """REQ-MEM-01: Verify Hybrid RAG RRF retrieval and strict tenant isolation."""
    vault = HybridBrandVault()
    chunks = vault.retrieve_hybrid_rrf(
        tenant_id="tenant_aurora",
        brand_id="aurora_ev",
        query="DOOH word limit CTV overscan safe zone",
        top_k=3,
    )
    assert len(chunks) >= 1
    assert any(c["rule_id"].startswith("AUR-") for c in chunks)

    # Cross-tenant probing must raise TenantAccessViolationError
    with pytest.raises(TenantAccessViolationError):
        vault.get_brand_profile(
            tenant_id="tenant_nova",
            brand_id="novapay",
            requesting_tenant_id="tenant_aurora",
        )


def test_req_harn_01_live_spend_hmac_guard_and_circuit_breaker() -> None:
    """REQ-HARN-01: Verify LIVE_SPEND blocks unapproved calls and enforces FinOps circuit breaker."""
    harness = AgentHarness(max_steps=10, max_run_cost_usd=0.01)

    # Unapproved LIVE_SPEND call must raise SecurityViolationError
    with pytest.raises(SecurityViolationError):
        harness.execute_tool(
            node_name="test_node",
            tool_name="adcp_create_media_buy",
            tier="LIVE_SPEND",
            fn=lambda: {"ok": True},
            kwargs={},
            tenant_id="tenant_aurora",
            campaign_id="camp_sec_01",
            approval_jwt=None,
            expected_budget_usd=50000.0,
        )

    # Valid HMAC token for $50,000 must fail if budget changes to $60,000
    token = mint_approval_token("tenant_aurora", "camp_sec_01", 50000.0, "Tester")
    with pytest.raises(SecurityViolationError):
        verify_approval_token(token, "tenant_aurora", "camp_sec_01", 60000.0)

    # FinOps circuit breaker must trip when estimated_cost_usd exceeds ceiling
    with pytest.raises(BudgetCircuitBreakerError):
        harness.execute_tool(
            node_name="test_node",
            tool_name="expensive_tool",
            tier="READ_ONLY",
            fn=lambda: {"ok": True},
            kwargs={},
            tenant_id="tenant_aurora",
            campaign_id="camp_sec_01",
            estimated_cost_usd=0.05,
        )


def test_req_orch_01_and_hitl_01_end_to_end_langgraph_workflow() -> None:
    """REQ-ORCH-01 & REQ-HITL-01: Verify parallel Send(), compliance self-healing, and interrupt() HITL."""
    orchestrator = AdAizOrchestrator()
    brief = CampaignBrief(
        campaign_id="pytest_e2e_01",
        tenant_id="tenant_nova",
        brand_id="novapay",
        brand_name="NovaPay Treasury",
        objective="Launch NovaPay with Guaranteed 10x return and 503 recovery test.",
        total_budget_usd=54321.19,
        target_channels=["display", "ctv", "dooh"],
        target_geos=["SG"],
        simulate_dsp_503_once=True,
    )

    paused = orchestrator.run_until_hitl(brief)
    assert paused["workflow_status"] == "awaiting_human_approval"
    assert paused["revision_count"] == 1  # Self-corrected prohibited 'Guaranteed 10x' claim
    assert len(paused["creatives"]) == 3
    assert all(c.compliance_passed for c in paused["creatives"])

    # Request revision from human at HITL gate first
    revised = orchestrator.resume_from_hitl(
        campaign_id=brief.campaign_id,
        approved=False,
        reviewer="Media Director",
        notes="Emphasize institutional FX liquidity in headline.",
    )
    assert revised["workflow_status"] == "awaiting_human_approval"
    assert revised["revision_count"] == 2

    # Now approve with cryptographic JWT
    jwt_token = mint_approval_token(
        brief.tenant_id, brief.campaign_id, brief.total_budget_usd, "Media Director"
    )
    final = orchestrator.resume_from_hitl(
        campaign_id=brief.campaign_id,
        approved=True,
        reviewer="Media Director",
        notes="Looks great, ship it.",
        approval_jwt=jwt_token,
    )
    assert final["workflow_status"] == "active"
    assert len(final["activation_receipts"]) == 3


def test_req_eval_01_full_four_gate_evaluation_suite() -> None:
    """REQ-EVAL-01: Run the entire 4-Gate Evaluation Suite and assert 100% pass rate."""
    report = run_all_evaluation_gates()
    assert report["overall_passed"] is True
    assert report["gates"]["gate1_deterministic_specs_and_math"]["score_pct"] == 100.0
    assert report["gates"]["gate2_trajectory_and_fault_recovery"]["score_pct"] == 100.0
    assert report["gates"]["gate3_compliance_and_redteaming"]["score_pct"] == 100.0


def test_fastapi_operator_console_and_hitl_api_contracts() -> None:
    """Verify FastAPI endpoints, Operator UI serving, HITL approval flow, and cross-tenant HTTP 403."""
    with TestClient(app) as client:
        # 1. Health & UI root
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        ui_res = client.get("/")
        assert ui_res.status_code == 200
        assert "AdAiz" in ui_res.text

        # 2. Run campaign up to HITL interrupt()
        run_res = client.post(
            "/api/v1/campaigns/run",
            json={
                "campaign_id": "api_test_camp_01",
                "tenant_id": "tenant_aurora",
                "brand_id": "aurora_ev",
                "brand_name": "Aurora EV Motors",
                "objective": "Drive Q4 EV test drives across Singapore and California.",
                "total_budget_usd": 75000.00,
                "target_channels": ["display", "ctv", "dooh"],
                "target_geos": ["SG", "US-CA"],
                "simulate_dsp_503_once": True,
            },
        )
        assert run_res.status_code == 200
        state_data = run_res.json()
        assert state_data["workflow_status"] == "awaiting_human_approval"
        assert state_data["budget_math_valid"] is True

        # 3. Approve via HITL endpoint (mints HMAC-SHA256 JWT and activates DSP orders)
        app_res = client.post(
            "/api/v1/campaigns/api_test_camp_01/approve",
            json={
                "approved": True,
                "reviewer": "VP Media Operations",
                "notes": "Approved for Q4 launch",
            },
        )
        assert app_res.status_code == 200
        final_data = app_res.json()
        assert final_data["workflow_status"] == "active"
        assert len(final_data["activation_receipts"]) == 3

        # 4. Cross-tenant vault probe must return HTTP 403 Forbidden
        forbidden_res = client.get(
            "/api/v1/vault/tenant_nova/novapay?requesting_tenant_id=tenant_aurora"
        )
        assert forbidden_res.status_code == 403

        # 5. REQ-SALES-01: Unstructured RFP Intake & Commercial Pitch Proposal
        rfp_res = client.post(
            "/api/v1/sales/parse-rfp",
            json={
                "raw_rfp_text": (
                    "Subject: Q4 Launch RFP for Aurora EV Motors\n"
                    "We have $125,000 for Singapore (SG) and California (US-CA) across CTV, DOOH billboards, and Display."
                )
            },
        )
        assert rfp_res.status_code == 200
        rfp_data = rfp_res.json()
        assert rfp_data["extracted_brief"]["total_budget_usd"] == 125000.0
        assert "ctv" in rfp_data["extracted_brief"]["target_channels"]
        assert "dooh" in rfp_data["extracted_brief"]["target_channels"]
        assert rfp_data["sales_pitch_proposal"]["agency_margin_pct"] == 12.0

        # 6. REQ-INSIGHTS-01: Post-Launch Autonomous Pacing Optimization & Bid-Shading
        opt_res = client.post("/api/v1/campaigns/api_test_camp_01/optimize-pacing")
        assert opt_res.status_code == 200
        opt_data = opt_res.json()
        assert opt_data["pacing_insights"]["optimization_applied"] is True
        assert round(sum(m["allocated_budget_usd"] for m in opt_data["media_plan"]), 2) == 75000.00

        # 7. SSE Streaming Endpoint (`GET /api/v1/campaigns/{id}/stream`)
        sse_res = client.get("/api/v1/campaigns/api_test_camp_01/stream")
        assert sse_res.status_code == 200
        assert "event: trace_span" in sse_res.text
        assert "event: complete" in sse_res.text

        # 8. REQ-INSIGHTS-01: Saga Compensating Rollback (`cancel_media_buy`)
        saga_res = client.post(
            "/api/v1/campaigns/api_test_camp_01/saga-rollback",
            json={"reason": "Pytest Saga rollback verification"},
        )
        assert saga_res.status_code == 200
        saga_data = saga_res.json()
        assert all(
            r["status"] == "SAGA_ROLLED_BACK_CREDITED" for r in saga_data["activation_receipts"]
        )
        assert all(m["adcp_status"] == "quarantined" for m in saga_data["media_plan"])

        # 9. REQ-A2A-02 & REQ-AUD-01: Verify 3-Round A2A Negotiation Savings & Audience Clean-Room Signals
        assert state_data["negotiation_summary"]["rounds_completed"] == 3
        assert state_data["negotiation_summary"]["total_client_savings_usd"] > 0
        assert len(state_data["audience_signals"]) >= 1
        assert all("uid2_clean_room_cohort" in s for s in state_data["audience_signals"])

        # 10. REQ-DCO-01: Export IAB VAST 4.2 XML & HTML5 clickTag Ad Bundles + DCO Variants
        tags_res = client.get("/api/v1/campaigns/api_test_camp_01/ad-tags")
        assert tags_res.status_code == 200
        ad_tags = tags_res.json()["ad_tags"]
        assert len(ad_tags) == 3
        ctv_tag = next(t for t in ad_tags if t["channel"] == "ctv")
        disp_tag = next(t for t in ad_tags if t["channel"] == "display")
        assert "<VAST version=\"4.2\"" in ctv_tag["code"]
        assert "var clickTag" in disp_tag["code"]
        assert len(ctv_tag["dco_variants"]) == 2

        # 11. REQ-ORCH-02: LangGraph Time-Travel Checkpoint History & State Forking
        cp_res = client.get("/api/v1/campaigns/api_test_camp_01/checkpoints")
        assert cp_res.status_code == 200
        assert len(cp_res.json()["checkpoints"]) >= 1

        fork_res = client.post(
            "/api/v1/campaigns/api_test_camp_01/fork",
            json={"new_budget_usd": 110000.00},
        )
        assert fork_res.status_code == 200
        fork_data = fork_res.json()
        assert fork_data["brief"]["total_budget_usd"] == 110000.00
        assert fork_data["workflow_status"] == "awaiting_human_approval"

        # 12. REQ-FINOPS-01: RBAC Role Enforcement (media_planner blocked from approving LIVE_SPEND)
        rbac_block_res = client.post(
            f"/api/v1/campaigns/{fork_data['campaign_id']}/approve",
            json={
                "approved": True,
                "reviewer": "Junior Planner",
                "role": "media_planner",
                "notes": "Trying to approve live spend without director role",
            },
        )
        assert rbac_block_res.status_code == 403
        assert "RBAC Permission Denied" in rbac_block_res.json()["detail"]

        # 13. REQ-EVAL-02: Interactive Candidate Prompt & Config Version Regression Lab
        cand_pass_res = client.post(
            "/api/v1/evals/compare-candidate",
            json={
                "candidate_version": "adaiz-graph-v2.7.0-rc1",
                "prompt_persona": "Executive Direct",
                "strict_compliance": True,
                "model_routing_tier": "flash_optimized",
            },
        )
        assert cand_pass_res.status_code == 200
        assert cand_pass_res.json()["ci_cd_verdict"] == "ALLOW_DEPLOY"

        cand_block_res = client.post(
            "/api/v1/evals/compare-candidate",
            json={
                "candidate_version": "adaiz-graph-v2.7.0-unsafe",
                "prompt_persona": "Aggressive Hype",
                "strict_compliance": False,
                "model_routing_tier": "cascade_hybrid",
            },
        )
        assert cand_block_res.status_code == 200
        assert cand_block_res.json()["ci_cd_verdict"] == "BLOCK_DEPLOY_REGRESSION"

        # 14. REQ-ANALYTICS-01: Omnichannel Shapley Multi-Touch Attribution & ROAS Mart
        attr_res = client.get("/api/v1/campaigns/api_test_camp_01/attribution")
        assert attr_res.status_code == 200
        attr_data = attr_res.json()
        breakdown = attr_data["channel_breakdown"]
        assert len(breakdown) == 3
        assert round(sum(c["shapley_credit_weight"] for c in breakdown), 4) == 1.0
        assert round(sum(c["last_touch_weight"] for c in breakdown), 4) == 1.0
        assert attr_data["summary_kpis"]["blended_roas"] > 2.5
        assert len(attr_data["conversion_funnel"]) == 4




