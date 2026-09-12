# paper_search_mcp/academic_platforms/opencitations.py
"""OpenCitations Index REST API v2 client — citation-graph cross-check only.

Deliberately has no search(), so it does not subclass PaperSource and is not
registered in server.py's ALL_SOURCES / search_papers aggregator: a searcher
without search() would throw there (SPEC §7.4-7.5).
"""
from dataclasses import dataclass
from typing import List, Optional
import logging
import requests

logger = logging.getLogger(__name__)


@dataclass
class OpenCitationsEdge:
    oci: str
    citing_doi: Optional[str]
    cited_doi: Optional[str]
    citing_openalex_id: Optional[str]
    cited_openalex_id: Optional[str]


class OpenCitationsSearcher:
    """Client for the OpenCitations Index (no auth required)."""

    BASE_URL = "https://opencitations.net/index/api/v2"

    def __init__(self):
        self.session = requests.Session()

    @staticmethod
    def _extract_id_token(field_value: str, prefix: str) -> Optional[str]:
        for token in (field_value or "").split():
            if token.startswith(prefix):
                return token[len(prefix):]
        return None

    def _parse_edge(self, raw: dict) -> OpenCitationsEdge:
        citing = raw.get("citing", "")
        cited = raw.get("cited", "")
        return OpenCitationsEdge(
            oci=raw.get("oci", ""),
            citing_doi=self._extract_id_token(citing, "doi:"),
            cited_doi=self._extract_id_token(cited, "doi:"),
            citing_openalex_id=self._extract_id_token(citing, "openalex:"),
            cited_openalex_id=self._extract_id_token(cited, "openalex:"),
        )

    def _get_json(self, path: str):
        # opencitations.net 301-redirects to api.opencitations.net (verified
        # 2026-09-12, SPEC §7.3). A client that doesn't follow redirects gets
        # a 17-byte body and silently reports zero references — assert the
        # follow explicitly rather than trusting the client default.
        response = self.session.get(
            f"{self.BASE_URL}/{path}", timeout=30, allow_redirects=True
        )
        response.raise_for_status()
        return response.json()

    def get_references(self, doi: str) -> List[OpenCitationsEdge]:
        """Backward: works cited by `doi`."""
        return [self._parse_edge(edge) for edge in self._get_json(f"references/doi:{doi}")]

    def get_citations(self, doi: str) -> List[OpenCitationsEdge]:
        """Forward: works citing `doi`."""
        return [self._parse_edge(edge) for edge in self._get_json(f"citations/doi:{doi}")]

    def get_citation_count(self, doi: str) -> int:
        """OpenCitations' own forward-citation count for `doi`."""
        data = self._get_json(f"citation-count/doi:{doi}")
        if not data:
            return 0
        # OpenCitations returns the count as a quoted string, not an int — cast explicitly.
        return int(data[0]["count"])
