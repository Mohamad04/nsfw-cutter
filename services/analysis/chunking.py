from __future__ import annotations

from services.analysis.preprocessing_contracts import PreprocessingConfig, ProcessingChunk


def plan_processing_chunks(
    movie_duration_us: int,
    config: PreprocessingConfig,
) -> tuple[ProcessingChunk, ...]:
    """Plan gap-free logical cores plus clamped decode context.

    ``chunk_overlap_seconds`` is the total shared context around an interior core
    boundary. Half is added to each side of a chunk where media exists.
    """
    if movie_duration_us <= 0:
        raise ValueError("movie duration must be positive")

    core_duration_us = config.chunk_duration_us
    overlap_us = config.chunk_overlap_us
    context_before_us = overlap_us // 2
    context_after_us = overlap_us - context_before_us
    chunks: list[ProcessingChunk] = []

    core_start_us = 0
    while core_start_us < movie_duration_us:
        core_end_us = min(movie_duration_us, core_start_us + core_duration_us)
        chunks.append(
            ProcessingChunk(
                index=len(chunks),
                core_start_us=core_start_us,
                core_end_us=core_end_us,
                decode_start_us=max(0, core_start_us - context_before_us),
                decode_end_us=min(movie_duration_us, core_end_us + context_after_us),
            )
        )
        core_start_us = core_end_us

    return tuple(chunks)


def owning_chunk_index(chunks: tuple[ProcessingChunk, ...], timestamp_us: int) -> int | None:
    """Return the unique half-open core owner, including the final media endpoint."""
    for position, chunk in enumerate(chunks):
        is_last = position == len(chunks) - 1
        if chunk.core_start_us <= timestamp_us < chunk.core_end_us:
            return chunk.index
        if is_last and timestamp_us == chunk.core_end_us:
            return chunk.index
    return None
