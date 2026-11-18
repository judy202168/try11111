"""Deterministic SOX coaching tools. Outputs are drafts for human review."""
import re
from flask import Blueprint, jsonify, request

SOURCES = {
    "sec_management": {"title": "SEC management guidance on ICFR", "url": "https://www.sec.gov/files/rules/interp/2007/33-8810.pdf", "status": "Effective June 27, 2007"},
    "pcaob_alert_11": {"title": "PCAOB Staff Audit Practice Alert No. 11", "url": "https://pcaobus.org/Standards/QandA/10-24-2013_SAPA_11.pdf", "status": "Issued October 24, 2013; staff alert, not a Board rule"},
    "as1105": {"title": "PCAOB AS 1105 — Audit Evidence", "url": "https://pcaobus.org/oversight/standards/auditing-standards/details/AS1105", "status": "Current PCAOB standard page checked November 18, 2026"},
    "as2201": {"title": "PCAOB AS 2201 — Audit of ICFR", "url": "https://pcaobus.org/oversight/standards/auditing-standards/details/AS2201", "status": "Current page checked November 18, 2026; amendments to .09 and new .99 become effective December 15, 2026"},
}


def clean(value, key, limit=30000):
    result = value.get(key, "")
    if not isinstance(result, str) or len(result) > limit:
        raise ValueError(f"{key} must be text, at most {limit:,} characters.")
    return result.strip()


def payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("Send a JSON object.")
    return value


def missing(prepared, labels):
    return [labels[key] for key, value in prepared.items() if key in labels and not value]


def lines(text):
    return [line.strip(" \t-*•") for line in text.splitlines() if line.strip(" \t-*•")]


def register_practice_agents(app):
    bp = Blueprint("practice_agents", __name__, url_prefix="/api/practice-agents")

    @bp.post("/control-design")
    def control_design():
        value = payload()
        prepared = {key: clean(value, key) for key in ("risk", "control", "performer", "precision", "exceptions")}
        labels = {"risk": "financial-reporting risk", "control": "control activity", "performer": "performer and reviewer", "precision": "precision, thresholds, and evidence", "exceptions": "exception identification and resolution"}
        absent = missing(prepared, labels)
        explicit = []
        combined = " ".join(prepared.values()).lower()
        for phrase, finding in (("no review", "No review or approval is described."), ("no threshold", "The control explicitly has no threshold or investigation criterion."), ("exceptions are not", "Exceptions are explicitly described as unresolved."), ("no exception", "No exception-resolution process is described.")):
            if phrase in combined:
                explicit.append(finding)
        return jsonify(agent="Control Design Coach", missing_details=absent, design_concerns=explicit,
                       assessment="Potential design concerns were identified from explicit statements." if explicit else "No design problem is concluded from the supplied information. Missing details remain questions, not failures.",
                       follow_up=[f"Document the {name}." for name in absent], sources=[SOURCES["sec_management"], SOURCES["pcaob_alert_11"]],
                       boundary="PCAOB materials apply to auditors and are used here only as design references. Human review is required." )

    @bp.post("/evidence-readiness")
    def evidence_readiness():
        value = payload(); requested = lines(clean(value, "requested_items")); supplied = lines(clean(value, "supplied_material"))
        if not requested:
            raise ValueError("List at least one requested item, one per line.")
        if not supplied:
            raise ValueError("Describe the supplied material with filenames, tabs, pages, or other references.")
        results = []
        for item in requested[:200]:
            terms = {x for x in re.findall(r"[a-z0-9]{3,}", item.lower()) if x not in {"the", "and", "for", "with"}}
            ranked = sorted(((len(terms & set(re.findall(r"[a-z0-9]{3,}", material.lower()))), material) for material in supplied), reverse=True)
            score, reference = ranked[0]
            results.append({"request": item, "status": "Potential support found" if score else "Not found in supplied index", "supporting_reference": reference if score else "", "follow_up": "Verify relevance, reliability, period, and completeness." if score else "Request the item or clarify where it is located; this does not mean the control failed."})
        return jsonify(agent="Evidence Readiness Checker", items=results, conflicts=[], sources=[SOURCES["as1105"]],
                       boundary="This is an evidence-index comparison, not an audit conclusion. 'Not found' does not mean the control failed.")

    @bp.post("/scoping")
    def scoping():
        value = payload()
        prepared = {key: clean(value, key) for key in ("process", "systems", "interfaces", "reports", "controls", "unknowns")}
        if not prepared["process"]:
            raise ValueError("Describe the financial process being explored.")
        nodes = [{"type": key.title(), "details": prepared[key] or "Unknown — follow up required"} for key in ("process", "systems", "interfaces", "reports", "controls")]
        unknown = [key.title() for key in ("systems", "interfaces", "reports", "controls") if not prepared[key]] + lines(prepared["unknowns"])
        return jsonify(agent="SOX Scoping Explorer", trace=nodes, unknown_dependencies=unknown,
                       potential_relevance="The described components may affect financial reporting, but inclusion in scope requires a documented risk assessment and human decision.",
                       sources=[SOURCES["sec_management"], SOURCES["as2201"]],
                       boundary="PCAOB standards apply to auditors and are used only as design references. A person makes the final scope decision.")

    app.register_blueprint(bp)
