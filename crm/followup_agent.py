"""Draft-only agent. Has no mail transport, send function, or model tools."""
import json
import os
import time
from evaluation_telemetry import collect_calls
from model_client import metadata
from prompt_registry import prompt
from guardrails import AgentStore,prepare,assess,GuardedSuggestion
from guardrail_service import record_assessment
from datetime import datetime, timezone, timedelta
import requests

MODEL_DEFAULT = 'openai/gpt-4o-mini'

def candidates(contacts, deals, now=None, days=7):
    now = now or datetime.now(timezone.utc)
    for kind, rows in [('contacts', contacts), ('deals', deals)]:
        for row in rows:
            if kind == 'deals' and row['stage'] in ('Won', 'Lost'): continue
            if kind == 'contacts' and row['status'] == 'Inactive': continue
            version = row.get('last_activity_at') or row['created_at']
            if datetime.fromisoformat(version.replace('Z', '+00:00')) > now-timedelta(days=days): continue
            yield kind, row, version

def generate(context):
    from model_client import request_json
    return prepare(context,request_json(context,'followup'),'followup')


def run(db):
    if not isinstance(db,AgentStore):db=AgentStore(db)
    if not os.getenv('OPENROUTER_API_KEY'): raise RuntimeError('Add OPENROUTER_API_KEY in Railway Variables to enable drafting.')
    contacts=db('contacts'); deals=db('deals'); tasks=db('tasks'); existing=db('followups')
    seen={(r['entity_type'],r['entity_id'],r['activity_version']) for r in existing}
    by_id={c['id']:c for c in contacts}
    result={'created':0,'failed':0,'skipped':0}
    for kind,row,version in candidates(contacts,deals,days=int(os.getenv('STALL_DAYS','7'))):
        if (kind,row['id'],version) in seen:
            result['skipped']+=1;continue
        if result['created']+result['failed']>=10: break
        contact=row if kind=='contacts' else by_id.get(row.get('contact_id'))
        # Send only relevant context; exclude phone numbers and unrelated records.
        context={'customer_id':contact.get('id') if contact else None,'opportunity_id':row['id'] if kind=='deals' else None,'record':{k:row.get(k) for k in ['id','contact_id','name','title','company','role','stage','value','notes','owner','close_date'] if k in row},
                 'contact':{k:contact.get(k) for k in ['id','name','email','company','role','owner'] } if contact else None,
                 'last_recorded_activity':version,'activity_basis':'last_activity_at or creation date when unknown',
                 'open_tasks':[{'title':t['title'],'due_date':t['due_date']} for t in tasks if not t['done'] and contact and t.get('contact_id')==contact['id']]}
        try:
            claimed=db('followups','POST',{'entity_type':kind,'entity_id':row['id'],'activity_version':version,'context':context,'model':os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT),'workflow_type':'followup','prompt_version_id':prompt('followup')['id'],'prompt_label':prompt('followup')['label']})[0]
        except RuntimeError:
            # Unique key prevents concurrent runs generating the same follow-up.
            result['skipped']+=1;continue
        started=time.perf_counter();calls=[]
        try:
            preflight=assess(context,None,'followup')
            with collect_calls() as calls:draft=generate(context) if preflight['can_generate'] else GuardedSuggestion(preflight)
            if not isinstance(draft,GuardedSuggestion):draft=prepare(context,draft,'followup')
            result_guard=draft.assessment
            result_guard['audit_event_ids']=record_assessment(db,result_guard,claimed['id'])
            db('followups','PATCH',{**draft,'original_suggestion':result_guard['proposed_output'],'guardrail_result':result_guard,'status':'pending',**metadata(calls,started,'followup')},claimed['id'])
            result['created']+=1
        except Exception as error:
            record_assessment(db,assess(context,{'model_error':str(error)},'followup'),claimed['id'])
            db('followups','PATCH',{'status':'failed','error':str(error)[:500],**metadata(calls,started,'followup')},claimed['id']);result['failed']+=1
    return result
