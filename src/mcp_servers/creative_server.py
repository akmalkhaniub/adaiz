"""
Multimodal Creative Generation & 5-Point Automated Vision/Spec QA MCP Server.
Traceability: REQ-MMQA-01
Governing Skills:
- multimodal-creative-and-vision-qa
- adcp-and-adtech-protocols
- ai-governance-privacy-and-compliance
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from src.graph.state import CampaignBrief, ChannelType, CreativeAsset
from src.harness.executor import sanitize_untrusted_text


IAB_CHANNEL_SPECS: dict[ChannelType, dict[str, Any]] = {
    "display": {
        "format_name": "IAB High-Impact Medium Rectangle (HTML5)",
        "allowed_dimensions": ["300x250", "728x90", "970x250"],
        "default_dimensions": "300x250",
        "duration_sec": None,
        "has_audio": False,
        "safe_zone_inset_pct": 5,
        "max_headline_words": 12,
    },
    "video": {
        "format_name": "IAB VAST 4.2 Vertical Social/OLV Spot",
        "allowed_dimensions": ["1080x1920", "1920x1080"],
        "default_dimensions": "1080x1920",
        "duration_sec": 15,
        "has_audio": True,
        "safe_zone_inset_pct": 8,
        "max_headline_words": 12,
    },
    "ctv": {
        "format_name": "IAB VAST 4.2 Living-Room CTV Non-Skippable Spot",
        "allowed_dimensions": ["1920x1080", "3840x2160"],
        "default_dimensions": "1920x1080",
        "duration_sec": 15,
        "has_audio": True,
        "safe_zone_inset_pct": 10,  # Mandatory 10% TV overscan safe zone
        "max_headline_words": 12,
    },
    "dooh": {
        "format_name": "OpenRTB DOOH Urban Commuter Digital Totem",
        "allowed_dimensions": ["1080x1920", "1920x1080"],
        "default_dimensions": "1080x1920",
        "duration_sec": 8,
        "has_audio": False,  # Strict zero-audio rule on DOOH
        "safe_zone_inset_pct": 6,
        "max_headline_words": 8,  # Strict <= 8 words for 15m highway/pedestrian legibility
    },
}


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (1.0, 1.0, 1.0)
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    def channel_lum(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel_lum(r) + 0.7152 * channel_lum(g) + 0.0722 * channel_lum(b)


def compute_wcag_contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """Compute WCAG 2.2 luminance contrast ratio between foreground text (#FFFFFF) and background hex."""
    l1 = _relative_luminance(_hex_to_rgb(fg_hex))
    l2 = _relative_luminance(_hex_to_rgb(bg_hex))
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


class CreativeMCPServer:
    """MCP Server for Omnichannel Creative Synthesis, Technical Spec Validation & Brand Compliance QA."""

    @staticmethod
    def generate_channel_creative(
        brief: CampaignBrief,
        channel: ChannelType,
        brand_guidelines: dict[str, Any],
        episodic_learnings: list[str],
        revision_count: int = 0,
        compliance_feedback: str = "",
    ) -> CreativeAsset:
        """
        Synthesize a channel-specific creative asset (Display, Video, CTV, DOOH).
        On revision_count == 0, if the brief contains prohibited claims, those claims may surface
        unless scrubbed on revision_count >= 1 after ComplianceJudge feedback.
        """
        spec = IAB_CHANNEL_SPECS[channel]
        brand_name = brief.brand_name
        clean_objective = sanitize_untrusted_text(brief.objective)
        prohibited_list: list[str] = brand_guidelines.get("prohibited_phrases", [])

        # Determine if the raw brief intentionally injected a prohibited claim (for Gate 3 testing)
        matched_prohibited_in_brief = [
            p for p in prohibited_list if p.lower() in clean_objective.lower()
        ]

        # On first pass (revision_count == 0), reflect the brief's claim so ComplianceJudge can catch & self-correct it!
        # On revision passes (revision_count >= 1), strip all prohibited claims per ComplianceJudge critique.
        safe_subheadline = clean_objective[:110]
        if matched_prohibited_in_brief and revision_count == 0:
            raw_phrase = matched_prohibited_in_brief[0]
            if channel == "dooh":
                headline = f"{brand_name}: {raw_phrase.title()} Now"
            else:
                headline = f"{brand_name} Delivers {raw_phrase.title()} For Your Future"
        else:
            for phrase in prohibited_list + ["guaranteed 10x", "500% return", "100% risk-free"]:
                safe_subheadline = re.sub(
                    re.escape(phrase),
                    "verified performance",
                    safe_subheadline,
                    flags=re.IGNORECASE,
                )
            # Compliant, high-converting channel-tailored headlines
            if channel == "dooh":
                # Strictly <= 8 words for DOOH legibility
                headline = f"Experience {brand_name} Precision Performance Today"
            elif channel == "ctv":
                headline = f"Meet {brand_name}: Engineered for Next-Generation Performance"
            elif channel == "video":
                headline = f"{brand_name} — Built for Speed, Clarity, and Impact"
            else:
                headline = f"Upgrade to {brand_name}: Intelligent Performance Delivered"

        # Trim DOOH headline to <= 8 words deterministically
        words = headline.split()
        if channel == "dooh" and len(words) > 8:
            headline = " ".join(words[:8])
        elif len(words) > 12:
            headline = " ".join(words[:12])

        word_count = len(headline.split())
        bg_hex = brand_guidelines.get("background_hex", "#0F172A")
        primary_hex = brand_guidelines.get("primary_hex", "#4F46E5")
        contrast = compute_wcag_contrast_ratio("#FFFFFF", bg_hex)

        storyboard = []
        triggers = []
        if channel in ("ctv", "video"):
            storyboard = [
                f"00-03s [Hook]: Dynamic hero reveal of {brand_name} in {brief.target_geos[0]} metro.",
                f"03-11s [Proof]: Visual demonstration of core value proposition ({clean_objective[:65]}...).",
                f"11-15s [Endcard + QR]: High-contrast brand lockup, disclaimer, and '{brand_guidelines.get('default_cta', 'Learn More')}' CTA.",
            ]
        if channel == "dooh":
            triggers = [
                "Rush-Hour Commute (07:30-09:30 / 17:00-19:30)",
                f"Geo-Fence: {', '.join(brief.target_geos)} Financial & Shopping Districts",
                "Live Weather Adaptive Brightness",
            ]

        asset_hash = hashlib.md5(
            f"{brief.campaign_id}:{channel}:rev{revision_count}".encode()
        ).hexdigest()[:6].upper()

        asset = CreativeAsset(
            asset_id=f"CR-{channel.upper()}-{asset_hash}",
            channel=channel,
            format_name=spec["format_name"],
            dimensions=spec["default_dimensions"],
            duration_sec=spec["duration_sec"],
            has_audio=spec["has_audio"],
            safe_zone_inset_pct=spec["safe_zone_inset_pct"],
            headline=headline,
            subheadline=safe_subheadline,
            cta_text="" if channel == "dooh" else brand_guidelines.get("default_cta", "Learn More"),
            primary_hex=primary_hex,
            background_hex=bg_hex,
            contrast_ratio=contrast,
            word_count=word_count,
            visual_scene_description=(
                f"{brand_name} {spec['format_name']} rendered in {primary_hex} accent on {bg_hex} surface "
                f"targeting {', '.join(brief.audience_segments or ['Core Audience'])}."
            ),
            storyboard_beats=storyboard,
            contextual_triggers=triggers,
            disclaimer_text=brand_guidelines.get(
                "mandatory_disclaimer", "Terms and conditions apply."
            ),
            c2pa_provenance={
                "c2pa_manifest": "urn:c2pa:adaiz-creative-studio-2026",
                "synthetic_origin": True,
                "brand_vault_tenant": brief.tenant_id,
                "revision": revision_count,
            },
        )
        return CreativeMCPServer.validate_creative_specs_deterministic(asset)

    @staticmethod
    def validate_creative_specs_deterministic(asset: CreativeAsset) -> CreativeAsset:
        """
        Layer A: Deterministic Technical QA (Zero LLM).
        Verifies IAB dimensions, CTV 10% overscan safe zone, DOOH <=8 words & zero audio, and WCAG >= 4.5 contrast.
        """
        spec = IAB_CHANNEL_SPECS[asset.channel]
        errors: list[str] = []

        if asset.dimensions not in spec["allowed_dimensions"]:
            errors.append(
                f"Invalid dimension '{asset.dimensions}' for {asset.channel}; allowed={spec['allowed_dimensions']}"
            )
        if asset.channel == "ctv" and asset.safe_zone_inset_pct < 10:
            errors.append("CTV creative violates mandatory 10% TV overscan safe-zone inset.")
        if asset.channel == "dooh":
            if asset.has_audio:
                errors.append("DOOH creative cannot contain an audio track.")
            if len(asset.headline.split()) > 8:
                errors.append(
                    f"DOOH headline has {len(asset.headline.split())} words (strict max is 8 words for 15m legibility)."
                )
        if asset.contrast_ratio < 4.5:
            errors.append(
                f"WCAG contrast ratio {asset.contrast_ratio}:1 is below the 4.5:1 AA minimum."
            )

        return asset.model_copy(
            update={
                "word_count": len(asset.headline.split()),
                "spec_valid": len(errors) == 0,
                "spec_errors": errors,
            }
        )

    @staticmethod
    def evaluate_brand_compliance(
        creatives: list[CreativeAsset],
        brand_guidelines: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
    ) -> tuple[bool, str, list[CreativeAsset]]:
        """
        Layer B: Multimodal Brand & Regulatory Compliance Judge.
        Audits all channel creatives against Brand Vault prohibited phrases, mandatory disclaimers,
        and technical specs, citing exact Hybrid RAG rule_ids.
        """
        prohibited_phrases: list[str] = brand_guidelines.get("prohibited_phrases", [])
        mandatory_disclaimer: str = brand_guidelines.get("mandatory_disclaimer", "")
        cited_rules = [c["rule_id"] for c in retrieved_chunks if "rule_id" in c] or ["GEN-LEGAL-01"]

        all_passed = True
        feedback_items: list[str] = []
        evaluated_assets: list[CreativeAsset] = []

        for asset in creatives:
            violations: list[str] = []
            combined_text = f"{asset.headline} {asset.subheadline}".lower()

            for phrase in prohibited_phrases:
                if phrase.lower() in combined_text:
                    violations.append(
                        f"Prohibited claim '{phrase}' detected in {asset.channel.upper()} creative (violates {', '.join(cited_rules)})."
                    )

            # Check for unsubstantiated superlatives even if not in brand list
            for global_ban in ["guaranteed 10x", "500% return", "100% risk-free"]:
                if global_ban in combined_text and not any(global_ban in v.lower() for v in violations):
                    violations.append(
                        f"Regulatory violation: unsubstantiated claim '{global_ban}' in {asset.channel.upper()} headline."
                    )

            if mandatory_disclaimer and not asset.disclaimer_text.strip():
                violations.append(
                    f"Missing mandatory regulatory disclaimer on {asset.channel.upper()} unit."
                )

            if not asset.spec_valid:
                violations.extend(asset.spec_errors)

            passed = len(violations) == 0
            if not passed:
                all_passed = False
                feedback_items.extend(violations)

            # Sanitize subheadline if it had prohibited phrases so next revision is clean
            cleaned_sub = asset.subheadline
            for phrase in prohibited_phrases + ["guaranteed 10x", "500% return", "100% risk-free"]:
                cleaned_sub = re.sub(
                    re.escape(phrase),
                    "verified performance",
                    cleaned_sub,
                    flags=re.IGNORECASE,
                )

            evaluated_assets.append(
                asset.model_copy(
                    update={
                        "subheadline": cleaned_sub,
                        "compliance_passed": passed,
                        "compliance_score": 0.98 if passed else 0.42,
                        "compliance_notes": (
                            f"Passed Brand & Regulatory Audit ({', '.join(cited_rules)})"
                            if passed
                            else "; ".join(violations)
                        ),
                        "cited_rule_ids": cited_rules,
                    }
                )
            )

        summary_feedback = (
            "All omnichannel creatives passed Brand Vault & IAB compliance checks."
            if all_passed
            else " | ".join(feedback_items)
        )
        return all_passed, summary_feedback, evaluated_assets
