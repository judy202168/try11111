---
name: soc-report-review
description: Create reusable SOC review templates or review SOC reports and document results for Opendoor SOX and ICFR. Use for SOC 1 Type 2 reviews, ICFR-relevant SOC 2 reviews, complementary user entity control mapping, control exceptions, subservice organizations, bridge-period assessments, and requests to complete the SOC Report Review workbook using same-system FY24 controls and key procedures.
---

# SOC Report Review

Perform the requested SOC review step and document evidence, findings and conclusions in one reusable or completed file. Default to the single-tab layout of the user-supplied FY-25 NS-SOC Review file.xlsx and concise, professional language. Keep the form simple, without decorative formatting. Apply professional skepticism without claiming personal credentials or years of experience.

## Approved default presentation

Use the user's approved simple NS template format for future reviews. Preserve its report details, bridge fields, exceptions, CUECs, subservices, management conclusions and sign-off sections, original restrained colors and side-by-side columns. Keep commentary brief and practical. Include every CUEC in its own row with the report wording and page, paired with a concise OD procedure or assessment; add rows only for the actual population. Summarize shared mapping/evidence limitations once where they apply to the whole section.

Perform the full evidence review below, but present the results within the existing template cells. Do not automatically add objective-mapping tables, action registers, evidence inventories, dashboards or a separate final-review checklist. Add detailed supporting schedules only when the user requests them or a material issue cannot be explained clearly in the existing section. Never shorten the output by omitting a CUEC, exception, subservice or material reliance limitation. Use proposed mappings and Pending statuses when current evidence or human approval is missing.

## Select the requested task

- **Create or revise a template:** Use `assets/SOC_Report_Review_Template.xlsx`. Keep report-specific fields as descriptive placeholders and conclusions as Pending. Include the form itself, without the user's background, AI persona or workflow-planning narrative. Do not perform a vendor review unless requested.
- **Review a report:** Populate a separate copy of the template from the current SOC report and verified internal evidence. Leave the reusable asset unchanged.
- **Review one section or assess an existing review:** Work only on that section or review point. Preserve unrelated results. Respect a user-specified output format, location or supplied template.

If no current report is available, create the requested template or complete only supported preparatory fields. Ask for the report when necessary to perform the actual review. Do not imply that a template is a completed review.

Read [review-schema.md](references/review-schema.md) before completing a review or rebuilding the template. Read [source-guide.md](references/source-guide.md) when retrieving prior reviews, OD controls or authoritative guidance.

## 1. Establish scope and inputs

Identify the provider, actual Opendoor service usage, review year, fiscal year-end, SOX process and intended reliance period from supplied or verified records. Obtain, as applicable:

- Complete current SOC report, including the independent auditor's report, system description, tests, exceptions and CUECs.
- Same-system FY24 review, OD control documents and other key procedures as the preferred historical mapping reference; inspect more recent reviews when available for intervening changes.
- Current risk-control matrix, control owners, relevant procedures and evidence of operation.
- Bridge letter, gap-period evidence, provider responses, remediation evidence, relevant subservice reports and prior open issues.

Do not infer owners, dates, control IDs or sign-offs from a SOC report. Separate provider facts, provider management representations, internal confirmations and reviewer judgments.

Use the available Google Drive capability for authorized file retrieval, the PDF capability for report extraction and page inspection, and the spreadsheet capability for workbook creation or editing. Follow their current instructions. Record inaccessible files precisely and continue with useful supported work.

## 2. Verify report identity, opinion and coverage

Read the complete report structure. Find information by headings and content, not assumed Section III/IV labels or fixed page numbers.

- Verify the report type, exact title, legal entity, services, locations, period, auditor and signed report date.
- Record the opinion using the report's terminology. Assess qualifications, limitations and excluded or untested controls against Opendoor's intended reliance.
- Map relevant control objectives and tests to Opendoor risks, controls and financial statement assertions. Consider test nature, timing, extent and results.
- For SOC 2, explain how the selected controls support specific ICFR risks and identify evidence limitations. Do not automatically substitute SOC 2 for SOC 1.
- For Type 1, identify the lack of period-based operating-effectiveness evidence and any additional work needed.
- Compare coverage with the actual reliance period and year-end assessment. Identify gaps at the beginning, within and after the report period. Do not invent a universal minimum report duration or maximum bridge period.
- Record bridge dates, signer, representations and limitations. Treat the letter as provider management evidence, not an extension of the service auditor's testing or opinion. Assess whether additional procedures are needed and document their results before concluding coverage is adequate.

## 3. Document exceptions and Opendoor impact

Reconcile all reported exceptions to the exception records, including exceptions judged irrelevant with the reason. For each, record exact control IDs and page references, auditor test results, population/sample/deviation counts if provided, timing, root cause, management response, remediation status and verification.

Evaluate actual Opendoor usage, affected risks and assertions, exposure during the reliance period, possible financial impact, and compensating controls with their operating evidence. Challenge management responses where evidence is absent or inconsistent. Do not close an issue based only on a promised remediation or an unmodified overall opinion.

State essential follow-ups concisely in the relevant evaluation or conclusion cell. Include confirmed owners, due dates and closure evidence when available; mark unknowns explicitly without repeating the same missing-evidence caveat on every row. Emphasize critical findings. Use sequential finding IDs and a detailed action register only when requested or needed to track a material issue.

Assess potential Opendoor deficiency severity through the applicable SOX methodology: likelihood, potential misstatement magnitude, qualitative factors, aggregation and the precision and operation of compensating controls. Do not equate a vendor exception, qualification, carve-out or Low/Medium/High risk rating with an Opendoor CD, SD or MW. Do not infer low severity solely because no misstatement is known. Flag insufficient support for a formal human evaluation.

## 4. Map every CUEC

Extract the complete current CUEC list, preserving the wording and source pages. Reconcile the number of requirements to the mapping and account for requirements in multiple report sections.

For each CUEC:

1. Assess applicability to the service Opendoor actually uses and the relevant ICFR risk. Explain any not-applicable decision.
2. Retrieve the **same-system FY24** OD control or other key procedure and cite its document and worksheet/cell or page location.
3. Compare the current CUEC with the FY24 requirement. Identify new, changed and removed requirements; do not carry mappings across unrelated systems.
4. Confirm current control IDs, procedure wording, owners and current-period evidence. Identify control/procedure changes even when the user expects limited change.
5. Explain how the control or key procedure addresses the requirement. Record operation/testing evidence, gaps, specific recommendations and the owner's evaluation.

Keep the FY24 mapping distinct from the current validated mapping. A prior-year mapping is a starting point, not evidence of current operation. Accept a documented key procedure when it addresses the requirement; do not fabricate a formal SOX control ID. Do not exclude a requirement solely because it is not categorized as an ITGC.

## 5. Assess subservices and conclude

List all identified subservice organizations and the services they provide. Distinguish inclusive, carve-out or mixed treatment. Record relevant exclusions, complementary subservice organization controls, provider monitoring and management responses.

Assess relevant dependencies using the provider's tested controls, a subservice SOC review or other appropriate evidence. Identify any remaining scope or period gaps. Determine who performs applicable user responsibilities at each service layer; do not automatically assign the provider's CUECs to Opendoor. Document the owner's evaluation and follow-ups. Do not assume that every mentioned vendor is a subservice organization or that a carve-out itself is a deficiency.

Document prior issues, remediation, new services, migrations, incidents and significant changes during and after the report period through the review date. Then prepare the overall conclusion, specific reliance limits, Low/Medium/High risk rating with rationale, outstanding actions and any formal deficiency assessment reference. Use the approved methodology; do not invent materiality thresholds or rating criteria.

Keep preparer work distinct from process-owner evaluation and reviewer sign-off. AI may draft a proposed conclusion but must not fabricate human approval. Record additional approval only if the applicable process requires it. Do not send messages, share the review or contact Deloitte without explicit authorization.

## Final review point

Use this as an internal quality checklist. Check completeness, exact dates and IDs, source traceability, current mappings, gap-period support and consistency between detail and conclusion. Convey essential results in the existing conclusion and sign-off cells; do not add a separate checklist section by default. Verify:

- **What is checked:** Correct report and scope; all exceptions and CUECs; subservice and period evidence; supported conclusion and required sign-offs.
- **Risk if skipped:** Unsupported reliance, missed financial-reporting exposure, stale controls or unverified remediation.
- **What the human verifies:** Actual opinion and exception pages, relevant CUECs and current operating evidence, key judgments, unresolved items and sign-off evidence.
- **Decision:** Continue when evidence and required review support the conclusion; revise for correctable gaps; stop the reliance conclusion and escalate when critical evidence is unavailable or contradictory. Still deliver useful completed work and identified gaps.

Do not stop the entire task for routine missing information. Use `Not provided — [specific evidence needed]`, `Pending — [specific evidence needed]` or `Not applicable — [reason]`. State “No exceptions identified” only after inspecting the complete relevant tests. Do not leave a completed review section blank.

## Deliver the file

Default to **one native Google Sheets spreadsheet**, with one review tab, using the bundled template adapted from FY-25 NS-SOC Review file.xlsx. Preserve its section order, labels and side-by-side columns. Keep exceptions, CUECs and subservices as rows in their respective sections; do not expand each field into a separate vertical record or create extra tabs. Deliver Excel only when the user explicitly requests it. Follow the active Spreadsheets and Google Sheets skills: prepare and validate the local workbook when required, then import it with native Google Sheets conversion. Treat the local Excel file as an intermediate, not the default deliverable. For a conversion request, reuse the completed review without redoing or changing its conclusions.

Locate fields by their labels, not fixed row numbers after inserting records. Insert enough rows or duplicate exception records to capture the complete population; extend tables, validation and conditional formatting, and remove unused placeholders from completed reviews. Verify the native destination has one tab and preserves the template layout, complete content, exact dates, editable fields and source references after conversion. Follow the Google Sheets skill for destination placement and visual checks. Do not change sharing permissions without authorization. If native creation is blocked, explain the specific limitation rather than presenting Excel as the requested Google Sheet.

For a template-only request, retain placeholders and Pending statuses. For a completed review, replace each placeholder with supported facts, analysis or an explicit missing/not-applicable status. Cite every report-based finding with document identity and printed page; add PDF page when different. Use internal locators for control workpapers instead of invented SOC page numbers.

Retain the report, relevant evidence, final review version and sign-offs in the approved location. Follow current file-saving instructions for the output. Keep confidential reports in authorized environments; do not store full SOC reports, credentials, employee data or completed confidential reviews in this skill.

Return the verified Google Sheets link with a short statement of what was completed and a concise list of unresolved items the user should personally verify. Do not include the intermediate Excel link unless requested. For an explicit Excel request, return that file instead. Do not reproduce the entire workbook in chat or expand into unrelated weekly planning.
