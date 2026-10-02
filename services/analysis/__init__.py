"""Local-first VLM analysis services.

Heavy AI dependencies are imported only by their concrete adapters so importing the
desktop controller continues to work with the base application requirements.
"""

from services.analysis.cancellation import AnalysisCancelled, CancellationToken
from services.analysis.contracts import (
    AnalysisRecord,
    AnalysisRunRequest,
    AnalysisSettings,
    FinalSuggestion,
    NSFWCategory,
    VLMReviewResponse,
)

__all__ = [
    "AnalysisCancelled",
    "AnalysisRecord",
    "AnalysisRunRequest",
    "AnalysisSettings",
    "CancellationToken",
    "FinalSuggestion",
    "NSFWCategory",
    "VLMReviewResponse",
]
