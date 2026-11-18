# JD’s SOX/IA AI Lab

A Flask application for SOX, internal audit, and practical AI learning. Application state is stored in Supabase; Railway runs the web server from the connected GitHub repository.

## Run

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Populate the Supabase server variables in your shell or deployment environment.
python app.py
```

Open http://127.0.0.1:5000. If port 5000 is occupied, use `PORT=5050 python app.py` and open http://127.0.0.1:5050.

## Layout

- `templates/index.html`: the entire frontend, with TailwindCSS and inline JavaScript. Tailwind and the optional DM Sans font load from public CDNs, so initial styling requires internet access.
- `app.py`: Flask server, validation, search-based source retrieval, optional AI generation, and Supabase persistence.
- `supabase_store.py`: server-only Data API adapter. The browser never receives database credentials.
- `supabase_schema.sql`: isolated workspace table, private token-hash table, grants, RLS policies, and updated-at trigger.
- `railway.toml`: Railway build, Gunicorn start, restart, and health-check configuration.
- `data.example.json`: an empty reference shape. It is not the production persistence backend.

## Workflows

- Open **JD AI Builder** to browse the saved project portfolio.
- Add articles in **Knowledge hub**, cases and templates in **Cases & templates**, and experiments in **AI projects & learning**. Track project owner, phase, results, and lessons.
- Search across all resources using the header search and Enter. Each library also has live search, topic and status filters.
- Open any resource to read, edit, delete, or download it as plain text.
- Mark resources **Reviewed** or **Published** after human review to make them available to the assistant. These are workflow labels in a personal workspace, not separate-user approval controls.
- The assistant supports independent review, analysis, and draft requests with optional evidence notes. It retrieves up to five relevant reviewed/published sources using keyword overlap. It never treats Draft resources as authority. No matching sources means no generated answer.
- Without an API key, the assistant returns source excerpts only, clearly labeled **Local resource search**. It does not perform generative analysis in this mode.
- With a key, generated responses cite numbered source references, appear as drafts for human review, and can be saved back into the library as Draft resources. Past responses retain their text and source titles/timestamps even when the original resource is changed or deleted. Links open the current resource, if it still exists.
- Activity and assistant requests persist in Supabase. **Export workspace** downloads a full JSON backup, including notes and history.

## Optional AI generation

Set environment variables in the same shell before starting the server:

```sh
export OPENAI_API_KEY='your-key'
export OPENAI_MODEL='gpt-4.1-mini'  # optional; choose a model available to your account
python app.py
```

The key stays on the server and is never stored in JSON or sent to the browser. The server calls the [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create) with `store: false`. A request sends its question, evidence notes, and matching source excerpts to OpenAI. It does not send the full profile or conversation history. Each request is independent. Generated answers are working drafts; source sufficiency and audit judgments require human review.

## Scope

The deployed app still has no end-user authentication or role-based approval workflow. Supabase access is server-only and protected by RLS plus a random application token, but anyone who can reach the Railway URL can use the Flask endpoints. Add an approved access layer before placing confidential information in an internet-reachable deployment. `LAB_DATA_FILE` exists only as an explicit test adapter.

## Verification

```sh
python -m unittest discover -s tests -v
```

Tests use isolated temporary storage plus mocked Supabase and AI responses. They do not modify Supabase or call external AI services.

## Supabase and Railway deployment

1. Apply `supabase_schema.sql` to the selected Supabase project.
2. Generate a long random `IA_DATABASE_TOKEN`. Insert only its SHA-256 hash into `private.ia_access_tokens` for workspace `default`.
3. Set `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `IA_DATABASE_TOKEN`, `IA_WORKSPACE_KEY`, and `FLASK_SECRET_KEY` as server-side Railway variables.
4. Connect Railway to the GitHub repository and set its root directory to `/ia-app`.
5. Attach a persistent volume at the path used by `LAB_UPLOAD_DIR` if review uploads must survive redeployments.

The Supabase publishable/legacy anon key identifies the Data API request but does not by itself grant workspace access. RLS also requires the server-only `X-IA-Token`; only a SHA-256 hash of that token is stored in the private schema. The browser receives neither value.

## SOC report review agent

Open **SOC report review** in the sidebar, or follow the specialized-agent card in **AI audit assistant**.

1. Enter a review title and review year.
2. Upload the **complete current SOC report (PDF)** and **current company RCM**. Add the **same-system prior-year SOC review** if available. A bridge letter/supporting-evidence upload is also available.
3. Add actual service usage, process/owner, reliance dates, fiscal year-end, and any applicable methodology. Missing context stays Pending.
4. Confirm that the source documents may be processed by the configured AI service, then choose **Prepare SOC review**.
5. The background run extracts source text, identifies report facts/exceptions/CUECs/subservices, proposes RCM mappings, and prepares coverage and reliance commentary. Open the saved run to inspect progress, draft results, limitations, and source references.
6. Connect your Opendoor Google account and choose **Create review Google Sheet**. Open the returned native Google Sheets link to perform human review and sign-off.

The agent uses the description and single-tab template from the supplied `soc-report-review.zip`. It preserves the template's section sequence, side-by-side columns, complete extracted populations, and Pending human sign-off. It does not retrieve linked prior reviews, assume the template's old conclusions, change sharing permissions, or contact anyone. The binary template is read only; native Google grid data is generated by the web application at runtime.

### Connections required

**AI:** Set `OPENAI_API_KEY`. Optionally set `SOC_REVIEW_MODEL` (defaults to `OPENAI_MODEL`, then `gpt-4.1-mini`). The model must support Responses API structured JSON output and sufficient input/output length. Each stage is sent with `store: false`. All extracted SOC sections, RCM content, optional historical/bridge evidence, and entered context may be sent to OpenAI. The app validates structured responses and cited quotes against the uploaded text; this does not establish the substantive accuracy or completeness of the model's review.

**Google Sheets:** An authorized administrator must register a Google OAuth **Web application**, enable the **Google Sheets API**, and configure a consent audience appropriate for Opendoor. Use these server variables:

```sh
export GOOGLE_CLIENT_ID='your-client-id'
export GOOGLE_CLIENT_SECRET='your-client-secret'
export GOOGLE_REDIRECT_URI='http://127.0.0.1:5050/auth/google/callback'
export FLASK_SECRET_KEY='a-long-random-secret'
export PORT=5050
python app.py
```

Register the exact callback URI in Google Cloud. Use `http://localhost:5050/auth/google/callback` consistently instead if required by the OAuth registration; don't mix `localhost` with `127.0.0.1` during a connection. Production callbacks require HTTPS; set `COOKIE_SECURE=1` when using HTTPS. Credentials stay on the server. `.env.example` lists settings; it is a reference only, and `.env` files are **not automatically loaded**.

The Google OAuth connection requests `openid`, `email`, and `drive.file`. The latter scopes the app to files it creates or that are explicitly opened with it. The callback verifies Google's signed identity token through Authlib, requires verified `@opendoor.com` email **and** the `opendoor.com` hosted-domain claim, and rejects outside accounts. Access tokens stay in server memory, expire with Google's token, and are never saved in exported JSON. Reconnect after a server restart or token expiry. No background token refresh is configured.

A prepared draft can be saved without a Google connection. Creating a native Sheet is unavailable until Google OAuth is configured and the user connects. The app creates one `SOC REVIEW` tab directly through the Google Sheets API, using the supplied layout, merged spans, wrapped cells, and population-sized rows. It then reads back every populated cell and checks that there is exactly one tab. This direct API workflow is necessary for the standalone Flask application's runtime; it does not depend on a Codex connector or an agent being present. Visual verification in native Google Sheets is still required. Model output and file content are inserted as literal text, never evaluated as formulas.

### Source handling and limits

- SOC input: searchable PDF. RCM, prior-year review, and bridge/supporting input: PDF, XLSX, CSV (UTF-8), DOCX, or TXT.
- Up to **25 MB per file**, **80 MB per request**, **600 PDF pages per document**, and **600,000 extracted characters per document**. Oversized inputs are rejected rather than silently truncated.
- PDF extraction retains PDF page references. Printed page numbering is not assumed; verify it against the report. Low-text pages generate explicit completeness warnings. Image-only PDFs must be OCR-processed before upload. This version does not perform visual table/image analysis or OCR.
- Excel extraction includes all worksheets (including hidden ones), cell coordinates, formula text and cached values; formulas/macros are not executed. Excel files need an appropriately scoped export if they exceed 20,000 rows, 300 columns, or 80,000 populated cells. Embedded Excel images/charts and DOCX images are not interpreted; provide important content as readable text or searchable PDF.
- Original uploads are retained under `LAB_UPLOAD_DIR`, outside served paths, with restrictive filesystem permissions. Drafts, source filenames/hashes, progress, and Sheet links are stored in Supabase. Back up Supabase and the persistent upload volume together if source retention is needed.
- **Export workspace** includes saved draft review text and history, but does not include binary uploads, OAuth tokens, or API keys.
- A single background worker handles reviews; up to three runs can be active/queued. Restarted jobs are marked interrupted and must be restarted. Runs and results are visible to anyone who can access the deployed workspace.
- Google creation is idempotent once an ID has been returned and saved. A network timeout before Google returns an ID can leave an unconfirmed Sheet in Drive; check Drive before retrying to avoid duplicates.

### Review safeguards and remaining deployment scope

All outputs remain **Draft — human review required**. Current RCM descriptions and historical mappings do not establish current operating effectiveness. CUEC applicability/mappings, risk rating, deficiency evaluation, reliance decisions, and sign-off require human validation. No exceptions extracted is not a none-found audit conclusion. Verify source completeness and exact page/cell citations, especially tables and images.

The Google connection restricts **which account can create a Sheet**. It does **not** implement website-wide authentication: all existing pages and local APIs still have no login gate. Do not publicly expose this workspace or upload confidential data to a shared deployment until company-wide SSO/access controls and appropriate hosting are configured. Google Drive sharing follows account/organization defaults; the app makes no sharing or permission API calls.

## SEC filing disclosure review agent

Open **SEC disclosure review** in the sidebar, or select its card in **AI audit assistant**. This is an original implementation of the functional workflow described in the user's attachment. The attachment's bundled non-commercial software, script, tests, and assets were not incorporated or executed.

### Inputs and workflow

1. Choose **10-Q**, **10-K**, or **S-1**. Supply a review title, company ticker, confirmed industry, review date, and comparison filing cutoff. Add reporting period, filer status, reporting basis, and relevant facts/elections when available.
2. Upload the current draft as PDF, DOCX, TXT, or Markdown. Confirm company/form, industry and peer suitability.
3. Choose public SEC retrieval or uploaded comparison filings. Public retrieval requires the contact format **Full Name (email@domain.com)**. Enter up to three confirmed peer tickers; upload a prior filing or peer filings to override retrieval for those slots. Missing peer slots remain explicit unmatched records rather than disappearing.
4. Optionally provide up to eight official FASB ASU URLs. Only HTTPS `fasb.org`, `www.fasb.org`, and `storage.fasb.org` links are accepted; redirects are checked too. Filer status, period, and adoption elections are necessary for a defensible effective-date/applicability assessment.
5. Optionally upload a financial XLSX and filing PDF. If no separate PDF is supplied and the draft is a PDF, that draft is used. Choose all worksheets, including hidden sheets, or visible worksheets only.
6. Confirm permission to process the draft with the configured AI service, then start the review. The run and progress are saved. A prepared draft can be previewed by workbook tab, downloaded as Excel, or accompanied by a JSON source snapshot.

The same `OPENAI_API_KEY` used by the SOC agent enables SEC reviews. `SEC_REVIEW_MODEL` can override the default (`OPENAI_MODEL`, then `gpt-4.1-mini`). The model must support Responses API structured JSON output and sufficient context length. Unlike the SOC Google Sheets workflow, this agent's requested output is a multi-tab **Excel workbook**, so it does not require Google OAuth.

### Source retrieval and limitations

The standalone Flask app retrieves fresh SEC ticker identities/submissions and source filing documents directly using the [SEC public APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). It does not depend on the attachment's Cursor-specific MCP server. Requests include the supplied contact, are limited to approximately 3.3 requests/second, and are restricted to approved SEC/FASB HTTPS hosts. Only public ticker/source requests go to SEC; confidential draft text does not. The API source is fetched fresh for each run; no previous-run filing payloads are silently reused.

Retrieval selects the latest **exact form type**, without amendments, filed strictly before the chosen cutoff. Up to three older submission-history files are checked when recent history has no eligible filing. The cutoff controls chronological selection; it does not establish reporting-period or business comparability. Uploaded comparisons have user-confirmed identity/form/period, without invented accession metadata. Missing/blocked sources, unreadable documents, under-sectionized sources, failed AI batches, and unmatched subsections produce explicit Pending rows and coverage limitations.

Peer selection is supplied and confirmed by the user. This version does not automatically discover or approve a peer group through web search. Public source retrieval may be blocked by SEC access controls or network restrictions; upload the corresponding filing if needed. A contact is required only when SEC retrieval is enabled.

The parser keeps Part I/Part II Item keys separate for 10-Q, retains numbered financial statement notes as separate sections, detects internal heading cues, and emits fallback/continuation blocks when necessary. It uses the same parser on current and comparison sources. Footnote topics, rather than note numbers alone, govern note alignment across companies. TOC duplicates, repeated/continued section bodies, fallback granularity, missing structural headings, note sequence gaps, and unresolved references require human verification. S-1 heading recognition and all PDF/HTML layout extraction are heuristic; the source snapshot retains full extracted text, including duplicate heading occurrences. Substantive repeated/continued section bodies are merged in source order; only exact duplicate bodies and clearly TOC-only occurrences are excluded from analysis when substantive text is present.

ASU model suggestions are preliminary candidates only. The app attempts to locate relevant readable official PDFs from the FASB index when no links are supplied; dynamic pages or inaccessible sources may prevent this. An ASU row remains unverified/Pending unless its identifier and cited quotations can be checked against extracted official-source text. Even a source-supported draft assessment needs human verification of topic, current authoritative guidance, effective dates, applicability, and adoption facts. The screen is not a complete accounting-update universe or a compliance conclusion.

### Workbook tabs

The workbook includes these eight tabs, with header filters, frozen header rows, wrapped narrative text, source links/accession numbers when available, and source locators:

- `vs. prior version`
- `vs. company 1`
- `vs. company 2`
- `vs. company 3`
- `ASU screen`
- `Suggested Improvement`
- `Coverage QA`
- `cross-ref consistency`

Every parsed draft subsection has a record in all four comparison tabs. An unmatched block or invalid analysis response is Pending, never an implied pass. Peer comparisons are benchmarks, not disclosure requirements. Suggested wording is a draft and must not introduce unsupported company facts. Numeric or formula-like source text is written as literal text, preventing spreadsheet formula execution. Full subsection excerpts are retained up to the Excel cell limit; any limit truncation is labeled, and the full source snapshot is available. Very long narrative cells exceed visible row height; read the expanded formula bar or source snapshot and compare the original filing.

The `financial tie-out` tab is added **only when an XLSX is supplied**. It enumerates every included numeric/formula/error cell (subject to the documented processing limits), records evaluated/cached values or unavailable formula caches, and identifies exact numeric occurrences in the PDF. Matching numbers remain candidates; labels, periods, units, rounding, sign and statement context must be reconciled by a human. Scaling, semantic mapping, formula calculation, and final tie-out approval are not automated. Failures in this optional stage preserve the main review workbook and add an explicit incomplete status.

### Storage and operating scope

Draft and comparison uploads retain the SOC agent's 25 MB per-file and 80 MB request limits. Readable PDF/DOCX extraction uses the same limits; text/SEC HTML filings allow up to 1.2 million extracted characters and 650 subsection blocks. Oversized sources are rejected, without silently omitting disclosure content. Financial workbooks are limited to 20,000 rows, 300 columns, and 80,000 numeric/formula cells; unresolved census failures are explicit and do not become completed tie-outs.

Source uploads, the source snapshot, and the workbook are retained under `LAB_UPLOAD_DIR/sec/<run-id>/`. Review status, analysis, and activity are stored in Supabase. One SEC worker processes up to three queued/active runs independently of the SOC worker. Restarted runs are marked interrupted. Google credentials/API keys are never included in source snapshots or workbook exports.

Website-wide authentication is still separate from both agents. The application does not submit SEC filings, send communications, change sharing permissions, or record human approvals. All results require accounting and legal review before use.


## JD AI Builder

**JD AI Builder** is an internal `#builder` page rendered by the same single HTML frontend as every other tab. It uses the app's white/warm-grey surfaces, Opendoor blue accents, typography, navigation, and cards. It does not open, redirect to, or embed the original portfolio site.

The `builder` object in Supabase stores selected projects, self-assessed practice level, learning notes, and toolkit. Portfolio content is workspace data and is not included in the public source repository.

Project-category filters work inside this page. The SOC project and toolkit links open the existing SOC and SEC agents within this workspace. Demo-request buttons prefill the contact form. Submitted requests are stored in the Supabase workspace state and recorded in activity history. They do not send email, contact anyone, or book a meeting. Request contact details are excluded from `/api/state`; full workspace exports still include saved requests. There are no website-wide access controls yet.

## System implementation checklist

Open **System implementation** in the sidebar, then choose **New assessment**. This feature works locally without an OpenAI key or Google connection.

The source is the user-supplied **SDLC Checklist template.xlsx**, worksheet **✅ Self-Assessment**. It provides 37 source prompts across nine control areas. The data-migration prompt is expanded into nine separate evaluations, and the SOD applicability prompt is handled as a separate decision. This results in **44 actionable requirement responses plus one SOD applicability decision**. Each new assessment starts **Not assessed**, with IA conclusions **Not reviewed**. Historical Rippling responses, conclusions, named reviewer comments, and access discussions were excluded from the reusable template.

### Recording a review

- Create an assessment with its title and target system. Optionally specify migration source, assessment owner, business/SOX process, go-live date, and SOD assessment.
- Filter by control area, requirement status, owner/evidence keywords, or open items.
- Use the **Met** checkbox or **Assess / add evidence** to record **Not assessed**, **In progress**, **Met**, **Not met**, or **Not applicable**.
- **Met** requires a nonempty evidence reference or saved attachment. This verifies that a reference exists; a human must still evaluate evidence quality and operation.
- **Not met** requires a gap/next-action note. Record the requirement owner and target date to track follow-up.
- **Not applicable** requires an explanation. SDLC.05 has the extra SOD applicability conditions below.
- Upload evidence in the requirement dialog. Uploads save immediately; other fields save with **Save requirement**. Up to 20 MB per file, supporting PDF, Excel, Word, PowerPoint, CSV, TXT, PNG, and JPEG. Files are stored, not analyzed or executed.
- Enter optional IA audit procedures, review notes, conclusion, reviewer and review date separately. These fields are manually recorded; the app has no authenticated approval/sign-off workflow and does not infer IA conclusions from self-assessment statuses.

Questions use the selected target and migration-source system names while preserving template source-cell references and evidence guidance. Before an assessment is selected, placeholders identify the target/source system. Template requirements, examples and key/non-key classifications require confirmation for the actual implementation; this is not a universal statutory-compliance checklist.

### SOD and conditional post-migration review

The source template makes SDLC.05 compensating review conditional on whether SDLC.03 segregation of duties was fully in place. The app does not automatically mark the section Met or N/A. To save an SDLC.05 N/A response, the user must:

1. Record **Fully in place** in the assessment's SOD decision, with an evidence reference.
2. Save evidence-supported **Met** answers for the primary separation and deployment-approval requirements at source rows **C22** and **C23**.
3. Provide a rationale for each SDLC.05 N/A response.

If these prerequisites later change, the saved answers remain visible, but unsupported N/A responses are flagged for review and excluded from resolved/N/A progress counts. This is an explicit template-specific input safeguard, not an automatic SOX deficiency or compliance conclusion.

### Progress, storage, and export

Progress shows evidence-referenced Met responses, Not met gaps, supported N/A responses, pending/in-progress items, overdue unresolved requirements, and per-control resolution. **Resolved** means Met or a supported N/A; it does not represent audit approval. The progress summary also distinguishes manually entered IA conclusions.

Responses and assessment metadata persist in Supabase under `implementation_assessments`. Each assessment retains a snapshot/version of its source requirements. Optimistic revision checks reject stale changes rather than overwriting another saved update. A refresh retrieves the latest assessment.

Files are retained under `LAB_UPLOAD_DIR/implementation/<assessment-id>/`, outside served static paths, with restrictive directory/file permissions. Downloads check that the attachment belongs to the requested assessment and requirement. There is no automatic external sharing. Back up the persistent upload volume together with Supabase if evidence retention is needed. The dedicated assessment list avoids sending all responses on every general workspace refresh.

**Download CSV** exports all 44 detailed requirements and the SOD applicability decision, including evidence references, attachment names, owners, dates, notes, IA review fields and template provenance. Potential spreadsheet-formula text is escaped. Binary attachments are not included in CSV or the JSON workspace export.

This remains part of the same workspace; it does not add website-wide authentication or role-based approval controls.

## Useful Accounting AI Agent

Open **Useful Accounting AI Agent** in the sidebar. This is an operating workspace rather than a link directory:

- **Ask Contract** accepts contract metadata and pasted terms, then performs a preliminary revenue-contract, intake-completeness, or control-and-auditability review. It identifies potential evidence for the five contract criteria, obligation-related clauses, topic flags, missing fields, and control questions. It never issues an accounting conclusion or posts a journal entry.
- **Analyze SEC XBRL Data** accepts pasted CSV/TSV data and can summarize the dataset, find narrative facts, or calculate descriptive statistics for a numeric column. Up to 5,000 rows are analyzed per run. Results must be verified against the full filing and associated SEC metadata.

Each run synchronizes one fixed, allowlisted public repository using `git clone` or `git pull --ff-only`, records the exact commit and license, performs the selected work on the server, and stores the result under `accounting_agent_runs` in Supabase. Repository caches are retained under `LAB_UPLOAD_DIR/accounting_agent_repos/`. User-supplied repository URLs or commands are not accepted or executed.

The revenue workflow is grounded in `ChipmunkRPA/erev-cloud` (Apache-2.0). The complete eRev product itself requires Python/Node tooling and PostgreSQL 17; this local app does not silently claim to run that full multi-service subledger. The SEC workflow is grounded in the SEC DERA Python example repository (CC0-1.0) and follows its published analysis patterns. Repository synchronization requires internet access. These third-party sources are not independently validated or approved for production use by this app.
