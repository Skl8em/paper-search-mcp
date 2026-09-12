"""Tests for cross_check_citations — SPEC §6 Test 5, third bullet:
an OpenCitations 5xx must surface as an error on the OpenCitations field
while the OpenAlex field still returns its value. Partial success must
stay visible as partial, never collapsed into a single failure."""
import unittest
from unittest.mock import Mock

from paper_search_mcp.citation_cross_check import cross_check_citations, CrossCheckResult

DOI = "10.1016/0047-2727(72)90010-2"


class TestCrossCheckCitations(unittest.TestCase):
    def test_both_sources_succeed_reports_delta(self):
        openalex = Mock()
        openalex.get_citation_count.return_value = 4959
        opencitations = Mock()
        opencitations.get_citation_count.return_value = 2919

        result = cross_check_citations(DOI, openalex, opencitations)

        self.assertIsInstance(result, CrossCheckResult)
        self.assertEqual(result.openalex_count, 4959)
        self.assertEqual(result.opencitations_count, 2919)
        self.assertEqual(result.delta, 4959 - 2919)
        self.assertIsNone(result.openalex_error)
        self.assertIsNone(result.opencitations_error)

    def test_opencitations_failure_does_not_hide_openalex_result(self):
        openalex = Mock()
        openalex.get_citation_count.return_value = 4959
        opencitations = Mock()
        opencitations.get_citation_count.side_effect = RuntimeError("500 Server Error")

        result = cross_check_citations(DOI, openalex, opencitations)

        self.assertEqual(result.openalex_count, 4959)  # unaffected by the other source's failure
        self.assertIsNone(result.opencitations_count)
        self.assertIn("500", result.opencitations_error)
        self.assertIsNone(result.delta)  # can't compute a delta with a missing side

    def test_openalex_failure_does_not_hide_opencitations_result(self):
        openalex = Mock()
        openalex.get_citation_count.side_effect = ValueError("could not resolve identifier")
        opencitations = Mock()
        opencitations.get_citation_count.return_value = 2919

        result = cross_check_citations(DOI, openalex, opencitations)

        self.assertIsNone(result.openalex_count)
        self.assertIn("could not resolve", result.openalex_error)
        self.assertEqual(result.opencitations_count, 2919)
        self.assertIsNone(result.delta)


if __name__ == "__main__":
    unittest.main()
