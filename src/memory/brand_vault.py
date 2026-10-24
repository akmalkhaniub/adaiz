"""
Hybrid RAG Brand Vault with Reciprocal Rank Fusion (RRF) & Multi-Tenant Isolation.
Traceability: REQ-MEM-01
Governing Skills:
- context-engineering-and-rag
- security-and-multi-tenant-saas
- ai-governance-privacy-and-compliance
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


class TenantAccessViolationError(PermissionError):
    """Raised when a request attempts to access another tenant's Brand Vault."""


DEFAULT_BRAND_VAULT: dict[str, dict[str, Any]] = {
    "tenant_aurora:aurora_ev": {
        "tenant_id": "tenant_aurora",
        "brand_id": "aurora_ev",
        "brand_name": "Aurora EV Motors",
        "industry": "Automotive / Clean Mobility",
        "primary_hex": "#4F46E5",
        "secondary_hex": "#10B981",
        "background_hex": "#0F172A",
        "tone_archetype": "Precision, optimistic engineering, zero-emission luxury",
        "prohibited_phrases": [
            "guaranteed 10x",
            "100% risk-free",
            "self-driving autopilot",
            "cheapest car",
            "unlimited range",
            "zero maintenance ever",
        ],
        "mandatory_disclaimer": "EPA est. range 380 miles. Charging times vary by station peak output.",
        "default_cta": "Book Test Drive",
        "chunks": [
            {
                "rule_id": "AUR-TONE-01",
                "category": "tone",
                "source_section": "Brand Voice & Messaging v4.2",
                "content": "Aurora EV copy must highlight precision engineering, 380-mile EPA range, and ultra-fast 18-minute charging. Avoid hype or unverified superlatives.",
            },
            {
                "rule_id": "AUR-VIS-02",
                "category": "visual",
                "source_section": "Omnichannel Visual Standards",
                "content": "Primary brand palette uses Indigo (#4F46E5) and Emerald (#10B981) on Slate (#0F172A). Minimum WCAG luminance contrast ratio is 4.5:1 across Display and DOOH.",
            },
            {
                "rule_id": "AUR-LEGAL-03",
                "category": "prohibited_claims",
                "source_section": "FTC & Automotive Regulatory Compliance",
                "content": "Never claim 'self-driving autopilot', 'unlimited range', 'guaranteed 10x', or '100% risk-free'. Always include EPA range & charging disclaimer on video/CTV/display units.",
            },
            {
                "rule_id": "AUR-DOOH-04",
                "category": "channel_rules",
                "source_section": "DOOH & CTV Technical Playbook",
                "content": "DOOH highway and urban totem creatives must strictly contain 8 words or fewer in the primary headline with zero audio track. CTV spots require a 10% overscan safe zone.",
            },
        ],
    },
    "tenant_nova:novapay": {
        "tenant_id": "tenant_nova",
        "brand_id": "novapay",
        "brand_name": "NovaPay Treasury",
        "industry": "B2B FinTech & Cross-Border Payments",
        "primary_hex": "#0EA5E9",
        "secondary_hex": "#6366F1",
        "background_hex": "#0B1120",
        "tone_archetype": "Institutional trust, instant global liquidity, transparent FX",
        "prohibited_phrases": [
            "guaranteed return",
            "guaranteed 10x",
            "500% return",
            "100% risk-free",
            "no fees ever",
            "instant wealth",
            "fdic insured crypto",
        ],
        "mandatory_disclaimer": "NovaPay is a financial technology platform. Foreign exchange and treasury products involve market risk.",
        "default_cta": "Explore Treasury Platform",
        "chunks": [
            {
                "rule_id": "NOV-TONE-01",
                "category": "tone",
                "source_section": "Institutional Voice Guidelines",
                "content": "Emphasize real-time multi-currency settlement, transparent FX spreads, and CFO-grade controls. Maintain authoritative financial clarity.",
            },
            {
                "rule_id": "NOV-LEGAL-02",
                "category": "prohibited_claims",
                "source_section": "MAS / SEC / FCA Financial Promotions Rulebook",
                "content": "Strictly prohibit guaranteed return claims ('guaranteed 10x', '500% return', '100% risk-free', 'instant wealth'). Mandatory financial risk disclosure required.",
            },
            {
                "rule_id": "NOV-VIS-03",
                "category": "visual",
                "source_section": "Visual Identity System",
                "content": "Use Sky Blue (#0EA5E9) on deep navy (#0B1120) with high-contrast data typography and clear regulatory footer.",
            },
        ],
    },
    "tenant_verve:verve_brew": {
        "tenant_id": "tenant_verve",
        "brand_id": "verve_brew",
        "brand_name": "Verve Nitro Cold Brew",
        "industry": "CPG / Specialty Beverage",
        "primary_hex": "#F59E0B",
        "secondary_hex": "#10B981",
        "background_hex": "#18181B",
        "tone_archetype": "Crisp, kinetic energy, organic single-origin craft",
        "prohibited_phrases": [
            "cures fatigue",
            "medical energy",
            "guaranteed 10x",
            "100% risk-free",
            "zero caffeine jitter cure",
        ],
        "mandatory_disclaimer": "USDA Organic Certified. 140mg natural caffeine per 11oz can.",
        "default_cta": "Find Near You",
        "chunks": [
            {
                "rule_id": "VRV-TONE-01",
                "category": "tone",
                "source_section": "Creative Playbook",
                "content": "Focus on smooth nitrogen-infused cascade, zero grams added sugar, and single-origin Colombian beans.",
            },
            {
                "rule_id": "VRV-LEGAL-02",
                "category": "prohibited_claims",
                "source_section": "FDA Beverage Labeling Rules",
                "content": "Do not make medical or therapeutic claims such as 'cures fatigue' or 'medical energy'.",
            },
        ],
    },
}


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9#]+", text.lower())


class HybridBrandVault:
    """
    Multi-tenant Hybrid RAG store combining BM25 lexical scoring and semantic vector
    similarity via Reciprocal Rank Fusion (RRF, k=60).
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {
            k: dict(v) for k, v in DEFAULT_BRAND_VAULT.items()
        }

    def get_brand_profile(
        self, tenant_id: str, brand_id: str, requesting_tenant_id: str | None = None
    ) -> dict[str, Any]:
        """Retrieve brand profile enforcing strict tenant_id isolation."""
        effective_requester = requesting_tenant_id or tenant_id
        if effective_requester != tenant_id:
            raise TenantAccessViolationError(
                f"Security violation: Tenant '{effective_requester}' cannot access resources owned by '{tenant_id}'."
            )

        key = f"{tenant_id}:{brand_id}"
        if key in self._store:
            profile = self._store[key]
            if profile["tenant_id"] != tenant_id:
                raise TenantAccessViolationError("Cross-tenant profile mismatch.")
            return profile

        # Check if brand_id belongs to a different tenant (detect cross-tenant probing)
        for existing_key, existing_profile in self._store.items():
            if existing_profile["brand_id"] == brand_id and existing_profile["tenant_id"] != tenant_id:
                raise TenantAccessViolationError(
                    f"Cross-tenant access denied: Brand '{brand_id}' belongs to another tenant."
                )

        # Fallback default profile for dynamic brands within the same tenant
        return {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "brand_name": brand_id.replace("_", " ").title(),
            "industry": "General Advertising",
            "primary_hex": "#4F46E5",
            "secondary_hex": "#0EA5E9",
            "background_hex": "#0F172A",
            "tone_archetype": "Clear, high-trust modern brand communication",
            "prohibited_phrases": ["guaranteed 10x", "100% risk-free", "500% return"],
            "mandatory_disclaimer": "Terms and conditions apply. See official website for details.",
            "default_cta": "Learn More",
            "chunks": [
                {
                    "rule_id": "GEN-LEGAL-01",
                    "category": "prohibited_claims",
                    "source_section": "Standard IAB & FTC Advertising Rules",
                    "content": "Avoid unsubstantiated financial or performance claims ('guaranteed 10x', '100% risk-free').",
                }
            ],
        }

    def retrieve_hybrid_rrf(
        self,
        tenant_id: str,
        brand_id: str,
        query: str,
        top_k: int = 4,
        rrf_k: int = 60,
    ) -> list[dict[str, Any]]:
        """
        Execute Hybrid Search (BM25 + Dense Token-Vector Cosine Similarity) fused via RRF.
        Pre-filters strictly by (tenant_id, brand_id) before ranking.
        """
        profile = self.get_brand_profile(tenant_id=tenant_id, brand_id=brand_id)
        chunks: list[dict[str, Any]] = profile.get("chunks", [])
        if not chunks:
            return []

        q_tokens = _tokenize(query)
        q_counts = Counter(q_tokens)

        # 1. Compute BM25 lexical scores
        doc_tokens_list = [_tokenize(c["content"] + " " + c["category"]) for c in chunks]
        avgdl = sum(len(dt) for dt in doc_tokens_list) / max(len(doc_tokens_list), 1)
        bm25_scores: list[tuple[int, float]] = []

        for idx, d_tokens in enumerate(doc_tokens_list):
            d_counts = Counter(d_tokens)
            dl = len(d_tokens)
            score = 0.0
            for term in set(q_tokens):
                tf = d_counts.get(term, 0)
                if tf > 0:
                    df = sum(1 for dt in doc_tokens_list if term in dt)
                    idf = math.log(1.0 + (len(chunks) - df + 0.5) / (df + 0.5))
                    k1, b = 1.5, 0.75
                    score += idf * ((tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (dl / max(avgdl, 1.0)))))
            bm25_scores.append((idx, score))

        # 2. Compute Semantic Token/N-gram Vector Cosine Similarity
        vec_scores: list[tuple[int, float]] = []
        for idx, d_tokens in enumerate(doc_tokens_list):
            d_counts = Counter(d_tokens)
            dot = sum(q_counts[t] * d_counts.get(t, 0) for t in q_counts)
            q_norm = math.sqrt(sum(v * v for v in q_counts.values())) or 1.0
            d_norm = math.sqrt(sum(v * v for v in d_counts.values())) or 1.0
            vec_scores.append((idx, dot / (q_norm * d_norm)))

        bm25_ranked = [idx for idx, _ in sorted(bm25_scores, key=lambda x: x[1], reverse=True)]
        vec_ranked = [idx for idx, _ in sorted(vec_scores, key=lambda x: x[1], reverse=True)]

        # 3. Reciprocal Rank Fusion (RRF)
        fused_results: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            r_bm25 = bm25_ranked.index(idx) + 1
            r_vec = vec_ranked.index(idx) + 1
            rrf_score = (1.0 / (rrf_k + r_bm25)) + (1.0 / (rrf_k + r_vec))
            fused_results.append(
                {
                    **chunk,
                    "rrf_score": round(rrf_score, 5),
                    "tenant_id": tenant_id,
                    "brand_id": brand_id,
                }
            )

        fused_results.sort(key=lambda x: x["rrf_score"], reverse=True)
        return fused_results[:top_k]

    def update_brand_guidelines(
        self,
        tenant_id: str,
        brand_id: str,
        prohibited_phrases: list[str] | None = None,
        mandatory_disclaimer: str | None = None,
        custom_rule: str | None = None,
    ) -> dict[str, Any]:
        """Update tenant brand guidelines or append a new compliance rule chunk."""
        profile = self.get_brand_profile(tenant_id, brand_id)
        if prohibited_phrases is not None:
            profile["prohibited_phrases"] = prohibited_phrases
        if mandatory_disclaimer is not None:
            profile["mandatory_disclaimer"] = mandatory_disclaimer
        if custom_rule:
            rule_id = f"CUST-{len(profile['chunks']) + 1:02d}"
            profile["chunks"].append(
                {
                    "rule_id": rule_id,
                    "category": "custom_guideline",
                    "source_section": "Operator Vault Update",
                    "content": custom_rule,
                }
            )
        self._store[f"{tenant_id}:{brand_id}"] = profile
        return profile

    def purge_tenant_data(self, tenant_id: str) -> int:
        """GDPR / CCPA Right-to-Erasure: atomically purge all brand records for a tenant."""
        keys_to_delete = [
            k for k, v in self._store.items() if v.get("tenant_id") == tenant_id
        ]
        for k in keys_to_delete:
            del self._store[k]
        return len(keys_to_delete)

    def list_brands_for_tenant(self, tenant_id: str) -> list[dict[str, Any]]:
        """List all brand profiles owned by a specific tenant."""
        return [
            v for v in self._store.values() if v.get("tenant_id") == tenant_id
        ]
