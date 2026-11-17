import os
from datetime import datetime, timezone
from uuid import UUID
from flask import jsonify, request
from followup_agent import run, generate
from prompt_registry import active_prompts,use_prompts,prompt
from evaluation_telemetry import collect_calls
from model_client import metadata
import time

def register(app, db, rpc=None):
    @app.get('/api/followups')
    def list_followups():
        drafts=db('followups')
        for row in drafts:
            safe=row.get('final_suggestion') or (row.get('guardrail_result') or {}).get('safe_suggestion') or {}
            row['body']=safe.get('body',safe.get('summary',''))
            row['subject']=safe.get('subject','Meeting update' if row.get('workflow_type')=='meeting_update' else 'Unverified AI suggestion')
            row['next_action']=safe.get('next_action','Check the linked information before using this suggestion.')
        return jsonify(drafts=drafts,reviews=db('suggestion_reviews'),configured=bool(os.getenv('OPENROUTER_API_KEY')),schedule='Daily at 8:00 AM America/Los_Angeles',stall_days=int(os.getenv('STALL_DAYS','7')))

    @app.post('/api/followups/run')
    def run_followups():
        with use_prompts(active_prompts(db)):return jsonify(run(db))

    @app.post('/api/followups/<draft_id>/review')
    def review_followup(draft_id):
        from feedback_routes import review_suggestion
        return review_suggestion(db,rpc,draft_id)

    @app.post('/api/activity/<kind>/<record_id>')
    def log_activity(kind,record_id):
        if kind not in ('contacts','deals'):return jsonify(error='Invalid entity.'),400
        try:UUID(record_id)
        except ValueError:return jsonify(error='Invalid ID.'),400
        rows=db(kind,'PATCH',{'last_activity_at':datetime.now(timezone.utc).isoformat(),'suggested_next_action':None},record_id)
        if not rows:return jsonify(error='Record missing.'),404
        return jsonify(record=rows[0])

    @app.post('/api/followups/<draft_id>/retry')
    def retry_followup(draft_id):
        try:UUID(draft_id)
        except ValueError:return jsonify(error='Invalid ID.'),400
        rows=db('followups',record_id=draft_id)
        if not rows or rows[0]['status']!='failed':return jsonify(error='Only failed drafts can be retried.'),409
        row=rows[0]
        claimed=db('followups','PATCH',{'status':'generating','error':None},draft_id,extra_params={'status':'eq.failed'})
        if not claimed:return jsonify(error='Already retrying.'),409
        if row.get('original_suggestion'):
            db('followups','PATCH',{'status':'pending','error':None},draft_id)
            return jsonify(ok=True)
        from guardrail_service import linked_context,record_assessment
        from guardrails import assess,prepare,GuardedSuggestion,AgentStore
        context=linked_context(db,row);workflow=row.get('workflow_type','followup')
        started=time.perf_counter();calls=[]
        with use_prompts(active_prompts(db)):
            try:
                preflight=assess(context,None,workflow)
                with collect_calls() as calls:
                    if not preflight['can_generate']:draft=GuardedSuggestion(preflight)
                    elif workflow=='meeting_update':
                        from meeting_updates import generate as generate_meeting
                        draft=generate_meeting(context)
                    else:draft=generate(context)
                if not isinstance(draft,GuardedSuggestion):draft=prepare(context,draft,workflow)
                guarded=draft.assessment;guarded['audit_event_ids']=record_assessment(db,guarded,draft_id)
                values={'original_suggestion':guarded['proposed_output'],'guardrail_result':guarded,'body':draft.get('summary',draft.get('body','')),'next_action':draft['next_action']}
                if workflow=='followup':values['subject']=draft['subject']
                db('followups','PATCH',{**values,'status':'pending',**metadata(calls,started,workflow)},draft_id)
                return jsonify(ok=True)
            except Exception as error:
                record_assessment(db,assess(context,{'model_error':str(error)},workflow),draft_id)
                db('followups','PATCH',{'status':'failed','error':str(error)[:500],**metadata(calls,started,workflow)},draft_id)
                raise RuntimeError(str(error))
