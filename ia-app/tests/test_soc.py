import copy
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask
from pypdf import PdfWriter
from soc_agent import review, routes
from soc_agent.sheets import sheet_payload


def document(source_id, text):
    return {'id': source_id, 'filename': source_id+'.txt', 'sha256': 'fixture', 'warnings': [], 'units': [{'locator': 'Line 1', 'text': text}]}


def ref(source_id, quote):
    return {'source_id': source_id, 'locator': 'Line 1', 'quote': quote}


def extracted():
    return {'facts': {key: {'text': 'Verification provider' if key == 'provider' else '', 'references': [ref('soc', 'Verification provider')] if key == 'provider' else []} for key in review.FACT_NAMES}, 'exceptions': [], 'cuecs': [{'key': 'CUEC-1', 'wording': 'User entities are responsible for reviewing access quarterly.', 'references': [ref('soc','User entities are responsible for reviewing access quarterly.')]}], 'subservices': [], 'limitations': []}


def fake_ai(stage, schema, payload):
    if schema is review.EXTRACT_SCHEMA:
        return extracted()
    if schema is review.POPULATION_SCHEMA:
        value = extracted()
        return {key: value[key] for key in ('exceptions', 'cuecs', 'subservices', 'limitations')}
    if schema is review.MAP_SCHEMA:
        return {'mappings': [{'cuec_id': c['id'], 'applicability': 'Pending — confirm usage', 'historical_mapping': 'Not provided', 'current_mapping': 'Proposed CTRL-1 access review', 'control_ids': ['CTRL-1'], 'evidence_and_gaps': 'Current operating evidence is not provided.', 'references': [ref('rcm', 'CTRL-1: review access quarterly.')]} for c in payload['cuecs']]}
    return {'report_overview': 'Verification provider SOC review.', 'period_assessment': 'Pending — confirm reliance dates and bridge evidence.', 'reliance_assessment': 'Proposed draft; human review remains pending.', 'risk_rationale': 'Pending approved criteria.', 'change_assessment': 'Prior-year evidence not provided.', 'control_objective_assessment': 'Pending — confirm ICFR relevance.', 'test_results_assessment': 'Pending full test-population verification.', 'exception_reconciliation': 'No exceptions extracted — verify all tests.', 'cuec_reconciliation': 'One CUEC extracted and mapped.', 'subservice_assessment': 'No subservice extracted — verify the description.', 'follow_ups': ['Obtain current evidence.'], 'limitations': ['Source completeness requires human verification.']}


def prepared():
    with patch.object(review, 'ask_ai', side_effect=fake_ai):
        return review.prepare_review([document('soc','Verification provider. User entities are responsible for reviewing access quarterly.'), document('rcm','CTRL-1: review access quarterly.')], {'review_year': '2026'}, lambda *args: None)


class ReviewTests(unittest.TestCase):
    def test_grounded_pipeline_and_pending_signoff(self):
        result = prepared()
        self.assertEqual(result['counts']['cuecs'], 1)
        self.assertIn('Pending', result['mappings'][0]['status'])
        self.assertIn('Pending', result['sign_off'])
        self.assertTrue(any('Prior-year' in x for x in result['limitations']))

    def test_hallucinated_quotes_raise_but_unsupported_mapping_is_omitted(self):
        with self.assertRaises(review.ReviewError):
            review.validate_refs([ref('soc','not in the source')], [document('soc','Real text')], True)
        def wrong_id(stage, schema, payload):
            value = fake_ai(stage, schema, payload)
            if schema is review.MAP_SCHEMA:
                value['mappings'][0]['control_ids'] = ['MADE-UP-ID']
            return value
        with patch.object(review, 'ask_ai', side_effect=wrong_id):
            result = review.prepare_review([document('soc','Verification provider. User entities are responsible for reviewing access quarterly.'),document('rcm','CTRL-1: review access quarterly.')], {}, lambda *args: None)
        self.assertEqual(result['mappings'][0]['control_ids'],[])
        self.assertIn('unverified mapping omitted',result['mappings'][0]['status'])
        self.assertTrue(any('unverified RCM mapping was omitted' in item for item in result['limitations']))

    def test_unsupported_extracted_item_is_omitted_without_failing_review(self):
        def one_unsupported(stage, schema, payload):
            value = fake_ai(stage, schema, payload)
            if schema is review.EXTRACT_SCHEMA:
                value['facts']['auditor'] = {'text': 'Unsupported auditor', 'references': []}
                value['exceptions'] = [{'key':'EX-1','description':'Unsupported exception','provider_response':'','evaluation':'','references':[]}]
            return value
        with patch.object(review, 'ask_ai', side_effect=one_unsupported):
            result = review.prepare_review([document('soc','Verification provider. User entities are responsible for reviewing access quarterly.'), document('rcm','CTRL-1: review access quarterly.')], {'review_year':'2026'}, lambda *args: None)
        self.assertEqual(result['facts']['auditor'], [])
        self.assertEqual(result['exceptions'], [])
        self.assertTrue(any('source reference could not be verified' in item for item in result['limitations']))

    def test_review_without_optional_rcm_keeps_mappings_pending(self):
        with patch.object(review, 'ask_ai', side_effect=fake_ai):
            result = review.prepare_review([document('soc','Verification provider. User entities are responsible for reviewing access quarterly.')], {'review_year':'2026'}, lambda *args: None)
        self.assertEqual(result['mappings'][0]['current_mapping'], 'Pending — company RCM was not uploaded.')
        self.assertEqual(result['mappings'][0]['control_ids'], [])
        self.assertTrue(any('Company RCM not provided' in item for item in result['limitations']))

    def test_bridge_letter_does_not_create_an_auditor_opinion(self):
        bridge = document('soc','Bridge letter. There were no material changes during the gap period.')
        bridge['filename'] = 'Provider_Bridge_Letter.pdf'
        def bridge_ai(stage, schema, payload):
            value = fake_ai(stage, schema, payload)
            if schema is review.EXTRACT_SCHEMA:
                value['facts']['opinion'] = {'text':'Bridge letter only. No restatement of SOC 1 Type II opinion.','references':[ref('soc','Bridge letter')]}
            return value
        with patch.object(review, 'ask_ai', side_effect=bridge_ai):
            result = review.prepare_review([bridge], {'review_year':'2026'}, lambda *args: None)
        self.assertEqual(result['facts']['opinion'], [])
        self.assertTrue(any('auditor opinion was not provided' in item for item in result['limitations']))

    def test_subservice_aliases_and_generic_cross_references_are_one_provider(self):
        refs = [ref('soc','Amazon Web Services is the subservice organization.')]
        items = [
            {'name':'Amazon Web Services, Inc. (AWS)','scope':'Hosting','services':'Cloud','impact':'','provider_response':'','evaluation':'','references':copy.deepcopy(refs)},
            {'name':'AWS','scope':'Hosting and backup','services':'Cloud hosting and automated backups','impact':'Relevant','provider_response':'Monitored','evaluation':'Carve-out','references':copy.deepcopy(refs)},
            {'name':'Not explicitly named on these pages','scope':'Availability','services':'Not stated','impact':'','provider_response':'','evaluation':'','references':copy.deepcopy(refs)},
        ]
        limitations = []
        result = review.dedupe_subservices(items, limitations)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['name'],'Amazon Web Services, Inc. (AWS)')
        self.assertEqual(result[0]['services'],'Cloud hosting and automated backups')
        self.assertTrue(any('Generic subservice cross-references' in item for item in limitations))

    def test_population_classification_rejects_provider_controls_and_no_exception_tests(self):
        source = document('soc', 'Complementary User Entity Controls\nUser entities are responsible for verifying payroll.\nControl 9.1 validates payroll. No exceptions were noted.')
        real = {'key':'CUEC-1','wording':'User entities are responsible for verifying payroll.','references':[ref('soc','User entities are responsible for verifying payroll.')]}
        provider_control = {'key':'9.1','wording':'Control 9.1 validates payroll.','references':[ref('soc','Control 9.1 validates payroll.')]}
        no_exception = {'description':'Control 9.1 was tested. No exceptions were noted.','provider_response':'','evaluation':''}
        self.assertTrue(review.is_cuec(real, [source]))
        self.assertFalse(review.is_cuec(provider_control, [document('soc','Control 9.1 validates payroll.')]))
        self.assertFalse(review.is_actual_exception(no_exception))

    def test_dynamic_single_tab_template_population_and_safe_strings(self):
        result = prepared()
        original = result['cuecs'][0]
        result['cuecs'] = [dict(copy.deepcopy(original), id=f'CUEC-{i}') for i in range(1,28)]
        original_mapping = result['mappings'][0]
        result['mappings'] = [dict(copy.deepcopy(original_mapping), cuec_id=f'CUEC-{i}') for i in range(1,28)]
        result['cuecs'][0]['wording'] = '=IMPORTXML("https://untrusted.test","//x")'
        payload = sheet_payload(result)
        self.assertEqual(len(payload['sheets']), 1)
        sheet = payload['sheets'][0]
        self.assertEqual(sheet['properties']['title'], 'SOC REVIEW')
        cells = [cell for row in sheet['data'][0]['rowData'] for cell in row['values']]
        strings = [cell.get('userEnteredValue',{}).get('stringValue','') for cell in cells]
        self.assertEqual(sum('reviewing access quarterly.' in text or '=IMPORTXML' in text for text in strings), 27)
        self.assertTrue(any('Sign-Offs:' in text for text in strings))
        self.assertFalse(any('formulaValue' in cell.get('userEnteredValue',{}) for cell in cells))
        self.assertFalse(any('[CUEC wording' in text for text in strings))
        headings = [text for text in strings if any(x in text for x in ('CONTROL EXCEPTIONS,', 'COMPLEMENTARY USER ENTITY CONTROLS LISTED', 'SUB-SERVICE PROVIDERS,', 'OPENDOOR MANAGEMENT (REVIEWER'))]
        self.assertEqual(len(headings), 4)
        self.assertTrue(headings[0].startswith('CONTROL EXCEPTIONS'))
        for merge in sheet['merges']:
            self.assertLess(merge['startRowIndex'], sheet['properties']['gridProperties']['rowCount'])

    def test_extraction_full_text_and_blank_pdf(self):
        with tempfile.TemporaryDirectory() as folder:
            text = Path(folder)/'input.txt'
            text.write_text('First line\nSecond line')
            value = review.extract_document(text, 'rcm', 'input.txt')
            self.assertEqual(value['units'][1]['locator'], 'Line 2')
            pdf = Path(folder)/'blank.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=200,height=200)
            writer.write(pdf)
            with self.assertRaisesRegex(review.ReviewError, 'no readable text'):
                review.extract_document(pdf,'soc','blank.pdf')
        workbook = review.extract_document(Path('soc_agent/assets/SOC_Report_Review_Template.xlsx'), 'prior', 'template.xlsx')
        self.assertTrue(any("'SOC REVIEW '!A5:Z5" == unit['locator'] for unit in workbook['units']))

    def test_ai_incomplete_output_fails_closed(self):
        response = Mock(ok=True)
        response.json.return_value = {'status': 'incomplete', 'output': []}
        with patch.dict(os.environ, {'OPENAI_API_KEY':'test'}), patch.object(review.requests, 'post', return_value=response):
            with self.assertRaisesRegex(review.ReviewError, 'incomplete'):
                review.ask_ai('Test', review.SUMMARY_SCHEMA, {})

    def test_ai_rate_limit_is_retried(self):
        limited = Mock(ok=False, status_code=429, headers={'Retry-After': '1', 'x-ratelimit-reset-tokens': '1m2s'})
        limited.json.return_value = {'error': {'code': 'rate_limit_exceeded'}}
        completed = Mock(ok=True)
        completed.json.return_value = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(fake_ai('', review.SUMMARY_SCHEMA, {}))}]}]}
        with patch.dict(os.environ, {'OPENAI_API_KEY':'test'}), patch.object(review.requests, 'post', side_effect=[limited, completed]) as send, patch.object(review.time, 'sleep') as wait:
            result = review.ask_ai('Test', review.SUMMARY_SCHEMA, {})
        self.assertEqual(send.call_count, 2)
        self.assertGreaterEqual(wait.call_args.args[0], 62)
        self.assertEqual(send.call_args_list[0].kwargs['json']['max_output_tokens'], 4000)
        self.assertIn('report_overview', result)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = {'soc_reviews':[], 'activity':[]}
        self.app = Flask('soc-test')
        self.app.testing = True
        self.environment = patch.dict(os.environ, {'GOOGLE_CLIENT_ID':'test-client', 'GOOGLE_CLIENT_SECRET':'test-secret', 'OPENAI_API_KEY':'test-key'})
        self.environment.start()
        def read():
            return copy.deepcopy(self.data)
        def write(data):
            self.data = copy.deepcopy(data)
        self.services = routes.register_soc(self.app, read, write, __import__('threading').RLock(), lambda d,a,t:d['activity'].append({'action':a,'title':t}), self.temp.name)
        self.client = self.app.test_client()

    def tearDown(self):
        self.services['executor'].shutdown(wait=True)
        self.environment.stop()
        self.temp.cleanup()

    def test_required_files_and_configuration(self):
        response = self.client.post('/api/soc/reviews', data={'title':'Verification','review_year':'2026','consent':'yes'})
        self.assertEqual(response.status_code,400)
        with patch.dict(os.environ, {'OPENAI_API_KEY':''}):
            self.assertEqual(self.client.post('/api/soc/reviews').status_code,503)
        self.assertEqual(self.client.post('/api/soc/reviews/unknown/sheet').status_code,401)

    def test_background_upload_draft_and_google_export_idempotency(self):
        def extract(path, source_id, filename):
            return document(source_id,'Test source')
        with patch.object(routes,'extract_document',side_effect=extract), patch.object(routes,'prepare_review',return_value=prepared()):
            response = self.client.post('/api/soc/reviews',data={'title':'Verification','review_year':'2026','consent':'yes','soc':(io.BytesIO(b'%PDF test'),'soc.pdf'),'rcm':(io.BytesIO(b'controls'),'rcm.txt')})
            self.assertEqual(response.status_code,202)
            run_id=response.json['id']
            deadline=time.time()+3
            while time.time()<deadline:
                run=self.client.get('/api/soc/reviews/'+run_id).json
                if run['status'] not in ('Queued','Running'):
                    break
                time.sleep(.02)
            self.assertEqual(run['status'],'Draft ready')
        self.assertEqual(len(list(Path(self.temp.name).glob('*/*'))),2)
        with self.client.session_transaction() as sess:
            sess['soc_google_session']='test-session'
        self.services['tokens']['test-session']={'access_token':'not-real','expires_at':time.time()+3600,'email':'reviewer@opendoor.com'}
        created=Mock(ok=True)
        created.json.return_value={'spreadsheetId':'test_sheet_123'}
        verify=Mock(ok=True)
        verify.json.return_value=sheet_payload(prepared())
        with patch.object(routes.requests,'post',return_value=created) as send, patch.object(routes.requests,'get',return_value=verify):
            response=self.client.post('/api/soc/reviews/'+run_id+'/sheet')
            self.assertEqual(response.status_code,201)
            self.assertTrue(response.json['verified'])
            self.assertEqual(self.client.post('/api/soc/reviews/'+run_id+'/sheet').status_code,200)
            self.assertEqual(send.call_count,1)
        self.assertNotIn('not-real',json.dumps(self.data))
        self.assertEqual(len(self.data['soc_reviews']),1)

    def test_background_upload_accepts_soc_without_rcm(self):
        with patch.object(routes,'extract_document',return_value=document('soc','Test source')), patch.object(routes,'prepare_review',return_value=prepared()):
            response = self.client.post('/api/soc/reviews',data={'title':'Verification','review_year':'2026','consent':'yes','soc':(io.BytesIO(b'%PDF test'),'soc.pdf')})
        self.assertEqual(response.status_code,202)

    def test_google_verified_email_required_without_domain_restriction(self):
        for user in ({'email':'','email_verified':True}, {'email':'user@gmail.com','email_verified':False}):
            with patch.object(self.services['google'],'authorize_access_token',return_value={'userinfo':user,'access_token':'secret'}):
                response=self.client.get('/auth/google/callback')
                self.assertIn('domain-denied',response.location)
        self.assertEqual(self.services['tokens'],{})
        with patch.object(self.services['google'],'authorize_access_token',return_value={'userinfo':{'email':'user@gmail.com','email_verified':True},'access_token':'secret'}):
            response=self.client.get('/auth/google/callback')
            self.assertIn('google=connected',response.location)
        self.assertEqual(next(iter(self.services['tokens'].values()))['email'],'user@gmail.com')

    def test_google_oauth_preserves_review_and_resumes_export(self):
        run_id = str(__import__('uuid').uuid4())
        self.data['soc_reviews'] = [{'id': run_id}]
        authorization = self.app.response_class('', status=302, headers={'Location': 'https://accounts.google.com/o/oauth2/auth'})
        with patch.object(self.services['google'], 'authorize_redirect', return_value=authorization):
            response = self.client.get('/auth/google/connect?run_id=' + run_id)
            self.assertEqual(response.status_code, 302)
        with patch.object(self.services['google'], 'authorize_access_token', return_value={'userinfo': {'email': 'user@gmail.com', 'email_verified': True}, 'access_token': 'secret'}):
            response = self.client.get('/auth/google/callback')
        self.assertIn('google=connected', response.location)
        self.assertIn('run=' + run_id, response.location)
        self.assertIn('export=1', response.location)
