"""Tests for the OpenAlex citation-cascade tools added on top of upstream
search(): resolve_work, get_work_references, get_work_citations, plus the
Paper.references regression guard.  See paper_search_mcp-cascade-SPEC.md §6.

Mock-based tests are the primary suite (deterministic, no network flakiness).
A small number of live tests validate the SPEC's cross-validated anchor
fixture against the real OpenAlex API and are skipped when it's unreachable.
"""
import unittest
import requests
from unittest.mock import Mock, patch

from paper_search_mcp.academic_platforms.openalex import (
    OpenAlexSearcher,
    ReferencesResult,
    CitationsResult,
)

# SPEC §6 Test 1 anchor fixture, cross-validated against OpenAlex and
# OpenCitations on 2026-09-12.
ANCHOR_WORK_ID = "W2088435028"          # Allingham & Sandmo 1972
ANCHOR_WORK_DOI = "10.1016/0047-2727(72)90010-2"
ANCHOR_REFERENCE_ID = "W2084610231"      # doi:10.2307/2552162, appears in ANCHOR's referenced_works


def check_openalex_accessible():
    try:
        response = requests.get("https://api.openalex.org/works/W2088435028", timeout=5)
        return response.status_code == 200
    except Exception:
        return False


def _mock_response(json_data, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    return response


class TestResolveWork(unittest.TestCase):
    def setUp(self):
        self.searcher = OpenAlexSearcher()

    def test_resolves_bare_openalex_id(self):
        self.assertEqual(self.searcher.resolve_work("W2088435028"), "W2088435028")

    def test_resolves_lowercase_and_strips_whitespace(self):
        self.assertEqual(self.searcher.resolve_work("  w2088435028  "), "W2088435028")

    def test_resolves_openalex_url(self):
        self.assertEqual(
            self.searcher.resolve_work("https://openalex.org/W2088435028"),
            "W2088435028",
        )

    def test_zero_padded_id_is_rejected_without_a_network_call(self):
        with patch.object(self.searcher.session, "get") as mock_get:
            with self.assertRaises(ValueError):
                self.searcher.resolve_work("W0000000000")
            mock_get.assert_not_called()

    def test_empty_identifier_raises(self):
        with self.assertRaises(ValueError):
            self.searcher.resolve_work("")

    def test_resolves_doi_via_network(self):
        with patch.object(
            self.searcher.session,
            "get",
            return_value=_mock_response({"id": "https://openalex.org/W2088435028"}),
        ) as mock_get:
            resolved = self.searcher.resolve_work("10.1016/0047-2727(72)90010-2")
        self.assertEqual(resolved, "W2088435028")
        called_url = mock_get.call_args[0][0]
        self.assertIn("https://doi.org/10.1016/0047-2727(72)90010-2", called_url)

    def test_strips_doi_prefix_variants(self):
        with patch.object(
            self.searcher.session,
            "get",
            return_value=_mock_response({"id": "https://openalex.org/W2088435028"}),
        ):
            for identifier in (
                "doi:10.1016/0047-2727(72)90010-2",
                "https://doi.org/10.1016/0047-2727(72)90010-2",
            ):
                self.assertEqual(self.searcher.resolve_work(identifier), "W2088435028")

    def test_unresolvable_identifier_raises_not_empty(self):
        with patch.object(
            self.searcher.session, "get", return_value=_mock_response({}, status_code=404)
        ):
            with self.assertRaises(ValueError):
                self.searcher.resolve_work("10.9999/does-not-exist")


class TestPaperReferencesPopulation(unittest.TestCase):
    """SPEC §6 Test 2 — regression guard for the population bug in §1."""

    def setUp(self):
        self.searcher = OpenAlexSearcher()

    def test_search_populates_references(self):
        item = {
            "id": "https://openalex.org/W2088435028",
            "title": "Income tax evasion: a theoretical analysis",
            "authorships": [{"author": {"display_name": "Michael Allingham"}}],
            "abstract_inverted_index": None,
            "doi": "https://doi.org/10.1016/0047-2727(72)90010-2",
            "primary_location": {"landing_page_url": "https://example.com", "pdf_url": ""},
            "open_access": {"is_oa": False},
            "publication_date": "1972-11-01",
            "concepts": [],
            "cited_by_count": 4947,
            "referenced_works": [
                "https://openalex.org/W1991069915",
                "https://openalex.org/W2084610231",
            ],
        }
        with patch.object(
            self.searcher.session,
            "get",
            return_value=_mock_response({"results": [item]}),
        ):
            papers = self.searcher.search("income tax evasion", max_results=1)

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper.references, ["W1991069915", "W2084610231"])

        serialized = paper.to_dict()["references"]
        self.assertNotEqual(serialized, "")
        self.assertIn("W2084610231", serialized)


class TestGetWorkReferences(unittest.TestCase):
    def setUp(self):
        self.searcher = OpenAlexSearcher()

    def test_batches_and_returns_full_papers(self):
        work_response = _mock_response(
            {
                "id": "https://openalex.org/W2088435028",
                "referenced_works": [
                    "https://openalex.org/W1991069915",
                    "https://openalex.org/W2084610231",
                ],
            }
        )
        batch_response = _mock_response(
            {
                "results": [
                    {"id": "https://openalex.org/W1991069915", "title": "Ref One",
                     "authorships": [], "referenced_works": []},
                    {"id": "https://openalex.org/W2084610231", "title": "Ref Two",
                     "authorships": [], "referenced_works": []},
                ]
            }
        )
        with patch.object(
            self.searcher.session, "get", side_effect=[work_response, batch_response]
        ):
            result = self.searcher.get_work_references(ANCHOR_WORK_ID)

        self.assertIsInstance(result, ReferencesResult)
        self.assertEqual(result.work_id, ANCHOR_WORK_ID)
        self.assertEqual(set(result.ids), {"W1991069915", "W2084610231"})
        self.assertEqual(len(result.papers), 2)

    def test_zero_references_is_empty_not_error(self):
        work_response = _mock_response(
            {"id": "https://openalex.org/W123", "referenced_works": []}
        )
        with patch.object(self.searcher.session, "get", return_value=work_response):
            result = self.searcher.get_work_references("W123")

        self.assertEqual(result.ids, [])
        self.assertEqual(result.papers, [])

    def test_server_error_raises(self):
        with patch.object(
            self.searcher.session, "get", return_value=_mock_response({}, status_code=500)
        ):
            with self.assertRaises(RuntimeError):
                self.searcher.get_work_references("W123")


class TestGetWorkCitations(unittest.TestCase):
    """SPEC §6 Test 3 — pagination must not silently truncate at per-page cap."""

    def setUp(self):
        self.searcher = OpenAlexSearcher()

    def _page(self, ids, next_cursor, count=4959):
        return _mock_response(
            {
                "meta": {"count": count, "next_cursor": next_cursor},
                "results": [{"id": f"https://openalex.org/{i}"} for i in ids],
            }
        )

    def test_cursor_pagination_exceeds_single_page_cap(self):
        page1_ids = [f"W{n}" for n in range(200)]
        page2_ids = [f"W{n}" for n in range(200, 250)]
        page1 = self._page(page1_ids, next_cursor="cursor-2")
        page2 = self._page(page2_ids, next_cursor="cursor-3")

        with patch.object(self.searcher.session, "get", side_effect=[page1, page2]):
            result = self.searcher.get_work_citations(ANCHOR_WORK_ID, max_results=250)

        self.assertIsInstance(result, CitationsResult)
        self.assertEqual(len(result.ids), 250)
        self.assertEqual(len(set(result.ids)), 250)  # no duplicates
        for work_id in result.ids:
            self.assertRegex(work_id, r"^W\d+$")

    def test_never_asserts_exact_count_field(self):
        """SPEC §6 Test 4 — count is magnitude/structure only, not exact."""
        page = self._page([f"W{n}" for n in range(5)], next_cursor=None, count=4959)
        with patch.object(self.searcher.session, "get", return_value=page):
            result = self.searcher.get_work_citations(ANCHOR_WORK_ID, max_results=5)

        # Do not assert result.count == 4959: OpenAlex's own count for this
        # edge has been observed to differ between calls minutes apart.
        self.assertGreater(result.count, 4000)
        self.assertTrue(result.exhausted)

    def test_exhausted_when_source_has_fewer_results_than_requested(self):
        page = self._page(["W1"], next_cursor=None, count=1)
        with patch.object(self.searcher.session, "get", return_value=page):
            result = self.searcher.get_work_citations("W1", max_results=200)

        self.assertEqual(result.ids, ["W1"])
        self.assertTrue(result.exhausted)


class TestGetCitationCount(unittest.TestCase):
    def setUp(self):
        self.searcher = OpenAlexSearcher()

    def test_returns_cited_by_count(self):
        with patch.object(
            self.searcher.session,
            "get",
            side_effect=[
                _mock_response({"id": "https://openalex.org/W2088435028"}),
                _mock_response({"cited_by_count": 4947}),
            ],
        ):
            count = self.searcher.get_citation_count(ANCHOR_WORK_DOI)
        self.assertEqual(count, 4947)


@unittest.skipUnless(check_openalex_accessible(), "OpenAlex not accessible")
class TestAnchorFixtureLive(unittest.TestCase):
    """SPEC §6 Test 1 — the bidirectional contract the whole cascade rests on."""

    @classmethod
    def setUpClass(cls):
        cls.searcher = OpenAlexSearcher()

    def test_backward_edge(self):
        result = self.searcher.get_work_references(ANCHOR_WORK_ID)
        self.assertIn(ANCHOR_REFERENCE_ID, result.ids)

    def test_forward_edge_agrees_with_backward(self):
        result = self.searcher.get_work_citations(ANCHOR_REFERENCE_ID, max_results=250)
        self.assertIn(ANCHOR_WORK_ID, result.ids)


if __name__ == "__main__":
    unittest.main()
