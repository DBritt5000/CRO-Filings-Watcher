# CRO Filings Watcher

[![CI](https://github.com/DBritt5000/CRO-Filings-Watcher/actions/workflows/ci.yml/badge.svg)](https://github.com/DBritt5000/CRO-Filings-Watcher/actions/workflows/ci.yml)

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

(Or edit `DEFAULT_USER_AGENT` near the top of `edgar_watcher.py`.)

The SEC's
[developer guidance](https://www.sec.gov/os/webmaster-faq#developers) asks for
a real name and email here, so include both.

Note that a correct `User-Agent` is necessary but not always sufficient: EDGAR
also blocks by IP. A CI run from a GitHub-hosted runner got `HTTP 403` for all
five companies on its very first request while sending a valid contact email,
which is consistent with the SEC blocking cloud-datacenter address ranges.
From a normal home or office connection this isn't an issue.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `HTTP 403 from EDGAR` | Either the `User-Agent` has no contact email (set `SEC_USER_AGENT`), or EDGAR has blocked your IP. Cloud and datacenter addresses are frequently blocked. |
| `HTTP 404 from EDGAR` | That CIK doesn't exist — check `companies.json`. |
| `HTTP 429 from EDGAR` | Rate limited. Wait a minute. |
| Digest shows nothing new | Expected. Delete `state.json`, or use `--all`, to see recent filings again. |
| ICON plc never appears | You're filtering with `--forms` and left out `20-F`/`6-K`. See the note below. |

A failed company is reported on its own line in the digest; the run continues
for the others and exits with status 1.

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
| `--email` | Also email the digest (see below) |
| `--email-always` | With `--email`, send even when there's nothing new |

Exit code is `0` on success, `1` if any company failed to fetch or the email
couldn't be sent. Handy if you want to wire it into a cron job.

## Email delivery

The digest always prints to the terminal. Add `--email` to also send it.

Configuration comes from environment variables — never a file in this
repository, so a password can't be committed by accident:

| Variable | Required | Notes |
| --- | --- | --- |
| `SMTP_HOST` | yes | e.g. `smtp.gmail.com` |
| `EMAIL_TO` | yes | one address, or several separated by commas |
| `SMTP_PORT` | no | default `587` |
| `SMTP_USERNAME` | no | omit for a relay that needs no login |
| `SMTP_PASSWORD` | no | omit for a relay that needs no login |
| `EMAIL_FROM` | no | defaults to `SMTP_USERNAME` |
| `SMTP_STARTTLS` | no | set to `0` for a plaintext relay on localhost |

Port `465` uses implicit TLS; any other port uses STARTTLS.

### Gmail

Gmail rejects your normal password. Create an
[App Password](https://myaccount.google.com/apppasswords) (requires 2-Step
Verification) and use that instead:

```sh
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USERNAME=you@gmail.com
export SMTP_PASSWORD=abcdefghijklmnop   # the 16-character app password
export EMAIL_TO=you@gmail.com

python3 edgar_watcher.py --email
```

### Two behaviours worth knowing

**Nothing new means no email.** A daily cron that mails "no new filings" every
morning is a daily message you learn to ignore, and then you miss the one that
matters. Pass `--email-always` if you'd rather have the heartbeat.

**A failed send never costs you the run.** The digest has already printed, and
the state file still advances. If email failure rolled back the run, a flaky
mail server would make the same filings re-report forever. You get a non-zero
exit code, so cron can still tell you something went wrong.

## Files

| File | Purpose |
| --- | --- |
| `edgar_watcher.py` | The script |
| `emailer.py` | SMTP delivery, used only when `--email` is passed |
| `companies.json` | The watch list — edit this to add or remove companies |
| `state.json` | Auto-created. Last filing seen per company. Delete to reset. |
| `test_edgar_watcher.py`, `test_emailer.py` | Offline tests (`python3 -m unittest discover`) |
| `.github/workflows/ci.yml` | Runs the tests on every push and pull request |

## CI

Two jobs run on GitHub Actions:

- **Tests** — the offline suite on Python 3.9, 3.11, and 3.13. No network, so
  it's fast and deterministic. This is the job that gates a merge.
- **Live EDGAR smoke test** — calls the real API with `--dry-run` to confirm
  EDGAR still responds the way the script expects. **Manual trigger only**
  (Actions tab → Run workflow). It does not run on pull requests, because
  EDGAR returns 403 to GitHub's hosted runners regardless of `User-Agent` —
  their IPs are in cloud-datacenter ranges the SEC blocks. The job is kept
  for use from a self-hosted runner on a non-datacenter connection; from a
  GitHub-hosted runner it is expected to fail.

  To verify against the live API, the reliable route is your own machine:

  ```sh
  SEC_USER_AGENT="Your Name you@example.com" python3 edgar_watcher.py --dry-run
  ```

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

Cron doesn't read your shell profile, so exported variables won't be visible
to it. Put them in an env file that only you can read, and source it:

```sh
cat > ~/.edgar-watcher.env <<'EOF'
export SEC_USER_AGENT="Your Name you@example.com"
export SMTP_HOST=smtp.gmail.com
export SMTP_USERNAME=you@gmail.com
export SMTP_PASSWORD=abcdefghijklmnop
export EMAIL_TO=you@gmail.com
EOF
chmod 600 ~/.edgar-watcher.env
```

```
0 8 * * * . $HOME/.edgar-watcher.env && cd /path/to/CRO-Filings-Watcher && /usr/bin/python3 edgar_watcher.py --email >> digest.log 2>&1
```

`chmod 600` matters — the file holds your app password.

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
