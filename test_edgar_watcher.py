#!/usr/bin/env python3
"""Offline tests for edgar_watcher.py.

These use a small fake EDGAR response instead of the real network, so they
run instantly and work without an internet connection.

Run them with:   python3 -m unittest -v test_edgar_watcher
"""

import contextlib
import io
import json
import smtplib
import tempfile
import unittest
import urllib.error
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
            # Only 8-Ks carry items; everything else is an empty string.
            "items": ["2.02,9.01", "", "", "5.02", "", ""],
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


class TestItems(unittest.TestCase):
    def test_items_are_extracted_only_for_8ks(self):
        result = filings()
        self.assertEqual(result[0]["items"], ["2.02", "9.01"])  # 8-K
        self.assertEqual(result[1]["items"], [])                # 10-Q
        self.assertEqual(result[3]["items"], ["5.02"])          # 8-K

    def test_filter_by_exact_item(self):
        result = w.filter_items(filings(), {"5.02"})
        self.assertEqual([f["accession"] for f in result], ["0001478242-25-000024"])

    def test_filter_by_section(self):
        result = w.filter_items(filings(), {"2"})
        self.assertEqual([f["form"] for f in result], ["8-K"])

    def test_filter_excludes_forms_without_items(self):
        # Only 8-Ks carry items, so a 10-K can never match.
        forms = [f["form"] for f in w.filter_items(filings(), {"2.02", "5.02"})]
        self.assertEqual(forms, ["8-K", "8-K"])

    def test_empty_filter_keeps_everything(self):
        self.assertEqual(len(w.filter_items(filings(), set())), 6)

    def test_digest_shows_what_an_8k_was_about(self):
        results = [{"company": {"name": "IQVIA Holdings Inc.", "ticker": "IQV"},
                    "filings": filings()[:1], "error": None}]
        text = w.format_digest(results, [])
        self.assertIn("Item:  2.02 Results of Operations and Financial Condition", text)
        self.assertIn("9.01 Financial Statements and Exhibits", text)

    def test_digest_omits_the_item_line_for_non_8ks(self):
        results = [{"company": {"name": "IQVIA Holdings Inc.", "ticker": "IQV"},
                    "filings": filings()[1:2], "error": None}]   # the 10-Q
        self.assertNotIn("Item:", w.format_digest(results, []))


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

    def test_http_403_explains_both_causes(self):
        # A 403 means either a User-Agent with no contact email or a blocked
        # IP. The digest should name both rather than just printing the code.
        def raise_403(cik, ua):
            raise urllib.error.HTTPError(
                url="https://data.sec.gov/", code=403, msg="Forbidden",
                hdrs=None, fp=None)

        w.fetch_submissions = raise_403
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exit_code = w.main(["--state", str(state_path)])

        self.assertEqual(exit_code, 1)  # fetch failures are reported as failure
        output = buffer.getvalue()
        self.assertIn("HTTP 403", output)
        self.assertIn("SEC_USER_AGENT", output)
        self.assertIn("blocked this IP", output)

    def test_http_404_points_at_the_cik(self):
        def raise_404(cik, ua):
            raise urllib.error.HTTPError(
                url="https://data.sec.gov/", code=404, msg="Not Found",
                hdrs=None, fp=None)

        w.fetch_submissions = raise_404
        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                w.main(["--state", str(Path(tmp) / "state.json")])
        self.assertIn("is CIK 0001478242 correct?", buffer.getvalue())

    def test_one_company_failing_does_not_stop_the_others(self):
        calls = {"n": 0}

        def fail_first_only(cik, ua):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    url="https://data.sec.gov/", code=500, msg="Server Error",
                    hdrs=None, fp=None)
            return SAMPLE_PAYLOAD

        w.fetch_submissions = fail_first_only
        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                w.main(["--state", str(Path(tmp) / "state.json")])

        output = buffer.getvalue()
        self.assertIn("HTTP 500", output)
        self.assertEqual(calls["n"], 5)  # all five were still attempted
        self.assertIn("Thermo Fisher Scientific Inc. (TMO): 5 new filings", output)

    def test_filtered_run_still_records_the_newest_filing(self):
        # A --forms run must not make skipped filings look new on the next run.
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            w.main(["--state", str(state_path), "--forms", "10-K"])
            saved = json.loads(state_path.read_text())["companies"]
            self.assertEqual(saved["0001478242"]["last_accession"],
                             "0001478242-25-000042")

    def test_items_run_still_records_the_newest_filing(self):
        # Same trap as --forms: state must advance past filings we skipped.
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                w.main(["--state", str(state_path), "--items", "5.02"])
            saved = json.loads(state_path.read_text())["companies"]

        self.assertEqual(saved["0001478242"]["last_accession"],
                         "0001478242-25-000042")
        output = buffer.getvalue()
        self.assertIn("5.02 Departure or Election of Directors", output)
        self.assertNotIn("2.02 Results of Operations", output)


class TestEmailWiring(unittest.TestCase):
    """The --email flag, with the SMTP layer stubbed out."""

    def setUp(self):
        self.real_fetch = w.fetch_submissions
        self.real_send = w.emailer.send_digest
        self.real_load = w.emailer.load_email_config
        w.fetch_submissions = lambda cik, ua: SAMPLE_PAYLOAD
        w.REQUEST_DELAY_SECONDS = 0
        self.sent = []
        w.emailer.send_digest = lambda cfg, subject, body: self.sent.append((subject, body))
        w.emailer.load_email_config = lambda: w.emailer.EmailConfig(
            host="smtp.example.com", sender="me@example.com",
            recipients=["you@example.com"])

    def tearDown(self):
        w.fetch_submissions = self.real_fetch
        w.emailer.send_digest = self.real_send
        w.emailer.load_email_config = self.real_load

    def _run(self, extra_args):
        with tempfile.TemporaryDirectory() as tmp:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = w.main(["--state", str(Path(tmp) / "state.json")] + extra_args)
        return code, buffer.getvalue()

    def test_new_filings_are_emailed_with_a_useful_subject(self):
        code, output = self._run(["--email"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.sent), 1)
        subject, body = self.sent[0]
        self.assertIn("25 new filings", subject)  # 5 companies x 5 filings
        self.assertIn("SEC EDGAR FILINGS DIGEST", body)
        self.assertIn("Emailed to you@example.com", output)

    def test_nothing_new_sends_no_email_by_default(self):
        # A daily cron shouldn't mail "nothing new" every morning.
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with contextlib.redirect_stdout(io.StringIO()):
                w.main(["--state", str(state_path)])          # first run, saves state
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    code = w.main(["--state", str(state_path), "--email"])

        self.assertEqual(code, 0)
        self.assertEqual(self.sent, [])
        self.assertIn("nothing new, so no email sent", buffer.getvalue())

    def test_email_always_sends_even_with_nothing_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with contextlib.redirect_stdout(io.StringIO()):
                w.main(["--state", str(state_path)])
                w.main(["--state", str(state_path), "--email", "--email-always"])

        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0], "SEC filings: nothing new")

    def test_missing_configuration_fails_the_run_but_keeps_the_digest(self):
        def unconfigured():
            raise w.emailer.EmailConfigError("missing SMTP_HOST, EMAIL_TO")

        w.emailer.load_email_config = unconfigured
        code, output = self._run(["--email"])

        self.assertEqual(code, 1)                          # reported as a failure
        self.assertIn("SEC EDGAR FILINGS DIGEST", output)  # digest still printed
        self.assertEqual(self.sent, [])

    def test_smtp_failure_does_not_lose_the_run(self):
        # The state file must still advance, or a flaky mail server would
        # make the same filings re-report forever.
        def explode(cfg, subject, body):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

        w.emailer.send_digest = explode
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            with contextlib.redirect_stdout(io.StringIO()):
                code = w.main(["--state", str(state_path), "--email"])
            saved = json.loads(state_path.read_text())["companies"]

        self.assertEqual(code, 1)
        self.assertEqual(saved["0001478242"]["last_accession"],
                         "0001478242-25-000042")

    def test_no_email_flag_means_no_email(self):
        code, _ = self._run([])
        self.assertEqual(code, 0)
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
