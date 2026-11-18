"""Runtime Excel output for the independently implemented Flask review workflow."""
import re
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

COLUMNS={
 'vs. prior version':['parent_section','subsection','current_excerpt','prior_subsection','prior_excerpt','gap_type','risk_level','review_comment','match_method','source_link'],
 **{f'vs. company {i}':['parent_section','subsection','current_excerpt','peer_subsection','peer_excerpt','assessment','reasoning','match_method','source_link'] for i in range(1,4)},
 'ASU screen':['asu_id','asu_topic','effective_window','applicability','relevant_section','draft_coverage','comment','source_link'],
 'Suggested Improvement':['section','current_disclosure','proposed_disclosure','reasoning_basis','driver'],
 'Coverage QA':['check_type','item_key','item_title','status','detail'],
 'cross-ref consistency':['source_section','reference_text','target_section','status','comment'],
 'financial tie-out':['source_workbook','excel_sheet','cell','excel_value','cell_type','period_label','row_context','filing_value','filing_locator','status','review_comment']
}
EXTRA_COMPARISON_COLUMNS=['source_accession','draft_locator','comparison_locator','draft_subsection_id']


def display_text(value):
    text=re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]','',str(value if value is not None else ''))
    if len(text)>32700:
        text=text[:32500]+'\n[Excel cell excerpt limit reached. Full source text is retained in the run source snapshot; review the original before concluding.]'
    return text


def create_workbook(result,path):
    workbook=Workbook()
    workbook.remove(workbook.active)
    for name,base_columns in COLUMNS.items():
        if name=='financial tie-out' and name not in result['tables']:
            continue
        columns=list(base_columns)+(EXTRA_COMPARISON_COLUMNS if name.startswith('vs. ') else [])
        sheet=workbook.create_sheet(name)
        sheet.append(columns)
        for cell in sheet[1]:
            cell.fill=PatternFill('solid',fgColor='0040E6')
            cell.font=Font(name='Arial',size=10,color='FFFFFF',bold=True)
            cell.alignment=Alignment(wrap_text=True,vertical='center')
        sheet.row_dimensions[1].height=32
        for index,row in enumerate(result['tables'].get(name,[]),2):
            for col,key in enumerate(columns,1):
                cell=sheet.cell(index,col)
                cell.value=display_text(row.get(key,''))
                cell.data_type='s'  # Disclosures and model text must never become Excel formulas.
                cell.font=Font(name='Arial',size=10,color='403E3C')
                cell.alignment=Alignment(wrap_text=True,vertical='top')
                if index%2==0:
                    cell.fill=PatternFill('solid',fgColor='F2F4F7')
            sheet.row_dimensions[index].height=100 if name.startswith('vs. ') or name=='Suggested Improvement' else 72
        for index,key in enumerate(columns,1):
            wide=any(word in key for word in ('excerpt','comment','disclosure','reasoning','detail'))
            sheet.column_dimensions[get_column_letter(index)].width=68 if wide else 38 if 'source' in key or 'locator' in key else 28
        sheet.freeze_panes='A2'
        sheet.auto_filter.ref=sheet.dimensions
        sheet.sheet_view.zoomScale=85
    workbook.properties.title='SEC disclosure review — draft for human review'
    workbook.properties.subject=result['context']['title']
    workbook.properties.description='Source-referenced draft comparison. Automated outputs do not constitute approval or a completed professional review.'
    workbook.save(path)
    workbook.close()
    # Verify the saved native workbook rather than assuming the export succeeded.
    check=load_workbook(path,read_only=True,data_only=False)
    expected=[name for name in COLUMNS if name!='financial tie-out' or name in result['tables']]
    if check.sheetnames!=expected:
        raise ValueError('Workbook tab reconciliation failed.')
    for name in check.sheetnames:
        sheet=check[name]
        if sheet.max_row!=len(result['tables'].get(name,[]))+1:
            raise ValueError('Workbook row reconciliation failed: '+name)
        if any(cell.data_type=='f' for row in sheet for cell in row):
            raise ValueError('Unexpected executable formula in disclosure output.')
    check.close()
    return Path(path)
