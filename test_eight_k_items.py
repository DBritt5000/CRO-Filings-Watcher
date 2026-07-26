#!/usr/bin/env python3
"""Tests for eight_k_items.py.

Run them with:   python3 -m unittest -v test_eight_k_items
"""

import unittest

import eight_k_items as items


class TestParseItems(unittest.TestCase):
    def test_comma_separated_codes(self):
        self.assertEqual(items.parse_items("2.02,9.01"), ["2.02", "9.01"])

    def test_whitespace_and_spacing_variations(self):
        self.assertEqual(items.parse_items(" 5.02 , 9.01 "), ["5.02", "9.01"])

    def test_prose_form_is_handled(self):
        # The field has been seen carrying descriptions rather than bare codes.
        raw = "Item 5.02 Departure of Directors; Item 9.01 Financial Statements"
        self.assertEqual(items.parse_items(raw), ["5.02", "9.01"])

    def test_duplicates_are_collapsed_in_order(self):
        self.assertEqual(items.parse_items("9.01,2.02,9.01"), ["9.01", "2.02"])

    def test_non_8k_filings_have_no_items(self):
        self.assertEqual(items.parse_items(""), [])
        self.assertEqual(items.parse_items(None), [])


class TestDescribe(unittest.TestCase):
    def test_known_code_gets_a_label(self):
        self.assertEqual(items.describe("2.02"),
                         "2.02 Results of Operations and Financial Condition")

    def test_unknown_code_passes_through_rather_than_vanishing(self):
        # If the SEC adds an item, it should still appear in the digest.
        self.assertEqual(items.describe("1.99"), "1.99")

    def test_describe_all_joins_with_semicolons(self):
        self.assertEqual(
            items.describe_all(["2.02", "9.01"]),
            "2.02 Results of Operations and Financial Condition; "
            "9.01 Financial Statements and Exhibits")

    def test_every_name_is_non_empty(self):
        for code, name in items.ITEM_NAMES.items():
            self.assertTrue(name.strip(), f"{code} has an empty label")

    def test_codes_are_well_formed(self):
        for code in items.ITEM_NAMES:
            section, _, sub = code.partition(".")
            self.assertTrue(section.isdigit() and sub.isdigit(), code)


class TestMatches(unittest.TestCase):
    def test_empty_filter_matches_everything(self):
        self.assertTrue(items.matches(["2.02"], set()))
        self.assertTrue(items.matches([], set()))

    def test_exact_code_match(self):
        self.assertTrue(items.matches(["2.02", "9.01"], {"2.02"}))
        self.assertFalse(items.matches(["2.02", "9.01"], {"5.02"}))

    def test_section_number_matches_every_sub_item(self):
        self.assertTrue(items.matches(["5.02"], {"5"}))
        self.assertTrue(items.matches(["5.07"], {"5"}))
        self.assertFalse(items.matches(["2.02"], {"5"}))

    def test_filings_without_items_never_match_a_filter(self):
        # A 10-K has no items, so --items necessarily excludes it.
        self.assertFalse(items.matches([], {"2.02"}))

    def test_section_filter_does_not_match_on_a_prefix_coincidence(self):
        # "1" must not match "10.01" if such a code ever appears.
        self.assertFalse(items.matches(["10.01"], {"1"}))


if __name__ == "__main__":
    unittest.main()
