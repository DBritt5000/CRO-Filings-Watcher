# CRO Filings Watcher

Checks SEC EDGAR for new filings from a handful of clinical research
organizations and prints a plain-text digest. Re-runs only show what's new.

Watched by default: IQVIA (IQV), ICON plc (ICLR), Medpace (MEDP),
Fortrea (FTRE), Thermo Fisher Scientific (TMO).

## Requirements

Python 3.9 or newer. Nothing to install — the script only uses the standard
library.

## Setup

The SEC asks that automated requests identify who is making them. Set your
name and email once:

```sh
export SEC_USER_AGENT="Your Name your.email@example.com"
```

(Or edit `DEFAULT_USER_AGENT` near the top of `edgar_watcher.py`.) The script
still runs without this, but the SEC may throttle or block anonymous traffic.

## Usage

```sh
python3 edgar_watcher.py
```

The first run has no saved state, so it prints the 5 most recent filings per
company and records where it left off. Every run after that prints only
filings that appeared since.

Options:

| Flag | What it does |
| --- | --- |
| `--all` | Ignore saved state and show recent filings again |
| `--dry-run` | Print the digest without updating the state file |
| `--first-run-limit N` | Show N filings per company on a first run (default 5) |
| `--forms 8-K,10-Q` | Only report these form types |
| `--state PATH` | Use a different state file |
| `--companies PATH` | Use a different company list |

Exit code is `0` on success, `1` if any company failed to fetch. Handy if you
want to wire it into a cron job.

## Files

| File | Purpose |
| --- | --- |
| `edgar_watcher.py` | The script |
| `companies.json` | The watch list — edit this to add or remove companies |
| `state.json` | Auto-created. Last filing seen per company. Delete to reset. |
| `test_edgar_watcher.py` | Offline tests (`python3 -m unittest test_edgar_watcher`) |

## Adding a company

Add an entry to `companies.json` with the company's CIK — EDGAR's permanent
ID number for a filer:

```json
{ "name": "Charles River Laboratories", "ticker": "CRL", "cik": "0001100682" }
```

Find a CIK by searching https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany
or the full list at https://www.sec.gov/files/company_tickers.json.

## How it works

The script calls the free EDGAR submissions API, one request per company:

```
https://data.sec.gov/submissions/CIK0001478242.json
```

No API key is required. The response holds roughly the last year (up to ~1000)
of that company's filings, newest first, as parallel arrays — one array of
form types, one of dates, one of accession numbers. The script zips them into
records, then compares against `state.json` to decide what's new.

Two details worth knowing if you extend it:

- **Accession numbers** (`0001478242-25-000042`) uniquely identify a filing.
  The document URL uses the same number with dashes stripped as the folder
  name, and the CIK without its leading zeros.
- **Filings older than the recent window** live in extra files listed under
  `filings.files` in the API response. This script doesn't page into them,
  which is fine for a watcher that runs regularly.

## Running it on a schedule

Once a day on a Mac or Linux box, via `crontab -e`:

```
0 8 * * * cd /path/to/CRO-Filings-Watcher && SEC_USER_AGENT="Your Name you@example.com" /usr/bin/python3 edgar_watcher.py >> digest.log 2>&1
```

## Notes

- Rate limiting: the SEC allows up to 10 requests per second. The script waits
  0.2s between companies, well inside that.
- Insider transactions (Form 3/4/5) are frequent and will dominate a digest.
  To see only material corporate events, use:

  ```sh
  python3 edgar_watcher.py --forms 8-K,10-Q,10-K,20-F,6-K
  ```

  Include `20-F` and `6-K`, not just the domestic forms. **ICON plc is an
  Irish foreign private issuer and files 20-F and 6-K instead of
  10-K/10-Q/8-K** — a filter of `8-K,10-Q,10-K` would silently drop ICON from
  every digest. The same applies to any non-US filer you add later.
- The CIKs in `companies.json` were verified against EDGAR archive paths in
  July 2026. If you add a company, double-check its CIK: a wrong one isn't an
  error, it just quietly watches the wrong company.
