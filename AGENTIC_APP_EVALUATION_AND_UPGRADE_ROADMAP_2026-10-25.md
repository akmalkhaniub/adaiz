# AdAiz Architecture Evaluation & Agentic Upgrade Roadmap (2026-10-25)

**Audit Date:** October 25, 2026  
**Audited Target:** `AdAiz` (`g:\ReplitProjects\adaiz`)  
**Benchmarked Against:**
1. *AI Agents in Action, Second Edition* (Micheal Lanham, Manning 2026)
2. *Building Applications with AI Agents: Designing and Implementing Multi-Agent Systems* (Michael Albada, O'Reilly 2026)
3. *Building AI Agents* (Bojie Li, 2026)
4. *The Comprehensive Guide to AI Agent Engineering* (Dmitriy Vasilyev, 2026)

---

## 1. Executive Summary & Architecture Scorecard

`AdAiz` is an enterprise-grade agentic advertising system featuring strong stateful graph orchestration (LangGraph v1.x), Human-in-the-Loop financial safety guardrails (HMAC-SHA256 live spend token verification), and a 4-Gate automated test suite passing with 100% reliability.

However, compared against state-of-the-art 2026 agentic systems, `AdAiz` currently operates in a "closed in-process silo": its MCP servers are standard Python classes rather than wire-protocol MCP microservices, its observability lacks an OpenTelemetry/Arize Phoenix telemetry pipeline, its vector memory is simulated in-memory rather than persisted in a vector database, and its evaluation suite lacks an LLM-as-a-Judge semantic rubric.

### 2026 Architecture Maturity Scorecard

| Dimension | Score | Current Implementation | 2026 Best Practice Benchmark |
| :--- | :---: | :--- | :--- |
| **1. State & Graph Orchestration** | **10/10** | LangGraph v1.x, `Send()` fan-out, `Command` routing, checkpoint timelines. | State-of-the-art multi-agent pattern matching Albada (O'Reilly). |
| **2. Safety, HITL & Harness** | **10/10** | `interrupt()` gate, HMAC-SHA256 live spend tokens, SHA-256 idempotency, circuit breakers. | Matches Lanham Ch 4 & 8 financial guardrail specifications. |
| **3. Automated TestOps** | **9/10** | 4-Gate test suite (Specs, 503 Recovery, Adversarial Red-Team, Regressions). | Passes 6/6 tests in 15 seconds. |
| **4. Wire Protocol MCP** | **4/10** | Internal Python classes (`AdCPServer`, `CreativeServer`) in `src/mcp_servers/`. | Missing official `mcp[cli]` / `FastMCP` exposing JSON-RPC over STDIO & SSE/HTTP. |
| **5. Observability & Tracing** | **3/10** | Python console logs and SQLite audit table. | Missing OpenTelemetry + Arize Phoenix (`arize-phoenix-otel`, OpenInference). |
| **6. Memory & Vector Persistence** | **6/10** | In-memory lexical BM25 + character n-gram TF-IDF with RRF ($k=60$). | Missing persistent vector store (ChromaDB / Qdrant) with dense embeddings. |
| **7. Metacognitive Loops** | **5/10** | Static max retries and timeout backoff. | Missing `StagnationDetector`, `ConfidenceGate`, and dynamic loop circuit breakers. |
| **8. Qualitative Evaluation** | **6/10** | Deterministic regex and spec checks. | Missing LLM-as-a-Judge semantic rubric (G-Eval / groundedness scoring). |

**Overall Maturity Score: 7.5 / 10**

---

## 2. Gap Analysis: Tools & Capabilities Not Yet Used

### Gap 1: Protocol-Level Model Context Protocol (`FastMCP` / `mcp`)
* **Reference:** Lanham *AI Agents in Action 2E* (Chapters 3 & 4), Bojie Li (Chapter 4).
* **The Gap:** `src/mcp_servers/adcp_server.py` and `creative_server.py` are named "mcp_servers", but they are standard Python classes imported into the same runtime. External clients (Claude Desktop, OpenAI Agents SDK, Cursor, or peer agents) cannot discover them via JSON-RPC.
* **The Solution:** Use `mcp.server.fastmcp.FastMCP` to expose tools (`@mcp.tool()`), resources (`@mcp.resource()`), and prompts (`@mcp.prompt()`) over both **STDIO** (for local CLI integration) and **SSE/Streamable HTTP** (for microservice orchestration).

### Gap 2: OpenTelemetry & Arize Phoenix Tracing
* **Reference:** Lanham (Chapters 2 & 7), Albada (O'Reilly).
* **The Gap:** No visual telemetry into agent execution graphs. When an agent experiences latency or fails a compliance check, developers must parse raw console logs rather than inspecting a visual waterfall trace.
* **The Solution:** Add `arize-phoenix-otel` and `openinference-instrumentation-langgraph` to automatically instrument LangGraph node executions, LLM token usages, latency distributions, and tool payloads into an embedded Phoenix server (`http://localhost:6006`).

### Gap 3: Persistent Vector Storage (ChromaDB)
* **Reference:** Lanham (Chapter 6), Umang Yadav (*Practitioner's Guide to Agentic AI*).
* **The Gap:** Brand Vault chunks are held in a static Python dictionary (`DEFAULT_BRAND_VAULT`). Semantic similarity is calculated on character n-grams. It cannot scale to thousands of brand guideline PDFs or persist across service restarts.
* **The Solution:** Integrate `chromadb` with persistent local storage (`data/chroma/`), supporting dense neural embeddings (`text-embedding-3-small` / ONNX local embeddings) combined with BM25 sparse keyword search via Reciprocal Rank Fusion.

### Gap 4: Metacognitive Stagnation & Confidence Gates
* **Reference:** Lanham (Chapter 10: Metacognition & Cognitive Loops).
* **The Gap:** If creative generation produces low-conviction copy or an agent oscillates between similar channel strategies, the current system relies solely on hard retry counts.
* **The Solution:** Implement a `StagnationDetector` (measuring Jaccard/Levenshtein distance between successive draft iterations) and a `ConfidenceGate` (forcing human review or fallback if confidence score falls below 0.75).

### Gap 5: Automated LLM-as-a-Judge Evaluator
* **Reference:** Lanham (Chapter 7), Vasilyev (*AI Agent Engineering Handbook*).
* **The Gap:** Gate 3 tests compliance with keyword blacklists, but cannot evaluate subjective brand voice alignment ("precision luxury" vs "bland corporate").
* **The Solution:** Implement a structured LLM-as-a-Judge scoring module evaluating Faithfulness, Answer Relevance, and Brand Tone Consistency on a 1–5 scale.

---

## 3. Implementation Backlog (Traceability IDs)

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  REQ-MCP-02  │ ──► │ REQ-OTEL-01  │ ──► │  REQ-VEC-01  │
│  FastMCP CLI │     │Phoenix Traces│     │ ChromaDB RAG │
└──────────────┘     └──────────────┘     └──────────────┘
                           │
                           ▼
                     ┌──────────────┐     ┌──────────────┐
                     │ REQ-META-01  │ ──► │ REQ-JUDGE-01 │
                     │Stagnation Det│     │ LLM-as-Judge │
                     └──────────────┘     └──────────────┘
```

1. **`REQ-MCP-02` [FastMCP Protocol Adapter]:**
   Create `src/mcp_servers/standalone_fastmcp.py` exposing `AdCPServer` and `CreativeServer` as a runnable FastMCP server supporting `stdio` and `sse` transports.
2. **`REQ-OTEL-01` [Arize Phoenix Tracing]:**
   Create `src/harness/tracing.py` initializing Phoenix OTEL instrumentation for LangGraph and FastAPI endpoints, with optional UI launch on port `6006`.
3. **`REQ-VEC-01` [ChromaDB Persistent Brand Vault]:**
   Upgrade `src/memory/brand_vault.py` to optionally back the semantic tier with `chromadb.PersistentClient`, retaining BM25 + RRF ($k=60$) and tenant isolation.
4. **`REQ-META-01` [Metacognitive Guardrails]:**
   Create `src/graph/metacognition.py` with `StagnationDetector` and `ConfidenceGate` hooked into `workflow.py` node transitions.
5. **`REQ-JUDGE-01` [LLM-as-a-Judge Gate]:**
   Extend `evals/run_evals.py` with Gate 3.5: Multi-dimensional LLM-as-a-Judge evaluation for Brand Archetype Tone & Hallucination Scoring.

---

## 4. Autonomous Coding Agent Prompt (Copy & Paste)

```markdown
You are an expert Principal AI Systems Engineer tasked with upgrading the `AdAiz` enterprise agentic platform (`g:\ReplitProjects\adaiz`) to align with the 2026 Agentic AI literature (Micheal Lanham 2E, Michael Albada O'Reilly, Bojie Li, and Dmitriy Vasilyev).

### CONTEXT & REFERENCE
Read `AGENTIC_APP_EVALUATION_AND_UPGRADE_ROADMAP_2026-10-25.md` in the repository root for background and architecture scorecard.

### OBJECTIVES & ACCEPTANCE CRITERIA

#### Task 1: Protocol-Level FastMCP Server (`REQ-MCP-02`)
- Add `mcp[cli]>=1.3.0` to `pyproject.toml` dependencies.
- Create `src/mcp_servers/fastmcp_runner.py`:
  - Initialize a `FastMCP("AdAiz-Advertising-Protocol")` server instance.
  - Expose `@mcp.tool()` endpoints for:
    - `adcp_get_capabilities`
    - `adcp_get_products`
    - `adcp_allocate_budget`
    - `creative_generate_omnichannel`
    - `creative_validate_compliance`
  - Expose `@mcp.resource("adcp://brands/{tenant_id}/{brand_id}")` returning the Brand Vault profile.
  - Expose `@mcp.prompt("campaign_brief_template")` returning the standardized RFP intake prompt.
  - Support both CLI STDIO mode (`python -m src.mcp_servers.fastmcp_runner`) and SSE mode (`--transport sse --port 8001`).

#### Task 2: Arize Phoenix / OpenTelemetry Instrumentation (`REQ-OTEL-01`)
- Add `arize-phoenix-otel>=0.17.0` and `openinference-instrumentation-langgraph>=0.1.0` to `pyproject.toml`.
- Create `src/harness/tracing.py`:
  - Define `setup_agent_tracing(app_name="AdAiz-Advertising-Engine") -> bool`.
  - Safely initialize OpenInference LangGraph instrumentation if Phoenix is available or if `PHOENIX_COLLECTOR_ENDPOINT` is configured.
  - Gracefully fallback without errors if the collector is unreachable.
- Hook tracing initialization into FastAPI lifespan in `src/api/main.py`.

#### Task 3: Metacognitive Stagnation & Confidence Gate (`REQ-META-01`)
- Create `src/graph/metacognition.py` implementing:
  - `StagnationDetector`: Tracks output history across loop iterations; computes token set similarity; triggers `AgentStagnationError` if consecutive iterations exhibit $\ge 90\%$ semantic stagnation without resolving validation errors.
  - `ConfidenceGate`: Computes a deterministic confidence score $[0.0, 1.0]$ based on spec compliance, contrast margin, and budget precision; flags iterations with $< 0.80$ confidence for supervisor attention.
- Integrate the metacognitive checks into the LangGraph loop in `src/graph/workflow.py`.

#### Task 4: LLM-as-a-Judge Evaluation Gate (`REQ-JUDGE-01`)
- In `evals/run_evals.py`, add `Gate 3.5: LLM-as-a-Judge Semantic Rubric`:
  - Evaluates generated creatives on 3 dimensions: Brand Tone Alignment (1-5), Value Proposition Clarity (1-5), and Hallucination Absence (1-5).
  - Provides a deterministic fallback judge using cosine similarity and rule scoring when running offline without API keys.

#### Task 5: Verification & Regression Protection
- Run `.\.venv\Scripts\python.exe -m pytest -v` ensuring all existing 6 test suites continue to pass.
- Add unit tests in `tests/test_2026_upgrades.py` validating:
  - FastMCP tool registration and schema export.
  - Metacognitive stagnation detection triggering on identical repeated errors.
  - LLM-as-a-Judge evaluation rubric calculation.
- Run `.\.venv\Scripts\python.exe -m evals.run_evals` ensuring the complete 4-Gate (now 5-Gate) evaluation pipeline succeeds with zero regressions.

### STRICT ENGINEERING GUIDELINES
1. Preserve all existing `REQ-ID` traceability, HMAC live-spend security checks, and penny-perfect math conservation.
2. Keep code modular, strictly typed with Pydantic v2 and Python 3.11+ type hints.
3. Ensure offline resilience: all new components must function with high-fidelity deterministic fallbacks when external API keys or network servers are not present.
```
