import os,sys,unittest
from datetime import datetime,timezone
from uuid import uuid4
from unittest.mock import Mock,patch
from copy import deepcopy
from flask import Flask,session
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from feedback_routes import register,review_suggestion,FeedbackError
from feedback_reporting import report,weekly_summary
from feedback_constants import REASONS,HIGH_RISK
from prompt_registry import prompt,use_prompts,BASELINES
from model_client import validate_suggestion
from evaluation_telemetry import collect_calls,record_response
from evaluation_runner import Sandbox,evaluate_one
from evaluation_fixtures import scenarios,rules,NOTE
from meeting_updates import propose,sandbox_executor

class DummyLimiter:
 def limit(self,*args,**kwargs):return lambda f:f

class FeedbackReviewTests(unittest.TestCase):
 def setUp(self):
  self.actor={'id':str(uuid4()),'username':'morgan','display_name':'Morgan Lee','team':'Sales','role':'admin','active':True}
  self.draft={'id':str(uuid4()),'status':'pending','workflow_type':'followup','original_suggestion':{'subject':'Hello','body':'Original message','next_action':'Review'},'context':{}}
  self.db=Mock(side_effect=lambda resource,*args,**kwargs:[self.actor] if resource=='reviewers' else [self.draft])
  self.rpc=Mock(return_value={'review_id':'review','message':'No message sent'})
  self.app=Flask('feedback_test');self.app.secret_key='test';register(self.app,self.db,self.rpc,DummyLimiter())
  @self.app.post('/test-review')
  def test_review():return review_suggestion(self.db,self.rpc,self.draft['id'])
  self.client=self.app.test_client()
  with self.client.session_transaction() as s:s['reviewer_id']=self.actor['id']
 def test_approval_uses_server_identity(self):
  r=self.client.post('/test-review',json={'action':'approve','reviewer_id':'forged'})
  self.assertEqual(r.status_code,200)
  payload=self.rpc.call_args.args[1]
  self.assertEqual(payload['p_reviewer'],self.actor['id']);self.assertIsNone(payload['p_final']);self.assertIsNone(payload['p_reason'])
 def test_every_rejection_reason_is_accepted(self):
  for reason in REASONS:
   self.assertEqual(self.client.post('/test-review',json={'action':'reject','reason':reason}).status_code,200)
 def test_reject_and_edit_require_reason(self):
  for action in ('reject','edit_approve'):
   self.assertEqual(self.client.post('/test-review',json={'action':action}).status_code,400)
  self.rpc.assert_not_called()
 def test_edit_requires_changed_final(self):
  r=self.client.post('/test-review',json={'action':'edit_approve','reason':'Incorrect tone','final_suggestion':self.draft['original_suggestion']})
  self.assertEqual(r.status_code,400);self.rpc.assert_not_called()
  final={**self.draft['original_suggestion'],'body':'A clearer, reviewed message'}
  r=self.client.post('/test-review',json={'action':'edit_approve','reason':'Incorrect tone','final_suggestion':final,'note':'Adjusted phrasing'})
  self.assertEqual(r.status_code,200);self.assertEqual(self.rpc.call_args.args[1]['p_final'],final)
 def test_duplicate_review_conflict(self):
  self.rpc.return_value={'error':'Suggestion is no longer pending.'}
  self.assertEqual(self.client.post('/test-review',json={'action':'approve'}).status_code,409)
 def test_inactive_or_missing_reviewer_cannot_review(self):
  self.actor['active']=False
  self.assertEqual(self.client.post('/test-review',json={'action':'approve'}).status_code,401)
  self.rpc.assert_not_called()
 def test_personal_login_error_does_not_expire_workspace(self):
  self.db.side_effect=lambda *args,**kwargs:[]
  r=self.client.post('/api/reviewer/login',json={'username':'missing','password':'wrong'})
  self.assertEqual(r.status_code,401);self.assertEqual(r.json['code'],'REVIEWER_AUTH_REQUIRED')
 def test_empty_reporting_preserves_aggregate_reason_list(self):
  self.db.side_effect=lambda *args,**kwargs:[]
  r=self.client.get('/api/feedback')
  self.assertEqual(r.status_code,200);self.assertEqual(r.json['reasons'],[]);self.assertEqual(len(r.json['reason_options']),8)
 def test_nonadmin_cannot_approve_or_release_prompt(self):
  self.actor['role']='reviewer'
  for endpoint in ('approve','release'):
   r=self.client.post('/api/prompt-versions/'+str(uuid4())+'/'+endpoint,json={'batch_id':str(uuid4())})
   self.assertEqual(r.status_code,403)
 def test_meeting_final_requires_source_evidence(self):
  self.draft.update(workflow_type='meeting_update',context={'notes':NOTE})
  final={'summary':'Reviewed meeting','next_action':'Verify pricing','commitments':[{'title':'Pricing update','owner':'Priya','due_date':'2026-11-21','source_evidence':'Invented source'}]}
  self.assertEqual(self.client.post('/test-review',json={'action':'edit_approve','reason':'Wrong deadline','final_suggestion':final}).status_code,400)
 def test_password_hash_not_in_public_profiles(self):
  self.actor['password_hash']='not-for-browser'
  data=self.client.get('/api/reviewer').json
  self.assertNotIn('password_hash',data['reviewer']);self.assertNotIn('password_hash',data['reviewers'][0])

class ReportingTests(unittest.TestCase):
 def rows(self):
  return [{'id':str(i),'action':action,'reason':reason,'workflow':'followup' if i%2 else 'meeting_update','team':'Sales','model':'model','prompt_label':'followup/v1','reviewed_at':'2026-11-17T18:00:00Z'} for i,(action,reason) in enumerate([('approve',None),('reject','Wrong owner'),('edit_approve','Wrong deadline'),('reject','Wrong owner'),('reject','Hallucinated or unsupported information'),('edit_approve','Incorrect tone')])]
 def test_rates_high_risk_and_dimensions(self):
  r=report(self.rows());self.assertEqual(r['overall']['total'],6);self.assertEqual(r['overall']['approvals'],1);self.assertEqual(r['overall']['rejections'],3);self.assertEqual(r['overall']['edits'],2)
  self.assertEqual(r['high_risk_count'],4);self.assertEqual(r['reasons'][0]['reason'],'Wrong owner');self.assertEqual(len(r['dimensions']['workflow']),2)
 def test_summary_top_three_and_no_prompt_writes(self):
  rows=self.rows();writes=[]
  def db(resource,method='GET',data=None,record_id=None,extra_params=None):
   if method=='POST':writes.append((resource,data));return [{'id':'report',**data}]
   return rows if resource=='suggestion_reviews' else []
  result=weekly_summary(db,now=datetime(2026,11,18,tzinfo=timezone.utc))
  self.assertEqual(len(result['patterns']),3);self.assertEqual(result['patterns'][0]['reason'],'Wrong owner');self.assertEqual(writes[0][0],'weekly_quality_summaries')
  self.assertTrue(all(p['business_risk'] and p['recommended_evaluation_case'] for p in result['patterns']))
 def test_empty_summary_does_not_invent_three_patterns(self):
  def db(resource,method='GET',data=None,record_id=None,extra_params=None):return [{'id':'report',**data}] if method=='POST' else []
  self.assertEqual(weekly_summary(db,now=datetime(2026,11,18,tzinfo=timezone.utc))['patterns'],[])
 def test_closed_week_excludes_current_week(self):
  writes=[]
  def db(resource,method='GET',data=None,record_id=None,extra_params=None):
   if method=='POST':writes.append(data);return [{'id':'r',**data}]
   return self.rows() if resource=='suggestion_reviews' else []
  r=weekly_summary(db,closed=True,now=datetime(2026,11,23,16,tzinfo=timezone.utc))
  self.assertEqual(r['week_start'],'2026-11-16');self.assertEqual(r['week_end'],'2026-11-23');self.assertEqual(r['review_count'],6)

class PromptAndMeetingTests(unittest.TestCase):
 def test_candidate_prompt_does_not_leak_to_production(self):
  original=prompt()['system_prompt']
  with use_prompts({'followup':{'system_prompt':'candidate','id':'v2'}}):self.assertEqual(prompt()['system_prompt'],'candidate')
  self.assertEqual(prompt()['system_prompt'],original)
 def test_nested_telemetry_keeps_outer_evaluation_cost(self):
  class Response:
   status_code=200
   def json(self):return {'usage':{'cost':.001},'model':'model'}
  with collect_calls() as outer:
   with collect_calls() as inner:record_response(Response(),.1,'model')
  self.assertEqual(len(inner),1);self.assertEqual(len(outer),1)
 @patch('meeting_updates.generate')
 def test_meeting_proposal_is_idempotent_and_never_applies_tasks(self,generate):
  generate.return_value={'summary':'Pricing discussion','next_action':'Review commitment','commitments':[{'title':'Pricing update','owner':'Priya','due_date':'2026-11-21','source_evidence':NOTE}]}
  fixture=next(s for s in scenarios() if s['scenario_number']==7);box=Sandbox(fixture['input_context'])
  original=deepcopy(box.rows)
  sandbox_executor(box);sandbox_executor(box)
  self.assertEqual(generate.call_count,1);self.assertEqual(len(box.rows['followups']),1);self.assertEqual(box.rows['tasks'],[]);self.assertEqual(box.rows['contacts'],original['contacts'])
  self.assertFalse(any(o['resource']=='tasks' and o['method']!='GET' for o in box.operations))
 def test_invalid_model_meeting_output_is_rejected(self):
  with self.assertRaises(ValueError):validate_suggestion({'summary':'ok','commitments':[{'title':'x','owner':'Priya','due_date':'tomorrow','source_evidence':NOTE}],'next_action':'review'},'meeting_update',NOTE)
