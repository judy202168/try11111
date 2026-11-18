"""Fresh, rate-limited public-source retrieval; no confidential draft is sent to SEC."""
import re
import hashlib
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, NavigableString
from docx import Document
from soc_agent.review import ReviewError, extract_document

NETWORK_LOCK = threading.Lock()
LAST_REQUEST = 0.0
MAX_DOWNLOAD = 25 * 1024 * 1024
ALLOWED_HOSTS = {'www.sec.gov', 'data.sec.gov', 'sec.gov', 'fasb.org', 'www.fasb.org', 'storage.fasb.org'}


def safe_url(url, hosts=ALLOWED_HOSTS):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ReviewError('Only HTTPS links on approved SEC/FASB hosts are supported.')
    return url


class PublicClient:
    def __init__(self, contact):
        self.headers = {'User-Agent': 'JD-Audit-Lab ' + contact, 'Accept-Encoding': 'gzip, deflate'}
        self.tickers = None

    def get(self, url):
        global LAST_REQUEST
        for _ in range(4):
            safe_url(url)
            with NETWORK_LOCK:
                delay = .3 - (time.monotonic()-LAST_REQUEST)
                if delay > 0:
                    time.sleep(delay)
                LAST_REQUEST = time.monotonic()
            try:
                with requests.get(url, headers=self.headers, timeout=(10,40), stream=True, allow_redirects=False) as response:
                    if response.status_code in (301,302,303,307,308):
                        url = urljoin(url, response.headers.get('Location',''))
                        continue
                    if not response.ok:
                        raise ReviewError(f'Public source returned HTTP {response.status_code}: {url}. Supply an uploaded filing or retry later.')
                    data = bytearray()
                    for piece in response.iter_content(65536):
                        data.extend(piece)
                        if len(data)>MAX_DOWNLOAD:
                            raise ReviewError('Public source exceeds 25 MB; supply a scoped uploaded document.')
                    return bytes(data), url, response.headers.get('Content-Type','')
            except requests.RequestException as exc:
                raise ReviewError('Public source retrieval failed or timed out: '+url) from exc
        raise ReviewError('Public source redirected too many times.')

    def json(self, url):
        import json
        content,_,_=self.get(url)
        try:
            return json.loads(content)
        except ValueError as exc:
            raise ReviewError('Public source did not return usable JSON: '+url) from exc

    def identity(self, ticker):
        if self.tickers is None:
            self.tickers = self.json('https://www.sec.gov/files/company_tickers.json')
        record = next((x for x in self.tickers.values() if x.get('ticker','').upper()==ticker.upper()),None)
        if not record:
            raise ReviewError(f'No SEC ticker identity found for {ticker}; upload the correct filing instead.')
        cik=str(record['cik_str']).zfill(10)
        submissions=self.json(f'https://data.sec.gov/submissions/CIK{cik}.json')
        return {'ticker':ticker.upper(),'cik':cik,'name':submissions.get('name',record.get('title','')),'sic':submissions.get('sic',''),'industry':submissions.get('sicDescription',''),'submissions':submissions}

    def filing(self, ticker, form, cutoff, source_id):
        identity=self.identity(ticker)
        filings=identity['submissions'].get('filings',{})
        datasets=[filings.get('recent',{})]
        selected=None
        # Older history is requested fresh only when recent history has no eligible filing.
        history=filings.get('files',[])
        for index in range(min(len(history),3)+1):
            dataset=datasets[-1]
            candidates=[]
            for i,value in enumerate(dataset.get('form',[])):
                date=dataset.get('filingDate',[])[i]
                if value==form and date<cutoff:
                    candidates.append({key:dataset.get(key,['']*len(dataset['form']))[i] for key in ('accessionNumber','primaryDocument','filingDate','reportDate')})
            if candidates:
                selected=max(candidates,key=lambda x:x['filingDate'])
                break
            if index<min(len(history),3):
                name=history[index].get('name','')
                if not re.fullmatch(r'CIK\d{10}-submissions-\d+\.json',name):
                    break
                datasets.append(self.json('https://data.sec.gov/submissions/'+name))
        if not selected:
            raise ReviewError(f'No eligible {form} for {ticker} filed before {cutoff} in recent history and up to three history files. Upload a comparison filing or check the cutoff.')
        accession=selected['accessionNumber']
        primary=selected['primaryDocument']
        if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession) or not re.fullmatch(r'[A-Za-z0-9_.-]+',primary):
            raise ReviewError('SEC filing metadata could not be safely resolved.')
        url=f'https://www.sec.gov/Archives/edgar/data/{int(identity["cik"])}/{accession.replace("-","")}/{primary}'
        content,final_url,_=self.get(url)
        doc=html_document(content,source_id,primary)
        doc.update(url=final_url,accession=accession,filing_date=selected['filingDate'],report_date=selected['reportDate'],company=identity['name'],ticker=ticker,sic=identity['sic'],industry=identity['industry'],retrieval='Fresh SEC EDGAR public API')
        return doc


def html_document(content,source_id,filename):
    soup=BeautifulSoup(content,'html.parser')
    for item in soup.find_all(['script','style','head','noscript','ix:hidden']):
        item.decompose()
    units=[]
    block_tags={'p','div','h1','h2','h3','h4','h5','h6','tr','li','pre'}
    owner=None; pieces=[]
    def flush():
        if pieces:
            text=' '.join(pieces).strip()
            if text:
                units.append({'locator':f'HTML block {len(units)+1}','text':text,'heading':bool(owner and (owner.name.startswith('h') or owner.find(['b','strong']) and len(text)<130))})
    # Group visible text nodes in document order, including mixed-content containers.
    # A parent div with nested paragraphs must not cause its direct text to disappear.
    for node in soup.descendants:
        if not isinstance(node,NavigableString) or not node.strip():
            continue
        nearest=next((p for p in node.parents if p.name in block_tags),node.parent)
        if nearest is not owner:
            flush();pieces=[];owner=nearest
        pieces.append(str(node).strip())
    flush()
    if sum(len(u['text']) for u in units)<500:
        text=soup.get_text('\n',strip=True)
        units=[{'locator':f'HTML line {i}','text':line} for i,line in enumerate(text.splitlines(),1) if line.strip()]
    if sum(len(u['text']) for u in units)>1200000:
        raise ReviewError('Filing text exceeds 1.2 million characters; upload a scoped source. No text was silently omitted.')
    if not units:
        raise ReviewError('The retrieved filing contains no readable disclosure text.')
    return {'id':source_id,'filename':filename,'units':units,'warnings':['HTML extraction and heading recognition require verification against the filing, including tables and inline XBRL.'],'url':'','accession':'','retrieval':'Uploaded HTML','sha256':hashlib.sha256(content).hexdigest()}


def uploaded_filing(path,source_id,filename):
    path=Path(path)
    if path.suffix.lower() in ('.txt','.md'):
        text=path.read_text(encoding='utf-8-sig')
        if len(text)>1200000 or not text.strip():
            raise ReviewError('Upload a nonempty draft no longer than 1.2 million characters.')
        doc={'id':source_id,'filename':filename,'units':[{'locator':f'Line {i}','text':line,'heading':bool(re.match(r'^#{1,6}\s',line))} for i,line in enumerate(text.splitlines(),1)],'warnings':[]}
    elif path.suffix.lower()=='.docx':
        doc=extract_document(path,source_id,filename)
        # Add explicit paragraph style/bold cues to the existing text-based source locators.
        original=Document(path)
        headings={}
        for i,block in enumerate(original.iter_inner_content(),1):
            if hasattr(block,'runs'):
                headings[f'Paragraph/block {i}']=bool(block.style and block.style.name.startswith('Heading')) or bool(block.runs) and all(r.bold for r in block.runs if r.text.strip()) and len(block.text)<130
        for unit in doc['units']:
            unit['heading']=headings.get(unit['locator'],False)
    else:
        doc=extract_document(path,source_id,filename)
    doc.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),url='',accession='',retrieval='User-uploaded comparison; form, period and entity need human confirmation' if source_id!='draft' else 'User-uploaded draft')
    return doc


def fasb_sources(client,urls,directory):
    documents,issues=[],[]
    for index,url in enumerate(urls,1):
        try:
            safe_url(url,{'fasb.org','www.fasb.org','storage.fasb.org'})
            data,final_url,mime=client.get(url)
            safe_url(final_url,{'fasb.org','www.fasb.org','storage.fasb.org'})
            if data.startswith(b'%PDF'):
                path=Path(directory)/f'fasb_{index}.pdf'
                path.write_bytes(data)
                doc=extract_document(path,f'fasb_{index}',f'FASB source {index}')
            else:
                doc=html_document(data,f'fasb_{index}',f'FASB source {index}')
            if sum(len(u['text']) for u in doc['units'])<300:
                raise ReviewError('Official source has insufficient extractable text, possibly a dynamic page.')
            doc['url']=final_url
            documents.append(doc)
        except ReviewError as exc:
            issues.append(str(exc))
    return documents,issues
