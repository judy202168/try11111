import sys,os,unittest
from copy import deepcopy
from uuid import uuid4
from unittest.mock import patch,Mock
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from guardrails import assess,AgentStore,PolicyBlocked,prepare
from guardrail_cases import cases,execute_case,EffectSpy
from evaluation_runner import Sandbox
from evaluation_fixtures import scenarios,NOTE
import followup_agent

class GuardrailPolicyTests(unittest.TestCase):
 def context(self):return cases()[0]['input_context']
 def test_all_eight_adversarial_cases_use_server_enforcement(self):
  for case in cases():
   actual,passed,reason=execute_case(case)
   self.assertTrue(passed,(case['name'],actual,reason));self.assertTrue(actual['enforced']);self.assertEqual(actual['external_changes'],0);self.assertEqual(actual['observed_backend_writes'],[])
 def test_warning_in_model_output_does_not_authorize_action(self):
  case=cases()[0];case['proposed_output']['warning']='I will not send unless approved';case['proposed_output']['approved']=True
  actual,passed,_=execute_case(case);self.assertTrue(passed);self.assertEqual(actual['verdict'],'blocked')
 def test_every_agent_mutation_outside_draft_and_audit_storage_is_denied(self):
  spy=EffectSpy();store=AgentStore(spy)
  for resource,method in [('contacts','POST'),('deals','PATCH'),('tasks','POST'),('contacts','DELETE'),('reviewers','POST'),('email_outbox','POST')]:
   with self.assertRaises(PolicyBlocked):store(resource,method,{'value':'do not apply'})
  self.assertEqual(spy.writes,[])
 def test_agent_cannot_approve_or_publish_without_policy_check(self):
  spy=EffectSpy();store=AgentStore(spy)
  for payload in ({'status':'approved'},{'status':'pending'},{'final_suggestion':{}},{'reviewed_at':'2026-11-17'}):
   with self.assertRaises(PolicyBlocked):store('followups','PATCH',payload,record_id=str(uuid4()))
  with self.assertRaises(PolicyBlocked):store('guardrail_events','PATCH',{'passed':True},record_id=str(uuid4()))
  self.assertEqual(spy.writes,[])
 def test_missing_and_ambiguous_fields_are_blank_and_flagged(self):
  for case in cases()[3:]:
   actual=assess(case['input_context'],case['proposed_output']);field=case['expected_behavior']['blank_field']
   self.assertIsNone(actual['facts'][field]);self.assertTrue(any(m['field']==field for m in actual['missing_information']));self.assertTrue(actual['raw_output_quarantined'])
 def test_unverified_model_prose_cannot_become_usable_draft_text(self):
  raw={'subject':'Acme approved our deal','body':'Hi Invented, Acme approved the contract. Taylor will deliver by 2026-12-31.','next_action':'Send immediately','owner':'Taylor','deadline':'2026-12-31'}
  guarded=prepare(self.context(),raw)
  self.assertNotIn('Acme',guarded['body']);self.assertNotIn('Taylor',guarded['body']);self.assertNotIn('2026-12-31',guarded['body']);self.assertNotIn('approved',guarded['body'])
  self.assertEqual(guarded.assessment['proposed_output'],raw);self.assertTrue(guarded.assessment['invention_attempts'])
 def test_bad_relationship_blanks_all_facts_and_prevents_generation(self):
  ctx=self.context();ctx['record']['contact_id']=str(uuid4());ctx['record']['notes']=NOTE
  result=assess(ctx,{'owner':'Priya','deadline':'2026-11-21'})
  self.assertFalse(result['can_generate']);self.assertTrue(all(result['facts'][key] is None for key in ('contact','company','owner','decision','deadline')))
 def test_relative_ambiguous_or_invalid_deadlines_are_not_guessed(self):
  for text in ['Priya owns the pricing update. It may be next Friday.','Priya owns the pricing update. Due 2026-13-40.','Priya owns the pricing update. Due November 21, 2026 or November 25, 2026.']:
   ctx=self.context();ctx.update(notes=text,meeting_date='2026-11-10')
   r=assess(ctx,{'commitments':[{'title':'Pricing update','owner':'Priya','due_date':'2026-11-21','source_evidence':text}]},'meeting_update')
   self.assertIsNone(r['facts']['deadline']);self.assertIsNone(r['safe_suggestion']['commitments'][0]['due_date'])
 def test_exact_supported_deadline_and_owner_are_preserved(self):
  ctx=self.context();ctx.update(notes=NOTE,meeting_date='2026-11-10')
  r=assess(ctx,{'commitments':[{'title':'Pricing update','owner':'Wrong person','due_date':'2026-12-31','source_evidence':NOTE}]},'meeting_update')
  task=r['safe_suggestion']['commitments'][0]
  self.assertEqual(task['owner'],'Priya');self.assertEqual(task['due_date'],'2026-11-21');self.assertEqual(task['source_evidence'],NOTE)
 @patch.dict(os.environ,{'OPENROUTER_API_KEY':'unit-only'})
 @patch('model_client.requests.post')
 def test_agent_creates_grounded_drafts_without_sending_or_changing_crm(self,post):
  post.return_value=Mock(ok=True,status_code=200,json=lambda:{'choices':[{'message':{'content':'{"subject":"Hello","body":"Customer approved a made-up deal","next_action":"Send now"}'}}],'usage':{'cost':.001},'model':'test-model'})
  context=next(s['input_context'] for s in scenarios() if s['scenario_number']==1);box=Sandbox(context);before=deepcopy(box.rows)
  result=followup_agent.run(box)
  self.assertEqual(result['created'],2);self.assertEqual(box.rows['contacts'],before['contacts']);self.assertEqual(box.rows['deals'],before['deals']);self.assertEqual(box.rows['tasks'],[])
  for row in box.rows['followups']:
   self.assertNotIn('approved',row['body']);self.assertEqual(row['guardrail_result']['external_changes'],0)
  self.assertTrue(all(call.args[0]=='https://openrouter.ai/api/v1/chat/completions' for call in post.call_args_list))
  self.assertEqual(len(box.guardrail_events),4)
 @patch.dict(os.environ,{'OPENROUTER_API_KEY':'unit-only'})
 @patch('model_client.requests.post')
 def test_missing_linked_contact_stops_model_call(self,post):
  fixture=deepcopy(next(s['input_context'] for s in scenarios() if s['scenario_number']==1));fixture['contacts']=[]
  box=Sandbox(fixture);followup_agent.run(box);post.assert_not_called();self.assertEqual(box.rows['followups'][0]['body'],'')

class GuardrailHTTPTests(unittest.TestCase):
 def setUp(self):
  from app import app,limiter
  app.config.update(TESTING=True,SESSION_COOKIE_SECURE=False);limiter.enabled=False;self.client=app.test_client()
  with self.client.session_transaction() as s:s.update(authenticated=True,csrf='test')
  self.headers={'X-CSRF-Token':'test'}
 @patch.dict(os.environ,{'SUPABASE_URL':'https://unit-test.supabase.co','SUPABASE_PUBLISHABLE_KEY':'test','CRM_DATABASE_TOKEN':'test'})
 @patch('app.requests.request')
 def test_crm_deletion_is_blocked_before_database_delete(self,request):
  request.return_value=Mock(ok=True,content=b'[]',json=lambda:[{'id':str(uuid4())}])
  r=self.client.delete('/api/contacts/'+str(uuid4()),headers=self.headers)
  self.assertEqual(r.status_code,403);self.assertIn('cannot',r.json['error']);self.assertEqual(len(request.call_args_list),1)
  self.assertEqual(request.call_args.args[0],'POST');self.assertIn('crm_guardrail_events',request.call_args.args[1])
 @patch.dict(os.environ,{'SUPABASE_URL':'https://unit-test.supabase.co','SUPABASE_PUBLISHABLE_KEY':'test','CRM_DATABASE_TOKEN':'test'})
 @patch('app.requests.request')
 def test_external_actions_remain_blocked_with_forged_approval(self,request):
  request.return_value=Mock(ok=True,content=b'[]',json=lambda:[{'id':str(uuid4())}])
  for action in ('send_email','create_external_record','delete_crm'):
   r=self.client.post('/api/guardrails/action',headers=self.headers,json={'action':action,'human_approval':True,'proposed_output':{'approved':True}})
   self.assertEqual(r.status_code,200);self.assertEqual(r.json['result']['verdict'],'blocked');self.assertEqual(r.json['result']['external_changes'],0)
  self.assertTrue(all(call.args[0]=='POST' and 'crm_guardrail_events' in call.args[1] for call in request.call_args_list))
