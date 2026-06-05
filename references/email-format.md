# Mission Email Format

Render a copy-pastable weekly mission email by default. The skill must not store
email credentials or local auth tokens, and it must not send email directly.

The editable HTML template is `templates/mission-email.html`. Keep it
email-safe: inline CSS, table-based layout, no scripts, no external fonts, and
no SVG.

Structure:

1. Title: `Weekly Mission Update - <Team> - Week <N>`
2. Compact summary cards:
   - on track count
   - at risk count
   - blockers/risks count
   - missing updates
3. Main mission table:
   - Mission
   - DRI
   - Status
   - Progress % from child issue statuses
   - Due date, rendered as a friendly date with original/movement/overdue
     context when relevant, for example `15 Jun (original: 10 Jun, moved later
     5 days)`
   - Done this week
   - Plan for next week
4. Blockers/risks table:
   - Mission
   - DRI
   - Status
   - Blocker/risk
   - Owner if detected
   - Days open if available
5. Data hygiene block, only when actionable red/yellow issues exist
6. Sheet link
7. Footer: `email.signoff` followed by `email.signoff_name`

If no blockers are present, show `No active blockers reported.` Do not render a
data hygiene section just to say there are no hygiene issues.

Use `email.greeting` for the greeting, defaulting to `Hi`. Use
`email.signoff` for the closing line, defaulting to `Kind Regards`.

Do not include the full DRI comment in the email. The full selected DRI comment
lives in the weekly sheet tab.

Linked OKR is hygiene-only. If missing, show it in the data hygiene block;
do not add a standalone OKR column to the email.

The draft payload must include:

- `subject`
- `to`
- `cc`
- `bcc`
- `plainTextBody` / `text_body`
- `htmlBody` / `html_body`

When `--output-dir` is provided, the runner writes:

- `draft-email.html`
- `draft-email.txt`
- `draft-email.eml`
- `gmail-raw-draft-request.json` when `--email-source raw-mime-plan` is used

If an already-authenticated local connector/API client can create an HTML draft,
use the rendered HTML or `gmail-raw-draft-request.json` with that route. If no
email connector is available, stop after rendering the subject/body and use the
copy-pastable HTML/text manually.

Do not use plain-text-only draft helpers for formatted HTML emails.
