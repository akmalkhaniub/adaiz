# AdAiz — Enterprise Agentic Advertising Platform

**AdAiz** (*Ad-Eyes / Ad A-to-Z*) is a Spec-Driven, production-grade Agentic Advertising Platform connecting **Omnichannel Creative Generation (Display, Video, CTV, DOOH)**, **AdCP / OpenRTB Media Discovery**, **Brand & Regulatory Compliance**, **Human-in-the-Loop (HITL) Campaign Activation**, and **4-Gate Automated Evaluations**.

---

## 1. Quickstart (60-Second Bootstrap)

```bash
cd g:\ReplitProjects\adaiz

# 1. Run the Pytest Unit, Security, Contract & E2E Test Suite
uv run pytest -v

# 2. Run the 4-Gate Evaluation, Chaos Recovery & Red-Teaming CLI Runner
uv run python -m evals.run_evals

# 3. Launch the Full-Stack FastAPI Gateway + Agency Operator Console
uv run uvicorn src.api.main:app --reload --port 8000
```

Open **`http://localhost:8000`** to access the **AdAiz Agency Operator Console** (or `http://localhost:8000/docs` for the interactive OpenAPI 3.1 specification).

---

## 2. Architecture & Requirement Traceability (`REQ-ID`)

| Req ID | Engineering Capability | Implementation Module | Verification Gate |
| :--- | :--- | :--- | :--- |
| **`REQ-ORCH-01`** | Stateful LangGraph v1.x orchestration with parallel `Send()` creative fan-out & `Command` routing | `src/graph/workflow.py` | `test_req_orch_01_and_hitl_01_end_to_end_langgraph_workflow` |
| **`REQ-HITL-01`** | Persistent checkpointing & `interrupt()` Human-in-the-Loop approval gate before live spend | `src/graph/workflow.py` | Gate 2 + FastAPI HITL Resume Test |
| **`REQ-HARN-01`** | Agent Harness (`READ_ONLY` / `DRAFT_MUTATION` / `LIVE_SPEND`), `HMAC-SHA256` JWT verification, SHA-256 idempotency, exponential backoff retries & FinOps circuit breaker | `src/harness/executor.py` | `test_req_harn_01_live_spend_hmac_guard_and_circuit_breaker` |
| **`REQ-MEM-01`** | Multi-tenant Hybrid RAG Brand Vault (`BM25 + Vector RRF`) + LangGraph `BaseStore` Episodic Memory | `src/memory/brand_vault.py`, `src/memory/episodic_store.py` | `test_req_mem_01_hybrid_rag_and_multi_tenant_isolation` |
| **`REQ-ADCP-01`** | Official `adcontextprotocol/adcp` MCP tasks (`get_adcp_capabilities`, `get_products`, `create_content_standards`, `sync_creatives`, `create_media_buy`) + penny-perfect budget math | `src/mcp_servers/adcp_server.py` | `test_req_adcp_01_penny_perfect_budget_conservation` |
| **`REQ-MMQA-01`** | Omnichannel creative synthesis & 5-Point Technical/Brand QA (IAB dimensions, CTV 10% overscan safe-zone, DOOH $\le 8$ words & zero-audio, WCAG 2.2 contrast, C2PA provenance) | `src/mcp_servers/creative_server.py` | Gate 1 & Gate 3 Compliance Self-Healing |
| **`REQ-EVAL-01`** | 4-Gate Evaluation Suite (Deterministic Math/Specs, Trajectory & 503 Recovery, Compliance & AI Red-Teaming, Baseline vs. Candidate Regression Matrix) | `evals/run_evals.py` | `test_req_eval_01_full_four_gate_evaluation_suite` |
| **`REQ-SALES-01`** | Unstructured Client RFP Intake Agent & Commercial Sales Pitch / Margin Calculator | `src/graph/rfp_agent.py` | `test_fastapi_operator_console_and_hitl_api_contracts` |
| **`REQ-LLM-01`** | Resilient Multi-Provider LLM Gateway (`Gemini` / `OpenAI` / `Anthropic` + Deterministic Cascade Failover) | `src/harness/llm_gateway.py` | `/api/v1/health` & RFP Parser |
| **`REQ-DB-01`** | Durable SQLite WAL Persistence (`adaiz_state.db`) & GDPR Cascading Right-to-Erasure (`DELETE /api/v1/vault/{tenant_id}`) | `src/memory/persistence.py` | SQLite WAL Snapshot & Audit Ledger |
| **`REQ-INSIGHTS-01`** | Post-Launch Autonomous Pacing Optimizer, OpenRTB Bid-Shading & Saga Compensating Rollback (`cancel_media_buy`) | `src/graph/insights_agent.py` | `/optimize-pacing` & `/saga-rollback` |
| **`REQ-DEVOPS-01`** | Multi-stage `Dockerfile`, `docker-compose.yml`, `.gitignore` & Eval-Gated GitHub Actions CI/CD | `Dockerfile`, `ci/ci-eval-gate.yml` | Automated Two-Stage CI Pipeline |
| **`REQ-A2A-02`** | 3-Round Agent-to-Agent (`A2A`) Rate Negotiation Engine yielding CPM discounts & bonus impressions | `src/mcp_servers/adcp_server.py` | `negotiate_a2a_rates` |
| **`REQ-AUD-01`** | Privacy-Safe Audience Signal & Clean-Room Resolver (`AAMP` / IAB Seller-Defined Audiences `SDA` / `UID2` cohorts) | `src/mcp_servers/adcp_server.py` | `resolve_audience_signals_aamp` |
| **`REQ-DCO-01`** | Traffickable Ad Tag Exporter (IAB VAST 4.2 XML + HTML5 `clickTag` Ad Bundle + DCO Variants) | `src/mcp_servers/creative_server.py` | `/api/v1/campaigns/{id}/ad-tags` |
| **`REQ-ORCH-02`** | LangGraph Time-Travel Checkpoint Timeline (`get_state_history`) & State Forking | `src/graph/workflow.py` | `/checkpoints` & `/fork` |
| **`REQ-EVAL-02`** | Interactive Prompt & Config Version Regression Lab (`ALLOW_DEPLOY` vs `BLOCK_DEPLOY_REGRESSION`) | `evals/run_evals.py` | `/api/v1/evals/compare-candidate` |
| **`REQ-FINOPS-01`** | Role-Based Access Control (`RBAC`: `media_director` vs `media_planner` vs `compliance_auditor`) | `src/harness/executor.py` | HTTP 403 RBAC Live-Spend Guard |
