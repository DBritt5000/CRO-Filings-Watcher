#!/usr/bin/env python3
"""Human-readable names for 8-K item codes.

An 8-K is the "something happened" filing, and on its own the form type tells
you nothing — quarterly results and a CFO resignation are both 8-Ks. What
distinguishes them is the item code, which EDGAR returns in the submissions
JSON alongside the form type.

Item numbers come from the SEC's Form 8-K instructions. Codes not listed here
are passed through unchanged rather than dropped, so a new item the SEC adds
still shows up in the digest, just without a label.
"""

from __future__ import annotations

import re

ITEM_NAMES = {
    # Section 1 - Registrant's business and operations
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "1.04": "Mine Safety - Reporting of Shutdowns and Patterns of Violations",
    "1.05": "Material Cybersecurity Incidents",

    # Section 2 - Financial information
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation",
    "2.04": "Triggering Events That Accelerate a Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",

    # Section 3 - Securities and trading markets
    "3.01": "Notice of Delisting or Failure to Satisfy a Listing Rule",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",

    # Section 4 - Accountants and financial statements
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements",

    # Section 5 - Corporate governance and management
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure or Election of Directors or Certain Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws",
    "5.04": "Temporary Suspension of Trading Under Employee Benefit Plans",
    "5.05": "Amendment to Code of Ethics, or Waiver of a Provision",
    "5.06": "Change in Shell Company Status",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "5.08": "Shareholder Director Nominations",

    # Section 6 - Asset-backed securities
    "6.01": "ABS Informational and Computational Material",
    "6.02": "Change of Servicer or Trustee",
    "6.03": "Change in Credit Enhancement or Other External Support",
    "6.04": "Failure to Make a Required Distribution",
    "6.05": "Securities Act Updating Disclosure",

    # Sections 7-9 - Regulation FD, other events, exhibits
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

# Items that appear alongside almost every other item and carry no news of
# their own. Worth knowing about when deciding what to filter on.
BOILERPLATE_ITEMS = {"9.01"}

_ITEM_PATTERN = re.compile(r"\d+\.\d+")


def parse_items(raw: str) -> list:
    """Pull item codes out of whatever EDGAR put in the 'items' field.

    Normally a comma-separated list like "2.02,9.01", but the field has also
    been seen carrying prose. Pulling out anything shaped like an item code
    handles both, and returns an empty list for forms that aren't 8-Ks.
    """
    if not raw:
        return []
    seen, codes = set(), []
    for code in _ITEM_PATTERN.findall(raw):
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def describe(code: str) -> str:
    """'5.02' -> '5.02 Departure or Election of Directors or Certain Officers'."""
    name = ITEM_NAMES.get(code)
    return f"{code} {name}" if name else code


def describe_all(codes: list) -> str:
    """Join several item descriptions into one line for the digest."""
    return "; ".join(describe(code) for code in codes)


def matches(codes: list, wanted: set) -> bool:
    """Does this filing match an --items filter?

    A filter entry is either a full code ("5.02") or a section number ("5",
    meaning every 5.x item). Section filtering is the common case: "tell me
    about governance changes" rather than one specific sub-item.
    """
    if not wanted:
        return True
    for code in codes:
        section = code.split(".")[0]
        if code in wanted or section in wanted:
            return True
    return False
