"""Opt-in live integration test. Creates test records and removes only those records."""
import os
import json
from pathlib import Path
import requests

root=Path(__file__).resolve().parents[1]
env=dict(line.split('=',1) for line in (root/'.env').read_text().splitlines() if '=' in line)
url='https://orbit-crm-production-ace6467a.up.railway.app'
s=requests.Session()
assert s.get(url+'/health',timeout=20).json()['database_configured']
assert s.get(url+'/api/data',timeout=20).status_code==401
r=s.post(url+'/api/login',json={'password':env['CRM_PASSWORD']},timeout=20)
assert r.status_code==200,r.text
headers={'X-CSRF-Token':r.json()['csrf']}
assert s.post(url+'/api/contacts',json={'name':'Blocked Test'},timeout=20).status_code==403
r=s.get(url+'/api/data',timeout=30)
assert r.status_code==200,r.text
counts={k:len(v) for k,v in r.json().items()}
assert counts=={'contacts':24,'deals':22,'tasks':16},counts
created=[]
try:
 for resource,payload in [('contacts',{'name':'Disposable Integration Test','email':'test@example.com','company':'Synthetic QA'}),('deals',{'title':'Disposable Test Deal','value':12345,'stage':'Lead'}),('tasks',{'title':'Disposable Test Follow-up','due_date':'2026-11-20'})]:
  if created:payload['contact_id']=created[0][1]
  r=s.post(url+'/api/'+resource,json=payload,headers=headers,timeout=20)
  assert r.status_code==201,(resource,r.text)
  created.append((resource,r.json()['record']['id']))
 updates=[('contacts',{'status':'Customer'}),('deals',{'stage':'Won','value':24500}),('tasks',{'done':True})]
 for (resource,id),(_,payload) in zip(created,updates):
  r=s.patch(url+'/api/'+resource+'/'+id,json=payload,headers=headers,timeout=20)
  assert r.status_code==200,r.text
  for key,value in payload.items():assert r.json()['record'][key]==value,r.text
 # Fresh reads must reflect persisted changes.
 data=s.get(url+'/api/data',timeout=30).json()
 for (resource,id),(_,payload) in zip(created,updates):
  record=next(x for x in data[resource] if x['id']==id)
  for key,value in payload.items():assert record[key]==value
finally:
 for resource,id in reversed(created):
  r=s.delete(url+'/api/'+resource+'/'+id,headers=headers,timeout=20)
  assert r.status_code==200,r.text
# Publishable key alone must not expose records or accept writes.
rest=env['SUPABASE_URL']+'/rest/v1/crm_contacts'
r=requests.get(rest,headers={'apikey':env['SUPABASE_PUBLISHABLE_KEY']},timeout=20)
assert r.status_code==200 and r.json()==[],r.text
r=requests.post(rest,headers={'apikey':env['SUPABASE_PUBLISHABLE_KEY']},json={'name':'Blocked Anonymous'},timeout=20)
assert r.status_code in (401,403),r.text
assert s.post(url+'/api/logout',headers=headers,timeout=20).status_code==200
assert s.get(url+'/api/data',timeout=20).status_code==401
print(json.dumps({'status':'PASS','seed_counts':counts,'checks':['login','session','csrf','create','edit','persisted reads','delete','anonymous database denial','logout']}))
