import os,re
from datetime import date,datetime,timezone,timedelta
from uuid import UUID,uuid4
from flask import jsonify,request,session
from werkzeug.security import check_password_hash,generate_password_hash
from feedback_constants import REASONS,HIGH_RISK
from feedback_reporting import all_rows,report,weekly_summary
from model_client import validate_suggestion,MODEL_DEFAULT
from prompt_registry import active_prompts,use_prompts
from evaluation_fixtures import scenarios as canonical_scenarios,rules as canonical_rules
from evaluation_runner import evaluate_one,pricing_for,version

class FeedbackError(Exception):
    def __init__(self,message,status=400):self.message=message;self.status=status

def identifier(value):
    try:return str(UUID(str(value)))
    except (ValueError,TypeError):raise FeedbackError('Invalid identifier.')

def reviewer(db,admin=False):
    identity=session.get('reviewer_id')
    rows=db('reviewers',record_id=identity) if identity else []
    if not rows or not rows[0]['active']:raise FeedbackError('Sign in with your personal reviewer account first.',401)
    if admin and rows[0]['role']!='admin':raise FeedbackError('An administrator must perform this action.',403)
    return rows[0]

def public_reviewer(row):return {k:row[k] for k in ('id','username','display_name','team','role','active')}

def review_suggestion(db,rpc,suggestion_id):
    actor=reviewer(db);identity=identifier(suggestion_id);payload=request.get_json(silent=True)
    if not isinstance(payload,dict):raise FeedbackError('Choose an action.')
    action=payload.get('action');reason=payload.get('reason');note=payload.get('note','')
    if action not in ('approve','reject','edit_approve'):raise FeedbackError('Choose Approve, Reject, or Edit and approve.')
    if action in ('reject','edit_approve') and reason not in REASONS:raise FeedbackError('Select one reason for rejecting or editing.')
    if action=='approve':reason=None
    if not isinstance(note,str) or len(note)>2000:raise FeedbackError('Reviewer note must be at most 2,000 characters.')
    rows=db('followups',record_id=identity)
    if not rows or rows[0]['status']!='pending':raise FeedbackError('Suggestion is no longer pending.',409)
    row=rows[0];final=None
    from guardrail_service import check_suggestion,record_assessment
    from guardrails import assess
    guarded=check_suggestion(db,row)
    if action!='reject' and not guarded['can_approve']:raise FeedbackError(guarded['reason']+' '+guarded['next_action'],409)
    if action=='edit_approve':
        try:final=validate_suggestion(payload.get('final_suggestion'),row['workflow_type'],row['context'].get('notes') if row['workflow_type']=='meeting_update' else None)
        except (ValueError,TypeError) as error:raise FeedbackError(str(error))
        human_check=assess(guarded['model_input'],final,row['workflow_type'])
        if human_check['invention_attempts']:
            record_assessment(db,human_check,identity)
            raise FeedbackError('The edited facts are not supported by the linked source. Confirm the source information and check again.',409)
        if row['workflow_type']=='meeting_update' and final['commitments']!=human_check['safe_suggestion']['commitments']:
            record_assessment(db,human_check,identity)
            raise FeedbackError('Commitment owners and dates must match explicit source evidence; unknown values must remain blank.',409)
        if final==guarded['safe_suggestion']:raise FeedbackError('Make an edit before choosing Edit and approve.')
    result=rpc('crm_record_suggestion_review',{'p_suggestion':identity,'p_reviewer':actor['id'],'p_action':action,'p_reason':reason,'p_note':note,'p_final':final})
    if result.get('error'):raise FeedbackError(result['error'],409)
    return jsonify(result)

def register(app,db,rpc,limiter):
    @app.errorhandler(FeedbackError)
    def feedback_error(error):return jsonify(error=error.message,code='REVIEWER_AUTH_REQUIRED' if error.status==401 else 'FEEDBACK_ERROR'),error.status

    @app.get('/api/reviewer')
    def reviewer_state():
        rows=all_rows(db,'reviewers');identity=session.get('reviewer_id');current=next((r for r in rows if r['id']==identity and r['active']),None)
        return jsonify(reviewer=public_reviewer(current) if current else None,bootstrap_available=not rows,reviewers=[public_reviewer(r) for r in rows],reasons=REASONS)

    @app.post('/api/reviewer/login')
    @limiter.limit('5 per minute')
    def reviewer_login():
        data=request.get_json(silent=True) or {}
        if not isinstance(data,dict) or not isinstance(data.get('username'),str) or not isinstance(data.get('password'),str):raise FeedbackError('Enter your reviewer username and password.')
        rows=db('reviewers',extra_params={'username':'eq.'+data['username'].strip().lower()})
        if not rows or not rows[0]['active'] or not check_password_hash(rows[0]['password_hash'],data['password']):raise FeedbackError('Incorrect reviewer credentials.',401)
        session['reviewer_id']=rows[0]['id'];return jsonify(reviewer=public_reviewer(rows[0]))

    @app.post('/api/reviewer/logout')
    def reviewer_logout():session.pop('reviewer_id',None);return jsonify(ok=True)

    @app.post('/api/reviewers')
    @limiter.limit('5 per minute')
    def create_reviewer():
        existing=db('reviewers',extra_params={'limit':1});bootstrap=not existing
        if not bootstrap:reviewer(db,admin=True)
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise FeedbackError('Enter reviewer details.')
        if any(not isinstance(data.get(k),str) for k in ('username','display_name','team','password')):raise FeedbackError('Enter all reviewer fields as text.')
        username=data.get('username','').strip().lower();name=data.get('display_name','').strip();team=data.get('team','').strip();password=data.get('password','')
        if not re.fullmatch(r'[a-z0-9._-]{3,64}',username) or not 1<=len(name)<=100 or not 1<=len(team)<=100 or not isinstance(password,str) or not 8<=len(password)<=256:raise FeedbackError('Use a 3–64 character username, a name and team, and a personal password of 8–256 characters.')
        if db('reviewers',extra_params={'username':'eq.'+username}):raise FeedbackError('That username already exists.',409)
        role='admin' if bootstrap else data.get('role','reviewer')
        if role not in ('admin','reviewer'):raise FeedbackError('Choose a valid reviewer role.')
        row=db('reviewers','POST',{'username':username,'display_name':name,'team':team,'password_hash':generate_password_hash(password,method='pbkdf2:sha256:600000'),'role':role,'bootstrap':bootstrap})[0]
        if bootstrap:session['reviewer_id']=row['id']
        return jsonify(reviewer=public_reviewer(row)),201

    @app.get('/api/feedback')
    def feedback_report():
        days=request.args.get('days','90')
        if days not in ('7','30','90','365'):raise FeedbackError('Choose a supported date range.')
        cutoff=(datetime.now(timezone.utc)-timedelta(days=int(days))).isoformat()
        rows=all_rows(db,'suggestion_reviews',{'reviewed_at':'gte.'+cutoff})
        options={key:sorted({r.get(key) or 'Unknown' for r in rows}) for key in ('workflow','team','model','prompt_label')}
        for key in options:
            chosen=request.args.get(key,'')
            if chosen:rows=[r for r in rows if (r.get(key) or 'Unknown')==chosen]
        data=report(rows);data['filter_options']=options;data.update(reviews=rows,reason_options=REASONS,high_risk_reasons=sorted(HIGH_RISK),days=int(days),summaries=db('weekly_quality_summaries',extra_params={'limit':30}))
        legacy=db('followups',extra_params={'status':'in.(approved,rejected)'})
        reviewed_ids={r['suggestion_id'] for r in all_rows(db,'suggestion_reviews')}
        data['legacy_decisions_excluded']=sum(r['id'] not in reviewed_ids for r in legacy)
        return jsonify(data)

    @app.post('/api/feedback/weekly-summary')
    def build_weekly_summary():
        actor=reviewer(db);return jsonify(summary=weekly_summary(db,actor['id']))

    @app.post('/api/meeting-updates')
    @limiter.limit('5 per minute')
    def meeting_update():
        actor=reviewer(db);data=request.get_json(silent=True)
        if not isinstance(data,dict):raise FeedbackError('Provide meeting details.')
        customer_id=identifier(data.get('customer_id'));opportunity_id=identifier(data['opportunity_id']) if data.get('opportunity_id') else None
        contacts=db('contacts',record_id=customer_id)
        if not contacts:raise FeedbackError('Contact not found.',404)
        opportunity=None
        if opportunity_id:
            matches=db('deals',record_id=opportunity_id)
            if not matches or matches[0].get('contact_id')!=customer_id:raise FeedbackError('Select an opportunity linked to this contact.')
            opportunity=matches[0]
        notes=data.get('notes');meeting_date=data.get('meeting_date')
        try:
            if not isinstance(meeting_date,str) or date.fromisoformat(meeting_date).isoformat()!=meeting_date:raise ValueError()
        except (ValueError,TypeError):raise FeedbackError('Use an exact meeting date.')
        if not isinstance(notes,str) or not 1<=len(notes.strip())<=8000:raise FeedbackError('Enter meeting notes of at most 8,000 characters.')
        context={'customer_id':customer_id,'opportunity_id':opportunity_id,'meeting_date':meeting_date,'notes':notes,'contact':{k:contacts[0].get(k) for k in ('id','name','company','role','owner')},'record':{k:(opportunity or contacts[0]).get(k) for k in ('id','contact_id','title','name','company','owner','value','stage')},'generated_by':actor['id']}
        from meeting_updates import propose
        with use_prompts(active_prompts(db)):row=propose(db,context,actor['team'])
        return jsonify(suggestion=row)

    @app.get('/api/prompt-versions')
    def prompt_versions():return jsonify(versions=db('prompt_versions'),batches=db('prompt_evaluation_batches',extra_params={'limit':100}))

    @app.post('/api/prompt-versions')
    def create_prompt_version():
        actor=reviewer(db,admin=True);data=request.get_json(silent=True)
        if not isinstance(data,dict) or data.get('workflow') not in ('followup','meeting_update'):raise FeedbackError('Choose a workflow.')
        text=data.get('system_prompt');rationale=data.get('rationale')
        if not isinstance(text,str) or not 20<=len(text)<=10000 or not isinstance(rationale,str) or not 1<=len(rationale.strip())<=1000:raise FeedbackError('Provide a system prompt and change rationale.')
        existing=db('prompt_versions',extra_params={'workflow':'eq.'+data['workflow']})
        row=db('prompt_versions','POST',{'workflow':data['workflow'],'version':max((r['version'] for r in existing),default=0)+1,'system_prompt':text,'rationale':rationale,'status':'draft','created_by':actor['id']})[0]
        return jsonify(version=row),201

    @app.post('/api/prompt-versions/<version_id>/approve')
    def approve_prompt_version(version_id):
        actor=reviewer(db,admin=True);identity=identifier(version_id)
        rows=db('prompt_versions','PATCH',{'status':'approved','approved_by':actor['id'],'approved_at':datetime.now(timezone.utc).isoformat()},identity,extra_params={'status':'eq.draft'})
        if not rows:raise FeedbackError('Only a draft prompt can be approved.',409)
        return jsonify(version=rows[0])

    @app.post('/api/prompt-versions/<version_id>/batches')
    def start_prompt_evaluations(version_id):
        actor=reviewer(db,admin=True);identity=identifier(version_id);rows=db('prompt_versions',record_id=identity)
        if not rows or rows[0]['status']!='approved':raise FeedbackError('Approve this prompt before evaluating it.',409)
        batch=db('prompt_evaluation_batches','POST',{'prompt_version_id':identity,'created_by':actor['id'],'agent_version':version(),'model':os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT)})[0]
        return jsonify(batch=batch,scenarios=[{'id':s['id'],'scenario_number':s['scenario_number']} for s in canonical_scenarios()])

    @app.post('/api/prompt-versions/<version_id>/batches/<batch_id>/run/<scenario_id>')
    @limiter.limit('6 per minute')
    def evaluate_candidate(version_id,batch_id,scenario_id):
        reviewer(db,admin=True);identity=identifier(version_id);batch_identity=identifier(batch_id);scenario_identity=identifier(scenario_id)
        rows=db('prompt_versions',record_id=identity);batches=db('prompt_evaluation_batches',record_id=batch_identity)
        if not rows or not batches or batches[0]['prompt_version_id']!=identity or rows[0]['status']!='approved':raise FeedbackError('This approved prompt and batch are not available.',409)
        target=rows[0];batch=batches[0]
        if batch['agent_version']!=version() or batch['model']!=os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT):raise FeedbackError('Code or model changed; start a new evaluation suite.',409)
        scenario=next((s for s in canonical_scenarios() if s['id']==scenario_identity),None)
        if not scenario:raise FeedbackError('Unknown release-gate scenario.')
        prior=db('evaluation_runs',extra_params={'batch_id':'eq.'+batch_identity})
        if any(r['scenario_id']==scenario_identity for r in prior):raise FeedbackError('This batch already has a run for the scenario.',409)
        allowed={'evaluation_runs','evaluation_check_results'}
        def storage(resource,method='GET',data=None,record_id=None):
            if resource not in allowed:raise RuntimeError('Candidate evaluations may write only evaluation records.')
            return db(resource,method,data,record_id)
        prompts=active_prompts(db);prompts[target['workflow']]={**target,'label':target['workflow']+'/v'+str(target['version'])}
        executor=None
        if target['workflow']=='meeting_update' and scenario['scenario_number']==7:
            from meeting_updates import sandbox_executor
            executor=sandbox_executor
        with use_prompts(prompts):
            result=evaluate_one(scenario,[r for r in canonical_rules() if r['scenario_id']==scenario_identity],storage,batch_identity,pricing_for(batch['model']),prompt_version=target,executor=executor)
        runs=db('evaluation_runs',extra_params={'batch_id':'eq.'+batch_identity})
        if len(runs)==3:
            status='passed' if all(r['status']=='passed' for r in runs) else 'error' if any(r['status']=='error' for r in runs) else 'failed'
            db('prompt_evaluation_batches','PATCH',{'status':status,'completed_at':datetime.now(timezone.utc).isoformat()},batch_identity)
        return jsonify(run=result)

    @app.post('/api/prompt-versions/<version_id>/release')
    def release_prompt_version(version_id):
        actor=reviewer(db,admin=True);data=request.get_json(silent=True) or {}
        if not isinstance(data,dict):raise FeedbackError('Select a passing evaluation batch.')
        result=rpc('crm_release_prompt',{'p_version':identifier(version_id),'p_batch':identifier(data.get('batch_id')),'p_reviewer':actor['id'],'p_agent_version':version(),'p_model':os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT)})
        if result.get('error'):raise FeedbackError(result['error'],409)
        return jsonify(result)
