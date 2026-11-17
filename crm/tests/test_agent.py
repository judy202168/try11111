import os,sys,unittest
from datetime import datetime,timezone
from unittest.mock import patch,Mock
sys.path.insert(0,os.path.dirname(os.path.dirname(__file__)))
from followup_agent import candidates,generate,run
class AgentTests(unittest.TestCase):
 def test_stalled_and_closed(self):
  old={'id':'1','created_at':'2026-01-01T00:00:00Z','status':'Active'}
  fresh={**old,'id':'2','last_activity_at':'2026-11-15T00:00:00Z'}
  rows=list(candidates([old,fresh],[{**old,'stage':'Won'},{**old,'stage':'Lost'}],datetime(2026,11,16,tzinfo=timezone.utc)))
  self.assertEqual(len(rows),1)
 @patch.dict(os.environ,{'OPENROUTER_API_KEY':'test'})
 @patch('followup_agent.requests.post')
 def test_model_json_validation(self,post):
  post.return_value=Mock(ok=True,json=lambda:{'choices':[{'message':{'content':'{"subject":"Hello","body":"Checking in","next_action":"Review draft"}'}}]})
  self.assertEqual(generate({})['next_action'],'Review draft')
  self.assertNotIn('tools',post.call_args.kwargs['json'])
  post.return_value.json=lambda:{'choices':[{'message':{'content':'bad json'}}]}
  with self.assertRaises(RuntimeError):generate({})
 @patch.dict(os.environ,{'OPENROUTER_API_KEY':'test'})
 @patch('followup_agent.generate')
 def test_dedupe(self,generate):
  version='2026-01-01T00:00:00+00:00'
  rows={'contacts':[{'id':'1','created_at':version,'status':'Active'}],'deals':[],'tasks':[],'followups':[{'entity_type':'contacts','entity_id':'1','activity_version':version}]}
  result=run(lambda resource:rows[resource]);self.assertEqual(result['skipped'],1);generate.assert_not_called()

class ReviewTests(unittest.TestCase):
 def setUp(self):
  from app import app,limiter
  app.config.update(TESTING=True,SESSION_COOKIE_SECURE=False)
  limiter.enabled=False
  self.client=app.test_client()
  with self.client.session_transaction() as session:session.update(authenticated=True,csrf='test')
  self.headers={'X-CSRF-Token':'test'}
 @patch('agent_routes.active_prompts',return_value={})
 @patch('agent_routes.run')
 def test_manual_run(self,run,prompts):
  run.return_value={'created':1,'failed':0,'skipped':0}
  self.assertEqual(self.client.post('/api/followups/run',json={},headers=self.headers).status_code,200)
 def test_workspace_password_alone_cannot_review(self):
  response=self.client.post('/api/followups/5d8195fe-1051-4df3-a1e5-e42fcb1523a5/review',json={'action':'approve'},headers=self.headers)
  self.assertEqual(response.status_code,401)
  self.assertIn('personal reviewer',response.json['error'])
