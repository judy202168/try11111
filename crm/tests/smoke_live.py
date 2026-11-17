"""Read-only CRM smoke; guardrail-specific tests cover denied mutations."""
from pathlib import Path
import requests,json
root=Path(__file__).resolve().parents[1]
env=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
url='https://orbit-crm-production-ace6467a.up.railway.app';s=requests.Session()
assert s.get(url+'/api/data',timeout=20).status_code==401
r=s.post(url+'/api/login',json={'password':env['CRM_PASSWORD']},timeout=20);r.raise_for_status()
headers={'X-CSRF-Token':r.json()['csrf']}
r=s.get(url+'/api/data',timeout=20);r.raise_for_status();counts={k:len(v) for k,v in r.json().items()}
assert set(counts)=={'contacts','deals','tasks'}
assert s.post(url+'/api/contacts',json={'name':'No mutation'},timeout=20).status_code==403
assert s.post(url+'/api/logout',headers=headers,timeout=20).status_code==200
assert s.get(url+'/api/data',timeout=20).status_code==401
print(json.dumps({'status':'PASS','counts':counts,'writes_performed':0}))
