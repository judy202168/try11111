"""Flask routes for repository-backed accounting agents."""
import uuid
from flask import Blueprint, jsonify, request
from .repos import SOURCES, sync_source
from .review import review_contract, analyze_sec_data


def register_accounting_agents(app, read_store, write_store, lock, activity, repo_root, now):
    bp = Blueprint("accounting_agents", __name__, url_prefix="/api/accounting-agents")

    def clean(value, key, limit, required=False):
        result = value.get(key, "")
        if not isinstance(result, str) or len(result) > limit:
            raise ValueError(f"{key} must be text, at most {limit:,} characters.")
        result = result.strip()
        if required and not result:
            raise ValueError(f"{key} is required.")
        return result

    def save_run(kind, task, result):
        run = {"id": str(uuid.uuid4()), "kind": kind, "task": task, "created_at": now(), "result": result}
        with lock:
            data = read_store()
            data.setdefault("accounting_agent_runs", []).insert(0, run)
            data["accounting_agent_runs"] = data["accounting_agent_runs"][:100]
            activity(data, "Accounting agent · " + task.lower(), result.get("summary", task)[:160])
            write_store(data)
        return run

    @bp.get("/status")
    def status():
        with lock:
            runs = read_store().get("accounting_agent_runs", [])
        return jsonify(sources=SOURCES, recent_runs=[{"id": r["id"], "kind": r["kind"], "task": r["task"], "created_at": r["created_at"]} for r in runs[:10]])

    @bp.post("/contract-review")
    def contract_review():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("Send a JSON object.")
        task = clean(value, "task", 80, True)
        if task not in ("Review revenue contract", "Prepare contract intake", "Review control and auditability"):
            raise ValueError("Choose a valid contract task.")
        prepared = {"task": task, "contract_text": clean(value, "contract_text", 100000, True)}
        for key, limit in (("contract_id", 120), ("customer", 200), ("start_date", 20), ("end_date", 20), ("currency", 10), ("consideration", 100)):
            prepared[key] = clean(value, key, limit)
        source = sync_source("revenue", repo_root)
        return jsonify(save_run("revenue", task, review_contract(prepared, source))), 201

    @bp.post("/sec-analysis")
    def sec_analysis():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("Send a JSON object.")
        task = clean(value, "task", 80, True)
        if task not in ("Summarize dataset", "Find narrative facts", "Analyze numeric column"):
            raise ValueError("Choose a valid SEC analysis task.")
        prepared = {"task": task, "query": clean(value, "query", 300), "dataset_text": clean(value, "dataset_text", 1500000, True)}
        source = sync_source("sec", repo_root)
        return jsonify(save_run("sec", task, analyze_sec_data(prepared, source))), 201

    app.register_blueprint(bp)
