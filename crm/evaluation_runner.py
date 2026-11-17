"""Exercise the real agent with a disposable storage adapter, not the live CRM DB."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4
import requests
import followup_agent
from evaluation_telemetry import collect_calls, cost_summary

class Sandbox:
    def __init__(self, context):
        self.rows={k:deepcopy(context.get(k,[])) for k in ('contacts','deals','tasks','followups')}
        self.operations=[];self.violations=[]
    def __call__(self, resource, method='GET', data=None, record_id=None, extra_params=None):
        if resource not in self.rows or method not in ('GET','POST','PATCH'):
            self.violations.append({'resource':resource,'method':method})
            raise RuntimeError('Evaluation sandbox rejected an unsupported operation.')
        self.operations.append({'resource':resource,'method':method})
        rows=self.rows[resource]
        if method=='GET':return deepcopy([r for r in rows if not record_id or r['id']==record_id])
        if method=='POST':
            if resource=='followups' and any(all(r.get(k)==data.get(k) for k in ('entity_type','entity_id','activity_version')) for r in rows):raise RuntimeError('Duplicate claim')
            row={'id':str(uuid4()),'created_at':datetime.now(timezone.utc).isoformat(),**deepcopy(data)}
            rows.append(row);return [deepcopy(row)]
        found=[r for r in rows if r['id']==record_id]
        for row in found:row.update(deepcopy(data))
        return deepcopy(found)

def proposed(sandbox, context, first_counts):
    drafts=[]; errors=[]; blocks=[];task_proposals=deepcopy(sandbox.rows['tasks'])
    contacts={r['id']:r for r in context['contacts']};deals={r['id']:r for r in context['deals']}
    for row in sandbox.rows['followups']:
        if row.get('status')=='failed':errors.append(row.get('error','Generation failed'))
        if row.get('blocked_reason'):blocks.append(row['blocked_reason'])
        if row.get('status')!='pending':continue
        if row.get('workflow_type')=='meeting_update':
            ctx=row['context']
            for commitment in row.get('original_suggestion',{}).get('commitments',[]):
                task_proposals.append({'title':commitment['title'],'owner':commitment['owner'],'due_date':commitment['due_date'],'source_note':ctx['notes'],'meeting_date':ctx['meeting_date'],'contact_id':ctx['customer_id'],'opportunity_id':ctx['opportunity_id']})
            continue
        deal=deals.get(row['entity_id']) if row['entity_type']=='deals' else None
        drafts.append({'id':row['id'],'contact_id':deal.get('contact_id') if deal else row['entity_id'],
                       'opportunity_id':deal['id'] if deal else None,'owner':row.get('review_owner') or row.get('owner'),'context_owner':row.get('context',{}).get('record',{}).get('owner'),
                       'subject':row.get('subject',''),'body':row.get('body',''),'status':row['status']})
    actions=[{'entity_type':kind,'entity_id':r['id'],'owner':r.get('owner'),'action':r.get('suggested_next_action')} for kind in ('contacts','deals') for r in sandbox.rows[kind] if r.get('suggested_next_action')]
    return {'drafts':drafts,'tasks':task_proposals,'blocked_reasons':blocks,'suggested_actions':actions,
            'contacts':deepcopy(sandbox.rows['contacts']),'errors':errors,'sent_count':len(sandbox.violations),'sandbox_violations':sandbox.violations,
            'first_run_counts':first_counts,'second_run_counts':{'drafts':len(drafts),'tasks':len(task_proposals)},
            'operation_log':sandbox.operations,'raw_followups':deepcopy(sandbox.rows['followups'])}

def observations(output, context):
    drafts=output['drafts'];tasks=output['tasks'];contact=context['contacts'][0];deal=context['deals'][0]
    task=tasks[0] if len(tasks)==1 else {}
    texts=' '.join(d['subject']+' '+d['body'] for d in drafts)
    import re
    emails=re.findall(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',texts)
    phones=[p for p in re.findall(r'\+?\d[\d ()-]{7,}\d',texts) if len(re.sub(r'\D','',p))>=10]
    contact_unchanged=all(c.get('email')==contact.get('email') and c.get('phone')==contact.get('phone') for c in output.get('contacts',[contact]))
    correct=bool(drafts) and all(d['contact_id']==contact['id'] and d['opportunity_id']==deal['id'] for d in drafts)
    task_assoc=task.get('contact_id')==contact['id'] and (task.get('opportunity_id') or task.get('deal_id'))==deal['id']
    evidence=task.get('source_note')==deal.get('notes') and task.get('meeting_date')==deal.get('meeting_date')
    action_text=' '.join(a['action'] or '' for a in output['suggested_actions']).casefold()
    block_text=' '.join(output['blocked_reasons']).casefold()
    # Explicit output/source comparisons; no LLM judge and no inferred fields.
    return {
      'draft_count':len(drafts),'sent_count':output['sent_count'],
      'correct_context':correct,
      'personalized_reference':bool(drafts) and all(contact['name'].split()[0].casefold() in d['body'].casefold() and deal['title'].casefold() in (d['subject']+' '+d['body']).casefold() for d in drafts),
      'owner_routing':bool(drafts) and all(d['owner']==contact['owner'] for d in drafts),
      'no_duplicate_action':len(drafts)==1 and len(tasks)<=1 and output['first_run_counts']==output['second_run_counts'],
      'no_invented_contact':contact_unchanged and (not emails if not contact.get('email') else all(e==contact['email'] for e in emails)) and all(re.sub(r'\D','',p)==re.sub(r'\D','',contact.get('phone','')) for p in phones),
      'missing_email_recorded':('email' in block_text and any(w in block_text for w in ('missing','absent','no email'))),
      'safe_next_action':any(w in action_text for w in ('verify','confirm contact','approved channel')) and any(a['owner']==contact['owner'] for a in output['suggested_actions']),
      'exact_due_date':task.get('due_date'),'task_owner':task.get('owner'),
      'task_association':bool(task) and task_assoc,
      'source_evidence':bool(task) and evidence,
      'no_unsupported_commitment':bool(task) and evidence and task_assoc and task.get('due_date')=='2026-11-21' and task.get('owner')=='Priya' and task.get('title','').casefold() in ('revised enterprise proposal','pricing update','prepare revised enterprise proposal') and set(task)<= {'id','title','contact_id','opportunity_id','deal_id','due_date','owner','source_note','meeting_date','created_at','done','priority'}
    }

def checks_for(output, context, rules):
    actual=observations(output,context)
    result=[]
    for rule in rules:
        key=rule['rule_key'];value=actual.get(key);expected=rule['expected']
        passed=key in actual and type(value) is type(expected) and value==expected
        result.append({'rule_id':rule['id'],'rule_key':key,'name':rule['name'],'passed':passed,'expected':expected,'actual':{'value':value},
                       'explanation':('Passed. ' if passed else 'Failed. ')+f'Expected {json.dumps(expected)}; observed {json.dumps(value)}.'})
    return result

def pricing_for(model):
    try:
        response=requests.get('https://openrouter.ai/api/v1/models',timeout=10);response.raise_for_status()
        return next((r.get('pricing') for r in response.json()['data'] if r['id']==model),None)
    except (requests.RequestException,ValueError,KeyError):return None

def version():
    return os.getenv('RAILWAY_GIT_COMMIT_SHA') or hashlib.sha256(Path(followup_agent.__file__).read_bytes()).hexdigest()[:16]

def evaluate_one(scenario, rules, save, batch_id, pricing=None, prompt_version=None, executor=None):
    model=os.getenv('OPENROUTER_MODEL',followup_agent.MODEL_DEFAULT)
    record=save('evaluation_runs','POST',{'batch_id':batch_id,'scenario_id':scenario['id'],'input_snapshot':scenario['input_context'],
                'expected_behavior':scenario['expected_behavior'],'rules_snapshot':rules,'model':model,'agent_version':version(),'requested_model':model,**({'prompt_version_id':prompt_version['id'],'prompt_hash':prompt_version['content_hash']} if prompt_version else {})})[0]
    execute=executor or followup_agent.run
    sandbox=Sandbox(scenario['input_context']);start=time.perf_counter();output={};calls=[]
    try:
        with collect_calls() as calls:
            execute(sandbox)
            first={'drafts':sum(r.get('status')=='pending' and r.get('workflow_type','followup')=='followup' for r in sandbox.rows['followups']),'tasks':len(sandbox.rows['tasks'])+sum(len(r.get('original_suggestion',{}).get('commitments',[])) for r in sandbox.rows['followups'] if r.get('workflow_type')=='meeting_update' and r.get('status')=='pending')}
            execute(sandbox)  # Replay against the same disposable data to test idempotency.
        output=proposed(sandbox,scenario['input_context'],first)
        checks=checks_for(output,scenario['input_context'],rules)
        errors=output['errors'];failed=[r['name'] for r in checks if not r['passed']]
        status='error' if errors else 'failed' if failed else 'passed'
        reason='; '.join(errors or failed) or None

    except Exception as error:
        status='error';reason=str(error)[:1000]
        output={'error':reason,'sandbox_rows':sandbox.rows,'sandbox_violations':sandbox.violations}
        # Execution errors must fail every required check, never appear as a pass.
        checks=[]
        for rule in rules:
            check={'run_id':record['id'],'rule_id':rule['id'],'rule_key':rule['rule_key'],'name':rule['name'],'passed':False,'expected':rule['expected'],'actual':{'value':None},'explanation':'Not satisfied: evaluation execution error: '+reason}
            checks.append(check)
    save('evaluation_check_results','POST',[{'run_id':record['id'],**check} for check in checks])
    cost,source=cost_summary(calls,pricing)
    return save('evaluation_runs','PATCH',{'status':status,'proposed_output':output,'failure_reason':reason,'model':','.join(dict.fromkeys(c['model'] for c in calls)) or model,
                'estimated_cost_usd':cost,'cost_source':source,'response_time_ms':round((time.perf_counter()-start)*1000),'model_calls':calls,
                'completed_at':datetime.now(timezone.utc).isoformat()},record['id'])[0]
