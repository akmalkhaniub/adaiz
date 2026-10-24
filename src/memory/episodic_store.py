"""
Cross-Campaign Episodic Memory & Golden Dataset Flywheel.
Traceability: REQ-MEM-01, REQ-EVAL-01
Governing Skills:
- langgraph-multi-agent-orchestration
- context-engineering-and-rag
- agentops-production-lifecycle
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from langgraph.store.memory import InMemoryStore


SEEDED_EPISODIC_LEARNINGS: dict[str, list[str]] = {
    "tenant_aurora:aurora_ev": [
        "CMO prefers concise engineering numbers (380-mile EPA range, 18-min fast charge) in primary headline.",
        "CTV 15s spots paired with urban DOOH commute totems drove 2.3x higher test-drive bookings in Q3.",
        "Always enforce 10% overscan safe-zone on CTV and <=8 words on highway DOOH.",
    ],
    "tenant_nova:novapay": [
        "Compliance requires explicit market risk disclaimer on all B2B treasury creatives.",
        "Executive audience responds best to transparent FX spread metrics over generic fintech buzzwords.",
    ],
    "tenant_verve:verve_brew": [
        "Highlight '0g Added Sugar' and '140mg Natural Caffeine' on vertical video and DOOH screens.",
    ],
}


class EpisodicMemoryManager:
    """
    Manages cross-thread episodic memory using LangGraph's BaseStore interface
    and captures human HITL feedback into the Golden Evaluation Dataset Flywheel.
    """

    def __init__(self) -> None:
        self.store = InMemoryStore()
        self.dataset_flywheel: list[dict[str, Any]] = []
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        for key, learnings in SEEDED_EPISODIC_LEARNINGS.items():
            tenant_id, brand_id = key.split(":", 1)
            namespace = (tenant_id, brand_id, "episodic_learnings")
            for idx, text in enumerate(learnings):
                self.store.put(
                    namespace,
                    f"seed_{idx}",
                    {
                        "learning": text,
                        "source": "historical_campaign_insight",
                        "created_at": "2026-10-01T00:00:00Z",
                    },
                )

    def get_learnings(self, tenant_id: str, brand_id: str) -> list[str]:
        """Retrieve cross-campaign learnings strictly scoped by (tenant_id, brand_id)."""
        namespace = (tenant_id, brand_id, "episodic_learnings")
        items = self.store.search(namespace)
        return [item.value["learning"] for item in items if "learning" in item.value]

    def record_hitl_feedback(
        self,
        tenant_id: str,
        brand_id: str,
        campaign_id: str,
        approved: bool,
        reviewer: str,
        notes: str,
    ) -> dict[str, Any]:
        """
        Distill human HITL feedback into long-term episodic memory and append
        corrective feedback to the Golden Evaluation Dataset Flywheel.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        namespace = (tenant_id, brand_id, "episodic_learnings")

        if notes.strip():
            distilled = (
                f"[Reviewer {reviewer} ({'Approved' if approved else 'Revision Requested'})]: {notes.strip()}"
            )
            key = f"hitl_{campaign_id}_{int(datetime.now(timezone.utc).timestamp())}"
            self.store.put(
                namespace,
                key,
                {
                    "learning": distilled,
                    "source": "hitl_operator_feedback",
                    "campaign_id": campaign_id,
                    "approved": approved,
                    "created_at": now_iso,
                },
            )

        flywheel_entry = {
            "campaign_id": campaign_id,
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "approved": approved,
            "reviewer": reviewer,
            "notes": notes,
            "timestamp": now_iso,
        }
        self.dataset_flywheel.append(flywheel_entry)
        return flywheel_entry
