"""Flask intake, background review progress, and private workbook downloads."""
import os
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request, send_file
from werkzeug.utils import secure_filename
from soc_agent.review import MAX_FILE, ReviewError
from .review import prepare_disclosure
from .sources import safe_url
from .workbook import create_workbook


def register_sec(app,read_store,write_store,lock,activity,storage_root):
    executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='sec-review')
    gate=threading.BoundedSemaphore(3)

    def stamp():
        return datetime.now(timezone.utc).isoformat()

    def update(run_id,**changes):
        with lock:
            data=read_store()
            run=next(r for r in data.get('sec_reviews',[]) if r['id']==run_id)
            run.update(changes,updated_at=stamp())
            write_store(data)

    def progress(run_id,stage,message):
        with lock:
            data=read_store()
            run=next(r for r in data['sec_reviews'] if r['id']==run_id)
            run.update(stage=stage,updated_at=stamp())
            run['steps'].append({'at':stamp(),'stage':stage,'message':message})
            write_store(data)

    def worker(run_id,files,context,directory):
        try:
            update(run_id,status='Running')
            result=prepare_disclosure(files,context,directory,lambda stage,message:progress(run_id,stage,message))
            progress(run_id,'Preparing workbook','Writing comparison, ASU, suggested wording, coverage, cross-reference, and optional financial tie-out tabs; reconciling saved rows.')
            create_workbook(result,Path(directory)/'sec_disclosure_review.xlsx')
            update(run_id,status='Draft ready',stage='Workbook ready for human review',result=result,error=None)
            progress(run_id,'Draft ready','Download the review workbook. Findings and suggested wording require human accounting/legal review; open evidence gaps remain visible.')
            with lock:
                data=read_store()
                activity(data,'SEC disclosure review draft prepared',context['title'])
                write_store(data)
        except Exception as exc:
            message=str(exc) if isinstance(exc,ReviewError) else 'The disclosure review could not finish. Sources are retained; check the server log and start a new run.'
            if not isinstance(exc,ReviewError):
                app.logger.exception('SEC disclosure review failed')
            update(run_id,status='Failed',stage='Needs attention',error=message)
        finally:
            gate.release()

    @app.get('/api/sec/config')
    def sec_config():
        return jsonify(ai_configured=bool(os.environ.get('OPENAI_API_KEY')),source_method='Direct SEC EDGAR public API or uploaded filings',output='Excel workbook',max_file_mb=25,forms=['10-Q','10-K','S-1'])

    @app.get('/api/sec/reviews')
    def sec_list():
        with lock:
            runs=read_store().get('sec_reviews',[])
        return jsonify([{k:v for k,v in r.items() if k!='result'} for r in runs])

    @app.get('/api/sec/reviews/<run_id>')
    def sec_get(run_id):
        with lock:
            run=next((r for r in read_store().get('sec_reviews',[]) if r['id']==run_id),None)
        return (jsonify(run),200) if run else (jsonify(error='SEC review not found.'),404)

    @app.post('/api/sec/reviews')
    def sec_create():
        if not os.environ.get('OPENAI_API_KEY'):
            return jsonify(error='Configure OPENAI_API_KEY before uploading confidential draft disclosures.'),503
        if request.form.get('consent')!='yes' or request.form.get('industry_confirmed')!='yes':
            return jsonify(error='Confirm the industry/peer choices and permission to process draft disclosure content with the AI service.'),400
        context={}
        for name,limit in (('title',180),('ticker',12),('industry',500),('form_type',10),('filing_contact',200),('company_name',200),('filer_status',300),('reporting_basis',100),('notes',4000)):
            value=request.form.get(name,'').strip()
            if len(value)>limit:
                return jsonify(error=f'{name} exceeds {limit} characters.'),400
            context[name]=value
        context['ticker']=context['ticker'].upper()
        if not context['title'] or not context['industry'] or not re.fullmatch(r'[A-Z0-9.-]{1,12}',context['ticker']) or context['form_type'] not in ('10-Q','10-K','S-1'):
            return jsonify(error='Provide a title, valid company ticker, confirmed industry, and supported filing form.'),400
        for name in ('comparison_cutoff','review_as_of','period_end'):
            value=request.form.get(name,'').strip()
            if not value and name!='period_end':
                return jsonify(error='Provide the review date and comparison filing cutoff date.'),400
            if value:
                try:
                    datetime.strptime(value,'%Y-%m-%d')
                except ValueError:
                    return jsonify(error='Use valid YYYY-MM-DD dates.'),400
            context[name]=value
        if context['comparison_cutoff']>context['review_as_of']:
            return jsonify(error='The comparison filing cutoff cannot be later than the review date.'),400
        context['retrieve_sec']=request.form.get('retrieve_sec')=='yes'
        if context['retrieve_sec'] and not re.fullmatch(r'[^()\r\n]{2,120}\s*\([^\s()@]+@[^\s()@]+\.[^\s()@]+\)',context['filing_contact']):
            return jsonify(error='SEC retrieval requires a contact in the format Full Name (email@domain.com).'),400
        peers=[value.strip().upper() for value in re.split(r'[,\s]+',request.form.get('peers','')) if value.strip()]
        if len(peers)>3 or len(set(peers))!=len(peers) or context['ticker'] in peers or any(not re.fullmatch(r'[A-Z0-9.-]{1,12}',value) for value in peers):
            return jsonify(error='Use up to three distinct peer tickers, excluding the company being reviewed.'),400
        context['peers']=peers
        context['tieout_policy']=request.form.get('tieout_policy','all')
        if context['tieout_policy'] not in ('all','visible'):
            return jsonify(error='Choose all worksheets or visible worksheets for financial tie-out.'),400
        urls=[value.strip() for value in request.form.get('fasb_urls','').splitlines() if value.strip()]
        if len(urls)>8 or any(len(url)>2000 for url in urls):
            return jsonify(error='Provide up to eight official FASB links, one per line.'),400
        try:
            for url in urls:
                safe_url(url,{'www.fasb.org','fasb.org','storage.fasb.org'})
        except ReviewError as exc:
            return jsonify(error=str(exc)),400
        context['fasb_urls']=urls
        selected=[]
        for name in ('draft','prior','peer1','peer2','peer3','financials','tieout_pdf'):
            file=request.files.get(name)
            if not file or not file.filename:
                if name=='draft':
                    return jsonify(error='Upload the current draft filing.'),400
                continue
            filename=secure_filename(file.filename)
            extension=Path(filename).suffix.lower()
            allowed={'.xlsx'} if name=='financials' else {'.pdf'} if name=='tieout_pdf' else {'.pdf','.docx','.txt','.md'}
            if extension not in allowed:
                return jsonify(error='Draft/comparison filings support PDF, DOCX, TXT or MD; financials must be XLSX and tie-out filing must be PDF.'),400
            selected.append((name,file,filename))
        if not gate.acquire(blocking=False):
            return jsonify(error='Three SEC reviews are active or queued. Wait for a run to finish.'),429
        run_id=str(uuid.uuid4())
        directory=Path(storage_root)/run_id
        files={}
        try:
            directory.mkdir(parents=True,mode=0o700)
            for name,file,filename in selected:
                content=file.stream.read(MAX_FILE+1)
                if not content or len(content)>MAX_FILE:
                    raise ReviewError(f'{filename}: upload a nonempty file no larger than 25 MB.')
                path=directory/(name+Path(filename).suffix.lower())
                path.write_bytes(content);path.chmod(0o600)
                files[name]={'name':filename,'path':str(path)}
            run={'id':run_id,'title':context['title'],'context':context,'status':'Queued','stage':'Waiting to start','created_at':stamp(),'updated_at':stamp(),'steps':[],'files':[{'role':name,'name':file['name']} for name,file in files.items()],'error':None}
            with lock:
                data=read_store()
                data.setdefault('sec_reviews',[]).insert(0,run)
                activity(data,'SEC disclosure review started',context['title'])
                write_store(data)
            executor.submit(worker,run_id,files,context,directory)
            return jsonify(run),202
        except Exception as exc:
            gate.release();shutil.rmtree(directory,ignore_errors=True)
            if isinstance(exc,ReviewError):
                return jsonify(error=str(exc)),400
            raise

    def downloadable(run_id,filename,mime,download_name):
        with lock:
            run=next((r for r in read_store().get('sec_reviews',[]) if r['id']==run_id),None)
        if not run:
            return jsonify(error='SEC review not found.'),404
        if run['status']!='Draft ready':
            return jsonify(error='Wait for the review workbook to be prepared.'),409
        path=Path(storage_root)/run['id']/filename
        if not path.is_file():
            return jsonify(error='The saved output is unavailable. Restore the private run directory or prepare a new review.'),404
        return send_file(path,mimetype=mime,as_attachment=True,download_name=download_name)

    @app.get('/api/sec/reviews/<run_id>/workbook')
    def sec_workbook(run_id):
        return downloadable(run_id,'sec_disclosure_review.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','SEC_Disclosure_Review.xlsx')

    @app.get('/api/sec/reviews/<run_id>/sources')
    def sec_sources(run_id):
        return downloadable(run_id,'source_snapshot.json','application/json','SEC_Review_Source_Snapshot.json')

    with lock:
        data=read_store();changed=False
        for run in data.get('sec_reviews',[]):
            if run['status'] in ('Queued','Running'):
                run.update(status='Failed',stage='Interrupted by server restart',error='The server restarted. Start a new review with the same documents; no finished review was recorded.')
                changed=True
        if changed:
            write_store(data)
    return {'executor':executor,'worker':worker}
