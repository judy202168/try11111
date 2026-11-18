"""Streamlined SOX checklist supplied by the workspace owner on 2026-11-18."""


def item(number, control_id, title, question, evidence, guidance=""):
    return {"id": f"sox-implementation-{number}", "number": number, "control_id": control_id,
            "title": title, "question": question, "evidence_required": evidence, "guidance": guidance,
            "source_row": number, "source_cell": f"Item {number}", "evidence_cell": f"Evidence {number}",
            "kind": "requirement", "subchecks": []}


TEMPLATE = {
    "version": "sox-key-checklist-2026-11-18",
    "name": "System Implementation: Key SOX Checklist",
    "source_filename": "Workspace owner-provided checklist",
    "source_sheet": "System Implementation",
    "source_title": "System Implementation: Key SOX Checklist",
    "intro": "Use this checklist for systems that affect financial reporting.",
    "evidence_note": "Save test results, reconciliations, deployment records, and approvals showing who approved and when. For each item, track status, owner, and an evidence link; explain any N/A.",
    "sections": [
        {"id": "SOX.IMP.01", "title": "Approve the scope", "key": True, "source_cell": "Item 1"},
        {"id": "SOX.IMP.02", "title": "Test before go-live", "key": True, "source_cell": "Item 2"},
        {"id": "SOX.IMP.03", "title": "Validate migrated data", "key": True, "source_cell": "Item 3"},
        {"id": "SOX.IMP.04", "title": "Approve and restrict access", "key": True, "source_cell": "Item 4"},
        {"id": "SOX.IMP.05", "title": "Separate development and deployment", "key": True, "source_cell": "Item 5"},
        {"id": "SOX.IMP.06", "title": "Authorize go-live", "key": True, "source_cell": "Item 6"},
    ],
    "items": [
        item(1, "SOX.IMP.01", "Approve the scope",
             "Document the project scope, financial reporting requirements, responsible owners, and business approval before work begins.",
             "Approved scope or project charter showing financial reporting requirements, responsible owners, business approver, and approval date."),
        item(2, "SOX.IMP.02", "Test before go-live",
             "Test key configurations, approval workflows, integrations, and financial reports in a non-production environment. Obtain business owner sign-off on user acceptance testing (UAT). Resolve significant issues or document approved exceptions before go-live.",
             "Non-production test results; UAT results and business-owner sign-off; resolved defect log or documented and approved exceptions."),
        item(3, "SOX.IMP.03", "Validate migrated data",
             "If migrating data, reconcile record counts and key balances, validate data accuracy, and obtain business owner approval before go-live.",
             "Record-count and key-balance reconciliations, data-accuracy validation, exception resolution, and dated business-owner approval.",
             "If no data was migrated, select Not applicable and explain why."),
        item(4, "SOX.IMP.04", "Approve and restrict access",
             "Define roles and permissions, address conflicting duties, and approve the initial user access list. Limit administrator access and remove temporary implementation privileges after go-live.",
             "Approved role and permission design, segregation-of-duties review, initial user access approval, administrator listing, and evidence temporary access was removed."),
        item(5, "SOX.IMP.05", "Separate development and deployment",
             "Separate development or configuration from production deployment and independent approval. If separation is incomplete, maintain a complete deployment log and obtain independent technical and business review of every production deployment.",
             "Role or responsibility matrix and deployment approvals. If separation is incomplete: complete deployment log plus independent technical and business review for every production deployment.",
             "Document the compensating review when full separation is not possible."),
        item(6, "SOX.IMP.06", "Authorize go-live",
             "Obtain technical and business approval before go-live, confirming testing, data validation, access readiness, and an approved rollback plan.",
             "Dated technical and business go-live approvals referencing testing, data validation, access readiness, and the approved rollback plan."),
    ],
}
