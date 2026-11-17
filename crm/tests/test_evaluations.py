import os,sys,unittest
from copy import deepcopy
from unittest.mock import patch
from uuid import uuid4
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from evaluation_fixtures import scenarios,rules,NOTE
from evaluation_runner import Sandbox,checks_for,evaluate_one,proposed
from evaluation_telemetry import collect_calls,cost_summary,record_response

def case(number):return next(s for s in scenarios() if s['scenario_number']==number)
def case_rules(number):return [r for r in rules() if r['scenario_id']==case(number)['id']]
def output(number):
 c=case(number)['input_context'];contact=c['contacts'][0];deal=c['deals'][0]
 draft={'id':'test','contact_id':contact['id'],'opportunity_id':deal['id'],'owner':contact['owner'],'subject':'Enterprise expansion proposal','body':'Hi Avery, following up on your Enterprise expansion proposal request.'}
 return {'drafts':[draft],'tasks':[],'sent_count':0,'blocked_reasons':[],'suggested_actions':[],'first_run_counts':{'drafts':1,'tasks':0},'second_run_counts':{'drafts':1,'tasks':0}}

class EvaluationTests(unittest.TestCase):
 def test_positive_dormant_and_duplicate_negative(self):
  c=case(1);o=output(1)
  self.assertTrue(all(x['passed'] for x in checks_for(o,c['input_context'],case_rules(1))))
  o['drafts'].append(deepcopy(o['drafts'][0]))
  checks={x['rule_key']:x['passed'] for x in checks_for(o,c['input_context'],case_rules(1))}
  self.assertFalse(checks['draft_count']);self.assertFalse(checks['no_duplicate_action'])
 def test_missing_email_and_fabrication(self):
  c=case(5);o=output(5);o.update(drafts=[],blocked_reasons=['Email is missing'],suggested_actions=[{'owner':'Morgan Lee','action':'Verify contact information before choosing an approved channel.'}])
  self.assertTrue(all(x['passed'] for x in checks_for(o,c['input_context'],case_rules(5))))
  o['drafts']=output(5)['drafts'];o['drafts'][0]['body']='Reach out to fabricated@example.com'
  checks={x['rule_key']:x['passed'] for x in checks_for(o,c['input_context'],case_rules(5))}
  self.assertFalse(checks['no_invented_contact']);self.assertFalse(checks['draft_count'])
 def test_exact_deadline_owner_and_evidence(self):
  c=case(7);o=output(7);o['drafts']=[]
  o['tasks']=[{'title':'Pricing update','owner':'Priya','due_date':'2026-11-21','contact_id':c['input_context']['contacts'][0]['id'],'opportunity_id':c['input_context']['deals'][0]['id'],'source_note':NOTE,'meeting_date':'2026-11-10'}]
  self.assertTrue(all(x['passed'] for x in checks_for(o,c['input_context'],case_rules(7))))
  for field,value,failed_key in [('due_date','2026-11-22','exact_due_date'),('owner','Morgan Lee','task_owner'),('source_note','Estimated date','source_evidence')]:
   bad=deepcopy(o);bad['tasks'][0][field]=value
   checks={x['rule_key']:x['passed'] for x in checks_for(bad,c['input_context'],case_rules(7))}
   self.assertFalse(checks[failed_key]);self.assertFalse(checks['no_unsupported_commitment'])
 def test_sandbox_deep_copy_and_no_external_resources(self):
  c=case(1);original=deepcopy(c)
  box=Sandbox(c['input_context']);box('contacts','PATCH',{'name':'Changed'},c['input_context']['contacts'][0]['id'])
  self.assertEqual(c,original)
  with self.assertRaises(RuntimeError):box('messages','POST',{'body':'Send'})
  self.assertEqual(len(box.violations),1)
 @patch.dict(os.environ,{'OPENROUTER_API_KEY':'mock-key'})
 @patch('followup_agent.generate',return_value={'subject':'Hi','body':'Hello Avery','next_action':'Review draft'})
 def test_actual_agent_detects_failures_and_only_saves_evaluation_rows(self,generate):
  saved=[];c=case(1)
  def save(resource,method='GET',data=None,record_id=None):
   self.assertTrue(resource.startswith('evaluation_'));saved.append((resource,method,data))
   return [{'id':str(uuid4()),**data}] if isinstance(data,dict) else data
  result=evaluate_one(c,case_rules(1),save,str(uuid4()))
  self.assertEqual(result['status'],'failed')
  self.assertEqual(len(result['proposed_output']['drafts']),2)
  self.assertEqual(generate.call_count,2) # Replay does not generate more.
  self.assertEqual(result['proposed_output']['first_run_counts'],result['proposed_output']['second_run_counts'])
  self.assertEqual(saved[-2][0],'evaluation_check_results')
 @patch('followup_agent.run',side_effect=RuntimeError('Provider unavailable'))
 def test_generation_error_is_logged_as_error(self,run):
  saved=[]
  def save(resource,method='GET',data=None,record_id=None):
   saved.append((resource,data));return [{'id':str(uuid4()),**data}] if isinstance(data,dict) else data
  result=evaluate_one(case(5),case_rules(5),save,str(uuid4()))
  self.assertEqual(result['status'],'error');self.assertIn('Provider unavailable',result['failure_reason'])
  checks=next(data for resource,data in saved if resource=='evaluation_check_results')
  self.assertTrue(all(not c['passed'] for c in checks))
 def test_cost_unavailable_is_not_zero(self):
  calls=[{'usage':{'prompt_tokens':100,'completion_tokens':10,'cost':None}}]
  self.assertEqual(cost_summary(calls),(None,'unavailable'))
  value,source=cost_summary(calls,{'prompt':'0.000001','completion':'0.000002'})
  self.assertAlmostEqual(value,.00012);self.assertEqual(source,'token_estimate')
 def test_request_scoped_telemetry(self):
  class Response:
   status_code=200
   def json(self):return {'model':'test-model','usage':{'cost':.001}}
  with collect_calls() as calls:record_response(Response(),.2,'requested')
  self.assertEqual(len(calls),1)
  record_response(Response(),.2,'requested')
  self.assertEqual(len(calls),1)

class EvaluationAPITests(unittest.TestCase):
 def setUp(self):
  from app import app,limiter
  self.app=app;app.config.update(TESTING=True,SESSION_COOKIE_SECURE=False);limiter.enabled=False
  self.client=app.test_client()
 def login(self):
  with self.client.session_transaction() as session:session.update(authenticated=True,csrf='test')
 def test_auth_and_csrf(self):
  self.assertEqual(self.client.get('/api/evaluations').status_code,401)
  self.login();self.assertEqual(self.client.post('/api/evaluations/run',json={'scenario_id':case(1)['id']}).status_code,403)
 def test_reject_bad_run_payload(self):
  self.login()
  self.assertEqual(self.client.post('/api/evaluations/run',json={'scenario_id':'not-an-id'},headers={'X-CSRF-Token':'test'}).status_code,400)
