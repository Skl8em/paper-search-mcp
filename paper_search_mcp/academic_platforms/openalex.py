from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime
import re
import requests
import logging
from ..paper import Paper
from .base import PaperSource
from ..config import get_env
from ..utils import extract_doi

logger = logging.getLogger(__name__)

# Canonical OpenAlex work ID: "W" + digits, no leading zero. OpenAlex has been
# observed (verified 2026-09-12) to silently resolve a zero-padded ID like
# "W0000000000" to an unrelated work instead of 404ing, so any ID that
# doesn't match this is treated as unresolvable rather than sent to the API.
_WORK_ID_RE = re.compile(r"^W[1-9]\d*$")
_OPENALEX_URL_RE = re.compile(r"^https?://(api\.)?openalex\.org/(works/)?(W[0-9]+)$", re.IGNORECASE)


@dataclass
class ReferencesResult:
    """Backward citation traversal result — see get_work_references()."""
    work_id: str
    ids: List[str] = field(default_factory=list)
    papers: List[Paper] = field(default_factory=list)


@dataclass
class CitationsResult:
    """Forward citation traversal result — see get_work_citations().

    `count` is OpenAlex's own count for this edge (meta.count from the first
    page), not len(ids) — the two can and do diverge (SPEC §3.2).
    """
    work_id: str
    ids: List[str] = field(default_factory=list)
    count: Optional[int] = None
    next_cursor: Optional[str] = None
    exhausted: bool = False


class OpenAlexSearcher(PaperSource):
    """OpenAlex paper search implementation"""

    BASE_URL = "https://api.openalex.org/works"

    def __init__(self):
        self.session = requests.Session()
        # OpenAlex's "polite pool" wants a contact email in the User-Agent.
        # Configurable via OPENALEX_EMAIL; omit mailto entirely when unset
        # rather than sending a fake address belonging to someone else.
        email = get_env("OPENALEX_EMAIL", "")
        user_agent = "paper-search-mcp/1.0"
        if email:
            user_agent += f" (mailto:{email})"
        self.session.headers.update({"User-Agent": user_agent})

    def _reconstruct_abstract(self, inverted_index: dict) -> str:
        """
        OpenAlex provides abstracts as an inverted index to save space.
        This function reconstructs the original abstract text.
        """
        if not inverted_index:
            return ""
        try:
            word_positions = []
            for word, positions in inverted_index.items():
                for pos in positions:
                    word_positions.append((pos, word))
            # Sort by position
            word_positions.sort(key=lambda x: x[0])
            return " ".join([word for _, word in word_positions])
        except Exception as e:
            logger.warning(f"Error reconstructing OpenAlex abstract: {e}")
            return ""

    @staticmethod
    def _strip_openalex_prefix(value: str) -> str:
        # OpenAlex IDs come back as full URLs, e.g. 'https://openalex.org/W2741809807'
        return (value or "").replace("https://openalex.org/", "")

    def _parse_work_item(self, item: dict) -> Optional[Paper]:
        """Build a Paper from one OpenAlex work record. Returns None for
        items without a title (matches upstream search() skip behavior)."""
        title = item.get("title")
        if not title:
            return None

        paper_id = self._strip_openalex_prefix(item.get("id", ""))

        authors = [
            author.get("author", {}).get("display_name", "")
            for author in item.get("authorships", [])
            if author.get("author", {}).get("display_name")
        ]

        abstract = self._reconstruct_abstract(item.get("abstract_inverted_index"))

        doi = item.get("doi", "")
        if doi:
            # OpenAlex DOI is returned as a full url e.g. https://doi.org/10...
            doi = doi.replace("https://doi.org/", "")

        if not doi and abstract:
            doi = extract_doi(abstract)

        url = ""
        pdf_url = ""

        primary_location = item.get("primary_location")
        if primary_location:
            url = primary_location.get("landing_page_url", "")
            pdf_url = primary_location.get("pdf_url", "")

        if not url:
            url = item.get("id", "")

        open_access = item.get("open_access", {})
        if not pdf_url and open_access.get("is_oa"):
            pdf_url = open_access.get("oa_url", "")

        pub_date_str = item.get("publication_date")
        published_date = None
        if pub_date_str:
            try:
                published_date = datetime.strptime(pub_date_str, "%Y-%m-%d")
            except ValueError:
                pass

        concepts = [
            concept.get("display_name")
            for concept in item.get("concepts", [])
            if concept.get("display_name")
        ]

        references = [
            self._strip_openalex_prefix(ref)
            for ref in item.get("referenced_works", [])
        ]

        return Paper(
            paper_id=paper_id,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url or "",
            published_date=published_date,
            source="openalex",
            categories=concepts[:5],  # Keep top 5 concepts to reduce size
            doi=doi,
            citations=item.get("cited_by_count", 0),
            references=references,
        )

    def search(self, query: str, max_results: int = 10) -> List[Paper]:
        """
        Search OpenAlex works. Uses the 'search' filter.

        Args:
            query: Search query string
            max_results: Maximum results to return (natively max 200 per page)

        Returns:
            List[Paper]: List of found papers with metadata.
        """
        papers = []

        try:
            params = {
                "search": query,
                "per_page": min(max_results, 200),
            }

            response = self.session.get(self.BASE_URL, params=params, timeout=30)

            if response.status_code != 200:
                logger.error(f"OpenAlex search failed with status {response.status_code}")
                return papers

            data = response.json()
            results = data.get("results", [])

            for item in results:
                if len(papers) >= max_results:
                    break
                paper = self._parse_work_item(item)
                if paper:
                    papers.append(paper)

        except Exception as e:
            logger.error(f"OpenAlex search error: {e}")

        return papers

    def resolve_work(self, identifier: str) -> str:
        """Normalize a DOI, OpenAlex work ID, or OpenAlex URL to a canonical
        OpenAlex work ID (e.g. 'W2088435028').

        Every traversal method depends on this normalization. Raises
        ValueError for anything that cannot be resolved — an unresolvable
        identifier must fail loudly, not come back as an empty result.
        """
        if not identifier or not identifier.strip():
            raise ValueError("resolve_work: identifier must not be empty")

        ident = identifier.strip()

        url_match = _OPENALEX_URL_RE.match(ident)
        if url_match:
            ident = url_match.group(3)

        if re.match(r"^[Ww]\d+$", ident):
            normalized = ident.upper()
            if _WORK_ID_RE.match(normalized):
                return normalized
            raise ValueError(
                f"resolve_work: '{identifier}' is not a canonical OpenAlex work ID "
                "(leading zeros are ambiguous — OpenAlex has been observed silently "
                "resolving these to an unrelated work)"
            )

        doi = ident
        for prefix in ("doi:", "https://doi.org/", "http://doi.org/"):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix):]
                break

        response = self.session.get(
            f"{self.BASE_URL}/https://doi.org/{doi}",
            params={"select": "id"},
            timeout=30,
        )
        if response.status_code != 200:
            raise ValueError(
                f"resolve_work: could not resolve identifier '{identifier}' "
                f"(HTTP {response.status_code})"
            )

        resolved = self._strip_openalex_prefix(response.json().get("id", ""))
        if not _WORK_ID_RE.match(resolved):
            raise ValueError(
                f"resolve_work: OpenAlex returned an unexpected id '{resolved}' "
                f"for '{identifier}'"
            )
        return resolved

    def _fetch_works_by_ids(self, ids: List[str]) -> List[Paper]:
        papers: List[Paper] = []
        batch_size = 50  # pipe-joined OR filter; batched defensively — no documented upper bound verified
        for start in range(0, len(ids), batch_size):
            batch = ids[start:start + batch_size]
            response = self.session.get(
                self.BASE_URL,
                params={"filter": "openalex_id:" + "|".join(batch), "per_page": len(batch)},
                timeout=30,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"OpenAlex batch lookup failed with HTTP {response.status_code}"
                )
            for item in response.json().get("results", []):
                paper = self._parse_work_item(item)
                if paper:
                    papers.append(paper)
        return papers

    def get_work_references(self, work_id: str) -> ReferencesResult:
        """Backward traversal: resolve a work's `referenced_works` to full
        Paper objects. A work with genuinely no references returns an empty
        ReferencesResult, not an error — see resolve_work() for the error case."""
        resolved = self.resolve_work(work_id)

        response = self.session.get(
            f"{self.BASE_URL}/{resolved}",
            params={"select": "id,referenced_works"},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"get_work_references: OpenAlex returned HTTP {response.status_code} "
                f"for '{resolved}'"
            )

        ref_ids = [
            self._strip_openalex_prefix(u)
            for u in response.json().get("referenced_works", [])
        ]
        if not ref_ids:
            return ReferencesResult(work_id=resolved, ids=[], papers=[])

        papers = self._fetch_works_by_ids(ref_ids)
        return ReferencesResult(work_id=resolved, ids=ref_ids, papers=papers)

    def get_work_citations(
        self,
        work_id: str,
        max_results: int = 200,
        cursor: Optional[str] = None,
    ) -> CitationsResult:
        """Forward traversal via filter=cites:<id>, cursor-paginated.

        Minimal `select` (id only) — a cascade can hit thousands of citers
        and full records dominate both time and quota (SPEC §7.2). Never
        assert an exact `count`: OpenAlex's own count is unstable within
        minutes (SPEC §3.2) — assert magnitude/structure instead.
        """
        resolved = self.resolve_work(work_id)

        ids: List[str] = []
        count: Optional[int] = None
        next_cursor = cursor or "*"
        exhausted = False

        while len(ids) < max_results:
            page_size = min(200, max_results - len(ids))
            response = self.session.get(
                self.BASE_URL,
                params={
                    "filter": f"cites:{resolved}",
                    "per-page": page_size,
                    "select": "id",
                    "cursor": next_cursor,
                },
                timeout=30,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"get_work_citations: OpenAlex returned HTTP {response.status_code} "
                    f"for '{resolved}'"
                )

            data = response.json()
            if count is None:
                count = data.get("meta", {}).get("count")

            page_ids = [
                self._strip_openalex_prefix(item.get("id", ""))
                for item in data.get("results", [])
            ]
            ids.extend(page_ids)

            next_cursor = data.get("meta", {}).get("next_cursor")
            if not next_cursor or not page_ids:
                exhausted = True
                break

        return CitationsResult(
            work_id=resolved,
            ids=ids[:max_results],
            count=count,
            next_cursor=next_cursor,
            exhausted=exhausted,
        )

    def get_citation_count(self, identifier: str) -> int:
        """OpenAlex's own `cited_by_count` for a work — used by cross_check_citations."""
        resolved = self.resolve_work(identifier)
        response = self.session.get(
            f"{self.BASE_URL}/{resolved}",
            params={"select": "id,cited_by_count"},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"get_citation_count: OpenAlex returned HTTP {response.status_code} "
                f"for '{resolved}'"
            )
        return response.json().get("cited_by_count", 0)

    def download_pdf(self, paper_id: str, save_path: str) -> str:
        """
        OpenAlex does not host PDFs natively, it only links to open access versions.
        """
        raise NotImplementedError(
            "OpenAlex does not provide direct PDF downloads natively. "
            "Please use the extracted 'pdf_url' if available, or DOI for fallback."
        )

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """
        Not implemented for OpenAlex.
        """
        return (
            "OpenAlex papers cannot be read directly through this aggregator. "
            "Please use the paper's DOI or pdf_url to access the full text."
        )


if __name__ == "__main__":
    searcher = OpenAlexSearcher()
    print("Testing OpenAlex search...")
    papers = searcher.search("CRISPR Cas9 Nature", max_results=3)

    for i, paper in enumerate(papers, 1):
        print(f"\n{i}. {paper.title}")
        print(f"   DOI: {paper.doi}")
        print(f"   URL: {paper.url}")
        print(f"   OA PDF: {paper.pdf_url}")
        print(f"   Citations: {paper.citations}")
        print(f"   Authors: {', '.join(paper.authors[:3])}")
        if paper.abstract:
            print(f"   Abstract: {paper.abstract[:100]}...")
