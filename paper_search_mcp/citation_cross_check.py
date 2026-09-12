# paper_search_mcp/citation_cross_check.py
"""Cross-source citation-count check — SPEC §3.2 and §5.4.

OpenAlex and OpenCitations routinely disagree (verified 2026-09-12: 4959 vs
2919 forward citers for the same work), and OpenAlex disagrees with itself
between calls minutes apart. That divergence is a property of the indices,
not a bug to average away — this reports both counts and their delta rather
than merging them, and keeps a failure on one source from hiding the other's
result (partial success must stay visible as partial).
"""
from dataclasses import dataclass
from typing import Optional

from .academic_platforms.openalex import OpenAlexSearcher
from .academic_platforms.opencitations import OpenCitationsSearcher


@dataclass
class CrossCheckResult:
    doi: str
    openalex_count: Optional[int] = None
    openalex_error: Optional[str] = None
    opencitations_count: Optional[int] = None
    opencitations_error: Optional[str] = None

    @property
    def delta(self) -> Optional[int]:
        if self.openalex_count is None or self.opencitations_count is None:
            return None
        return self.openalex_count - self.opencitations_count


def cross_check_citations(
    doi: str,
    openalex_searcher: OpenAlexSearcher,
    opencitations_searcher: OpenCitationsSearcher,
) -> CrossCheckResult:
    result = CrossCheckResult(doi=doi)

    try:
        result.openalex_count = openalex_searcher.get_citation_count(doi)
    except Exception as exc:
        result.openalex_error = str(exc)

    try:
        result.opencitations_count = opencitations_searcher.get_citation_count(doi)
    except Exception as exc:
        result.opencitations_error = str(exc)

    return result
