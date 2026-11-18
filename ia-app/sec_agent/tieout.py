"""Complete cell census and conservative numeric occurrence candidates, never automatic approval."""
import re
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import load_workbook
from soc_agent.review import ReviewError, extract_document

NUMBER=re.compile(r'(?<![A-Za-z0-9])\(?[−-]?\$?\s*\d[\d,]*(?:\.\d+)?\)?%?(?![A-Za-z0-9])')


def numeric(text):
    text=text.strip().replace('−','-').replace('$','').replace(',','').replace(' ','')
    negative=text.startswith('(') and ')' in text
    percent=text.endswith('%')
    text=text.replace('(','').replace(')','').rstrip('%')
    try:
        value=Decimal(text)
        if negative:
            value=-value
        return value/100 if percent else value
    except InvalidOperation:
        return None


def financial_tieout(file,pdf,policy):
    path=Path(file['path'])
    with zipfile.ZipFile(path) as archive:
        if sum(x.file_size for x in archive.infolist())>160*1024*1024:
            raise ReviewError('Financial workbook expanded size exceeds 160 MB. Supply a scoped export.')
    original=load_workbook(path,read_only=True,data_only=False)
    cached=load_workbook(path,read_only=True,data_only=True)
    occurrences={};pdf_issue=''
    if pdf:
        try:
            doc=extract_document(pdf['path'],'tieout_pdf',pdf['name'])
            for unit in doc['units']:
                for line_index,line in enumerate(unit['text'].splitlines(),1):
                    for match in NUMBER.finditer(line):
                        number=numeric(match.group(0))
                        if number is not None:
                            occurrences.setdefault(number,[]).append((match.group(0).strip(),unit['locator']+f', line {line_index}',line))
            if doc.get('warnings'):
                pdf_issue='Some PDF pages have extraction warnings. Verify the original PDF. '
        except ReviewError as exc:
            pdf_issue=str(exc)+' '
    else:
        pdf_issue='No filing PDF provided. Upload a filing PDF to compare numeric occurrences. '
    rows=[]
    try:
        for sheet in original:
            if policy=='visible' and sheet.sheet_state!='visible':
                continue
            if sheet.max_row is None or sheet.max_column is None:
                sheet.calculate_dimension(force=True)
            values_sheet=cached[sheet.title]
            if values_sheet.max_row is None or values_sheet.max_column is None:
                values_sheet.calculate_dimension(force=True)
            if sheet.max_row>20000 or sheet.max_column>300:
                raise ReviewError('Financial workbook exceeds 20,000 rows or 300 columns on a selected sheet. No complete cell census was produced.')
            column_context={}
            for row_index,(source_row,value_row) in enumerate(zip(sheet.iter_rows(),values_sheet.iter_rows()),1):
                row_label=''
                for cell,value_cell in zip(source_row,value_row):
                    value=cell.value
                    if isinstance(value,str) and cell.data_type!='f':
                        if not row_label and value.strip():
                            row_label=value.strip()
                        if row_index<=15:
                            column_context[cell.column]=value
                    is_formula=cell.data_type=='f'
                    is_number=isinstance(value,(int,float,Decimal)) and not isinstance(value,bool)
                    is_error=cell.data_type=='e'
                    if not (is_formula or is_number or is_error):
                        continue
                    actual=value_cell.value if is_formula else value
                    evaluated=isinstance(actual,(int,float,Decimal)) and not isinstance(actual,bool)
                    amount=Decimal(str(actual)) if evaluated else None
                    hits=occurrences.get(amount,[]) if amount is not None else []
                    status='Pending — formula cache/error unavailable' if not evaluated else 'Not assessed — filing PDF unavailable' if not pdf or pdf_issue and not occurrences else 'Candidate occurrence — context verification required' if len(hits)==1 else 'Ambiguous numeric occurrences — human mapping required' if hits else 'No exact numeric occurrence found — investigate'
                    rows.append({'source_workbook':file['name'],'excel_sheet':sheet.title,'cell':cell.coordinate,'excel_value':str(actual) if actual is not None else 'unavailable','cell_type':'formula' if is_formula else 'literal' if is_number else 'unknown','period_label':str(column_context.get(cell.column,'')),'row_context':row_label,'filing_value':'; '.join(h[0] for h in hits[:8]) or 'Not found / not assessed','filing_locator':'; '.join(h[1] for h in hits[:8]),'status':status,'review_comment':pdf_issue+(f'{len(hits)} numeric occurrences; first eight locations shown. ' if len(hits)>8 else '')+'Confirm row label, period, units, sign, rounding, scope, and statement context. Numeric equality alone is not a completed tie-out.'})
                    if len(rows)>80000:
                        raise ReviewError('More than 80,000 numeric/formula cells. Supply a scoped workbook; no complete tie-out census was produced.')
    finally:
        original.close();cached.close()
    return rows or [{'source_workbook':file['name'],'excel_sheet':'Selected worksheet policy: '+policy,'cell':'Not applicable','excel_value':'No numeric/formula cells enumerated','cell_type':'unknown','period_label':'','row_context':'','filing_value':'Not assessed','filing_locator':'','status':'Pending source verification','review_comment':'Confirm that the intended financial statements and worksheet policy were supplied.'}]
