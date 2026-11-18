import copy
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask
from openpyxl import Workbook, load_workbook
from soc_agent.review import ReviewError
from sec_agent import parsing, review, routes, sources
from sec_agent.tieout import financial_tieout
from sec_agent.workbook import COLUMNS, create_workbook


DRAFT='''PART I
Item 1. Financial Statements
Balance Sheets
Cash was 100 at period-end.
Note 1 — Accounting Policies
Revenue Recognition
Revenue is recognized when the service transfers.
Note 3 — Leases
Operating Leases
Lease costs were 20. See Note 2.
Item 2. Management Discussion and Analysis
Results of Operations
Revenue increased by 10.
Liquidity and Capital Resources
Cash was 100. See Item 1.
PART II
Item 1. Legal Proceedings
Pending litigation is described here.
'''


def doc(identifier,text):
    return {'id':identifier,'filename':identifier+'.txt','url':'','accession':'','warnings':[],'units':[{'locator':f'Line {i}','text':line} for i,line in enumerate(text.splitlines(),1)]}


def context():
    return {'title':'Disclosure verification','form_type':'10-Q','ticker':'TEST','industry':'Verification industry','peers':[],'comparison_cutoff':'2026-10-01','review_as_of':'2026-11-17','period_end':'2026-09-30','retrieve_sec':False,'filing_contact':'','fasb_urls':[],'tieout_policy':'all'}


def fake_ai(task,schema,payload):
    if schema is review.CANDIDATE_SCHEMA:
        return {'candidates':[]}
    if schema is review.COMPARISON_SCHEMA:
        return {'rows':[{'id':p['id'],'assessment':'Differences need review','gap_type':'Change','risk_level':'Pending','comment':'Compare reporting period and scope.','draft_quote':p['draft']['text'][:50],'source_quote':p['comparison']['text'][:50],'proposal':'[Confirm the amount and reporting period before disclosure.]','proposal_basis':'Comparison source text, subject to human verification.'} for p in payload['pairs']]}
    raise AssertionError('Unexpected AI task')


def prepared(folder):
    path=Path(folder)/'draft.txt';path.write_text(DRAFT)
    prior=Path(folder)/'prior.txt';prior.write_text(DRAFT.replace('100','90'))
    files={'draft':{'path':str(path),'name':'draft.txt'},'prior':{'path':str(prior),'name':'prior.txt'}}
    with patch.object(review,'ask_ai',side_effect=fake_ai):
        return review.prepare_disclosure(files,context(),folder,lambda *args:None)


class ParsingTests(unittest.TestCase):
    def test_part_keys_subsections_footnote_gaps_and_crossrefs(self):
        parsed=parsing.parse_filing(doc('draft',DRAFT),'10-Q')
        keys={s['key'] for s in parsed['sections']}
        self.assertIn('part_i_item_1',keys)
        self.assertIn('part_ii_item_1',keys)
        md=next(s for s in parsed['sections'] if s['key']=='part_i_item_2')
        self.assertGreaterEqual(len(md['subsections']),2)
        qa=parsing.coverage(parsed,'10-Q')
        self.assertTrue(any(r['check_type']=='Footnote sequence' and r['item_key']=='note_2' for r in qa))
        refs=parsing.cross_references(parsed)
        self.assertTrue(any(r['reference_text']=='Note 2' and r['status'].startswith('Unresolved') for r in refs))

    def test_numbered_financial_notes_without_note_prefix(self):
        text='Item 8. Financial Statements\nNOTES TO CONSOLIDATED FINANCIAL STATEMENTS\n1. Accounting Policies\nAccounting policies are described here.\n2. Revenue Recognition\nRevenue transfers when service is delivered.'
        parsed=parsing.parse_filing(doc('draft',text),'10-K')
        self.assertEqual({s['code'] for s in parsed['sections'] if s['kind']=='note'},{'1','2'})

    def test_notes_align_by_topic_not_unrelated_note_number(self):
        current=parsing.parse_filing(doc('draft','Note 1 — Leases\nOperating Leases\nLease costs were 25.'),'10-K')
        peer=parsing.parse_filing(doc('peer','Note 1 — Debt\nCredit Facilities\nDebt was 100.'),'10-K')
        self.assertTrue(all(pair['comparison'] is None for pair in parsing.align(current,peer)))

    def test_toc_duplicate_retained_and_long_body_not_silently_dropped(self):
        text='Item 7. Management Discussion and Analysis\n4\nItem 8. Financial Statements\n5\nItem 7. Management Discussion and Analysis\nResults of Operations\n'+'The disclosed business activity increased. '*2000
        parsed=parsing.parse_filing(doc('draft',text),'10-K')
        self.assertTrue(any(r['check_type']=='Duplicate headings / TOC' for r in parsed['qa']))
        self.assertGreater(sum(len(s['text']) for s in parsed['subsections']),70000)
        self.assertTrue(any('continuation' in s['subsection_title'] for s in parsed['subsections']))

    def test_repeated_continued_section_bodies_are_retained(self):
        text='Note 2 — Revenue\nFirst substantive disclosure unique wording.\nNote 2 — Revenue\nSecond substantive continuation unique wording.'
        parsed=parsing.parse_filing(doc('draft',text),'10-K')
        body=' '.join(s['text'] for s in parsed['subsections'])
        self.assertIn('First substantive disclosure',body)
        self.assertIn('Second substantive continuation',body)

    def test_html_mixed_container_text_not_omitted(self):
        source=sources.html_document(b'<html><body><div>Heading before paragraph<p>Body text here</p>Trailing disclosure</div><table><tr><td>Cash</td><td>100</td></tr></table></body></html>','source','source.htm')
        text=' '.join(u['text'] for u in source['units'])
        for phrase in ('Heading before paragraph','Body text here','Trailing disclosure','Cash','100'):
            self.assertIn(phrase,text)


class ReviewTests(unittest.TestCase):
    def test_full_population_partial_sources_and_expected_workbook_tabs(self):
        with tempfile.TemporaryDirectory() as folder:
            result=prepared(folder)
            self.assertGreater(result['counts']['subsections'],5)
            for name in ('vs. prior version','vs. company 1','vs. company 2','vs. company 3'):
                self.assertEqual(len(result['tables'][name]),result['counts']['subsections'])
            self.assertTrue(all(r['assessment'].startswith('Pending') for r in result['tables']['vs. company 1']))
            self.assertIn('ASU screen',result['tables'])
            self.assertNotIn('financial tie-out',result['tables'])
            self.assertTrue(Path(folder,'source_snapshot.json').is_file())
            result['tables']['Suggested Improvement'][0]['proposed_disclosure']='=HYPERLINK("https://untrusted.test")'
            path=create_workbook(result,Path(folder)/'review.xlsx')
            workbook=load_workbook(path)
            self.assertEqual(workbook.sheetnames,list(COLUMNS)[:-1])
            self.assertEqual(workbook['Suggested Improvement']['C2'].data_type,'s')
            for sheet in workbook:
                self.assertEqual(sheet.freeze_panes,'A2')
                self.assertTrue(sheet.auto_filter.ref)
            workbook.close()

    def test_invalid_quotes_fail_closed_but_population_is_still_emitted(self):
        parsed=parsing.parse_filing(doc('draft',DRAFT),'10-Q')
        prior=parsing.parse_filing(doc('prior',DRAFT),'10-Q')
        def invalid(task,schema,payload):
            result=fake_ai(task,schema,payload)
            for row in result['rows']:
                row['source_quote']='Quotation invented by the model'
            return result
        with patch.object(review,'ask_ai',side_effect=invalid):
            records,suggestions,issues=review.compare(parsed,prior,'prior version',context(),lambda *args:None)
        self.assertEqual(len(records),len(parsed['subsections']))
        self.assertEqual(suggestions,[])
        self.assertTrue(issues)
        self.assertTrue(all(r['gap_type'].startswith('Pending') for r in records))

    def test_unverified_asu_candidates_cannot_become_effective_date_conclusions(self):
        draft=parsing.parse_filing(doc('draft',DRAFT),'10-Q')
        client=Mock()
        client.get.side_effect=ReviewError('Official index unavailable')
        candidate={'candidates':[{'asu_id':'ASU 2023-09','topic':'Candidate topic','reason':'Screen for relevance','relevant_section':'note_1'}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(review,'ask_ai',return_value=candidate):
            rows,issues,official,suggestions=review.asu_screen(draft,context(),client,folder,[],lambda *args:None)
        self.assertEqual(rows[0]['applicability'],'Pending — candidate only')
        self.assertTrue(rows[0]['effective_window'].startswith('Pending'))
        self.assertEqual(suggestions,[])

    def test_financial_census_includes_uncached_formula_and_hidden_sheet(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'financials.xlsx'
            workbook=Workbook();sheet=workbook.active;sheet.title='Statements'
            sheet.append(['Line','2026']);sheet.append(['Cash',100]);sheet.append(['Formula','=SUM(B2)'])
            hidden=workbook.create_sheet('Hidden');hidden.sheet_state='hidden';hidden['A1']=25
            workbook.save(path);workbook.close()
            rows=financial_tieout({'path':str(path),'name':'financials.xlsx'},None,'all')
            self.assertEqual(len(rows),3)
            self.assertTrue(any(r['cell']=='B3' and r['excel_value']=='unavailable' for r in rows))
            self.assertTrue(any(r['excel_sheet']=='Hidden' for r in rows))
            self.assertTrue(all('completed' not in r['status'].lower() for r in rows))
            self.assertEqual(len(financial_tieout({'path':str(path),'name':'financials.xlsx'},None,'visible')),2)

    def test_public_source_url_allowlist(self):
        for url in ('http://www.sec.gov/test','https://127.0.0.1/test','https://sec.gov.external.test/','https://name:secret@www.sec.gov/path','https://storage.fasb.org:444/a.pdf'):
            with self.assertRaises(ReviewError):
                sources.safe_url(url)

    def test_sec_selects_latest_eligible_exact_form_before_cutoff(self):
        client=sources.PublicClient('Test Contact (test@example.com)')
        identity={'ticker':'TEST','cik':'0000000001','name':'Verification company','sic':'0000','industry':'Test industry','submissions':{'filings':{'recent':{'form':['10-Q','10-Q','10-K','10-Q/A'],'filingDate':['2026-11-01','2026-08-01','2026-02-01','2026-08-15'],'reportDate':['2026-09-30','2026-06-30','2025-12-31','2026-06-30'],'accessionNumber':['0000000001-26-000004','0000000001-26-000003','0000000001-26-000002','0000000001-26-000005'],'primaryDocument':['q3.htm','q2.htm','k.htm','qa.htm']},'files':[]}}}
        html=b'<h1>PART I</h1><h2>Item 1. Financial Statements</h2><p>Full substantive filing text.</p>'
        with patch.object(client,'identity',return_value=identity),patch.object(client,'get',return_value=(html,'https://www.sec.gov/Archives/test/q2.htm','text/html')) as fetch:
            filing=client.filing('TEST','10-Q','2026-10-01','prior')
        self.assertEqual(filing['accession'],'0000000001-26-000003')
        self.assertIn('/q2.htm',fetch.call_args.args[0])


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.data={'sec_reviews':[],'activity':[]}
        self.environment=patch.dict(os.environ,{'OPENAI_API_KEY':'test-key'});self.environment.start()
        self.app=Flask('sec-test');self.app.testing=True
        def read():return copy.deepcopy(self.data)
        def write(data):self.data=copy.deepcopy(data)
        self.services=routes.register_sec(self.app,read,write,threading.RLock(),lambda d,a,t:d['activity'].append(a),self.temp.name)
        self.client=self.app.test_client()

    def tearDown(self):
        self.services['executor'].shutdown(wait=True);self.environment.stop();self.temp.cleanup()

    def fields(self):
        return {'title':'Verification','ticker':'TEST','industry':'Confirmed test industry','form_type':'10-Q','review_as_of':'2026-11-17','comparison_cutoff':'2026-10-01','retrieve_sec':'no','industry_confirmed':'yes','consent':'yes','draft':(io.BytesIO(DRAFT.encode()),'draft.txt')}

    def test_input_validation_and_no_contact_retrieval_block(self):
        fields=self.fields();fields['retrieve_sec']='yes'
        self.assertEqual(self.client.post('/api/sec/reviews',data=fields).status_code,400)
        self.assertEqual(self.data['sec_reviews'],[])
        fields=self.fields();fields['fasb_urls']='https://private.test/secret'
        self.assertEqual(self.client.post('/api/sec/reviews',data=fields).status_code,400)
        fields=self.fields();fields['peers']='TEST,TEST'
        self.assertEqual(self.client.post('/api/sec/reviews',data=fields).status_code,400)
        with patch.dict(os.environ,{'OPENAI_API_KEY':''}):
            self.assertEqual(self.client.post('/api/sec/reviews',data=self.fields()).status_code,503)

    def test_background_run_and_real_workbook_download_with_mocked_ai(self):
        with patch.object(review,'ask_ai',side_effect=fake_ai):
            response=self.client.post('/api/sec/reviews',data=self.fields())
            self.assertEqual(response.status_code,202)
            run_id=response.json['id'];deadline=time.time()+4
            while time.time()<deadline:
                run=self.client.get('/api/sec/reviews/'+run_id).json
                if run['status'] not in ('Queued','Running'):break
                time.sleep(.02)
            self.assertEqual(run['status'],'Draft ready',run.get('error'))
            with self.client.get('/api/sec/reviews/'+run_id+'/workbook') as output:
                self.assertEqual(output.status_code,200)
                workbook=load_workbook(io.BytesIO(output.data),read_only=True)
                self.assertEqual(len(workbook.sheetnames),8);workbook.close()
            with self.client.get('/api/sec/reviews/'+run_id+'/sources') as output:
                self.assertEqual(output.status_code,200)
                self.assertIn('draft',json.loads(output.data))
        self.assertEqual(self.client.get('/api/sec/reviews/../../data.json/workbook').status_code,404)
