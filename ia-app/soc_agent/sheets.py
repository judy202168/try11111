"""Convert the supplied template layout to one editable native Google review tab.

The template is read only. No local Excel review is substituted for Google Sheets.
"""
import math
from pathlib import Path
from openpyxl import load_workbook
from .review import ReviewError

TEMPLATE = Path(__file__).parent / 'assets' / 'SOC_Report_Review_Template.xlsx'


def ref_text(refs, sources):
    names = {source['id']: source['filename'] for source in sources}
    return '; '.join(dict.fromkeys(f'{names.get(ref["source_id"], ref["source_id"])} — {ref["locator"]}' for ref in refs))


def fact_text(review, key):
    facts = review['facts'].get(key, [])
    return '\n'.join(dict.fromkeys(f'{fact["text"]}\nSource: {ref_text(fact["references"], review["sources"])}' for fact in facts)) or 'Not provided — confirm from source evidence.'


def color(value, fallback=None):
    if value is not None and value.type == 'rgb' and isinstance(value.rgb, str):
        rgb = value.rgb[-6:]
        return {'red': int(rgb[:2], 16)/255, 'green': int(rgb[2:4], 16)/255, 'blue': int(rgb[4:], 16)/255}
    return fallback


def template_format(cell):
    fmt = {'wrapStrategy': 'WRAP', 'verticalAlignment': 'TOP', 'textFormat': {'fontFamily': cell.font.name or 'Arial', 'fontSize': max(10, round(cell.font.sz or 10)), 'bold': bool(cell.font.bold), 'italic': bool(cell.font.italic), 'foregroundColor': color(cell.font.color, {'red': .13, 'green': .13, 'blue': .12})}}
    if cell.fill.patternType == 'solid':
        fill = color(cell.fill.fgColor)
        if fill:
            fmt['backgroundColor'] = fill
    alignment = cell.alignment.horizontal
    if alignment in ('left', 'center', 'right'):
        fmt['horizontalAlignment'] = alignment.upper()
    borders = {}
    for edge in ('top', 'bottom', 'left', 'right'):
        side = getattr(cell.border, edge, None)
        if side and side.style:
            borders[edge] = {'style': 'SOLID', 'color': color(side.color, {'red': .8, 'green': .8, 'blue': .8})}
    if borders:
        fmt['borders'] = borders
    return fmt


def sheet_payload(review):
    """Preserve template section order, labels and column spans; size each population."""
    workbook = load_workbook(TEMPLATE, data_only=False)
    template = workbook.active
    sources = review['sources']
    mapping = {r['cuec_id']: r for r in review['mappings']}
    values = {1: {1: 'OPENDOOR FY' + str(review['context']['review_year']) + ' SOX PROGRAM'},
              2: {1: 'SOC REPORT REVIEW · DRAFT — HUMAN REVIEW REQUIRED'},
              6: {3: review['context'].get('process') or 'Not provided — confirm SOX process.'},
              7: {3: review['context'].get('owner') or 'Not provided — confirm owner and role.'},
              56: {3: 'Pending — preparer, process-owner evaluation, reviewer name/date and sign-off evidence not recorded.\nAI preparation does not constitute approval.'}}
    for row, key in ((5,'provider'), (8,'report_type'), (9,'title'), (10,'period'), (11,'auditor'), (12,'report_date'), (13,'opinion'), (15,'bridge_period'), (16,'bridge_date'), (17,'bridge_signer')):
        values[row] = {3: fact_text(review, key)}
    values[9][3] += '\nActual Opendoor usage: ' + (review['context'].get('usage') or 'Pending — confirm actual service usage and ICFR scope.')
    values[10][3] += '\nIntended reliance: ' + (review['context'].get('reliance_start') or 'Not provided') + ' to ' + (review['context'].get('reliance_end') or 'Not provided') + '\nFiscal year-end: ' + (review['context'].get('fiscal_year_end') or 'Not provided')
    values[50] = {4: 'PROPOSED ASSESSMENT — HUMAN REVIEW PENDING\n' + review['summary']['period_assessment']}
    conclusion = ['PROPOSED ASSESSMENT — HUMAN REVIEW PENDING', review['summary']['reliance_assessment'], 'Objectives/tests and ICFR relevance: ' + review['summary']['control_objective_assessment'], fact_text(review,'scope_and_tests'), 'Prior-year and significant changes: ' + review['summary']['change_assessment'], 'Risk rating: ' + review['risk_rating'], 'Formal deficiency evaluation: Pending — apply approved SOX methodology and document human evaluation.', 'Population reconciliation (extracted, not independently verified): ' + ', '.join(f'{key}: {value}' for key, value in review['counts'].items()), 'Outstanding actions:\n' + '\n'.join(review['summary']['follow_ups']), 'Evidence and completeness limitations:\n' + '\n'.join(review['limitations']), 'Final decision and sign-off: Pending — human verification of the report, mappings, evidence, coverage, and required approvals.']
    values[51] = {4: '\n\n'.join(conclusion)}
    if len(values[51][4]) > 45000:
        raise ReviewError('The conclusion exceeds a Google Sheets cell limit. Use a scoped report; no content was omitted.')

    exceptions = []
    for i, item in enumerate(review['exceptions'], 1):
        exceptions.append({1: str(i), 2: item['key'] + '\n' + item['description'] + '\nSource: ' + ref_text(item['references'], sources), 3: item['provider_response'] or 'Not provided', 4: 'PROPOSED — OWNER REVIEW PENDING\n' + item['evaluation']})
    if not exceptions:
        exceptions = [{1: '—', 2: 'No exceptions extracted — Pending verification against all auditor tests and exception pages.', 3: 'Not applicable to extracted population; completeness is unconfirmed.', 4: 'Pending — absence of extracted exceptions is not a no-exception conclusion.'}]
    cuecs = []
    for i, item in enumerate(review['cuecs'], 1):
        m = mapping[item['id']]
        cuecs.append({1: str(i), 2: item['key'] + '\n' + item['wording'] + '\nSource: ' + ref_text(item['references'], sources), 3: '\n\n'.join(['Proposed applicability: ' + m['applicability'], 'Historical mapping: ' + (m['historical_mapping'] or 'Not provided'), 'Proposed current mapping: ' + (m['current_mapping'] or 'Pending — no supported match.'), 'Evidence and gaps: ' + m['evidence_and_gaps'], 'Mapping sources: ' + (ref_text(m['references'], sources) or 'Not provided'), m['status']])})
    if not cuecs:
        cuecs = [{1: '—', 2: 'No CUECs extracted — Pending human completeness verification.', 3: 'Pending — confirm whether the report contains CUECs before concluding that none apply.'}]
    subservices = []
    for i, item in enumerate(review['subservices'], 1):
        subservices.append({1: str(i), 2: item['name']+'\nScope: '+item['scope']+'\nSource: '+ref_text(item['references'], sources), 3: item['services'], 4: item['impact'], 5: item['provider_response'], 6: 'PROPOSED — OWNER REVIEW PENDING\n'+item['evaluation']})
    if not subservices:
        subservices = [{1: '—', 2: 'No subservices extracted — Pending verification of the complete system description.', 3: 'Pending', 4: 'Pending', 5: 'Not provided', 6: 'Pending — verify dependencies, carve-outs and CSOC responsibilities.'}]
    output_rows, merges, row_heights = [], [], []
    widths = [38, 296, 454, 356, 350, 385]
    row_map = {}

    def append_row(template_row, replacements=None):
        destination = len(output_rows)
        row_map.setdefault(template_row, []).append(destination)
        local_merges = [(m.min_col, m.max_col) for m in template.merged_cells.ranges if m.min_row == template_row and m.max_row == template_row]
        cells = []
        height = 25
        replacements = replacements or {}
        for column in range(1, 7):
            cell = template.cell(template_row, column)
            value = replacements.get(column, cell.value)
            # Native stringValue prevents formula injection from uploaded/model-generated content.
            entry = {'userEnteredFormat': template_format(cell)}
            if value is not None:
                text = str(value)
                if len(text) > 45000:
                    raise ReviewError('A review cell exceeds 45,000 characters. No content was omitted.')
                entry['userEnteredValue'] = {'stringValue': text}
                end_column = next((end for start, end in local_merges if start == column), column)
                available = sum(widths[column-1:end_column]) - 20
                chars = max(10, available / 6.2)
                lines = sum(max(1, math.ceil(len(line) / chars)) for line in text.split('\n'))
                height = max(height, lines * 16 + 16)
            cells.append(entry)
        output_rows.append({'values': cells})
        row_heights.append({'pixelSize': height})
        for start, end in local_merges:
            merges.append({'sheetId': 0, 'startRowIndex': destination, 'endRowIndex': destination+1, 'startColumnIndex': start-1, 'endColumnIndex': end})

    def split_text(text, limit=2200):
        parts = []
        while len(text) > limit:
            stop = text.rfind('\n', 0, limit)
            if stop < limit // 2:
                stop = text.rfind(' ', 0, limit)
            if stop < limit // 2:
                stop = limit
            parts.append(text[:stop])
            text = text[stop:]
        return parts + [text]

    row = 1
    while row <= 56:
        if row in (24, 28, 46):
            population = {24: exceptions, 28: cuecs, 46: subservices}[row]
            for item in population:
                append_row(row, item)
            row = 42 if row == 28 else row + 1
        elif row == 51:
            for index, text in enumerate(split_text(values[51][4])):
                replacements = dict(values[51])
                replacements[4] = text
                if index:
                    replacements.update({1: '', 2: 'Reliance assessment — continued'})
                append_row(row, replacements)
            row += 1
        else:
            append_row(row, values.get(row))
            row += 1
    workbook.close()
    # Metadata remains outside the review data, not in additional tabs.
    return {'properties': {'title': ('SOC Review — ' + (review['facts']['provider'][0]['text'] if review['facts']['provider'] else 'Provider pending') + ' — FY' + str(review['context']['review_year']))[:180], 'locale': 'en_US'},
            'sheets': [{'properties': {'sheetId': 0, 'title': 'SOC REVIEW', 'gridProperties': {'rowCount': len(output_rows), 'columnCount': 6, 'hideGridlines': True, 'frozenRowCount': 2}},
                        'merges': merges, 'data': [{'startRow': 0, 'startColumn': 0, 'rowData': output_rows, 'columnMetadata': [{'pixelSize': value} for value in widths], 'rowMetadata': row_heights}]}]}
