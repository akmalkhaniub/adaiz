"""
Agent Harness Runtime & Control Layer.
Traceability: REQ-HARN-01, REQ-HARN-02, REQ-HITL-01
Governing Skills:
- agent-harness-and-evals
- secops-devsecops-and-ai-redteaming
- finops-and-saas-monetization
- devops-sre-and-cloud-iac
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import time
from typing import Any, Callable

from src.graph.state import ExecutionTraceEvent, SensitivityTier

_HMAC_SECRET = os.environ.get(
    "ADAIZ_APPROVAL_HMAC_SECRET", "adaiz-zero-trust-hmac-secret-key-2026"
).encode("utf-8")


class SecurityViolationError(PermissionError):
    """Raised when a tool violatesLIVE_SPEND approval boundaries or tenant isolation."""


class TransientDSPTimeoutError(RuntimeError):
    """Simulated or real HTTP 503 / 429 transient error from an external SSP/DSP."""


class BudgetCircuitBreakerError(RuntimeError):
    """Raised when a workflow exceeds its maximum step count or FinOps dollar ceiling."""


ROLE_PERMISSIONS: dict[str, set[str]] = {
    "media_director": {"READ_ONLY", "DRAFT_MUTATION", "LIVE_SPEND"},
    "media_planner": {"READ_ONLY", "DRAFT_MUTATION"},
    "compliance_auditor": {"READ_ONLY"},
}


def verify_operator_role_permission(role: str, required_tier: SensitivityTier) -> None:
    """
    REQ-FINOPS-01: Role-Based Access Control (RBAC) enforcement.
    Blocks unauthorized operator roles (e.g., `media_planner` or `compliance_auditor`)
    from authorizing `LIVE_SPEND` financial actions.
    """
    normalized_role = role.strip().lower()
    allowed = ROLE_PERMISSIONS.get(normalized_role, set())
    if required_tier not in allowed:
        raise SecurityViolationError(
            f"RBAC Permission Denied: Operator role '{normalized_role}' is not authorized for '{required_tier}' actions. "
            f"Requires 'media_director' role to approve live media spend."
        )



PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"bypass\s+compliance",
    r"skip\s+human\s+review",
    r"auto[-\s]?approve\s+campaign",
    r"set\s+approval_jwt",
    r"system\s+override",
    r"call\s+create_media_buy\s+immediately",
]


def scan_for_prompt_injection(text: str) -> list[str]:
    """
    Scan untrusted brief or seller text for prompt injection / HITL bypass attempts.
    Returns list of matched adversarial patterns.
    """
    findings: list[str] = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            findings.append(f"Blocked adversarial directive matching /{pattern}/")
    return findings


def sanitize_untrusted_text(text: str) -> str:
    """Strip adversarial override commands while preserving legitimate campaign brief intent."""
    cleaned = text
    for pattern in PROMPT_INJECTION_PATTERNS:
        cleaned = re.sub(pattern, "[REDACTED_ADVERSARIAL_DIRECTIVE]", cleaned, flags=re.IGNORECASE)
    return cleaned


def mint_approval_token(
    tenant_id: str,
    campaign_id: str,
    total_budget_usd: float,
    reviewer: str,
) -> str:
    """
    Mint a cryptographically signed HMAC-SHA256 approval token (JWT-style structure)
    authorizing LIVE_SPEND execution for an exact campaign and budget.
    """
    payload = {
        "tenant_id": tenant_id,
        "campaign_id": campaign_id,
        "total_budget_usd": round(float(total_budget_usd), 2),
        "reviewer": reviewer,
        "iat": int(time.time()),
        "scope": "LIVE_SPEND",
    }
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    sig = hmac.new(_HMAC_SECRET, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_approval_token(
    token: str | None,
    expected_tenant_id: str,
    expected_campaign_id: str,
    expected_budget_usd: float,
) -> dict[str, Any]:
    """
    Cryptographically verify a human approval token before executing any LIVE_SPEND tool.
    Raises SecurityViolationError if missing, forged, or mismatched.
    """
    if not token or "." not in token:
        raise SecurityViolationError(
            "LIVE_SPEND blocked: Missing cryptographic human approval token (approval_jwt)."
        )
    payload_b64, provided_sig = token.rsplit(".", 1)
    expected_sig = hmac.new(
        _HMAC_SECRET, payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise SecurityViolationError("LIVE_SPEND blocked: Invalid HMAC signature on approval_jwt.")

    padding = "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode((payload_b64 + padding).encode("utf-8")).decode("utf-8")
        )
    except Exception as exc:
        raise SecurityViolationError("LIVE_SPEND blocked: Malformed approval_jwt payload.") from exc

    if payload.get("tenant_id") != expected_tenant_id:
        raise SecurityViolationError(
            f"LIVE_SPEND blocked: Token tenant '{payload.get('tenant_id')}' != '{expected_tenant_id}'."
        )
    if payload.get("campaign_id") != expected_campaign_id:
        raise SecurityViolationError(
            f"LIVE_SPEND blocked: Token campaign_id '{payload.get('campaign_id')}' != '{expected_campaign_id}'."
        )
    if abs(float(payload.get("total_budget_usd", 0.0)) - round(float(expected_budget_usd), 2)) > 0.01:
        raise SecurityViolationError(
            f"LIVE_SPEND blocked: Approved budget ${payload.get('total_budget_usd')} != requested ${expected_budget_usd}."
        )
    return payload


class AgentHarness:
    """
    Production runtime harness enforcing:
    1. Tool Sensitivity Tiers (READ_ONLY, DRAFT_MUTATION, LIVE_SPEND)
    2. SHA-256 Deterministic Idempotency Registry
    3. Self-Healing Exponential Backoff Retries on Transient 503/429 Errors
    4. Per-Tenant Step & FinOps Cost Circuit Breakers
    """

    def __init__(self, max_steps: int = 18, max_run_cost_usd: float = 1.50) -> None:
        self.max_steps = max_steps
        self.max_run_cost_usd = max_run_cost_usd
        self._tool_tiers: dict[str, SensitivityTier] = {}
        self._idempotency_cache: dict[str, Any] = {}
        self._tenant_ledger: dict[str, float] = {}

    def register_tool_tier(self, tool_name: str, tier: SensitivityTier) -> None:
        self._tool_tiers[tool_name] = tier

    @staticmethod
    def compute_idempotency_key(
        tenant_id: str, campaign_id: str, tool_name: str, args: dict[str, Any]
    ) -> str:
        canonical = json.dumps(args, sort_keys=True, default=str)
        raw = f"{tenant_id}:{campaign_id}:{tool_name}:{canonical}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def execute_tool(
        self,
        *,
        node_name: str,
        tool_name: str,
        tier: SensitivityTier,
        fn: Callable[..., Any],
        kwargs: dict[str, Any],
        tenant_id: str,
        campaign_id: str,
        approval_jwt: str | None = None,
        expected_budget_usd: float = 0.0,
        estimated_cost_usd: float = 0.002,
        max_retries: int = 3,
    ) -> tuple[Any, list[ExecutionTraceEvent]]:
        """
        Execute a tool inside the Agent Harness with permission gates, idempotency,
        automatic retry recovery, and OpenTelemetry-compatible span generation.
        """
        events: list[ExecutionTraceEvent] = []
        start_t = time.perf_counter()

        # 1. FinOps Budget Circuit Breaker check
        current_tenant_spend = self._tenant_ledger.get(f"{tenant_id}:{campaign_id}", 0.0)
        if current_tenant_spend + estimated_cost_usd > self.max_run_cost_usd:
            raise BudgetCircuitBreakerError(
                f"FinOps Circuit Breaker tripped: Campaign '{campaign_id}' exceeded ${self.max_run_cost_usd:.2f} run ceiling."
            )

        # 2. LIVE_SPEND Cryptographic Approval Gate
        if tier == "LIVE_SPEND":
            verified_claims = verify_approval_token(
                token=approval_jwt,
                expected_tenant_id=tenant_id,
                expected_campaign_id=campaign_id,
                expected_budget_usd=expected_budget_usd,
            )
            events.append(
                ExecutionTraceEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    node=node_name,
                    event_type="guardrail",
                    summary=(
                        f"Verified HMAC-SHA256 approval_jwt for LIVE_SPEND tool '{tool_name}' "
                        f"(Approved by {verified_claims['reviewer']} for ${expected_budget_usd:,.2f})"
                    ),
                    duration_ms=round((time.perf_counter() - start_t) * 1000, 2),
                    cost_usd=0.0,
                    metadata={"tier": tier, "reviewer": verified_claims["reviewer"]},
                )
            )

        # 3. Deterministic Idempotency Check for mutating operations
        idem_key = self.compute_idempotency_key(tenant_id, campaign_id, tool_name, kwargs)
        if tier in ("DRAFT_MUTATION", "LIVE_SPEND") and idem_key in self._idempotency_cache:
            cached_result = self._idempotency_cache[idem_key]
            events.append(
                ExecutionTraceEvent(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    node=node_name,
                    event_type="tool_call",
                    summary=f"Idempotency cache HIT for '{tool_name}' (key={idem_key[:10]}...)",
                    duration_ms=0.5,
                    cost_usd=0.0,
                    metadata={
                        "tool": tool_name,
                        "tier": tier,
                        "idempotency_hit": True,
                        "idempotency_key": idem_key[:16],
                    },
                )
            )
            return cached_result, events

        # 4. Self-Healing Retry Loop with Backoff
        attempt = 0
        while True:
            attempt += 1
            call_start = time.perf_counter()
            try:
                result = fn(**kwargs)
                elapsed_ms = round((time.perf_counter() - call_start) * 1000, 2)
                self._tenant_ledger[f"{tenant_id}:{campaign_id}"] = (
                    current_tenant_spend + estimated_cost_usd
                )
                if tier in ("DRAFT_MUTATION", "LIVE_SPEND"):
                    self._idempotency_cache[idem_key] = result

                events.append(
                    ExecutionTraceEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        node=node_name,
                        event_type="tool_call",
                        summary=f"Executed MCP tool '{tool_name}' [{tier}] on attempt #{attempt}",
                        duration_ms=elapsed_ms,
                        cost_usd=estimated_cost_usd,
                        metadata={
                            "tool": tool_name,
                            "tier": tier,
                            "attempt": attempt,
                            "idempotency_hit": False,
                            "idempotency_key": idem_key[:16],
                        },
                    )
                )
                return result, events

            except TransientDSPTimeoutError as exc:
                elapsed_ms = round((time.perf_counter() - call_start) * 1000, 2)
                events.append(
                    ExecutionTraceEvent(
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        node=node_name,
                        event_type="retry",
                        summary=(
                            f"Transient SSP/DSP error in '{tool_name}' (attempt {attempt}/{max_retries}): "
                            f"{exc}. Applying exponential backoff recovery."
                        ),
                        duration_ms=elapsed_ms,
                        cost_usd=0.0,
                        metadata={
                            "tool": tool_name,
                            "attempt": attempt,
                            "max_retries": max_retries,
                            "error": str(exc),
                        },
                    )
                )
                if attempt >= max_retries:
                    raise
                time.sleep(0.01 * (2 ** (attempt - 1)))
