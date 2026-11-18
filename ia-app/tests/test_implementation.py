import copy
import csv
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify
from implementation.routes import register_implementation, requirements
from implementation.template import TEMPLATE


class ImplementationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store_file = Path(self.temp.name) / 'data.json'
        self.store_file.write_text(json.dumps({'implementation_assessments': [], 'activity': []}))
        self.app = Flask('implementation-test')
        self.app.testing = True
        @self.app.errorhandler(ValueError)
        def invalid(exc):
            return jsonify(error=str(exc)), 400
        def read():
            return json.loads(self.store_file.read_text())
        def write(data):
            self.store_file.write_text(json.dumps(data))
        self.read = read
        register_implementation(self.app, read, write, threading.RLock(), lambda d,a,t:d['activity'].append({'action':a,'title':t}), Path(self.temp.name)/'evidence', lambda:datetime.now(timezone.utc).isoformat())
        self.client = self.app.test_client()
        self.assessment = self.client.post('/api/implementation/assessments', json={'title':'Verification assessment','system_name':'Verification system','source_system':'Prior system'}).json
        self.id = self.assessment['id']

    def tearDown(self):
        self.temp.cleanup()

    def save(self, item_id, **changes):
        current = self.client.get('/api/implementation/assessments/'+self.id).json
        response = current['responses'][item_id]
        values = dict(response, expected_revision=response['revision'], **changes)
        return self.client.put(f'/api/implementation/assessments/{self.id}/requirements/{item_id}', json=values)

    def test_complete_source_population_and_no_historical_conclusions(self):
        self.assertEqual(len(TEMPLATE['sections']), 6)
        self.assertEqual(len(TEMPLATE['items']), 6)
        self.assertEqual(len(requirements(TEMPLATE)), 6)
        self.assertEqual(self.assessment['summary']['total'],6)
        self.assertEqual(self.assessment['summary']['pending'],6)
        self.assertTrue(all(r['status']=='Not assessed' and r['ia_conclusion']=='Not reviewed' for r in self.assessment['responses'].values()))
        serialized=json.dumps(TEMPLATE)
        self.assertNotIn('No issues noted',serialized)
        self.assertNotIn('Q3_UAR',serialized)
        self.assertNotIn('syed.ali@',serialized)
        self.assertIn('sox-implementation-6',self.assessment['responses'])

    def test_met_requires_evidence_and_ia_conclusion_is_separate(self):
        response=self.save('sox-implementation-1',status='Met')
        self.assertEqual(response.status_code,400)
        response=self.save('sox-implementation-1',status='Met',evidence_reference='Signed charter in the approved project folder')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['summary']['met'],1)
        self.assertEqual(response.json['responses']['sox-implementation-1']['ia_conclusion'],'Not reviewed')
        # Read from disk and a fresh client to establish persistence beyond the request object.
        self.assertEqual(self.read()['implementation_assessments'][0]['responses']['sox-implementation-1']['status'],'Met')
        self.assertEqual(self.app.test_client().get('/api/implementation/assessments/'+self.id).json['summary']['resolved'],1)

    def test_gap_and_na_require_explanation(self):
        self.assertEqual(self.save('sox-implementation-1',status='Not met').status_code,400)
        response=self.save('sox-implementation-1',status='Not met',notes='Obtain sponsor approval',owner='Project owner',target_date='2020-01-01')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['summary']['not_met'],1)
        self.assertEqual(response.json['summary']['overdue'],1)
        self.assertEqual(self.save('sox-implementation-3',status='Not applicable').status_code,400)
        self.assertEqual(self.save('sox-implementation-3',status='Not applicable',na_reason='No data migration occurred').status_code,200)

    def test_separation_item_requires_evidence_when_met(self):
        self.assertEqual(self.save('sox-implementation-5',status='Met').status_code,400)
        response=self.save('sox-implementation-5',status='Met',evidence_reference='Role matrix and independent deployment approvals')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['summary']['sod_na_eligible'])

    def test_optimistic_concurrency_preserves_other_saved_changes(self):
        first=self.save('sox-implementation-1',status='In progress',notes='First reviewer update')
        self.assertEqual(first.status_code,200)
        second=self.client.put(f'/api/implementation/assessments/{self.id}/requirements/sox-implementation-1',json={'expected_revision':0,'status':'Not assessed','notes':'Stale update'})
        self.assertEqual(second.status_code,409)
        self.assertEqual(self.read()['implementation_assessments'][0]['responses']['sox-implementation-1']['notes'],'First reviewer update')

    def test_evidence_upload_download_and_met_status(self):
        path=f'/api/implementation/assessments/{self.id}/requirements/sox-implementation-1'
        response=self.client.post(path+'/evidence',data={'file':(io.BytesIO(b'Verification charter evidence'),'charter.txt'),'expected_revision':'0'})
        self.assertEqual(response.status_code,201)
        row=response.json['responses']['sox-implementation-1']
        self.assertEqual(row['revision'],1)
        self.assertEqual(row['status'],'Not assessed')
        attachment=row['attachments'][0]
        with self.client.get(path+'/evidence/'+attachment['id']) as download:
            self.assertEqual(download.status_code,200)
            self.assertEqual(download.data,b'Verification charter evidence')
            self.assertIn('attachment',download.headers['Content-Disposition'])
        self.assertEqual(self.save('sox-implementation-1',status='Met').status_code,200)
        self.assertEqual(self.client.get(path+'/evidence/missing').status_code,404)
        self.assertEqual(self.client.post(path+'/evidence',data={'file':(io.BytesIO(b'executable'),'file.exe'),'expected_revision':'2'}).status_code,400)

    def test_csv_population_provenance_and_formula_injection_protection(self):
        self.save('sox-implementation-1',status='In progress',notes='=HYPERLINK("https://untrusted.test")')
        with self.client.get('/api/implementation/assessments/'+self.id+'/export') as export:
            self.assertEqual(export.status_code,200)
            rows=list(csv.reader(io.StringIO(export.data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),7) # Header + six key SOX requirements.
        self.assertTrue(rows[1][11].startswith("'="))
        self.assertIn('financial reporting requirements',rows[1][4])
        self.assertNotIn('Rippling',rows[1][4])
        self.assertIn('Item 1',rows[1][19])
        self.assertEqual(rows[-1][2],'6')
