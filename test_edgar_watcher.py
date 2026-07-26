#!/usr/bin/env python3
"""Offline tests for edgar_watcher.py.

These use a small fake EDGAR response instead of the real network, so they
run instantly and work without an internet connection.

Run them with:   python3 -m unittest -v test_edgar_watcher
"""

import json
import tempfile
import unittest
from pathlib import Path

import edgar_watcher as w

# A trimmed-down copy of a real submissions response. The real one has many
# more fields, but these are the ones the script reads.
SAMPLE_PAYLOAD = {
    "cik": "1478242",
    "name": "IQVIA HOLDINGS INC",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0001478242-25-000042",
                "0001478242-25-000039",
                "0001478242-25-000031",
                "0001478242-25-000024",
                "0001478242-25-000018",
                "0001478242-25-000011",
            ],
            "form": ["8-K", "10-Q", "4", "8-K", "10-K", "DEF 14A"],
            "filingDate": [
                "2025-07-22", "2025-07-21", "2025-06-30",
                "2025-05-12", "2025-02-11", "2025-03-28",
            ],
            "primaryDocument": [
                "iqv-20250722.htm", "iqv-20250630.htm", "xslF345X05/wk-form4.xml",
                "iqv-20250512.htm", "iqv-20241231.htm", "",
            ],
            "primaryDocDescription": ["8-K", "10-Q", "FORM 4", "8-K", "10-K", ""],
        }
    },
}


def filings():
    return w.extract_filings(SAMPLE_PAYLOAD, "0001478242")


class TestExtractFilings(unittest.TestCase):
    def test_parallel_arrays_are_zipped_into_records(self):
        result = filings()
        self.assertEqual(len(result), 6)
        self.assertEqual(result[0]["accession"], "0001478242-25-000042")
        self.assertEqual(result[0]["form"], "8-K")
        self.assertEqual(result[0]["filing_date"], "2025-07-22")

    def test_missing_filings_key_yields_empty_list(self):
        self.assertEqual(w.extract_filings({}, "0001478242"), [])


class TestFilingUrl(unittest.TestCase):
    def test_dashes_stripped_and_cik_unpadded(self):
        self.assertEqual(
            w.filing_url("0001478242", "0001478242-25-000042", "iqv-20250722.htm"),
            "https://www.sec.gov/Archives/edgar/data/1478242/"
            "000147824225000042/iqv-20250722.htm",
        )

    def test_falls_back_to_index_page_without_a_primary_document(self):
        self.assertTrue(
            w.filing_url("0001478242", "0001478242-25-000011", "")
            .endswith("/0001478242-25-000011-index.htm")
        )


class TestSelectNew(unittest.TestCase):
    def test_first_run_returns_the_newest_five(self):
        result = w.select_new(filings(), None, 5)
        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["accession"], "0001478242-25-000042")

    def test_first_run_limit_is_respected(self):
        self.assertEqual(len(w.select_new(filings(), None, 2)), 2)

    def test_only_filings_above_the_last_seen_accession_are_new(self):
        state = {"last_accession": "0001478242-25-000031",
                 "last_filing_date": "2025-06-30"}
        result = w.select_new(filings(), state, 5)
        self.assertEqual([f["accession"] for f in result],
                         ["0001478242-25-000042", "0001478242-25-000039"])

    def test_nothing_is_new_when_the_newest_was_already_seen(self):
        state = {"last_accession": "0001478242-25-000042",
                 "last_filing_date": "2025-07-22"}
        self.assertEqual(w.select_new(filings(), state, 5), [])

    def test_unknown_accession_falls_back_to_date_comparison(self):
        # This accession is not in the list (it aged out of the recent window).
        state = {"last_accession": "0000000000-00-000000",
                 "last_filing_date": "2025-06-30"}
        result = w.select_new(filings(), state, 5)
        self.assertEqual([f["accession"] for f in result],
                         ["0001478242-25-000042", "0001478242-25-000039"])

    def test_no_filings_at_all(self):
        self.assertEqual(w.select_new([], None, 5), [])


class TestFilterForms(unittest.TestCase):
    def test_empty_filter_keeps_everything(self):
        self.assertEqual(len(w.filter_forms(filings(), set())), 6)

    def test_filter_is_case_insensitive(self):
        result = w.filter_forms(filings(), {"8-K"})
        self.assertEqual([f["form"] for f in result], ["8-K", "8-K"])


class TestState(unittest.TestCase):
    def test_missing_state_file_reads_as_empty(self):
        self.assertEqual(w.load_state(Path("/nonexistent/state.json")), {})

    def test_state_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = {"0001478242": {"company": "IQVIA Holdings Inc.",
                                    "last_accession": "0001478242-25-000042",
                                    "last_filing_date": "2025-07-22"}}
            w.save_state(path, state)
            self.assertEqual(w.load_state(path), state)


class TestCompanyList(unittest.TestCase):
    def test_shipped_company_list_loads_and_pads_ciks(self):
        companies = w.load_companies(w.DEFAULT_COMPANIES_FILE)
        self.assertEqual(len(companies), 5)
        for company in companies:
            self.assertEqual(len(company["cik"]), 10, company["name"])
        self.assertIn("IQVIA Holdings Inc.", [c["name"] for c in companies])

    def test_bad_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "companies.json"
            path.write_text(json.dumps({"companies": [{"name": "No CIK Corp"}]}))
            with self.assertRaises(SystemExit):
                w.load_companies(path)


class TestDigest(unittest.TestCase):
    def test_digest_includes_form_date_and_url(self):
        results = [{
            "company": {"name": "IQVIA Holdings Inc.", "ticker": "IQV"},
            "filings": filings()[:1],
            "error": None,
        }]
        text = w.format_digest(results, ["IQVIA Holdings Inc."])
        self.assertIn("IQVIA Holdings Inc. (IQV)", text)
        self.assertIn("First run for:", text)
        self.assertIn("8-K", text)
        self.assertIn("2025-07-22", text)
        self.assertIn("https://www.sec.gov/Archives/edgar/data/1478242/", text)

    def test_no_new_filings_is_stated_explicitly(self):
        results = [{"company": {"name": "ICON plc", "ticker": "ICLR"},
                    "filings": [], "error": None}]
        self.assertIn("ICON plc (ICLR): no new filings", w.format_digest(results, []))

    def test_errors_are_shown_per_company(self):
        results = [{"company": {"name": "ICON plc", "ticker": "ICLR"},
                    "filings": [], "error": "HTTP 429 from EDGAR"}]
        self.assertIn("ERROR - HTTP 429", w.format_digest(results, []))


class TestEndToEnd(unittest.TestCase):
    """Run main() with the network call swapped out for the sample payload."""

    def setUp(self):
        self.real_fetch = w.fetch_submissions
        w.fetch_submissions = lambda cik, ua: SAMPLE_PAYLOAD
        w.REQUEST_DELAY_SECONDS = 0

    def tearDown(self):
        w.fetch_submissions = self.real_fetch

    def test_first_run_then_second_run_reports_nothing_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            argv = ["--state", str(state_path)]

            self.assertEqual(w.main(argv), 0)
            saved = json.loads(state_path.read_text())["companies"]
            self.assertEqual(len(saved), 5)  # one entry per company
            self.assertEqual(saved["0001478242"]["last_accession"],
                             "0001478242-25-000042")

            # Second run: same data, so nothing should be considered new.
            self.assertEqual(w.main(argv), 0)

    def test_dry_run_leaves_no_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            w.main(["--state", str(state_path), "--dry-run"])
            self.assertFalse(state_path.exists())

    def test_filtered_run_still_records_the_newest_filing(self):
        # A --forms run must not make skipped filings look new on the next run.
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            w.main(["--state", str(state_path), "--forms", "10-K"])
            saved = json.loads(state_path.read_text())["companies"]
            self.assertEqual(saved["0001478242"]["last_accession"],
                             "0001478242-25-000042")


if __name__ == "__main__":
    unittest.main()
