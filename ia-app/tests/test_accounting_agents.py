import unittest

from accounting_agents.review import analyze_sec_data, review_contract


SOURCE = {"name": "source", "url": "https://example.test/repo", "license": "test", "commit": "abc", "committed_at": "2026-01-01T00:00:00Z"}


class AccountingAgentTests(unittest.TestCase):
    def test_contract_review_detects_criteria_and_flags(self):
        result = review_contract({
            "task": "Review revenue contract", "contract_id": "C-1", "customer": "Customer",
            "start_date": "2026-01-01", "end_date": "2026-12-31", "currency": "USD",
            "consideration": "120000", "contract_text": "Both parties signed. Customer will pay monthly. Vendor shall provide hosted software and support. Customer may terminate and receive a refund. Credit review supports collectibility.",
        }, SOURCE)
        self.assertEqual(result["repository"]["commit"], "abc")
        self.assertTrue(any(item["name"] == "Payment terms" and item["status"] == "Potential evidence found" for item in result["contract_criteria"]))
        self.assertTrue(any(item["topic"] == "Termination or refund rights" for item in result["topic_flags"]))
        self.assertIn("No accounting conclusion", result["conclusion"])

    def test_sec_numeric_analysis(self):
        result = analyze_sec_data({"task": "Analyze numeric column", "query": "amount", "dataset_text": "name,amount\nA,10\nB,20\nC,30"}, SOURCE)
        self.assertEqual(result["row_count_analyzed"], 3)
        self.assertEqual(result["numeric_summary"]["mean"], "20")

    def test_sec_narrative_search(self):
        result = analyze_sec_data({"task": "Find narrative facts", "query": "liquidity", "dataset_text": "fund,note\nA,Liquidity risk\nB,Market risk"}, SOURCE)
        self.assertEqual(result["match_count"], 1)


if __name__ == "__main__":
    unittest.main()
