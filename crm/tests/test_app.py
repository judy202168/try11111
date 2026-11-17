import os
import sys
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.update(CRM_PASSWORD='test-only-password', SECRET_KEY='unit-test-secret', COOKIE_SECURE='false', SUPABASE_URL='https://unit-test.supabase.co', SUPABASE_PUBLISHABLE_KEY='publishable-test', CRM_DATABASE_TOKEN='backend-test')
from app import app, limiter

class CRMTests(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        limiter.enabled = False
        self.client = app.test_client()
    def login(self):
        result = self.client.post('/api/login', json={'password':'test-only-password'})
        self.assertEqual(result.status_code, 200)
        self.headers={'X-CSRF-Token':result.json['csrf']}
    def test_requires_login(self):
        self.assertEqual(self.client.get('/api/data').status_code,401)
        self.assertEqual(self.client.post('/api/contacts',json={'name':'Test'}).status_code,401)
    def test_login_and_session(self):
        self.assertEqual(self.client.post('/api/login',json={'password':'wrong'}).status_code,401)
        self.login()
        self.assertTrue(self.client.get('/api/session').json['authenticated'])
    def test_csrf_and_origin(self):
        self.login()
        self.assertEqual(self.client.post('/api/contacts',json={'name':'Test'}).status_code,403)
        self.assertEqual(self.client.post('/api/contacts',json={'name':'Test'},headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
    @patch('app.db')
    def test_contact_create_and_edit(self,db):
        self.login()
        db.return_value=[{'id':'5d8195fe-1051-4df3-a1e5-e42fcb1523a5','name':'Test Contact'}]
        response=self.client.post('/api/contacts',json={'name':' Test Contact ','email':'hello@example.com'},headers=self.headers)
        self.assertEqual(response.status_code,201)
        self.assertEqual(db.call_args.args[2]['name'],'Test Contact')
        response=self.client.patch('/api/contacts/5d8195fe-1051-4df3-a1e5-e42fcb1523a5',json={'status':'Customer'},headers=self.headers)
        self.assertEqual(response.status_code,200)
    @patch('app.db')
    def test_data(self,db):
        self.login()
        db.return_value=[]
        self.assertEqual(set(self.client.get('/api/data').json),{'contacts','deals','tasks'})
    def test_validation_rejects_bad_inputs(self):
        self.login()
        cases=[('contacts',{'name':''}),('contacts',{'name':'A','admin':True}),('contacts',{'name':'A','email':'no-email'}),('deals',{'title':'Deal','value':-1}),('deals',{'title':'Deal','value':float('inf')}),('deals',{'title':'Deal','stage':'Unexpected'}),('tasks',{'title':'Task','due_date':'nonsense'}),('tasks',{'title':'Task','done':'yes'})]
        for resource,payload in cases:
            self.assertEqual(self.client.post('/api/'+resource,json=payload,headers=self.headers).status_code,400)
    @patch('app.requests.request')
    def test_backend_token_not_service_role(self,req):
        self.login()
        req.return_value=Mock(ok=True,content=b'[]',json=lambda:[])
        self.assertEqual(self.client.get('/api/data').status_code,200)
        self.assertEqual(req.call_args.kwargs['headers']['X-CRM-Token'],'backend-test')
        self.assertNotIn('Authorization',req.call_args.kwargs['headers'])
    @patch('app.db',side_effect=RuntimeError('Database unavailable'))
    def test_database_error(self,db):
        self.login()
        self.assertEqual(self.client.get('/api/data').status_code,503)
    def test_logout(self):
        self.login()
        self.assertEqual(self.client.post('/api/logout',headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/data').status_code,401)
    def test_health_and_html(self):
        self.assertEqual(self.client.get('/health').json['status'],'ok')
        result=self.client.get('/')
        self.assertEqual(result.status_code,200)
        self.assertIn(b'Workspace overview',result.data)
        self.assertEqual(result.headers['X-Frame-Options'],'DENY')

if __name__=='__main__':unittest.main()
