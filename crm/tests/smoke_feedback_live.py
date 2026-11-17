"""Read-only feedback smoke plus one synthetic meeting evaluation; no real reviews."""
import json,hashlib
from pathlib import Path
import requests
base='https://orbit-crm-production-ace6467a.up.railway.app'
root=Path(__file__).resolve().parents[1]
env=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
s=requests.Session()
r=s.post(base+'/api/login',json={'password':env['CRM_PASSWORD']},timeout=20);r.raise_for_status();headers={'X-CSRF-Token':r.json()['csrf']}
def get(path):
 r=s.get(base+'/api/'+path,timeout=30);r.raise_for_status();return r.json()
def fingerprint():
 data=get('data');data['followups']=get('followups')['drafts']
 for key in data:data[key]=sorted(data[key],key=lambda row:row['id'])
 return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
before=fingerprint();identity=get('reviewer');report=get('feedback');prompts=get('prompt-versions')
assert all('password_hash' not in r for r in identity['reviewers'])
assert len(prompts['versions'])>=2
pending=next((r for r in get('followups')['drafts'] if r['status']=='pending'),None)
if pending:
 r=s.post(base+'/api/followups/'+pending['id']+'/review',json={'action':'approve','reviewer_id':'forged'},headers=headers,timeout=20)
 assert r.status_code==401,r.text
r=s.post(base+'/api/prompt-versions/'+prompts['versions'][0]['id']+'/release',json={'batch_id':'00000000-0000-0000-0000-000000000000'},headers=headers,timeout=20)
assert r.status_code==401,r.text
scenario=next(r for r in get('evaluations')['scenarios'] if r['scenario_number']==7)
r=s.post(base+'/api/evaluations/run',json={'scenario_id':scenario['id'],'workflow':'meeting_update'},headers=headers,timeout=150);r.raise_for_status();evaluation=r.json()['run']
assert evaluation['status']!='error',evaluation
assert evaluation['proposed_output']['workflow']=='meeting_update'
assert evaluation['proposed_output']['drafts']==[]
assert fingerprint()==before,'Production records changed during meeting evaluation'
for table in ('reviewers','suggestion_reviews','prompt_versions','prompt_evaluation_batches','weekly_quality_summaries'):
 r=requests.get(env['SUPABASE_URL']+'/rest/v1/crm_'+table,headers={'apikey':env['SUPABASE_PUBLISHABLE_KEY']},timeout=20)
 assert r.status_code==200 and r.json()==[],(table,r.text)
print(json.dumps({'status':'PASS','named_reviewer_required':True,'unauthorized_release_denied':True,'meeting_evaluation':evaluation['status'],'meeting_tasks_proposed':len(evaluation['proposed_output']['tasks']),'production_isolation':'PASS','reviewer_setup_required':identity['bootstrap_available'],'structured_reviews':report['overall']['total']}),flush=True)
