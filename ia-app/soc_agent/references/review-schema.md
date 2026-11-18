# SOC review output schema

Use `assets/SOC_Report_Review_Template.xlsx` as the default reusable form. Deliver one native Google Sheets spreadsheet per provider/report review unless the user requests consolidation or another format. The bundled Excel form is an authoring source; follow the Google Sheets skill for native conversion and verify the single review tab after import. The asset is a reusable, cleared version of FY-25 NS-SOC Review file.xlsx supplied by the user; the original completed NetSuite review is only a layout reference, not evidence for other providers. Keep the report metadata, evidence and conclusions attributable to the correct provider when several reports are combined.

## Supplied layout and field placement

Preserve the source form’s single `SOC REVIEW` tab (a trailing space in the asset name is immaterial), section sequence and side-by-side evaluation columns. Keep the source headings and merged spans; extend rows only to fit the actual population. Use simple professional formatting. Do not replace this form with the previous five-tab design or a long field-per-row report.

Original template coordinates are locators before row insertion:

- A1:C17: SOX year, report details and bridge fields. Replace FY[YY] and all descriptive placeholders for the actual review.
- A20:D24: process-owner review and control exceptions. A is record number; B is control/exception/page; C is provider response; D is OD evaluation.
- A26:D41: CUECs. A is number; B is the copied CUEC and page; C:D is the corresponding OD control/key procedure and assessment. Keep one row per CUEC.
- A44:F46: subservices. Preserve the six columns for number, provider/scope, services, OD impact, provider response and OD evaluation.
- A49:E51: management conclusions on period adequacy and reliance.
- B55:C56: reviewer sign-off.

Keep additional required evidence and analysis concise within the corresponding evaluation cells. The approved default is the simple original form, with rows scaled to the actual population. State shared limitations once in the relevant section and use brief source references. Add supporting rows only when a material issue cannot fit clearly in the existing cells or the user requests more detail. Do not automatically append objective-mapping tables, action registers, evidence inventories or a separate final-review checklist. Never carry over NetSuite-specific dates, control IDs, names, exceptions, responses or approvals. Do not infer that the sample’s favorable conclusion or bridge wording establishes adequate evidence.

## Report details

Populate these report-detail fields, preserving the supplied form labels:

1. **SERVICE PROVIDER NAME** — legal entity and relevant service.
2. **PROCESS CYCLE** — confirmed SOX process.
3. **PROCESS OWNER / SYSTEM OWNER** — confirmed name, role and source.
4. **SOC REPORT TYPE** — SOC 1 or SOC 2; Type 1 or Type 2; stated standard. Use a separate review-year field rather than a hardcoded 2024 label.
5. **SOC REPORT TITLE / FOCUS AREA** — exact report title, applicable service used by Opendoor, usage and ICFR scope.
6. **SOC REPORT PERIOD COVERED** — start/end dates, intended reliance period and year-end; scope exclusions.
7. **SERVICE AUDITOR** — exact firm name and suitability assessment reference.
8. **SERVICE AUDITOR REPORT DATE** — signed report date, distinct from coverage dates.
9. **SERVICE AUDIT CONCLUSIONS** — exact opinion terminology, qualification/basis and Opendoor impact.

Assess the following and summarize relevant results in existing report-detail, evaluation, conclusion and sign-off cells. These checks do not require additional supporting sections:

- Relevant SOC objectives/controls and their pages, OD risk/control/assertion, tests reviewed and reliance limits.
- All uncovered periods, bridge coverage and letter date, management signer, representations, additional procedures and results.
- Same-system FY24 reference, later changes, new/changed/removed CUECs, prior findings and significant changes through review date.
- **Management conclusion:** period adequacy, appropriateness and limits of reliance, exceptions/CUECs/subservices impact, unresolved matters, Low/Medium/High risk rating and basis, and formal OD deficiency conclusion/evaluation reference.
- **Final review point and sign-off:** check, risk if skipped, personal verification, Continue/Revise/Stop with rationale, preparer, process owner, reviewer, any required additional approval, evidence location and version.

Keep period adequacy, reliance, risk rating, deficiency assessment and final decision Pending in a blank template. Record evidence-supported proposed conclusions distinctly from human sign-off in a prepared review.

## Control exceptions section

Use one numbered record per exception. Reconcile total report exceptions to records; document a supported none-found result when applicable. Include:

- Highlight critical findings; use finding IDs only when needed for issue tracking.
- SOC objective/control ID and exact source location.
- Auditor exception and test result; nature and timing of testing.
- Population, sample and deviation counts/frequency, or Not stated.
- Root cause; provider management response; remediation date/status and verification evidence.
- Applicability to Opendoor usage and reliance period.
- Affected process, OD controls, risks, accounts/disclosures and assertions.
- Actual and potential financial impact; likelihood/magnitude assessment and materiality basis when available.
- Compensating control IDs, owners, precision, periods and testing evidence/results.
- Combined effect with related issues.
- Opendoor process/system owner's evaluation and conclusion.
- Disposition, formal SOX deficiency evaluation reference, follow-ups and reviewer decision.

Distinguish source findings from management responses and reviewer analysis. Do not characterize an unsupported management response as independently verified remediation.

## CUEC section

Capture the following information in the source template’s CUEC and OD procedure columns. These are content requirements, not instructions to add eight columns or separate records:

| Field | Required content |
|---|---|
| No. | Sequential CUEC record number |
| CUEC requirement and SOC reference | Current wording, ID/objective and printed/PDF page |
| Applicability and rationale | Applicable, not applicable or pending; service usage and ICFR reason |
| FY24 OD control or key procedure | Same-system mapping and original document/worksheet/cell locator |
| Current OD control or key procedure | Validated ID/procedure, owner, confirmation and changes |
| Current evidence and result | Evidence link, period and operating/test result |
| Conclusion, gaps and follow-up | Owner evaluation and concise specific gap/recommendation; finding ID only if needed |
| Assessment status | Pending, Addressed, Gap identified or Not applicable |

Keep one row per CUEC, with complete report wording and page beside a concise OD procedure/assessment. Summarize limitations shared by all mappings once in the section; retain any unique gap in its own row. Label historical or proposed mappings clearly. Reconcile the complete current CUEC list, including new/revised/removed requirements compared with the historical reference. Do not use “Addressed” when current evidence is outstanding. Retain the reason for any exclusion.

## Subservice section

Use one row per identified subservice organization. Reconcile completeness and include:

- Provider, services and report page.
- Scope method: inclusive, carve-out, mixed or supported not-applicable result.
- Included/excluded objectives/controls and CSOCs.
- Actual dependency and impact on OD processes, risks and controls.
- Service provider monitoring/response to exclusions and its source.
- Additional SOC or alternative evidence, scope, period, tests, exceptions and relevant CUEC responsibilities.
- Opendoor owner's evaluation, conclusion, open finding, action and reviewer/date.

## Concise follow-ups and source references

Put essential actions and unresolved reliance limitations in the relevant evaluation or management conclusion cells. Include confirmed owners, dates and status when available; do not invent them. Keep Low/Medium/High overall risk distinct from finding priority and CD/SD/MW classification. A shared pending-evidence note may cover multiple rows when its scope is clear.

Cite report pages and internal source locators beside the relevant facts. Use a brief shared source note if necessary. Preserve useful historical links without implying they establish current operation; update reference-check dates only when actually checked.

Create a detailed action register, input/evidence register or objective-mapping schedule only if the user requests it or a material issue needs that detail. If needed, preserve the original form and keep the added detail proportionate. The full review checks remain required even when the default deliverable is concise.

## Workbook operation and quality

- Follow the spreadsheet skill for authoring, date types, recalculation and visual checks. Preserve the supplied template’s layout and editable fields. Use plain headings and restrained emphasis; do not add dashboards, decorative colors or extra tabs.
- Treat row references as changeable. Use labels and table names to find fields. Extend native tables, validation and conditional-format rules when inserting rows or copying records.
- For completed reviews, remove unused template rows or mark an unused section N/A with a reason. Do not count placeholder rows as reviewed items.
- Do not add automatic reliance decisions based on empty cells, zero counts or a low risk rating. Keep professional judgment and human sign-off explicit.
- Respect SOC use restrictions and keep copies within authorized locations. Cite actual document pages; use worksheet/cell locators for Excel sources.
