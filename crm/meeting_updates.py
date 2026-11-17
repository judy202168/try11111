"""Meeting suggestions are reviewable proposals; no CRM tasks/fields are applied."""
import hashlib,os,time
from evaluation_telemetry import collect_calls
from model_client import request_json,validate_suggestion,metadata,MODEL_DEFAULT
from prompt_registry import prompt
from guardrails import AgentStore,prepare,assess,GuardedSuggestion
from guardrail_service import record_assessment

def generate(context):
    return prepare(context,request_json(context,'meeting_update'),'meeting_update')

def propose(db,context,team='Unassigned'):
    if not isinstance(db,AgentStore):db=AgentStore(db)
    identity=context['opportunity_id'] or context['customer_id']
    version='meeting:'+context['meeting_date']+':'+hashlib.sha256((identity+context['notes']).encode()).hexdigest()
    existing=db('followups')
    match=next((r for r in existing if r.get('activity_version')==version and r['entity_id']==identity),None)
    if match:return match
    current=prompt('meeting_update')
    row=db('followups','POST',{'entity_type':'deals' if context['opportunity_id'] else 'contacts','entity_id':identity,'activity_version':version,'context':context,'model':os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT),'workflow_type':'meeting_update','prompt_version_id':current['id'],'prompt_label':current['label'],'team':team})[0]
    started=time.perf_counter();calls=[]
    try:
        preflight=assess(context,None,'meeting_update')
        with collect_calls() as calls:plan=generate(context) if preflight['can_generate'] else GuardedSuggestion(preflight)
        if not isinstance(plan,GuardedSuggestion):plan=prepare(context,plan,'meeting_update')
        result_guard=plan.assessment;result_guard['audit_event_ids']=record_assessment(db,result_guard,row['id'])
        return db('followups','PATCH',{'subject':'Meeting update · '+context['meeting_date'],'body':plan['summary'],'next_action':plan['next_action'],'original_suggestion':result_guard['proposed_output'],'guardrail_result':result_guard,'status':'pending',**metadata(calls,started,'meeting_update')},row['id'])[0]
    except Exception as error:
        record_assessment(db,assess(context,{'model_error':str(error)},'meeting_update'),row['id'])
        db('followups','PATCH',{'status':'failed','error':str(error)[:500],**metadata(calls,started,'meeting_update')},row['id']);raise

def sandbox_executor(db):
    contact=db('contacts')[0];deal=db('deals')[0]
    context={'customer_id':contact['id'],'opportunity_id':deal['id'],'meeting_date':deal.get('meeting_date','2026-11-10'),'notes':deal['notes'],'record':deal,'contact':contact}
    propose(db,context)
