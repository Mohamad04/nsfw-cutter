from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from services.analysis.contracts import (
    AnalysisSettings,
    FinalSuggestion,
    NSFWCategory,
    TextEvidence,
    VisualEvidence,
)

_CATEGORY_PRIORITY = {
    NSFWCategory.SEXUAL_ACTIVITY: 4,
    NSFWCategory.NUDITY: 3,
    NSFWCategory.SEXUAL_CONTEXT: 2,
    NSFWCategory.UNCERTAIN: 1,
}


@dataclass
class _FusedCandidate:
    start_seconds: float
    end_seconds: float
    category: NSFWCategory
    visual_confidence: float
    text_confidence: float
    final_confidence: float
    evidence_timestamps: list[float] = field(default_factory=list)
    reason: str = ""


def fuse_evidence(
    visual_evidence: list[VisualEvidence],
    text_evidence: list[TextEvidence],
    settings: AnalysisSettings,
    duration_seconds: float,
    video_fingerprint: str,
) -> list[FinalSuggestion]:
    """Fuse text into visual candidates; text can never create a suggestion alone."""
    candidates: list[_FusedCandidate] = []
    for visual in visual_evidence:
        if visual.confidence < settings.visual_confidence_threshold:
            continue
        matching_text = [
            text
            for text in text_evidence
            if text.confidence >= settings.text_confidence_threshold
            and _intervals_near(
                visual.start_seconds,
                visual.end_seconds,
                text.start_seconds,
                text.end_seconds,
                tolerance=1.0,
            )
        ]
        text_confidence = max((item.confidence for item in matching_text), default=0.0)
        category_agrees = any(
            _categories_support_each_other(visual.category, item.category)
            for item in matching_text
        )
        final_confidence = _combined_confidence(
            visual.confidence,
            text_confidence,
            category_agrees,
        )
        candidates.append(
            _FusedCandidate(
                start_seconds=visual.start_seconds,
                end_seconds=visual.end_seconds,
                category=visual.category,
                visual_confidence=visual.confidence,
                text_confidence=text_confidence,
                final_confidence=final_confidence,
                evidence_timestamps=list(visual.evidence_timestamps),
                reason=visual.reason,
            )
        )

    merged = _merge_candidates(
        candidates,
        merge_gap_seconds=settings.merge_gap_seconds,
        context_padding_seconds=settings.context_padding_seconds,
        duration_seconds=duration_seconds,
    )
    suggestions = []
    for candidate in merged:
        suggestion_id = _suggestion_id(video_fingerprint, candidate)
        suggestions.append(
            FinalSuggestion(
                id=suggestion_id,
                start_seconds=round(candidate.start_seconds, 3),
                end_seconds=round(candidate.end_seconds, 3),
                category=candidate.category,
                visual_confidence=round(candidate.visual_confidence, 4),
                text_confidence=round(candidate.text_confidence, 4),
                final_confidence=round(candidate.final_confidence, 4),
                evidence_timestamps=[
                    round(timestamp, 3)
                    for timestamp in sorted(set(candidate.evidence_timestamps))
                ],
                reason=_safe_reason(candidate.reason),
                needs_review=True,
            )
        )
    return suggestions


def merge_time_ranges(
    ranges: list[tuple[float, float]],
    *,
    merge_gap_seconds: float,
    context_padding_seconds: float,
    duration_seconds: float,
) -> list[tuple[float, float]]:
    """Pad, clip, and merge ranges. This helper has no analysis dependencies."""
    normalized = []
    for start, end in ranges:
        padded_start = max(0.0, float(start) - context_padding_seconds)
        padded_end = min(float(duration_seconds), float(end) + context_padding_seconds)
        if padded_end > padded_start:
            normalized.append((padded_start, padded_end))
    normalized.sort()

    merged: list[list[float]] = []
    for start, end in normalized:
        if not merged or start > merged[-1][1] + merge_gap_seconds:
            merged.append([start, end])
            continue
        merged[-1][1] = max(merged[-1][1], end)
    return [(round(start, 6), round(end, 6)) for start, end in merged]


def _merge_candidates(
    candidates: list[_FusedCandidate],
    *,
    merge_gap_seconds: float,
    context_padding_seconds: float,
    duration_seconds: float,
) -> list[_FusedCandidate]:
    normalized_candidates = []
    for candidate in candidates:
        padded_start = max(0.0, candidate.start_seconds - context_padding_seconds)
        padded_end = min(duration_seconds, candidate.end_seconds + context_padding_seconds)
        if padded_end <= padded_start:
            continue
        candidate.start_seconds = padded_start
        candidate.end_seconds = padded_end
        candidate.evidence_timestamps = [
            max(0.0, min(duration_seconds, timestamp))
            for timestamp in candidate.evidence_timestamps
        ]
        normalized_candidates.append(candidate)

    ordered = sorted(
        normalized_candidates,
        key=lambda item: (item.start_seconds, item.end_seconds),
    )
    groups: list[list[_FusedCandidate]] = []
    current_end = 0.0
    for candidate in ordered:
        if not groups or candidate.start_seconds > current_end + merge_gap_seconds:
            groups.append([candidate])
            current_end = candidate.end_seconds
            continue
        groups[-1].append(candidate)
        current_end = max(current_end, candidate.end_seconds)

    return [_collapse_group(group) for group in groups]


def _collapse_group(group: list[_FusedCandidate]) -> _FusedCandidate:
    strongest = max(
        group,
        key=lambda item: (
            item.visual_confidence,
            _CATEGORY_PRIORITY[item.category],
            item.final_confidence,
        ),
    )
    reasons = []
    for item in sorted(group, key=lambda candidate: candidate.visual_confidence, reverse=True):
        reason = _safe_reason(item.reason)
        if reason and reason not in reasons:
            reasons.append(reason)
        if len(reasons) >= 2:
            break
    return _FusedCandidate(
        start_seconds=min(item.start_seconds for item in group),
        end_seconds=max(item.end_seconds for item in group),
        category=strongest.category,
        visual_confidence=max(item.visual_confidence for item in group),
        text_confidence=max(item.text_confidence for item in group),
        final_confidence=max(item.final_confidence for item in group),
        evidence_timestamps=[
            timestamp
            for item in group
            for timestamp in item.evidence_timestamps
        ],
        reason="; ".join(reasons),
    )


def _combined_confidence(
    visual_confidence: float,
    text_confidence: float,
    category_agrees: bool,
) -> float:
    # Text only adds a small residual boost; visual evidence remains the primary score.
    text_boost = (1.0 - visual_confidence) * 0.12 * text_confidence
    agreement_boost = (1.0 - visual_confidence) * 0.04 if category_agrees else 0.0
    return min(1.0, visual_confidence + text_boost + agreement_boost)


def _categories_support_each_other(left: NSFWCategory, right: NSFWCategory) -> bool:
    if left == right:
        return True
    sexual_categories = {
        NSFWCategory.NUDITY,
        NSFWCategory.SEXUAL_ACTIVITY,
        NSFWCategory.SEXUAL_CONTEXT,
    }
    return left in sexual_categories and right in sexual_categories


def _intervals_near(
    left_start: float,
    left_end: float,
    right_start: float,
    right_end: float,
    *,
    tolerance: float,
) -> bool:
    return right_start <= left_end + tolerance and left_start <= right_end + tolerance


def _suggestion_id(video_fingerprint: str, candidate: _FusedCandidate) -> str:
    payload = (
        f"{video_fingerprint}|{candidate.start_seconds:.3f}|"
        f"{candidate.end_seconds:.3f}|{candidate.category.value}"
    )
    return f"vlm-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"


def _safe_reason(value: str, limit: int = 320) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        return "Visual evidence requires manual review."
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
