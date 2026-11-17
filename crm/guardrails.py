"""Server policy: no external effects; only evidence-backed, extractive suggestions."""
from copy import deepcopy
from datetime import date,datetime
from uuid import UUID
import re

POLICY_VERSION='crm-guardrails-v1'
G1='No automatic external actions'
G2='Use linked evidence only'
FORBIDDEN={'send_email','create_external_record','delete_crm','delete_record','apply_task','apply_activity','send_message'}
AMBIGUOUS=re.compile(r'\b(maybe|might|possibly|tentative|unconfirmed|undecided|unknown|tbd|unassigned|pending confirmation|not decided|either|or)\b',re.I)

class PolicyBlocked(RuntimeError):
    def __init__(self,result):self.result=result;super().__init__(result['reason'])

class GuardedSuggestion(dict):
    def __init__(self,assessment):super().__init__(assessment['safe_suggestion']);self.assessment=assessment

def valid_id(value):
    try:UUID(str(value));return True
    except (ValueError,TypeError):return False

def known(value):
    if not isinstance(value,str) or not value.strip() or AMBIGUOUS.search(value):return None
    return value.strip()

def explicit_dates(text):
    if not isinstance(text,str) or AMBIGUOUS.search(text):return []
    values=[]
    for raw in re.findall(r'\b\d{4}-\d{2}-\d{2}\b',text):
        try:values.append(date.fromisoformat(raw).isoformat())
        except ValueError:pass
    for raw in re.findall(r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',text,re.I):
        try:values.append(datetime.strptime(raw.replace(',',''),'%B %d %Y').date().isoformat())
        except ValueError:pass
    return sorted(set(values))

def explicit_owners(text):
    if not isinstance(text,str) or AMBIGUOUS.search(text):return []
    matches=re.findall(r'\b([A-Z][a-zA-Z\'-]*(?: [A-Z][a-zA-Z\'-]*){0,2})\s+(?:owns|is responsible for|will prepare|will send|will deliver)\b',text)
    return sorted(set(matches))

def explicit_decision(text):
    if not isinstance(text,str) or AMBIGUOUS.search(text) or re.search(r'\b(?:not|hasn.t|haven.t)\b',text,re.I):return None
    matches=re.findall(r'\b(?:the )?customer (?:has )?(?:approved|accepted|rejected|decided to)[^.!?\n]*',text,re.I)
    return matches[0] if len(matches)==1 else None

def action_policy(action,proposed=None):
    # No mail client, external record connector, or deletion executor is available.
    allowed=action in ('prepare_draft','prepare_followup','prepare_meeting_update','recommendation')
    return {'policy_version':POLICY_VERSION,'guardrail':G1,'proposed_action':action,'status':'Draft only' if allowed else 'Blocked','verdict':'allowed' if allowed else 'blocked','reason':'Internal draft preparation is permitted; no external action is performed.' if allowed else 'This workspace cannot send messages, create external records, delete CRM data, or apply AI tasks. Approval reviews content only.', 'final_action':'Internal preparation only' if allowed else 'No external change; action prevented by server policy','external_changes':0,'enforced':True,'passed':True,'proposed_output':deepcopy(proposed or {})}

def assess(context,proposed,workflow='followup'):
    ctx=deepcopy(context or {});raw=deepcopy(proposed if isinstance(proposed,dict) else {'raw_text':proposed} if proposed is not None else {})
    contact=ctx.get('contact') if isinstance(ctx.get('contact'),dict) else {};record=ctx.get('record') if isinstance(ctx.get('record'),dict) else {}
    cid=ctx.get('customer_id');oid=ctx.get('opportunity_id')
    linked=valid_id(cid) and contact.get('id')==cid
    if oid:linked=linked and valid_id(oid) and record.get('id')==oid and record.get('contact_id')==cid
    elif record.get('id') not in (None,cid):linked=False
    notes=ctx.get('notes') if workflow=='meeting_update' else record.get('notes','')
    notes=notes if linked and isinstance(notes,str) else ''
    missing=[];attempts=[]
    def absent(field,label,required=False,reason=None):
        if not any(m['field']==field for m in missing):missing.append({'field':field,'label':label,'required':required,'reason':reason or label+' is missing or ambiguous.'})
    name=known(contact.get('name')) if linked else None
    company=known(contact.get('company')) if linked else None
    if linked and known(record.get('company')) and company and record['company'].strip()!=company:
        company=None;absent('company','Company',True,'Linked records disagree about the company; confirm the correct company.')
    owner=known(record.get('owner')) if linked and workflow=='followup' else None
    dates=explicit_dates(notes);deadline=dates[0] if len(dates)==1 and re.search(r'\b(by|due|deadline|needs)\b',notes,re.I) else None
    decision=explicit_decision(notes) if linked else None
    if not name:absent('contact','Contact',True,'A verified contact linked to this task is required.')
    if not company:absent('company','Company',True)
    if workflow=='followup' and not owner:absent('owner','Assigned owner',True)
    if not decision:absent('decision','Customer decision',False,'No clear customer decision is recorded; leave it blank.')
    if not deadline:absent('deadline','Customer deadline',False, 'No single confirmed customer deadline is recorded; leave it blank.')
    email=known(contact.get('email')) if linked else None
    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):email=None
    if workflow=='followup' and not email:absent('email','Email address',True,'Email address is missing or unverified. Ask the owner to verify contact details or choose an approved channel.')
    facts={'contact':name,'company':company,'owner':owner,'decision':decision,'deadline':deadline,'email':email,'customer_id':cid if linked else None,'opportunity_id':oid if linked else None}
    for field,keys in {'contact':['contact_name','customer_name','contact'],'company':['company'],'owner':['owner'],'decision':['decision','customer_decision'],'deadline':['deadline','due_date']}.items():
        for key in keys:
            value=raw.get(key)
            if isinstance(value,dict):value=value.get('name')
            if isinstance(value,str) and value.strip() and value.strip()!=facts[field]:attempts.append({'field':field,'proposed':value,'supported':facts[field]})
    text=' '.join(str(raw.get(k) or '') for k in ('subject','body','summary','next_action'))
    greeting=re.search(r'\bHi\s+([A-Z][a-z]+)',text)
    if greeting and greeting.group(1).casefold() not in ('there','team') and (not name or greeting.group(1).casefold()!=name.split()[0].casefold()):attempts.append({'field':'contact','proposed':greeting.group(1),'supported':name})
    if explicit_decision(text) and not decision:attempts.append({'field':'decision','proposed':explicit_decision(text),'supported':None})
    action=str(raw.get('action') or raw.get('proposed_action') or ('prepare_meeting_update' if workflow=='meeting_update' else 'prepare_followup'))
    effect=action_policy(action,raw);forbidden=effect['verdict']=='blocked'
    title=known(record.get('title')) if linked and oid else None
    if workflow=='followup':
        body=('Hi '+name.split()[0]+',\n\n'+('Would you like to discuss next steps for '+title+'?' if title else 'Would you like to discuss next steps?')+('\n\n'+owner if owner else '')) if name and email else ''
        safe={'subject':('Follow-up: '+title)[:250] if title else 'Follow-up' if body else '', 'body':body,'next_action':'Review this grounded draft with the assigned CRM owner.' if body else 'Ask the assigned owner to verify the missing contact information or choose an approved channel.'}
    else:
        commits=[];seen=set();proposals=raw.get('commitments') if isinstance(raw.get('commitments'),list) else []
        if not proposals and (explicit_owners(notes) or deadline):proposals=[{'source_evidence':notes}]
        for item in proposals[:15]:
            if not isinstance(item,dict):continue
            evidence=item.get('source_evidence');evidence=evidence if isinstance(evidence,str) and evidence and evidence in notes else notes
            owners=explicit_owners(evidence);values=explicit_dates(evidence)
            verified_owner=owners[0] if len(owners)==1 else None
            verified_due=values[0] if len(values)==1 and re.search(r'\b(by|due|deadline|needs)\b',evidence,re.I) else None
            for field,key,supported in [('owner','owner',verified_owner),('deadline','due_date',verified_due)]:
                if item.get(key) and item[key]!=supported:attempts.append({'field':field,'proposed':item[key],'supported':supported})
            if not verified_owner:absent('owner','Commitment owner',True,'No single owner is explicitly assigned in the source note; leave owner blank.')
            if not verified_due:absent('deadline','Customer deadline',True)
            task_title='Pricing update' if re.search(r'pricing update',evidence,re.I) else 'Revised enterprise proposal' if re.search(r'revised enterprise proposal',evidence,re.I) else 'Review recorded meeting commitment'
            identity=(task_title,verified_owner,verified_due,evidence)
            if identity in seen:continue
            seen.add(identity);commits.append({'title':task_title,'owner':verified_owner,'due_date':verified_due,'source_evidence':evidence})
        facts['owner']=commits[0]['owner'] if len(commits)==1 else None
        facts['deadline']=commits[0]['due_date'] if len(commits)==1 else None
        safe={'summary':'Meeting notes (verbatim):\n'+notes if notes else 'No meeting notes supplied.','commitments':commits,'next_action':'Verify missing or ambiguous details, then review the recorded commitments before applying any update.'}
    required=any(m['required'] for m in missing)
    if forbidden:status='Blocked';reason=effect['reason']
    elif not linked:status='Missing information';reason='The contact or opportunity link could not be verified. No customer action is permitted.'
    elif required:status='Missing information';reason='Required information is missing or ambiguous. Unknown fields were left blank and the suggestion is held for review.'
    elif attempts:status='Needs human review';reason='Unsupported model-proposed facts were withheld. Only the linked CRM facts and exact source evidence are used in the prepared version.'
    else:status='Draft only';reason='Only a grounded internal proposal is available. Human review is required; no customer message or external update is possible.'
    return {'policy_version':POLICY_VERSION,'status':status,'proposed_action':action,'guardrails_triggered':([G1] if forbidden else [])+([G2] if missing or attempts or raw!=safe else []),'reason':reason,'missing_information':missing,'invention_attempts':attempts,'facts':facts,'safe_suggestion':safe,'proposed_output':raw,'model_input':ctx,'can_approve':linked and not required and not forbidden,'can_generate':linked and not required and not forbidden,'next_action':'Correct the linked source information and recheck, or reject this suggestion.' if required or forbidden else 'Review the grounded proposal. Approval saves content only; sending and external actions stay disabled.','external_changes':0,'enforced':True,'raw_output_quarantined':raw!=safe}

def prepare(context,raw,workflow='followup'):return GuardedSuggestion(assess(context,raw,workflow))

class AgentStore:
    """The autonomous agent has internal-proposal storage, not general CRM write authority."""
    def __init__(self,store):self._store=store
    @property
    def guardrail_events(self):
        return self._store.guardrail_events
    def __call__(self,resource,method='GET',data=None,record_id=None,extra_params=None):
        if method=='GET' and resource in ('contacts','deals','tasks','followups'):
            if record_id is None and extra_params is None:return self._store(resource)
            return self._store(resource,method,data,record_id,extra_params)
        if resource=='guardrail_events' and method=='POST':return self._store(resource,method,data,record_id)
        if resource=='followups' and method in ('POST','PATCH'):
            value=data or {}
            if value.get('status','generating') not in ('generating','pending','failed') or set(value)&{'final_suggestion','reviewed_at','review_note'}:
                result=action_policy('record_human_review',value);result['reason']='Autonomous agents cannot approve, reject, edit human review evidence, or authorize an external action.';raise PolicyBlocked(result)
            if value.get('status')=='pending' and (value.get('guardrail_result') or {}).get('policy_version')!=POLICY_VERSION:
                result=action_policy('publish_unverified_suggestion',value);result['reason']='A server guardrail check is required before a suggestion can enter the review queue.';raise PolicyBlocked(result)
            return self._store(resource,method,data,record_id)
        raise PolicyBlocked(action_policy('delete_crm' if method=='DELETE' else 'create_external_record',{'resource':resource,'method':method,'data':data}))
