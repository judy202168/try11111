from collections import Counter
from datetime import datetime,timezone
import time
from flask import jsonify,request
from guardrails import PolicyBlocked,POLICY_VERSION,G1,G2,assess
from guardrail_service import check_suggestion,blocked_action,audit
from guardrail_cases import cases,execute_case
from feedback_reporting import all_rows
from feedback_routes import FeedbackError,identifier,reviewer
from evaluation_runner import version


def register(app,db,limiter):
    @app.errorhandler(PolicyBlocked)
    def policy_error(error):return jsonify(error=error.result['reason'],guardrail=error.result),403

    @app.post('/api/guardrails/action')
    @limiter.limit('30 per minute')
    def attempt_action():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict) or data.get('action') not in ('send_email','create_external_record','delete_crm'):raise FeedbackError('Choose a supported blocked-action demonstration.')
        result=blocked_action(db,data['action'],data.get('proposed_output') or {},context=data.get('input_context') or {},source='evaluation')
        return jsonify(result=result,message=result['reason'])

    @app.post('/api/guardrails/check/<suggestion_id>')
    def inspect_suggestion(suggestion_id):
        rows=db('followups',record_id=identifier(suggestion_id))
        if not rows:raise FeedbackError('Suggestion not found.',404)
        return jsonify(guardrail=check_suggestion(db,rows[0]))

    @app.get('/api/guardrails')
    def guardrail_data():
        source=request.args.get('source','production')
        if source not in ('production','evaluation','all'):raise FeedbackError('Choose production, evaluation, or all checks.')
        events=all_rows(db,'guardrail_events',{'source':'eq.'+source} if source!='all' else None)
        decisions=all_rows(db,'suggestion_reviews');by_suggestion={r['suggestion_id']:r for r in decisions}
        for event in events:
            decision=by_suggestion.get(event.get('suggestion_id'))
            event['reviewer_decision']=decision
            event['latest_final_action']=('Rejected; no external change.' if decision['action']=='reject' else 'Human-reviewed content stored; no message or external update performed.') if decision else event['final_action']
        verdicts=Counter(e['verdict'] for e in events)
        blocks=Counter(e['guardrail'] for e in events if e['verdict']=='blocked')
        passed=sum(e['enforced'] and e['passed'] and e['external_changes']==0 for e in events)
        return jsonify(policy_version=POLICY_VERSION,source=source,total=len(events),allowed=verdicts['allowed'],blocked=verdicts['blocked'],review=verdicts['review'],pass_rate=round(100*passed/len(events),1) if events else None,
                       blocks_by_type=dict(blocks),invention_attempts=sum(len(e['invention_attempts']) for e in events),unapproved_external_attempts=sum(e['guardrail']==G1 and e['verdict']=='blocked' for e in events),
                       recent_failures=[e for e in events if not e['passed'] or not e['enforced'] or e['external_changes']!=0][:30],events=events[:100],cases=db('guardrail_test_cases',extra_params={'order':'case_number.asc'}),runs=db('guardrail_test_runs',extra_params={'limit':100}))

    @app.post('/api/guardrails/evaluate')
    @limiter.limit('12 per minute')
    def evaluate_guardrails():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):raise FeedbackError('Choose valid evaluation options.')
        batch_id=data.get('batch_id');batch=None
        if batch_id:
            reviewer(db,admin=True);batch_id=identifier(batch_id);rows=db('prompt_evaluation_batches',record_id=batch_id)
            if not rows or rows[0]['agent_version']!=version():raise FeedbackError('Start a new evaluation batch for the current code.',409)
            batch=rows[0]
        selected=[c for c in cases() if not data.get('case_id') or c['id']==data['case_id']]
        if not selected:raise FeedbackError('Choose an existing guardrail case.')
        if batch and len(selected)!=8:raise FeedbackError('Release evaluation requires all eight guardrail cases.')
        runs=[]
        for case in selected:
            started=time.perf_counter();actual,passed,failure=execute_case(case)
            actual['passed']=passed
            event_id=audit(db,case['input_context'],case['proposed_output'],actual,case['expected_behavior']['guardrail'],source='evaluation',test_case_id=case['id'])
            row=db('guardrail_test_runs','POST',{'case_id':case['id'],'event_id':event_id,'batch_id':batch_id,'input_context':case['input_context'],'proposed_output':case['proposed_output'],'expected_behavior':case['expected_behavior'],'actual_behavior':actual,'guardrail':case['expected_behavior']['guardrail'],'passed':passed,'failure_explanation':failure,'response_time_ms':round((time.perf_counter()-started)*1000),'agent_version':version(),'policy_version':POLICY_VERSION})[0]
            runs.append(row)
        if batch:
            business=db('evaluation_runs',extra_params={'batch_id':'eq.'+batch_id})
            status='passed' if len(business)==3 and all(r['status']=='passed' for r in business) and all(r['passed'] for r in runs) else 'failed'
            db('prompt_evaluation_batches','PATCH',{'status':status,'completed_at':datetime.now(timezone.utc).isoformat()},batch_id)
        return jsonify(runs=runs,passed=sum(r['passed'] for r in runs),total=len(runs))
