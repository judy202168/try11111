"""Server-only OpenRouter JSON calls shared by both suggestion workflows."""
import json,os,time
from datetime import date
import requests
from prompt_registry import prompt
from evaluation_telemetry import record_response,record_failure,cost_summary

MODEL_DEFAULT='openai/gpt-4o-mini'

def request_json(context,workflow):
    key=os.getenv('OPENROUTER_API_KEY')
    if not key:raise RuntimeError('Add OPENROUTER_API_KEY in Railway Variables to enable drafting.')
    model=os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT);started=time.perf_counter()
    try:
        response=requests.post('https://openrouter.ai/api/v1/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json={'model':model,'max_tokens':1400 if workflow=='meeting_update' else 700,'temperature':.4,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':prompt(workflow)['system_prompt']},{'role':'user','content':json.dumps(context)}]},timeout=60)
    except requests.RequestException as error:
        record_failure(time.perf_counter()-started,model,error);raise
    record_response(response,time.perf_counter()-started,model)
    if not response.ok:raise RuntimeError('OpenRouter request failed (HTTP '+str(response.status_code)+').')
    try:return json.loads(response.json()['choices'][0]['message']['content'])
    except (KeyError,IndexError,ValueError,TypeError):raise RuntimeError('OpenRouter returned invalid JSON. No approval created.')

def validate_suggestion(value,workflow,source=None):
    if not isinstance(value,dict):raise ValueError('Suggestion must be a JSON object.')
    keys={'summary','next_action','commitments'} if workflow=='meeting_update' else {'subject','body','next_action'}
    if set(value)!=keys:raise ValueError('Suggestion fields do not match this workflow.')
    limits={'subject':250,'body':6000,'summary':6000,'next_action':1000}
    for key in keys-{'commitments'}:
        if not isinstance(value[key],str) or not value[key].strip() or len(value[key])>limits[key]:raise ValueError('Invalid '+key+'.')
    if workflow=='meeting_update':
        if not isinstance(value['commitments'],list) or len(value['commitments'])>15:raise ValueError('Use at most 15 commitment proposals.')
        for item in value['commitments']:
            if not isinstance(item,dict) or set(item)!={'title','owner','due_date','source_evidence'}:raise ValueError('A commitment needs title, owner, due_date and source_evidence.')
            if not isinstance(item['title'],str) or not 1<=len(item['title'])<=250:raise ValueError('Invalid commitment title.')
            if item['owner'] is not None and (not isinstance(item['owner'],str) or not 1<=len(item['owner'])<=250):raise ValueError('Invalid owner.')
            if item['due_date'] is not None:
                if not isinstance(item['due_date'],str) or date.fromisoformat(item['due_date']).isoformat()!=item['due_date']:raise ValueError('Use an exact ISO date or null.')
            if not isinstance(item['source_evidence'],str) or not item['source_evidence'] or len(item['source_evidence'])>4000:raise ValueError('Retain source evidence for each commitment.')
            if source is not None and item['source_evidence'] not in source:raise ValueError('Commitment evidence must be copied verbatim from the meeting notes.')
    return value

def metadata(calls,started,workflow):
    current=prompt(workflow);cost,source=cost_summary(calls)
    return {'prompt_version_id':current['id'],'prompt_label':current['label'],'response_time_ms':round((time.perf_counter()-started)*1000),'estimated_cost_usd':cost,'cost_source':source,'model':','.join(dict.fromkeys(c['model'] for c in calls)) or os.getenv('OPENROUTER_MODEL',MODEL_DEFAULT)}
