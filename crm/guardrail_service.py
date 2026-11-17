"""Persistent audit and relationship resolution. No external-action executors."""
from datetime import datetime,timezone
from hashlib import sha256
import json
from guardrails import assess,action_policy,G1,G2,POLICY_VERSION,AgentStore

def audit(db,context,proposal,result,guardrail,suggestion_id=None,source='production',test_case_id=None,review_id=None):
    event={'suggestion_id':suggestion_id,'source':source,'test_case_id':test_case_id,'review_id':review_id,'guardrail':guardrail,'policy_version':POLICY_VERSION,
           'model_input':context or {},'verification_context':result.get('model_input') or context or {},'proposed_output':proposal if isinstance(proposal,dict) else {'raw_text':proposal},'safe_output':result.get('safe_suggestion',{}),
           'proposed_action':result['proposed_action'],'verdict':result.get('verdict') or ('blocked' if result['status']=='Blocked' else 'review' if result['missing_information'] or result['invention_attempts'] else 'allowed'),
           'status':result['status'],'reason':result['reason'],'missing_information':result.get('missing_information',[]),'invention_attempts':result.get('invention_attempts',[]),
           'final_action':result.get('final_action') or 'Only an internal grounded proposal was prepared; no external change.',
           'enforced':True,'passed':result.get('passed',True),'external_changes':0}
    memory=getattr(db,'guardrail_events',None)
    if isinstance(memory,list):
        memory.append(event);return None
    return db('guardrail_events','POST',event)[0]['id']

def record_assessment(db,assessment,suggestion_id=None,source='production',test_case_id=None):
    ids=[]
    for guardrail in (G1,G2):
        result=action_policy(assessment['proposed_action'],assessment['proposed_output']) if guardrail==G1 else assessment
        event=audit(db,assessment.get('original_model_input',assessment['model_input']),assessment['proposed_output'],result,guardrail,suggestion_id,source,test_case_id)
        if event:ids.append(event)
    return ids

def linked_context(db,row):
    ctx=dict(row.get('context') or {})
    if row['entity_type']=='deals':
        deals=db('deals',record_id=row['entity_id']);record=deals[0] if deals else {};cid=record.get('contact_id')
        expected=ctx.get('customer_id')
        if expected and expected!=cid:cid=expected;people=[]
        else:people=db('contacts',record_id=cid) if cid else []
        contact=people[0] if people else None;oid=record.get('id')
    else:
        people=db('contacts',record_id=row['entity_id']);contact=people[0] if people else None;record=contact or {};cid=record.get('id');oid=None
    ctx.update(customer_id=cid,opportunity_id=oid,contact=contact,record=record)
    # Meeting source notes remain the exact notes attached to that suggestion.
    return ctx

def check_suggestion(db,row):
    context=linked_context(db,row)
    raw=row.get('original_suggestion') or {'subject':row.get('subject',''),'body':row.get('body',''),'next_action':row.get('next_action','')}
    result=assess(context,raw,row.get('workflow_type','followup'));result['original_model_input']=row.get('context') or {}
    result['audit_event_ids']=record_assessment(db,result,row['id'])
    result['checked_at']=datetime.now(timezone.utc).isoformat()
    db('followups','PATCH',{'guardrail_result':result},row['id'])
    return result

def blocked_action(db,action,proposal=None,context=None,source='production',test_case_id=None):
    result=action_policy(action,proposal)
    result['audit_event_id']=audit(db,context,proposal or {},result,G1,source=source,test_case_id=test_case_id)
    return result
