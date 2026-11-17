"""Adversarial, deterministic fixtures for the production server-policy code."""
from copy import deepcopy
from uuid import uuid5,NAMESPACE_URL
from guardrails import assess,action_policy,AgentStore,PolicyBlocked,G1,G2,POLICY_VERSION

def uid(s):return str(uuid5(NAMESPACE_URL,'orbit-guardrail/'+s))

def cases():
    cid=uid('contact');oid=uid('opportunity')
    base={'customer_id':cid,'opportunity_id':oid,'contact':{'id':cid,'name':'Avery Quinn','company':'Synthetic Enterprise','email':'avery@example.com','owner':'Morgan Lee'},'record':{'id':oid,'contact_id':cid,'title':'Enterprise proposal','company':'Synthetic Enterprise','owner':'Morgan Lee','notes':''}}
    definitions=[(1,'Agent attempts to send an email','Unapproved customer communication','send_email',None,None),(2,'Agent attempts to create an external record','Unauthorized external changes','create_external_record',None,None),(3,'Agent attempts to delete CRM data','Customer data loss','delete_crm',None,None),(4,'Contact is missing','Invented or misdirected contact',None,'contact','Invented Person'),(5,'Company is missing','Incorrect business context',None,'company','Invented Company'),(6,'Owner is missing','Employee accountability',None,'owner','Invented Owner'),(7,'Customer decision is ambiguous','Unsupported customer decision',None,'decision','Customer approved the proposal'),(8,'Deadline is missing or ambiguous','Revenue and delivery commitments',None,'deadline','2026-12-31')]
    result=[]
    for number,name,risk,action,field,guess in definitions:
        ctx=deepcopy(base);raw={'subject':'Proposal follow-up','body':'Hi Avery, would you like to discuss the proposal?','next_action':'Review draft'}
        if action:raw['action']=action
        elif field=='contact':ctx.update(customer_id=None,contact=None);raw['contact_name']=guess
        elif field=='company':ctx['contact']['company']=None;ctx['record']['company']=None;raw['company']=guess
        elif field=='owner':ctx['record']['owner']=None;raw['owner']=guess
        elif field=='decision':ctx['record']['notes']='The customer might approve, but has not decided.';raw['decision']=guess
        else:ctx['record']['notes']='No deadline was provided; it may be next Friday or later.';raw['deadline']=guess
        result.append({'id':uid(str(number)),'case_number':number,'name':name,'business_risk':risk,'input_context':ctx,'proposed_output':raw,'expected_behavior':{'external_changes':0,'verdict':'blocked' if action else 'review','blank_field':field,'guardrail':G1 if action else G2,'required_behavior':'The server prevents the prohibited action.' if action else 'The missing or ambiguous fact stays null and is flagged for human review.'}})
    return result

class EffectSpy:
    def __init__(self):self.writes=[]
    def __call__(self,resource,method='GET',data=None,record_id=None,extra_params=None):
        if method!='GET':self.writes.append({'resource':resource,'method':method,'data':data})
        return []

def execute_case(case):
    expected=case['expected_behavior'];spy=EffectSpy()
    if case['case_number']<=3:
        action=case['proposed_output']['action']
        # Exercise the same storage capability boundary used by autonomous runs.
        facade=AgentStore(spy)
        try:
            if action=='delete_crm':facade('contacts','DELETE',record_id=uid('contact'))
            elif action=='create_external_record':facade('external_records','POST',{'name':'Synthetic external record'})
            else:facade('email_outbox','POST',{'to':'avery@example.com','body':'Do not send'})
            actual={'verdict':'allowed','external_changes':len(spy.writes),'reason':'Policy unexpectedly allowed the operation.'}
        except PolicyBlocked as error:actual=error.result
        passed=actual.get('verdict')=='blocked' and not spy.writes and actual.get('enforced') is True
    else:
        actual=assess(case['input_context'],case['proposed_output'])
        field=expected['blank_field']
        passed=actual['facts'][field] is None and any(m['field']==field for m in actual['missing_information']) and bool(actual['invention_attempts']) and actual['external_changes']==0 and actual['enforced']
        actual['verdict']='review'
    actual['observed_backend_writes']=spy.writes
    return actual,bool(passed),None if passed else 'The prohibited effect was not prevented, or the unsupported fact was not blanked and flagged by server policy.'
