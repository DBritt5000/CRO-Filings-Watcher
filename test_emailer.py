#!/usr/bin/env python3
"""Offline tests for emailer.py.

A fake SMTP server stands in for the real one, so these tests send no mail
and need no network or credentials.

Run them with:   python3 -m unittest -v test_emailer
"""

import unittest

import emailer


class FakeSMTP:
    """Records what the code did instead of talking to a mail server."""

    def __init__(self, config):
        self.config = config
        self.started_tls = False
        self.login_args = None
        self.sent = []

    # Used as a context manager by send_digest.
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.sent.append(message)


MINIMAL_ENV = {"SMTP_HOST": "smtp.example.com", "EMAIL_TO": "you@example.com",
               "SMTP_USERNAME": "me@example.com", "SMTP_PASSWORD": "secret"}


class TestLoadEmailConfig(unittest.TestCase):
    def test_minimal_environment(self):
        config = emailer.load_email_config(MINIMAL_ENV)
        self.assertEqual(config.host, "smtp.example.com")
        self.assertEqual(config.port, 587)          # default
        self.assertEqual(config.recipients, ["you@example.com"])
        self.assertEqual(config.sender, "me@example.com")  # falls back to username
        self.assertTrue(config.use_starttls)
        self.assertFalse(config.use_ssl)

    def test_all_missing_variables_are_reported_at_once(self):
        with self.assertRaises(emailer.EmailConfigError) as caught:
            emailer.load_email_config({})
        message = str(caught.exception)
        self.assertIn("SMTP_HOST", message)
        self.assertIn("EMAIL_TO", message)

    def test_several_recipients_are_split_and_trimmed(self):
        env = dict(MINIMAL_ENV, EMAIL_TO=" a@example.com , b@example.com ,")
        self.assertEqual(emailer.load_email_config(env).recipients,
                         ["a@example.com", "b@example.com"])

    def test_port_465_uses_implicit_tls_instead_of_starttls(self):
        config = emailer.load_email_config(dict(MINIMAL_ENV, SMTP_PORT="465"))
        self.assertTrue(config.use_ssl)
        self.assertFalse(config.use_starttls)

    def test_starttls_can_be_disabled_for_a_local_relay(self):
        config = emailer.load_email_config(dict(MINIMAL_ENV, SMTP_STARTTLS="0"))
        self.assertFalse(config.use_starttls)

    def test_non_numeric_port_is_rejected(self):
        with self.assertRaises(emailer.EmailConfigError):
            emailer.load_email_config(dict(MINIMAL_ENV, SMTP_PORT="not-a-port"))

    def test_explicit_from_address_wins_over_username(self):
        env = dict(MINIMAL_ENV, EMAIL_FROM="digest@example.com")
        self.assertEqual(emailer.load_email_config(env).sender, "digest@example.com")

    def test_missing_sender_is_rejected(self):
        env = {"SMTP_HOST": "smtp.example.com", "EMAIL_TO": "you@example.com"}
        with self.assertRaises(emailer.EmailConfigError) as caught:
            emailer.load_email_config(env)
        self.assertIn("EMAIL_FROM", str(caught.exception))


class TestBuildSubject(unittest.TestCase):
    def test_single_filing_is_singular(self):
        self.assertEqual(emailer.build_subject(1, ["IQVIA Holdings Inc."]),
                         "SEC filings: 1 new filing - IQVIA Holdings Inc.")

    def test_several_companies_are_listed(self):
        subject = emailer.build_subject(4, ["IQVIA", "Medpace"])
        self.assertEqual(subject, "SEC filings: 4 new filings - IQVIA, Medpace")

    def test_long_company_lists_are_summarised(self):
        subject = emailer.build_subject(9, ["A", "B", "C", "D", "E"])
        self.assertEqual(subject, "SEC filings: 9 new filings - A, B, C +2 more")

    def test_empty_digest_says_so(self):
        self.assertEqual(emailer.build_subject(0, []), "SEC filings: nothing new")


class TestBuildMessage(unittest.TestCase):
    def test_headers_and_body(self):
        config = emailer.load_email_config(
            dict(MINIMAL_ENV, EMAIL_TO="a@example.com,b@example.com"))
        message = emailer.build_message(config, "Subject here", "Digest body")
        self.assertEqual(message["Subject"], "Subject here")
        self.assertEqual(message["From"], "me@example.com")
        self.assertEqual(message["To"], "a@example.com, b@example.com")
        self.assertEqual(message.get_content_type(), "text/plain")
        self.assertIn("Digest body", message.get_content())


class TestSendDigest(unittest.TestCase):
    def test_starttls_then_login_then_send(self):
        config = emailer.load_email_config(MINIMAL_ENV)
        fake = FakeSMTP(config)
        emailer.send_digest(config, "Subject", "Body", smtp_factory=lambda cfg: fake)

        self.assertTrue(fake.started_tls)
        self.assertEqual(fake.login_args, ("me@example.com", "secret"))
        self.assertEqual(len(fake.sent), 1)
        self.assertEqual(fake.sent[0]["Subject"], "Subject")

    def test_implicit_tls_does_not_also_call_starttls(self):
        config = emailer.load_email_config(dict(MINIMAL_ENV, SMTP_PORT="465"))
        fake = FakeSMTP(config)
        emailer.send_digest(config, "Subject", "Body", smtp_factory=lambda cfg: fake)
        self.assertFalse(fake.started_tls)
        self.assertEqual(len(fake.sent), 1)

    def test_relay_without_credentials_skips_login(self):
        env = {"SMTP_HOST": "localhost", "SMTP_PORT": "25",
               "EMAIL_TO": "you@example.com", "EMAIL_FROM": "watcher@example.com",
               "SMTP_STARTTLS": "0"}
        config = emailer.load_email_config(env)
        fake = FakeSMTP(config)
        emailer.send_digest(config, "Subject", "Body", smtp_factory=lambda cfg: fake)

        self.assertIsNone(fake.login_args)   # no credentials, no login attempt
        self.assertFalse(fake.started_tls)
        self.assertEqual(len(fake.sent), 1)


if __name__ == "__main__":
    unittest.main()
