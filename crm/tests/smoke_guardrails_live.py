"""Exercise server guardrails and save isolated evaluations; never delete a real record."""
from pathlib import Path
from uuid import uuid4
import requests,json,hashlib
base='https://orbit-crm-production-ace6467a.up.railway.app'
env=dict(x.split('=',1) for x in (Path(__file__).resolve().parents[1]/'.env').read_text().splitlines() if '=' in x)
s=requests.Session();r=s.post(base+'/api/login',json={'password':env['CRM_PASSWORD']},timeout=20);r.raise_for_status();headers={'X-CSRF-Token':r.json()['csrf']}
def get(path):
 r=s.get(base+'/api/'+path,timeout=30);r.raise_for_status();return r.json()
def fingerprint():return hashlib.sha256(json.dumps(get('data'),sort_keys=True).encode()).hexdigest()
before=fingerprint()
r=s.post(base+'/api/guardrails/evaluate',json={},headers=headers,timeout=90);r.raise_for_status();result=r.json()
assert result['total']==8 and result['passed']==8,result
for action in ('send_email','create_external_record','delete_crm'):
 r=s.post(base+'/api/guardrails/action',json={'action':action,'human_approval':True,'proposed_output':{'synthetic':True}},headers=headers,timeout=20);r.raise_for_status();assert r.json()['result']['verdict']=='blocked'
# A random non-existent ID is used to verify the API deletion boundary without risking a real row.
r=s.delete(base+'/api/contacts/'+str(uuid4()),headers=headers,timeout=20)
assert r.status_code==403 and r.json()['guardrail']['external_changes']==0,r.text
assert fingerprint()==before,'CRM records changed during guardrail evaluation'
for table in ('guardrail_events','guardrail_test_cases','guardrail_test_runs'):
 r=requests.get(env['SUPABASE_URL']+'/rest/v1/crm_'+table,headers={'apikey':env['SUPABASE_PUBLISHABLE_KEY']},timeout=20);assert r.ok and r.json()==[]
print(json.dumps({'status':'PASS','guardrail_cases':result['passed'],'forged_approval_did_not_bypass_policy':True,'deletion_api_blocked':True,'production_crm_unchanged':True}),flush=True)
