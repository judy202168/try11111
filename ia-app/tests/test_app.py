import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

# Import the app through its explicit test-only JSON adapter. Production startup
# requires Supabase environment variables and never selects this path.
os.environ.setdefault('LAB_DATA_FILE', str(Path(tempfile.gettempdir()) / 'jd-lab-test-bootstrap.json'))
import app as lab


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(lab, 'DATA_FILE', Path(self.temp.name) / 'data.json')
        self.path_patch.start()
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.client = lab.app.test_client()

    def tearDown(self):
        self.env_patch.stop()
        self.path_patch.stop()
        self.temp.cleanup()

    def resource(self, **overrides):
        value = {'title': 'Evidence completeness', 'content': 'Compare evidence to the requested period.', 'kind': 'article', 'status': 'Draft', 'category': 'Testing', 'tags': ['evidence']}
        value.update(overrides)
        response = self.client.post('/api/resources', json=value)
        self.assertEqual(response.status_code, 201)
        return response.json

    def test_empty_state_and_frontend(self):
        self.assertEqual(self.client.get('/api/state').json['resources'], [])
        self.assertEqual(self.client.get('/api/state').json['activity'], [])
        with self.client.get('/') as response:
            self.assertIn(b'tailwind', response.data)

    def test_crud_persistence_and_export(self):
        resource = self.resource()
        on_disk = json.loads(lab.DATA_FILE.read_text())
        self.assertEqual(on_disk['resources'][0]['title'], resource['title'])
        edited = copy.deepcopy(resource)
        edited.update(title='Revised evidence checks', status='Reviewed')
        self.assertEqual(self.client.put('/api/resources/'+resource['id'], json=edited).status_code, 200)
        self.assertEqual(self.client.get('/api/export').json['resources'][0]['title'], edited['title'])
        self.assertIn('attachment', self.client.get('/api/export').headers['Content-Disposition'])
        self.assertEqual(self.client.delete('/api/resources/'+resource['id']).status_code, 204)
        self.assertEqual(lab.read_store()['resources'], [])
        self.assertEqual(len(lab.read_store()['activity']), 3)
        self.assertEqual(self.client.delete('/api/resources/'+resource['id']).status_code, 404)

    def test_validation_does_not_modify_store(self):
        for payload in ({}, {'title': 'x', 'kind': 'unknown'}, {'title': ['invalid']}):
            self.assertEqual(self.client.post('/api/resources', json=payload).status_code, 400)
        self.assertFalse(lab.DATA_FILE.exists())
        self.assertEqual(self.client.post('/api/resources', json=[]).status_code, 400)

    def test_project_and_profile(self):
        resource = self.resource(kind='project', phase='Build', owner='Test owner', results='Measured result', lessons='Document the inputs')
        self.assertEqual(resource['phase'], 'Build')
        self.assertEqual(self.client.put('/api/profile', json={'name': 'Test profile', 'approach': 'Evidence first'}).status_code, 200)
        self.assertEqual(lab.read_store()['profile']['approach'], 'Evidence first')
        self.assertEqual(lab.read_store()['profile']['background'], '')

    def test_draft_excluded_and_local_search_persisted(self):
        resource = self.resource()
        query = {'question': 'Check evidence completeness', 'task': 'Review information'}
        response = self.client.post('/api/assistant', json=query)
        self.assertEqual(response.json['sources'], [])
        self.assertIn('No matching', response.json['answer'])
        resource['status'] = 'Reviewed'
        self.client.put('/api/resources/'+resource['id'], json=resource)
        response = self.client.post('/api/assistant', json=query)
        self.assertEqual(response.json['mode'], 'Local resource search')
        self.assertEqual(response.json['sources'][0]['id'], resource['id'])
        self.assertIn('Compare evidence', response.json['answer'])
        self.assertEqual(len(lab.read_store()['conversations']), 2)

    def test_ai_payload_response_and_failure(self):
        self.resource(status='Reviewed')
        os.environ['OPENAI_API_KEY'] = 'test-key'
        response = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Working draft [1]'}]}]}
        with patch.object(lab.request, 'urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as send:
            reply = self.client.post('/api/assistant', json={'question': 'Evidence completeness', 'task': 'Prepare a draft', 'evidence': 'Working notes'})
            self.assertEqual(reply.status_code, 200)
            self.assertEqual(reply.json['mode'], 'AI draft')
            payload = json.loads(send.call_args.args[0].data)
            self.assertFalse(payload['store'])
            self.assertEqual(json.loads(payload['input'])['user_evidence'], 'Working notes')
        with patch.object(lab.request, 'urlopen', side_effect=URLError('offline')):
            reply = self.client.post('/api/assistant', json={'question': 'Evidence completeness', 'task': 'Analyze findings'})
            self.assertEqual(reply.status_code, 502)
        self.assertEqual(len(lab.read_store()['conversations']), 1)

    def test_builder_request_saved_without_exposing_contacts_in_state(self):
        response = self.client.post('/api/builder/demo-requests', json={'name': 'Verification requester', 'email': 'verification@example.com', 'message': 'Explore the SOC review workflow.'})
        self.assertEqual(response.status_code, 201)
        self.assertIn('No email was sent', response.json['message'])
        self.assertEqual(lab.read_store()['builder_requests'][0]['email'], 'verification@example.com')
        self.assertNotIn('builder_requests', self.client.get('/api/state').json)
        self.assertEqual(lab.read_store()['activity'][0]['action'], 'Builder demo request saved')

    def test_builder_request_rejects_invalid_email_without_saving(self):
        response = self.client.post('/api/builder/demo-requests', json={'name': 'Verification requester', 'email': 'not-an-email', 'message': 'Explore a workflow.'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(lab.read_store()['builder_requests'], [])

    def test_cross_origin_write_rejected(self):
        response = self.client.put('/api/profile', json={'name': 'Unwanted'}, headers={'Origin': 'https://external.test'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(lab.DATA_FILE.exists())


if __name__ == '__main__':
    unittest.main()
