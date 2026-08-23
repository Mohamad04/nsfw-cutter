from __future__ import annotations

from services.analysis.pipeline import (
    AnalysisServices,
    AnalysisState,
    fuse_evidence_node,
    gather_text_evidence_node,
    persist_and_publish_node,
    prefilter_visual_evidence_node,
    preflight_node,
    review_visual_batches_node,
    sample_visual_evidence_node,
)


def build_analysis_graph(services: AnalysisServices):
    """Build the fixed LangGraph orchestration; nodes contain no graph-specific logic."""
    from langgraph.graph import END, START, StateGraph

    builder = StateGraph(AnalysisState)
    builder.add_node("preflight", lambda state: preflight_node(state, services))
    builder.add_node(
        "gather_text_evidence",
        lambda state: gather_text_evidence_node(state, services),
    )
    builder.add_node(
        "sample_visual_evidence",
        lambda state: sample_visual_evidence_node(state, services),
    )
    builder.add_node(
        "review_visual_batches",
        lambda state: review_visual_batches_node(state, services),
    )
    builder.add_node(
        "prefilter_visual_evidence",
        lambda state: prefilter_visual_evidence_node(state, services),
    )
    builder.add_node("fuse_evidence", lambda state: fuse_evidence_node(state, services))
    builder.add_node(
        "persist_and_publish",
        lambda state: persist_and_publish_node(state, services),
    )
    builder.add_edge(START, "preflight")
    builder.add_edge("preflight", "gather_text_evidence")
    builder.add_edge("gather_text_evidence", "sample_visual_evidence")
    builder.add_edge("sample_visual_evidence", "prefilter_visual_evidence")
    builder.add_edge("prefilter_visual_evidence", "review_visual_batches")
    builder.add_edge("review_visual_batches", "fuse_evidence")
    builder.add_edge("fuse_evidence", "persist_and_publish")
    builder.add_edge("persist_and_publish", END)
    return builder.compile()
