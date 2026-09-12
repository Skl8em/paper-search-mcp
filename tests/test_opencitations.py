"""Tests for the OpenCitations adapter — SPEC §5 (OpenCitations adapter) and
§7.3 (the 301-redirect gotcha that Test 5 exists to catch)."""
import unittest
import requests
from unittest.mock import Mock, patch

from paper_search_mcp.academic_platforms.opencitations import OpenCitationsSearcher

ANCHOR_WORK_DOI = "10.1016/0047-2727(72)90010-2"
ANCHOR_REFERENCE_OPENALEX_ID = "W2084610231"


def check_opencitations_accessible():
    try:
        response = requests.get(
            "https://opencitations.net/index/api/v2/citation-count/doi:10.1016/0047-2727(72)90010-2",
            timeout=5,
        )
        return response.status_code == 200
    except Exception:
        return False


class TestOpenCitationsSearcher(unittest.TestCase):
    def setUp(self):
        self.searcher = OpenCitationsSearcher()

    def test_citation_count_casts_string_to_int(self):
        response = Mock()
        response.json.return_value = [{"count": "2919"}]
        response.raise_for_status.return_value = None
        with patch.object(self.searcher.session, "get", return_value=response) as mock_get:
            count = self.searcher.get_citation_count(ANCHOR_WORK_DOI)

        self.assertIsInstance(count, int)
        self.assertEqual(count, 2919)
        # requests.Session.get follows redirects by default; assert we didn't
        # override that off, since a non-following client silently reports 0.
        self.assertNotEqual(mock_get.call_args.kwargs.get("allow_redirects"), False)

    def test_citation_count_empty_response_is_zero(self):
        response = Mock()
        response.json.return_value = []
        response.raise_for_status.return_value = None
        with patch.object(self.searcher.session, "get", return_value=response):
            self.assertEqual(self.searcher.get_citation_count(ANCHOR_WORK_DOI), 0)

    def test_5xx_raises(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        with patch.object(self.searcher.session, "get", return_value=response):
            with self.assertRaises(requests.HTTPError):
                self.searcher.get_citation_count(ANCHOR_WORK_DOI)

    def test_parses_references_extracting_openalex_and_doi(self):
        response = Mock()
        response.json.return_value = [
            {
                "oci": "0670982696-0610462181",
                "citing": "omid:br/0670982696 doi:10.1016/0047-2727(72)90010-2 openalex:W2088435028",
                "cited": "omid:br/0610462181 doi:10.2307/2552162 openalex:W2084610231",
            }
        ]
        response.raise_for_status.return_value = None
        with patch.object(self.searcher.session, "get", return_value=response):
            edges = self.searcher.get_references(ANCHOR_WORK_DOI)

        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertEqual(edge.cited_doi, "10.2307/2552162")
        self.assertEqual(edge.cited_openalex_id, ANCHOR_REFERENCE_OPENALEX_ID)
        self.assertEqual(edge.citing_openalex_id, "W2088435028")


@unittest.skipUnless(check_opencitations_accessible(), "OpenCitations not accessible")
class TestOpenCitationsLive(unittest.TestCase):
    """Cross-validates the SPEC §6 Test 1 anchor edge against a second, independent index."""

    @classmethod
    def setUpClass(cls):
        cls.searcher = OpenCitationsSearcher()

    def test_anchor_edge_present_in_references(self):
        edges = self.searcher.get_references(ANCHOR_WORK_DOI)
        cited_openalex_ids = {edge.cited_openalex_id for edge in edges}
        self.assertIn(ANCHOR_REFERENCE_OPENALEX_ID, cited_openalex_ids)

    def test_citation_count_is_positive(self):
        count = self.searcher.get_citation_count(ANCHOR_WORK_DOI)
        self.assertGreater(count, 0)


if __name__ == "__main__":
    unittest.main()
