"""Local, deterministic accounting workflows grounded in synchronized repositories."""
import csv
import io
import re
from datetime import date
from decimal import Decimal, InvalidOperation


def _sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def review_contract(value, source):
    text = value["contract_text"]
    lower = text.lower()
    fields = {key: value.get(key, "") for key in ("contract_id", "customer", "start_date", "end_date", "currency", "consideration")}
    checks = [
        ("Approval and commitment", ("approve", "signed", "signature", "commit"), "Identify evidence that both parties approved and are committed."),
        ("Each party’s rights", ("rights", "shall provide", "deliver", "service", "license"), "Document the enforceable rights of each party."),
        ("Payment terms", ("payment", "pay", "invoice", "fee", "price", "consideration"), "Document payment timing, amounts, and refund or credit terms."),
        ("Commercial substance", ("commercial substance", "business purpose"), "Document why the arrangement changes future cash flows."),
        ("Collectibility", ("collectib", "credit", "ability to pay"), "Document the collectibility assessment."),
    ]
    criteria = []
    for name, terms, gap in checks:
        evidence = [s for s in _sentences(text) if any(term in s.lower() for term in terms)][:2]
        criteria.append({"name": name, "status": "Potential evidence found" if evidence else "Needs review", "evidence": evidence, "question": "" if evidence else gap})
    obligation_terms = ("license", "subscription", "support", "implementation", "training", "service", "maintenance", "delivery", "hosting")
    obligations = []
    for sentence in _sentences(text):
        if any(term in sentence.lower() for term in obligation_terms) and sentence not in obligations:
            obligations.append(sentence[:500])
    risk_terms = {
        "Variable consideration": ("bonus", "rebate", "refund", "penalty", "usage", "variable"),
        "Contract modification": ("renewal", "amend", "modify", "change order"),
        "Financing component": ("interest", "financing", "advance payment", "more than one year"),
        "Termination or refund rights": ("terminate", "cancel", "refund", "return"),
        "Principal-versus-agent considerations": ("reseller", "third party", "commission", "agent"),
    }
    risks = [{"topic": name, "status": "Review indicated", "matches": [term for term in terms if term in lower]} for name, terms in risk_terms.items() if any(term in lower for term in terms)]
    missing_fields = [key.replace("_", " ").title() for key, val in fields.items() if not val]
    task = value["task"]
    if task == "Prepare contract intake":
        focus = "Intake completeness and items to resolve before accounting setup."
    elif task == "Review control and auditability":
        focus = "Evidence, approval, change control, traceability, and review checkpoints."
    else:
        focus = "Preliminary ASC 606 / IFRS 15 contract review and open accounting questions."
    return {
        "workflow": "Revenue Accounting Engine",
        "task": task,
        "focus": focus,
        "contract": fields,
        "summary": f"Reviewed {len(text):,} characters. Found {len(obligations)} potential obligation-related clauses and {len(risks)} topic flags.",
        "missing_fields": missing_fields,
        "contract_criteria": criteria,
        "potential_obligation_clauses": obligations[:12],
        "topic_flags": risks,
        "control_questions": [
            "Who prepared and who independently reviewed the accounting assessment?",
            "Which contract version and amendments support the conclusion?",
            "How will performance, billing, estimates, and modifications be evidenced and approved?",
            "Can each schedule amount and journal entry be traced to contract inputs and approved rules?",
        ],
        "conclusion": "Preliminary review only. No accounting conclusion, journal entry, or approval has been issued.",
        "repository": {k: source[k] for k in ("name", "url", "license", "commit", "committed_at")},
        "repository_files_used": ["README.md", "docs/guides/user-guide.md", "docs/release/LIMITS-1.0.md"],
    }


def _parse_table(text):
    if not text.strip():
        raise ValueError("Paste CSV or TSV data to analyze.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("The dataset needs a header row.")
    rows = []
    for index, row in enumerate(reader):
        if index >= 5000:
            break
        rows.append({str(k or "").strip(): str(v or "").strip() for k, v in row.items()})
    if not rows:
        raise ValueError("The dataset has no data rows.")
    return [str(h).strip() for h in reader.fieldnames], rows


def analyze_sec_data(value, source):
    headers, rows = _parse_table(value["dataset_text"])
    task, query = value["task"], value.get("query", "").strip()
    result = {"workflow": "SEC XBRL Data Analysis", "task": task, "row_count_analyzed": len(rows), "columns": headers}
    if task == "Summarize dataset":
        result["column_profile"] = [{"column": h, "nonblank": sum(bool(r.get(h)) for r in rows), "unique": len({r.get(h) for r in rows if r.get(h)})} for h in headers[:50]]
    elif task == "Find narrative facts":
        if not query:
            raise ValueError("Enter text to find.")
        matches = [r for r in rows if query.casefold() in " ".join(r.values()).casefold()]
        result["query"] = query
        result["match_count"] = len(matches)
        result["matches"] = matches[:50]
    elif task == "Analyze numeric column":
        if query not in headers:
            raise ValueError("For numeric analysis, enter a column name exactly as shown in the header.")
        numbers = []
        for row in rows:
            raw = row.get(query, "").replace(",", "").replace("$", "").strip()
            try:
                if raw:
                    numbers.append(Decimal(raw))
            except InvalidOperation:
                continue
        if not numbers:
            raise ValueError("No numeric values were found in that column.")
        result["column"] = query
        result["numeric_summary"] = {"count": len(numbers), "minimum": str(min(numbers)), "maximum": str(max(numbers)), "mean": str(sum(numbers) / len(numbers))}
    else:
        raise ValueError("Choose a valid SEC analysis task.")
    result["repository"] = {k: source[k] for k in ("name", "url", "license", "commit", "committed_at")}
    result["repository_files_used"] = ["examples/1_Read_And_Analyze_Submissions.ipynb", "examples/3_Find_Numeric_Facts.ipynb", "examples/4_Find_Narrative_Text_Facts.ipynb"]
    result["conclusion"] = "Exploratory analysis only. Verify results against the complete SEC filing and relevant metadata."
    result["run_date"] = date.today().isoformat()
    return result
