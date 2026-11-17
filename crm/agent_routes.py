import os
from datetime import datetime, timezone
from uuid import UUID
from flask import jsonify, request
from followup_agent import run, generate

def register(app, db):
    @app.get('/api/followups')
    def list_followups():
        return jsonify(drafts=db('followups'),configured=bool(os.getenv('OPENROUTER_API_KEY')),schedule='Daily at 8:00 AM America/Los_Angeles',stall_days=int(os.getenv('STALL_DAYS','7')))

    @app.post('/api/followups/run')
    def run_followups():
        return jsonify(run(db))

    @app.post('/api/followups/<draft_id>/review')
    def review_followup(draft_id):
        try: UUID(draft_id)
        except ValueError:return jsonify(error='Invalid draft ID.'),400
        payload=request.get_json(silent=True) or {}
        if not isinstance(payload,dict) or payload.get('decision') not in ('approved','rejected'):
            return jsonify(error='Choose approve or reject.'),400
        note=payload.get('note','')
        if not isinstance(note,str) or len(note)>1000:return jsonify(error='Review note too long.'),400
        # Atomic conditional update ensures a decision cannot overwrite a previous review.
        rows=db('followups','PATCH',{'status':payload['decision'],'reviewed_at':datetime.now(timezone.utc).isoformat(),'review_note':note},draft_id,extra_params={'status':'eq.pending'})
        if not rows:return jsonify(error='Draft was already reviewed or is not ready.'),409
        return jsonify(record=rows[0],message='Decision recorded. No email has been sent.')

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
        try:
            draft=generate(row['context'])
            db('followups','PATCH',{**draft,'status':'pending'},draft_id)
            db(row['entity_type'],'PATCH',{'suggested_next_action':draft['next_action']},row['entity_id'])
            return jsonify(ok=True)
        except Exception as error:
            db('followups','PATCH',{'status':'failed','error':str(error)[:500]},draft_id)
            raise RuntimeError(str(error))
