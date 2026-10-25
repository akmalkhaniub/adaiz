"""
Metacognitive Stagnation Detector & Confidence Gate (`REQ-META-01`).
Prevents degenerate oscillation in multi-agent critique loops and quantifies
iteration confidence before surfacing outputs to human operators.

Reference:
- Micheal Lanham, AI Agents in Action 2E (Chapter 10: Metacognition & Cognitive Loops)
Governing Skills:
- langgraph-multi-agent-orchestration
- agent-harness-and-evals
"""

from __future__ import annotations

import re
from typing import Any

from src.graph.state import CreativeAsset


class AgentStagnationError(RuntimeError):
    """
    Raised when consecutive agent loop iterations exhibit >= 90% token similarity
    without resolving validation or compliance errors.
    """


def _tokenize_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9#]+", text.lower()))


class StagnationDetector:
    """
    REQ-META-01: Tracks output history across revision loop iterations and computes
    Jaccard token-set similarity between consecutive drafts.
    Raises `AgentStagnationError` if similarity >= threshold (default 0.90) while
    errors remain unresolved.
    """

    def __init__(self, similarity_threshold: float = 0.90) -> None:
        self.similarity_threshold = similarity_threshold
        self._history_by_campaign: dict[str, list[str]] = {}

    @staticmethod
    def compute_jaccard_similarity(text_a: str, text_b: str) -> float:
        set_a = _tokenize_set(text_a)
        set_b = _tokenize_set(text_b)
        if not set_a and not set_b:
            return 1.0
        union = set_a | set_b
        if not union:
            return 0.0
        return round(len(set_a & set_b) / len(union), 4)

    def check_iteration(
        self,
        campaign_id: str,
        current_draft_signature: str,
        has_unresolved_errors: bool = True,
    ) -> dict[str, Any]:
        """
        Compare `current_draft_signature` against the immediately preceding iteration
        for `campaign_id`. If `has_unresolved_errors` is True and Jaccard similarity
        >= `self.similarity_threshold`, raises `AgentStagnationError`.
        """
        history = self._history_by_campaign.setdefault(campaign_id, [])
        similarity = 0.0
        stagnant = False

        if history:
            prev_signature = history[-1]
            similarity = self.compute_jaccard_similarity(prev_signature, current_draft_signature)
            if has_unresolved_errors and similarity >= self.similarity_threshold:
                stagnant = True
                history.append(current_draft_signature)
                raise AgentStagnationError(
                    f"Metacognitive Stagnation Circuit Breaker tripped for '{campaign_id}': "
                    f"Consecutive revision drafts exhibited {similarity * 100:.1f}% token similarity "
                    f"(threshold >= {self.similarity_threshold * 100:.0f}%) without resolving compliance errors."
                )

        history.append(current_draft_signature)
        return {
            "campaign_id": campaign_id,
            "iteration_count": len(history),
            "similarity_to_previous": similarity,
            "stagnant": stagnant,
        }


class ConfidenceGate:
    """
    REQ-META-01: Computes a deterministic metacognitive confidence score [0.0, 1.0]
    across spec compliance, WCAG contrast margin, brand compliance, and budget precision.
    Flags runs with confidence < 0.80 (`threshold`) for supervisor attention.
    """

    def __init__(self, min_confidence_threshold: float = 0.80) -> None:
        self.min_confidence_threshold = min_confidence_threshold

    def evaluate_confidence(
        self,
        *,
        creatives: list[CreativeAsset],
        budget_math_valid: bool,
        compliance_passed: bool,
    ) -> dict[str, Any]:
        if not creatives:
            return {
                "confidence_score": 0.0,
                "needs_supervisor_attention": True,
                "threshold": self.min_confidence_threshold,
                "components": {},
            }

        spec_ratio = sum(1.0 for c in creatives if c.spec_valid) / len(creatives)
        contrast_scores = [
            min(1.0, float(c.contrast_ratio) / 7.0) if c.contrast_ratio >= 4.5 else 0.3
            for c in creatives
        ]
        contrast_avg = sum(contrast_scores) / len(contrast_scores)
        budget_score = 1.0 if budget_math_valid else 0.0
        compliance_score = 1.0 if compliance_passed else 0.45

        # Weighted metacognitive confidence score in [0.0, 1.0]
        confidence = round(
            0.30 * spec_ratio
            + 0.25 * budget_score
            + 0.30 * compliance_score
            + 0.15 * contrast_avg,
            4,
        )
        needs_attention = confidence < self.min_confidence_threshold

        return {
            "confidence_score": confidence,
            "needs_supervisor_attention": needs_attention,
            "threshold": self.min_confidence_threshold,
            "status": "LOW_CONFIDENCE_FLAGGED" if needs_attention else "HIGH_CONFIDENCE_VERIFIED",
            "components": {
                "spec_compliance_score": round(spec_ratio, 3),
                "budget_precision_score": budget_score,
                "brand_compliance_score": compliance_score,
                "wcag_contrast_margin_score": round(contrast_avg, 3),
            },
        }
