# Review, demo, and interview preparation

## Current state

The first complete read-only scan found **35 website locations and 121 CRM accounts**. It generated **29 proposals**: 13 updates, 6 duplicate flags, 2 protected ownership changes, 3 account creations, 3 absence flags, and 2 ambiguous matches. Later scans may change these counts as decisions are applied. No real CRM corrections were made during implementation.

## Your review decisions

- **Portsmouth ZIP:** website 45662 versus CRM 45626. This is a simple first approval candidate. Open its evidence and decide yourself.
- **Ashtabula:** matching name and city, but CRM has a PO box. Decide whether those facts support matching it to the published physical location. Selecting a candidate creates a new correction preview; it does not approve it.
- **Union Square:** the names are similar but the published city differs from the candidate's city. Review the full evidence before choosing a match. Rejecting an unsupported proposed match is a legitimate demonstration of judgment; a rejection leaves the issue unresolved, so investigate before deciding whether a new account is needed.
- **Tiffin and Marietta:** positive lifetime revenue and positive unpaid receivables. Confirm that a new account is created and the old account is preserved with only a CHOW link added.
- **Duplicates:** review survivor evidence and financial fields. Approve duplicate flags before editing their survivor, or rescan if the survivor changed.
- **Absent records:** absence warrants investigation, not a fabricated acquisition or closure.

## Two-minute recording outline

Use your own words and show real decisions. Start recording before making the approval or rejection you intend to demonstrate. Do not show the workspace page or token.

- **0:00–0:20:** Explain the goal: reconcile the website with the CRM while keeping approval and billing safeguards in place. Show the complete scan and counts.
- **0:20–0:55:** Open a straightforward correction. Show source evidence and the current CRM field. Explain your reason and approve if justified.
- **0:55–1:20:** Open an uncertain proposal, explain why the evidence is insufficient, and reject it if that is your honest decision. Never reject a valid correction just to create a video event.
- **1:20–1:50:** Open the approved account in the assessment's CRM browser and show the changed field. Show the local verified audit event.
- **1:50–2:00:** Explain that daily scans are read-only, decisions persist, and protected ownership changes preserve billing history.

The assessment asks for a viewable video link. Review the recording for exposed tokens before sharing it. Do not make the private workspace or CRM token public.

## Explain the system in plain language

- **Scraper:** follows the community links and pages, including the new location linked only from the homepage.
- **Matcher:** compares normalized physical locations first, then names and locality; uncertain matches go to you.
- **Review app:** shows the evidence and proposed fields. Approval is the only way to write.
- **Billing rule:** revenue plus unpaid AR means the old record must stay intact; create a current record and link the old one to it.
- **Safe reruns:** a persistent fingerprint remembers decisions; a checkpoint remembers created account IDs after failures.
- **Verification:** re-read the CRM after writing. An uncertain result stays an error rather than being called successful.

## Practice a small live change

Use tests, not live CRM edits, to practice. For example, add `Terrace → Ter` to the street abbreviation dictionary and add a test proving the equivalence. Explain the tradeoff: new normalization may improve matches, but must not collapse distinct addresses. Run the tests, then demonstrate a read-only scan.

## Final checklist

- Review and apply the corrections you believe are right; a queue alone does not satisfy the exercise.
- Verify changes in the CRM browser and rescan for repeat proposals.
- Record about two minutes of review, including a justified approval and rejection.
- Review the writeup and honestly supply actual time spent.
- Generate and inspect the ZIP; share it and the video with the requested viewing permissions.
- Submit the links, time, and writeup before **November 4, 2026, 2:27 PM CST**. Save the confirmation.
