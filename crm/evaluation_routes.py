from datetime import datetime, timezone
from uuid import UUID,uuid4
from flask import jsonify, request
from evaluation_runner import evaluate_one, pricing_for
from followup_agent import MODEL_DEFAULT
from evaluation_fixtures import RULES
import os
from prompt_registry import active_prompts,use_prompts

RESOURCES={'evaluation_scenarios','evaluation_rules','evaluation_runs','evaluation_check_results'}

def register(app, db, limiter):
    def storage(resource,method='GET',data=None,record_id=None,extra_params=None):
        # The evaluator receives this closure, which cannot touch CRM entities.
        if resource not in RESOURCES:raise RuntimeError('Evaluation storage cannot access production CRM resources.')
        return db(resource,method,data,record_id,extra_params)

    @app.get('/api/evaluations')
    def evaluation_data():
        scenarios=storage('evaluation_scenarios',extra_params={'order':'scenario_number.asc'})
        rules=storage('evaluation_rules',extra_params={'order':'position.asc'})
        runs=storage('evaluation_runs',extra_params={'limit':100})
        results=[]
        if runs:
            ids=','.join(r['id'] for r in runs)
            for offset in range(0,10000,1000):
                page=storage('evaluation_check_results',extra_params={'run_id':'in.('+ids+')','limit':1000,'offset':offset})
                results.extend(page)
                if len(page)<1000:break
        return jsonify(scenarios=scenarios,rules=rules,runs=runs,checks=results,history_limit=100)

    @app.post('/api/evaluations/run')
    @limiter.limit('6 per minute')
    def run_evaluation():
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict):return jsonify(error='Select a scenario.'),400
        try:UUID(payload.get('scenario_id',''))
        except (ValueError,TypeError,AttributeError):return jsonify(error='Select a valid scenario.'),400
        scenarios=storage('evaluation_scenarios',record_id=payload['scenario_id'])
        if not scenarios:return jsonify(error='Scenario not found.'),404
        scenario=scenarios[0]
        rules=storage('evaluation_rules',extra_params={'scenario_id':'eq.'+scenario['id'],'order':'position.asc'})
        required={r[0] for r in RULES[scenario['scenario_number']]}
        if {r['rule_key'] for r in rules}!=required:return jsonify(error='Scenario rules are incomplete; no run started.'),409
        model=os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT)
        # No live CRM db handle is passed to the agent; only evaluation storage and fixtures.
        with use_prompts(active_prompts(db)):
            result=evaluate_one(scenario,rules,storage,str(uuid4()),pricing_for(model))
        return jsonify(run=result)

    @app.patch('/api/evaluations/rules/<rule_id>')
    def edit_rule(rule_id):
        try:UUID(rule_id)
        except ValueError:return jsonify(error='Invalid rule ID.'),400
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict) or set(payload)!={'description','expected'}:return jsonify(error='Provide a description and expected JSON value.'),400
        if not isinstance(payload['description'],str) or not 1<=len(payload['description'].strip())<=1000:return jsonify(error='Description must be 1–1000 characters.'),400
        rows=storage('evaluation_rules',record_id=rule_id)
        if not rows:return jsonify(error='Rule not found.'),404
        current=rows[0]['expected'];expected=payload['expected']
        if type(expected) is not type(current):return jsonify(error='Keep the expected value’s original JSON type.'),400
        if isinstance(expected,str) and len(expected)>250:return jsonify(error='Expected value is too long.'),400
        if type(expected) is int and not 0<=expected<=100:return jsonify(error='Expected count must be between 0 and 100.'),400
        updated=storage('evaluation_rules','PATCH',{'description':payload['description'].strip(),'expected':expected,'updated_at':datetime.now(timezone.utc).isoformat()},rule_id)
        return jsonify(rule=updated[0])
