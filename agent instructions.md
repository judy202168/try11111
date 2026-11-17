# Agent instructions

This file records the user's build instructions and subsequent changes for Orbit CRM. Credentials are intentionally omitted.

## Step 1 — Build and deploy the CRM

Original request:

> Build me a CRM application with the following stack:
>
> - **Frontend:** A single HTML file using Tailwind CSS for styling and inline JavaScript for interactivity
> - **Backend:** A simple Flask server
> - **Storage:** A Supabase Database
>
> Deploy everything to railway. Use our plugins for both railway and supabase to do so.
>
> Fill our database with synthetic data.

The user approved creating the Supabase project in **JD's Org**.

Implemented application scope:

- Password-protected shared workspace.
- Dashboard, searchable/filterable contacts, editable records, deal pipeline, follow-up tasks, and CSV export.
- Synthetic seed: 24 contacts, 22 deals, and 16 tasks.
- Flask application and scheduled worker deployed on Railway; database hosted by Supabase.
- Database access restricted through row-level security and a server-only token.
- Credentials remain in Railway variables and ignored local credential files; never commit them.

## Step 2 — Autonomous follow-up agent

Original request:

> Step 2: Create the Agent
>
> The follow-up agent
>
> 1. finds stalled contacts or deals.
> 2. sends the relevant CRM context to OpenRouter.
> 3. creates a follow-up draft.
> 4. is intentionally approval based. A person reviews and approves or rejects it.
> 5. does not automatically send email.
>
> Add an autonomous CRM follow-up agent. Each morning, review contacts and open opportunities for stalled activity, draft a personalized follow-up, update the suggested next action, and require human approval before any message could be sent. Use OpenRouter for the model.

Implementation defaults communicated during the build:

- Review daily at 8:00 AM America/Los_Angeles, accounting for daylight saving time.
- Flag records with no recorded activity for seven days; use creation date when activity is unknown.
- Exclude inactive contacts and closed Won/Lost deals.
- Use OpenRouter with configurable OPENROUTER_MODEL; initial model is openai/gpt-4o-mini.
- Limit each review to ten new drafts.
- Store subject, body, suggested next action, relevant context, generation status, and review decision.
- Save suggested next actions separately from actual activity timestamps.
- Prevent duplicate generation for an entity's same activity version.
- Require authenticated human approval or rejection; record review note and timestamp.
- Approval records a decision only. There is no email transport or sending endpoint.
- Support retrying failed generation and explicitly recording actual activity.
- Keep OPENROUTER_API_KEY server-side in Railway variables. The worker references the CRM service's configuration.

## Follow-up operational requests and results

- The user requested help obtaining and configuring an OpenRouter API key.
- An API key was supplied and configured in Railway. Its value is not included here.
- The user requested live checks, then added credit and requested another retry.
- Initial generation attempts returned OpenRouter HTTP 402.
- After the user added credit, a retry succeeded: a draft was stored as pending human approval and the suggested next action was persisted.
- No email was sent during implementation or verification.
- Fifteen automated tests passed before live OpenRouter verification, covering application behavior, stale-record selection, deduplication, model-output validation, and approval transitions.

## Step 3 — Save the build instructions in GitHub

Original request:

> Save log in GitHub
> Include in prompt above : Save all prior build instructions given to the repo in an MD file called agent instructions

Deliverable: this repository-root file, **agent instructions.md**. Preserve this record when continuing work. Append future build instructions and significant implementation/verification outcomes. Do not record API keys, passwords, session tokens, or other credentials.

## Source and deployment references

- Application source: crm/
- Setup and implementation details: crm/README.md
- Live application: https://orbit-crm-production-ace6467a.up.railway.app
- Follow-up review queue: https://orbit-crm-production-ace6467a.up.railway.app/#followups

## Continuing-agent prompt

Maintain Orbit CRM using the requested single-HTML/Tailwind/inline-JavaScript frontend, Flask backend, Supabase storage, and Railway deployment. Use the Railway and Supabase plugins for infrastructure operations. Keep follow-up generation autonomous each morning and all message decisions human-approved. Never automatically send email. Save all prior and future build instructions given to the repository in the Markdown file named **agent instructions.md**, keeping credentials out of GitHub.
