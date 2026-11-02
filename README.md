# Bellhaven CRM reconciliation

A local review tool for Clipboard's fictional analyst assessment. Discovery is read-only. Individual approvals apply evidence-backed changes to the reviewer's isolated CRM and verify the result.

## Run locally

Requires Python 3.10+ on macOS or Linux (the process lock uses `fcntl`). Tested locally with Python 3.14.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
mkdir -p private
chmod 700 private
```

Create `private/.env` containing `BELLHAVEN_TOKEN=your_personal_token`, or export that environment variable. Keep the file private (`chmod 600 private/.env`). Never include it in shared code, screen recordings, or GitHub. No paid or AI API key is needed.

```sh
.venv/bin/python bellhaven.py scan
.venv/bin/python bellhaven.py serve
```

Open **http://127.0.0.1:8765**. The app is intentionally local-only. Keep the terminal running. Stop it with Control-C. The existing database and your decisions survive restart. Do not delete `private/` during the assessment.

## Review workflow

1. Confirm the latest scan is complete. Review the queue by type and open the source evidence for each proposal.
2. Start with a straightforward correction, such as Portsmouth's ZIP. Compare published values with the exact change. Record the required demo while you review; nothing has been pre-approved.
3. Approve only corrections you believe are supported. The app checks for stale data, writes through the API, then reads the result back. The audit records request intent and verified outcomes.
4. For an ambiguous match, review the displayed candidates, select an account, and explain your evidence. This only creates a correction preview. Approving that separate preview is what writes the change. You may reject an unsupported proposal instead.
5. Review duplicate proposals before other corrections to their survivor, or rescan after changing a survivor. A stale proposal stops safely rather than applying an old snapshot.
6. Review the ownership proposals for Tiffin and Marietta carefully. The confirmation checkbox approves creating the replacement and linking the preserved billing account.
7. Investigate absent facilities. The proposed `Needs Review` flag does not claim they are closed or sold and does not invent a new parent.
8. Run another read-only scan. Approved changes should no longer require correction; unchanged rejected proposals remain rejected. Inspect the CRM browser as well as the local audit.

### Errors and recovery

The `error` queue preserves interrupted operations. Use **Reconcile / resume approved operation** only after reading the error. There is no automatic write retry. If a create timed out, the tool searches for its unique proposal marker before proceeding. If no unique marker is found, it refuses to create again: inspect the CRM and reconcile manually. A failed ownership-link step resumes using the previously recorded new ID. For stale untouched proposals, rescan; the original error remains in history.

The API documentation does not describe write request bodies. Reads and the browser interface have been verified against the live sandbox; write semantics must be verified on the first real reviewer-approved correction. A failed verification is shown as an error, never as success. Do not clear errors or retry uncertain creates by deleting the database.

## How it works

**Website → snapshots → matching → persisted proposals → human decision → API → verification**

- `bellhaven.py` contains the scraper, matching rules, SQLite persistence, and write safeguards. `webapp.py` exposes the local review UI; templates contain no credentials.
- The crawler starts at Home, About, and the community directory, follows same-domain community and pagination links, and saves source text and timestamps. The initial website has 35 total communities, including a homepage-only acquisition; the directory alone advertises 34. Counts are checks, not hardcoded location lists. Failed pages or a short count disable absence proposals.
- The CRM reader retrieves all pages, checks the reported total, and excludes corporate parents. Matching considers accounts under every parent, including independent records. Historical CHOW accounts and known inactive duplicates do not compete with their current records.
- Physical address, city, and state establish a confident unique match. Exact name and locality are sufficient only without a conflicting physical address. Fuzzy names and PO boxes require review. Street abbreviations and care synonyms are normalized for comparison, but raw evidence is retained.
- Distinct care offerings are kept in a stable semicolon-separated value. `Memory Support` maps to `Memory Care`; `Short-Term Rehabilitation & Nursing` maps to `Skilled Nursing`. Missing records are proposed only when no plausible candidate exists.
- Exact-place duplicates retain financial history first, then the correct parent, completeness, and stable ID. The loser is marked `Inactive` and linked with `duplicate_of_account`. Multiple records with financial history block automatic duplicate selection. No merge or delete is used.
- Ownership changes check both financial fields. Positive lifetime revenue **and** positive outstanding AR require a new, zero-balance account. Only `chow_current_account` changes on the old account. Other ownership changes re-parent directly. Unknown or invalid financial values block the change.
- SQLite stores runs, full evidence, proposals, decisions, explicit match selections, operation checkpoints, and audit events. Stable fingerprints suppress unchanged decided proposals. Changed facts can create a new proposal, and prior decisions remain visible in the history. Process locking serializes scans and writes; preflight checks catch intervening CRM changes.
- Server-side credentials, escaped templates, CSRF tokens, same-origin POST checks, strict cookies, and host validation protect the local approval interface. GET requests never write to the CRM.

## Daily schedule (example only — not installed)

`run_daily.sh` runs discovery and proposal generation only. Set the actual absolute path in a cron entry:

```cron
0 7 * * * "/absolute/path/to/assessment/run_daily.sh" >> "/absolute/path/to/assessment/private/daily.log" 2>&1
```

Cron uses the machine's configured timezone. Keep the private environment file and database on the same machine; a fresh database loses prior decisions and recovery checkpoints. Review log failures before using absence proposals.

## Tests and sharing

```sh
.venv/bin/python -m pytest -q
.venv/bin/python package.py
```

`package.py` creates `bellhaven-submission.zip` using an explicit allowlist. It excludes the virtual environment, local database, snapshots, credentials, and session key. The ZIP is suitable for sharing after you review its contents. Uploading, publishing, and final submission are manual steps.

## Limits and next improvements

This is a small sandbox tool, not a production identity-resolution service. Missing website records prove absence only, not a new owner. Conflicting addresses need human judgment; unrecognized care labels remain visible rather than being invented. The client assumes the documented account routes and verifies the sandbox's actual responses. It cannot atomically commit changes across two HTTP requests. Durable checkpoints reduce duplicate writes, but an uncertain create without a unique marker deliberately requires manual reconciliation. External writers can race the preflight check because the API exposes no documented conditional-update or idempotency-key support. Schema migrations, stronger cross-account consistency checks, contact migration, richer ownership evidence, and operational alerting would be next steps.

## AI assistance

Codex generated the initial implementation and tests, inspected the fictional website and documented API, and helped identify edge cases. No LLM is called by the pipeline. Human review of proposed corrections and understanding the system remain essential. Record actual elapsed working time honestly; do not substitute an AI-generated estimate.
