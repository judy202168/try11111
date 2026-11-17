"""Explicit live evaluation run: modifies evaluation tables only; uses model credits."""
import json
import hashlib
from pathlib import Path
import requests

base='https://orbit-crm-production-ace6467a.up.railway.app'
root=Path(__file__).resolve().parents[1]
env=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
s=requests.Session()
def api(path,method='GET',data=None):
 r=s.request(method,base+'/api/'+path,headers=headers if 'headers' in globals() else {},json=data,timeout=160)
 r.raise_for_status();return r.json()
login=api('login','POST',{'password':env['CRM_PASSWORD']});headers={'X-CSRF-Token':login['csrf']}
def fingerprint():
 data=api('data');data['followups']=api('followups')['drafts']
 for key in data:data[key]=sorted(data[key],key=lambda r:r['id'])
 return hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
before=fingerprint()
data=api('evaluations')
assert len(data['scenarios'])==3 and len(data['rules'])==17
summaries=[]
for scenario in data['scenarios']:
 result=api('evaluations/run','POST',{'scenario_id':scenario['id']})['run']
 summaries.append({'scenario':scenario['scenario_number'],'status':result['status'],'reason':result['failure_reason'],'model':result['model'],'cost_usd':result['estimated_cost_usd'],'cost_source':result['cost_source'],'duration_ms':result['response_time_ms']})
 print(json.dumps(summaries[-1]),flush=True)
 assert result['status'] in ('passed','failed','error')
 assert result['completed_at']
assert fingerprint()==before,'Production CRM records changed during evaluation'
data=api('evaluations');assert len(data['runs'])>=3
for scenario in data['scenarios']:
 latest=next(r for r in data['runs'] if r['scenario_id']==scenario['id'])
 checks=[c for c in data['checks'] if c['run_id']==latest['id']]
 assert len(checks)==len([rule for rule in data['rules'] if rule['scenario_id']==scenario['id']])
# Missing server token cannot read evaluation history.
for table in ('evaluation_scenarios','evaluation_rules','evaluation_runs','evaluation_check_results'):
 r=requests.get(env['SUPABASE_URL']+'/rest/v1/crm_'+table,headers={'apikey':env['SUPABASE_PUBLISHABLE_KEY']},timeout=20)
 assert r.status_code==200 and r.json()==[],(table,r.status_code)
print(json.dumps({'isolation':'PASS','persisted_checks':'PASS','anonymous_access_denied':'PASS','runs':len(summaries)}),flush=True)
