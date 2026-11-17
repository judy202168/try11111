"""Draft-only agent. Has no mail transport, send function, or model tools."""
import json
import os
import time
from evaluation_telemetry import collect_calls
from model_client import metadata
from prompt_registry import prompt
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
    from model_client import request_json,validate_suggestion
    try:return validate_suggestion(request_json(context,'followup'),'followup')
    except ValueError as error:raise RuntimeError(str(error))


def run(db):
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
        context={'customer_id':contact.get('id') if contact else None,'opportunity_id':row['id'] if kind=='deals' else None,'record':{k:row.get(k) for k in ['name','title','company','role','stage','value','notes','owner','close_date'] if k in row},
                 'contact':{k:contact.get(k) for k in ['name','email','company','role'] } if contact else None,
                 'last_recorded_activity':version,'activity_basis':'last_activity_at or creation date when unknown',
                 'open_tasks':[{'title':t['title'],'due_date':t['due_date']} for t in tasks if not t['done'] and contact and t.get('contact_id')==contact['id']]}
        try:
            claimed=db('followups','POST',{'entity_type':kind,'entity_id':row['id'],'activity_version':version,'context':context,'model':os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT),'workflow_type':'followup','prompt_version_id':prompt('followup')['id'],'prompt_label':prompt('followup')['label']})[0]
        except RuntimeError:
            # Unique key prevents concurrent runs generating the same follow-up.
            result['skipped']+=1;continue
        started=time.perf_counter();calls=[]
        try:
            with collect_calls() as calls:draft=generate(context)
            db('followups','PATCH',{**draft,'original_suggestion':draft,'status':'pending',**metadata(calls,started,'followup')},claimed['id'])
            db(kind,'PATCH',{'suggested_next_action':draft['next_action']},row['id'])
            result['created']+=1
        except Exception as error:
            db('followups','PATCH',{'status':'failed','error':str(error)[:500],**metadata(calls,started,'followup')},claimed['id']);result['failed']+=1
    return result
