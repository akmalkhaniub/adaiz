"""
Unit & Integration Tests for the 2026 Agentic Architecture Upgrades:
- Task 1 (REQ-MCP-02): FastMCP Wire-Protocol Adapter (Tools, Resources, Prompts, STDIO/SSE)
- Task 2 (REQ-OTEL-01): Arize Phoenix / OpenTelemetry Tracing Instrumentation
- Task 3 (REQ-META-01): Metacognitive StagnationDetector & ConfidenceGate in LangGraph
- Task 4 (REQ-JUDGE-01): Gate 3.5 LLM-as-a-Judge Semantic Rubric in 4-Gate Evals
"""

from __future__ import annotations

import json
import pytest

from evals.run_evals import evaluate_creatives_llm_as_a_judge, run_all_evaluation_gates
from src.graph.metacognition import (
    AgentStagnationError,
    ConfidenceGate,
    StagnationDetector,
)
from src.graph.state import CampaignBrief, CreativeAsset
from src.graph.workflow import AdAizOrchestrator
from src.harness.tracing import get_tracing_status, setup_agent_tracing
from src.mcp_servers.fastmcp_runner import (
    REGISTERED_PROMPTS,
    REGISTERED_RESOURCES,
    REGISTERED_TOOLS,
    adcp_allocate_budget,
    adcp_get_capabilities,
    adcp_get_products,
    campaign_brief_template,
    creative_generate_omnichannel,
    creative_validate_compliance,
    get_brand_vault_resource,
    get_fastmcp_manifest,
    mcp,
)
from src.memory.brand_vault import HybridBrandVault


# ============================================================================
# Task 1: REQ-MCP-02 — FastMCP Wire-Protocol Server Adapter
# ============================================================================


def test_req_mcp_02_fastmcp_tools_resources_and_prompts() -> None:
    """Verify FastMCP wire adapter exposes 5 tools, 1 resource, and 1 prompt."""
    assert mcp is not None
    manifest = get_fastmcp_manifest()
    assert len(manifest["tools"]) == 5
    assert "adcp://brands/{tenant_id}/{brand_id}" in manifest["resources"]
    assert "campaign_brief_template" in manifest["prompts"]
    assert len(REGISTERED_TOOLS) == 5
    assert len(REGISTERED_RESOURCES) == 1
    assert len(REGISTERED_PROMPTS) == 1

    # 1. Capabilities discovery tool
    caps = adcp_get_capabilities(channels=["ctv", "display"])
    assert caps["protocol_version"] == "adcp/1.0-mcp-streamable-http"
    assert caps["seller_count"] >= 2

    # 2. Product catalog discovery tool
    products = adcp_get_products(
        campaign_id="camp_mcp_test",
        brief_summary="Launch Aurora EV GT across CTV and Display",
        channels=["ctv", "display"],
        target_geos=["SG", "US-CA"],
    )
    assert len(products) >= 2
    assert all(p["channel"] in ("ctv", "display") for p in products)

    # 3. Deterministic budget allocation tool
    plan = adcp_allocate_budget(
        campaign_id="camp_mcp_test",
        total_budget_usd=25000.0,
        discovered_products=products,
    )
    assert round(sum(item["allocated_budget_usd"] for item in plan), 2) == 25000.0

    # 4. Creative generation + validation tools
    creative = creative_generate_omnichannel(
        campaign_id="camp_mcp_test",
        tenant_id="tenant_aurora",
        brand_id="aurora_ev",
        brand_name="Aurora EV Motors",
        objective="Drive Q4 test drives for the Aurora GT with 380-mile EPA range",
        total_budget_usd=25000.0,
        channel="display",
        target_geos=["SG"],
    )
    assert creative["channel"] == "display"
    assert creative["spec_valid"] is True

    report = creative_validate_compliance(
        creatives=[creative],
        tenant_id="tenant_aurora",
        brand_id="aurora_ev",
    )
    assert report["compliance_passed"] is True

    # 5. Resource & Prompt primitives
    brand_json = get_brand_vault_resource(tenant_id="tenant_aurora", brand_id="aurora_ev")
    brand_profile = json.loads(brand_json)
    assert brand_profile["brand_id"] == "aurora_ev"

    prompt_str = campaign_brief_template(
        brand_name="Aurora EV Motors",
        budget_usd=50000.0,
        channels="display, ctv",
    )
    assert "Aurora EV Motors" in prompt_str
    assert "$50,000.00" in prompt_str


# ============================================================================
# Task 2: REQ-OTEL-01 — Arize Phoenix / OpenTelemetry Instrumentation
# ============================================================================


def test_req_otel_01_tracing_initialization() -> None:
    """Verify OpenTelemetry / Phoenix tracing initializes cleanly offline."""
    ok = setup_agent_tracing(app_name="AdAiz-Test-Suite")
    assert ok is True

    status = get_tracing_status()
    assert status["initialized"] is True
    assert status["backend"] in (
        "arize_phoenix_otel",
        "opentelemetry_sdk",
        "opentelemetry_embedded_fallback",
        "deterministic_noop_tracer",
    )


# ============================================================================
# Task 3: REQ-META-01 — Metacognitive StagnationDetector & ConfidenceGate
# ============================================================================


def test_req_meta_01_stagnation_detector_circuit_breaker() -> None:
    """Verify StagnationDetector trips AgentStagnationError when similarity >= 0.90."""
    detector = StagnationDetector(similarity_threshold=0.90)

    draft_sig_v1 = (
        "display|Aurora EV: 100% guaranteed instant return|Book test drive now|#0EA5E9"
    )

    # Iteration 1: First failed draft -> should not raise
    check_1 = detector.check_iteration(
        campaign_id="camp_stag_01",
        current_draft_signature=draft_sig_v1,
        has_unresolved_errors=True,
    )
    assert check_1["stagnant"] is False
    assert check_1["iteration_count"] == 1

    # Iteration 2: Identical failed draft -> Jaccard similarity = 1.0 >= 0.90 -> raises AgentStagnationError
    with pytest.raises(AgentStagnationError) as exc_info:
        detector.check_iteration(
            campaign_id="camp_stag_01",
            current_draft_signature=draft_sig_v1,
            has_unresolved_errors=True,
        )
    assert "100.0% token similarity" in str(exc_info.value)


def test_req_meta_01_confidence_gate_scoring() -> None:
    """Verify ConfidenceGate scores high-confidence vs low-confidence plans accurately."""
    gate = ConfidenceGate(min_confidence_threshold=0.80)

    creatives_high = [
        CreativeAsset(
            asset_id="cr_hi",
            channel="display",
            format_name="IAB Medium Rectangle",
            dimensions="300x250",
            headline="Aurora EV 380-Mile EPA Range",
            subheadline="18-minute ultra-fast charging",
            cta_text="Book Test Drive",
            primary_hex="#0EA5E9",
            background_hex="#0F172A",
            contrast_ratio=9.2,
            word_count=5,
            spec_valid=True,
            compliance_passed=True,
        )
    ]

    eval_high = gate.evaluate_confidence(
        creatives=creatives_high,
        budget_math_valid=True,
        compliance_passed=True,
    )
    assert eval_high["confidence_score"] >= 0.90
    assert eval_high["needs_supervisor_attention"] is False
    assert eval_high["status"] == "HIGH_CONFIDENCE_VERIFIED"

    # Low-confidence scenario (failed spec + failed compliance + low contrast)
    creatives_low = [
        CreativeAsset(
            asset_id="cr_lo",
            channel="display",
            format_name="IAB Medium Rectangle",
            dimensions="300x250",
            headline="Bad draft",
            subheadline="Low contrast",
            cta_text="Click",
            primary_hex="#777777",
            background_hex="#888888",
            contrast_ratio=2.1,
            word_count=4,
            spec_valid=False,
            compliance_passed=False,
        )
    ]
    eval_low = gate.evaluate_confidence(
        creatives=creatives_low,
        budget_math_valid=True,
        compliance_passed=False,
    )
    assert eval_low["confidence_score"] < 0.80
    assert eval_low["needs_supervisor_attention"] is True
    assert eval_low["status"] == "LOW_CONFIDENCE_FLAGGED"


def test_req_meta_01_langgraph_workflow_populates_metacognition() -> None:
    """Verify end-to-end LangGraph workflow populates state['metacognition']."""
    orchestrator = AdAizOrchestrator()
    brief = CampaignBrief(
        campaign_id="camp_meta_e2e",
        tenant_id="tenant_aurora",
        brand_id="aurora_ev",
        brand_name="Aurora EV Motors",
        objective="Drive Q4 test drives for the Aurora GT with 380-mile EPA range",
        total_budget_usd=30000.0,
        target_channels=["display", "ctv"],
        target_geos=["SG"],
    )
    final_state = orchestrator.run_until_hitl(brief)

    assert "metacognition" in final_state
    meta = final_state["metacognition"]
    assert meta["confidence_score"] >= 0.80
    assert meta["needs_supervisor_attention"] is False
    assert meta["stagnation_check"]["stagnant"] is False


# ============================================================================
# Task 4: REQ-JUDGE-01 — Gate 3.5 LLM-as-a-Judge Semantic Rubric
# ============================================================================


def test_req_judge_01_llm_as_a_judge_rubric_and_eval_pipeline() -> None:
    """Verify Gate 3.5 LLM-as-a-Judge scores 1-5 rubric and integrates into run_all_evaluation_gates."""
    orchestrator = AdAizOrchestrator()
    vault = HybridBrandVault()
    brief = CampaignBrief(
        campaign_id="camp_judge_test",
        tenant_id="tenant_aurora",
        brand_id="aurora_ev",
        brand_name="Aurora EV Motors",
        objective="Drive Q4 test drives for the Aurora GT with 380-mile EPA range and 18-minute ultra-fast charging.",
        total_budget_usd=40000.0,
        target_channels=["display", "ctv"],
        target_geos=["SG"],
    )
    state = orchestrator.run_until_hitl(brief)
    guidelines = vault.get_brand_profile("tenant_aurora", "aurora_ev")

    rubric = evaluate_creatives_llm_as_a_judge(
        brief=brief,
        creatives=state["creatives"],
        brand_guidelines=guidelines,
    )
    assert rubric["passed"] is True
    assert rubric["overall_score_5"] >= 4.2
    assert rubric["brand_tone_alignment"] >= 4.0
    assert rubric["value_proposition_clarity"] >= 4.0
    assert rubric["hallucination_absence"] == 5.0

    # Full 5-gate evaluation harness check
    full_eval = run_all_evaluation_gates()
    assert full_eval["overall_passed"] is True
    assert "gate3_5_llm_as_a_judge_rubric" in full_eval["gates"]
    assert full_eval["gates"]["gate3_5_llm_as_a_judge_rubric"]["passed"] is True
