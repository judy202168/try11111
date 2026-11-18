"""Persistent implementation self-assessments and private evidence attachments."""
import copy
import csv
import io
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import jsonify, request, send_file
from werkzeug.utils import secure_filename
from .template import TEMPLATE

STATUSES = ('Not assessed', 'In progress', 'Met', 'Not met', 'Not applicable')
CONCLUSIONS = ('Not reviewed', 'No issues noted', 'Improvement opportunity', 'Issue identified', 'Further review needed')
SOD_MODES = ('Not determined', 'Fully in place', 'Not fully in place')
EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.docx', '.pptx', '.csv', '.txt', '.png', '.jpg', '.jpeg'}
MAX_EVIDENCE = 20 * 1024 * 1024


def requirements(template):
    result = []
    for parent in template['items']:
        if parent['kind'] != 'requirement':
            continue
        if parent['subchecks']:
            for child in parent['subchecks']:
                result.append(dict(parent, **child, parent_id=parent['id'], subchecks=[]))
        else:
            result.append(parent)
    return result


def adapt(text, assessment):
    return re.sub(r'\bWorkday\b', lambda _: assessment.get('source_system') or 'the source system', re.sub(r'\bRippling\b', lambda _: assessment.get('system_name') or 'the system', text))


def sod_eligible(assessment):
    response = assessment.get('responses', {}).get('sox-implementation-5', {})
    return response.get('status') == 'Met' and bool(response.get('evidence_reference') or response.get('attachments'))


def validity(assessment, requirement, response):
    status = response.get('status', 'Not assessed')
    if status == 'Met' and not (response.get('evidence_reference', '').strip() or response.get('attachments')):
        return 'Met requires a supporting evidence reference or attachment.'
    if status == 'Not applicable':
        if not response.get('na_reason', '').strip():
            return 'N/A requires an applicability rationale.'
    return ''


def summary(assessment):
    items = requirements(assessment['template'])
    today = datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()
    counts = {'total': len(items), 'met': 0, 'not_met': 0, 'not_applicable': 0, 'pending': 0, 'in_progress': 0, 'assessed': 0, 'resolved': 0, 'overdue': 0, 'ia_reviewed': 0, 'attention': 0}
    controls = {s['id']: {'total': 0, 'resolved': 0, 'not_met': 0} for s in assessment['template']['sections']}
    issues = []
    for item in items:
        response = assessment['responses'].get(item['id'], {})
        status = response.get('status', 'Not assessed')
        issue = validity(assessment, item, response)
        control = controls[item['control_id']]
        control['total'] += 1
        if issue:
            counts['attention'] += 1
            issues.append({'id': item['id'], 'message': issue})
        if status == 'Met' and not issue:
            counts['met'] += 1
        elif status == 'Not met':
            counts['not_met'] += 1
            control['not_met'] += 1
        elif status == 'Not applicable' and not issue:
            counts['not_applicable'] += 1
        else:
            counts['pending'] += 1
            if status == 'In progress':
                counts['in_progress'] += 1
        resolved = not issue and status in ('Met', 'Not applicable')
        if resolved:
            counts['resolved'] += 1
            control['resolved'] += 1
        if not issue and status in ('Met', 'Not met', 'Not applicable'):
            counts['assessed'] += 1
        if not resolved and response.get('target_date') and response['target_date'] < today:
            counts['overdue'] += 1
        if response.get('ia_conclusion', 'Not reviewed') != 'Not reviewed':
            counts['ia_reviewed'] += 1
    counts['percent_resolved'] = round(counts['resolved'] / max(counts['total'], 1) * 100)
    return dict(counts, controls=controls, applicability_issues=issues, sod_na_eligible=bool(sod_eligible(assessment)))


def register_implementation(app, read_store, write_store, lock, activity, storage_root, now):
    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError('Send a JSON object.')
        return value

    def text(value, key, maximum=5000, default=''):
        result = value.get(key, default)
        if not isinstance(result, str) or len(result) > maximum:
            raise ValueError(f'{key} must be text, at most {maximum:,} characters.')
        return result.strip()

    def date(value, key, default=''):
        result = text(value, key, 10, default)
        if result:
            try:
                datetime.strptime(result, '%Y-%m-%d')
            except ValueError:
                raise ValueError(f'{key} must be a valid YYYY-MM-DD date.')
        return result

    def metadata(value, original=None):
        original = original or {}
        result = {key: text(value, key, maximum, original.get(key, '')) for key, maximum in (('title', 200), ('system_name', 200), ('source_system', 200), ('owner', 200), ('process', 500), ('sod_evidence', 4000))}
        if not result['title'] or not result['system_name']:
            raise ValueError('Assessment title and system name are required.')
        result['go_live_date'] = date(value, 'go_live_date', original.get('go_live_date', ''))
        result['sod_mode'] = text(value, 'sod_mode', 30, original.get('sod_mode', 'Not determined'))
        if result['sod_mode'] not in SOD_MODES:
            raise ValueError('Choose a valid segregation-of-duties assessment.')
        if result['sod_mode'] == 'Fully in place' and not result['sod_evidence']:
            raise ValueError('Document the evidence supporting full SOD before selecting Fully in place.')
        return result

    def find(data, assessment_id):
        return next((a for a in data.get('implementation_assessments', []) if a['id'] == assessment_id), None)

    def serialize(assessment):
        return dict(assessment, summary=summary(assessment))

    def versions_match(expected, actual):
        return isinstance(expected, int) and not isinstance(expected, bool) and expected == actual

    @app.get('/api/implementation/template')
    def implementation_template():
        return jsonify(TEMPLATE)

    @app.get('/api/implementation/assessments')
    def implementation_list():
        with lock:
            assessments = read_store().get('implementation_assessments', [])
        return jsonify([{**{key: a.get(key) for key in ('id', 'title', 'system_name', 'owner', 'go_live_date', 'created_at', 'updated_at')}, 'summary': summary(a)} for a in assessments])

    @app.post('/api/implementation/assessments')
    def implementation_create():
        details = metadata(body())
        assessment = dict(details, id=str(uuid.uuid4()), created_at=now(), updated_at=now(), metadata_revision=0, template=copy.deepcopy(TEMPLATE), responses={})
        for requirement in requirements(TEMPLATE):
            assessment['responses'][requirement['id']] = {'status': 'Not assessed', 'revision': 0, 'evidence_reference': '', 'notes': '', 'na_reason': '', 'owner': '', 'target_date': '', 'ia_procedure': '', 'ia_notes': '', 'ia_conclusion': 'Not reviewed', 'reviewer': '', 'review_date': '', 'attachments': [], 'updated_at': None}
        with lock:
            data = read_store()
            data.setdefault('implementation_assessments', []).insert(0, assessment)
            activity(data, 'Implementation assessment created', assessment['title'])
            write_store(data)
        return jsonify(serialize(assessment)), 201

    @app.get('/api/implementation/assessments/<assessment_id>')
    def implementation_get(assessment_id):
        with lock:
            assessment = find(read_store(), assessment_id)
        if not assessment:
            return jsonify(error='Implementation assessment not found.'), 404
        return jsonify(serialize(assessment))

    @app.put('/api/implementation/assessments/<assessment_id>')
    def implementation_update(assessment_id):
        value = body()
        with lock:
            data = read_store()
            assessment = find(data, assessment_id)
            if not assessment:
                return jsonify(error='Implementation assessment not found.'), 404
            if not versions_match(value.get('expected_revision'), assessment['metadata_revision']):
                return jsonify(error='Assessment details changed since you opened them. Reload the latest assessment before saving.'), 409
            details = metadata(value, assessment)
            assessment.update(details, metadata_revision=assessment['metadata_revision'] + 1, updated_at=now())
            activity(data, 'Implementation assessment details updated', assessment['title'])
            write_store(data)
        return jsonify(serialize(assessment))

    @app.put('/api/implementation/assessments/<assessment_id>/requirements/<requirement_id>')
    def implementation_response(assessment_id, requirement_id):
        value = body()
        with lock:
            data = read_store()
            assessment = find(data, assessment_id)
            if not assessment:
                return jsonify(error='Implementation assessment not found.'), 404
            requirement = next((r for r in requirements(assessment['template']) if r['id'] == requirement_id), None)
            if not requirement:
                return jsonify(error='Requirement not found.'), 404
            original = assessment['responses'][requirement_id]
            if not versions_match(value.get('expected_revision'), original['revision']):
                return jsonify(error='This requirement changed since you opened it. Reload the assessment before saving to preserve the other changes.'), 409
            response = copy.deepcopy(original)
            for key, limit in (('status', 30), ('evidence_reference', 4000), ('notes', 5000), ('na_reason', 4000), ('owner', 200), ('ia_procedure', 5000), ('ia_notes', 5000), ('ia_conclusion', 50), ('reviewer', 200)):
                response[key] = text(value, key, limit, original.get(key, ''))
            response['target_date'] = date(value, 'target_date', original.get('target_date', ''))
            response['review_date'] = date(value, 'review_date', original.get('review_date', ''))
            if response['status'] not in STATUSES or response['ia_conclusion'] not in CONCLUSIONS:
                raise ValueError('Choose a valid requirement status and IA conclusion.')
            if response['status'] == 'Not met' and not response['notes']:
                raise ValueError('Describe the gap or next action when a requirement is not met.')
            issue = validity(assessment, requirement, response)
            if issue:
                raise ValueError(issue)
            response.update(revision=original['revision'] + 1, updated_at=now())
            assessment['responses'][requirement_id] = response
            assessment['updated_at'] = now()
            activity(data, 'Implementation requirement · ' + response['status'], f'{assessment["title"]} / {requirement["control_id"]} / Check {requirement["number"]}')
            write_store(data)
        return jsonify(serialize(assessment))

    @app.post('/api/implementation/assessments/<assessment_id>/requirements/<requirement_id>/evidence')
    def implementation_evidence(assessment_id, requirement_id):
        file = request.files.get('file')
        if not file or not file.filename:
            raise ValueError('Choose an evidence file to upload.')
        filename = secure_filename(file.filename)
        extension = Path(filename).suffix.lower()
        if extension not in EXTENSIONS:
            raise ValueError('Evidence supports PDF, Excel, Word, PowerPoint, CSV, TXT, PNG, and JPEG files.')
        content = file.stream.read(MAX_EVIDENCE + 1)
        if not content or len(content) > MAX_EVIDENCE:
            raise ValueError('Evidence files must be nonempty and no larger than 20 MB.')
        try:
            expected_revision = int(request.form.get('expected_revision', ''))
        except ValueError:
            raise ValueError('Reload the requirement before attaching evidence.')
        saved_path = None
        with lock:
            data = read_store()
            assessment = find(data, assessment_id)
            if not assessment or requirement_id not in assessment['responses']:
                return jsonify(error='Assessment or requirement not found.'), 404
            response = assessment['responses'][requirement_id]
            if not versions_match(expected_revision, response['revision']):
                return jsonify(error='This requirement changed. Reload the latest assessment before attaching evidence.'), 409
            attachment = {'id': str(uuid.uuid4()), 'name': filename, 'size': len(content), 'extension': extension, 'uploaded_at': now()}
            directory = Path(storage_root) / assessment['id']
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            saved_path = directory / (attachment['id'] + extension)
            saved_path.write_bytes(content)
            saved_path.chmod(0o600)
            response['attachments'].append(attachment)
            response.update(revision=response['revision'] + 1, updated_at=now())
            assessment['updated_at'] = now()
            activity(data, 'Implementation evidence attached', assessment['title'] + ' / ' + filename)
            try:
                write_store(data)
            except Exception:
                saved_path.unlink(missing_ok=True)
                raise
        return jsonify(serialize(assessment)), 201

    @app.get('/api/implementation/assessments/<assessment_id>/requirements/<requirement_id>/evidence/<attachment_id>')
    def implementation_download(assessment_id, requirement_id, attachment_id):
        with lock:
            assessment = find(read_store(), assessment_id)
            response = assessment['responses'].get(requirement_id) if assessment else None
            attachment = next((a for a in response.get('attachments', []) if a['id'] == attachment_id), None) if response else None
        if not attachment:
            return jsonify(error='Evidence file not found.'), 404
        path = Path(storage_root) / assessment['id'] / (attachment['id'] + attachment['extension'])
        if not path.is_file():
            return jsonify(error='Evidence file is missing from the private storage directory.'), 404
        return send_file(path, as_attachment=True, download_name=attachment['name'], mimetype='application/octet-stream')

    @app.get('/api/implementation/assessments/<assessment_id>/export')
    def implementation_export(assessment_id):
        with lock:
            assessment = find(read_store(), assessment_id)
        if not assessment:
            return jsonify(error='Implementation assessment not found.'), 404
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        header = ['Assessment', 'System', 'Check', 'Control ID', 'Checklist item', 'Evidence required', 'Status', 'Evidence reference', 'Attachments', 'Owner', 'Target date', 'Gap / action notes', 'N/A rationale', 'IA audit procedure', 'IA review notes', 'IA conclusion (manual)', 'Reviewer', 'Review date', 'Applicability / evidence validation', 'Template source', 'Template guidance', 'SOD assessment', 'SOD evidence']
        writer.writerow(header)
        def safe(value):
            value = str(value if value is not None else '')
            return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        for item in requirements(assessment['template']):
            response = assessment['responses'][item['id']]
            values = [assessment['title'], assessment['system_name'], item['number'], item['control_id'], adapt(item['question'], assessment), adapt(item['evidence_required'], assessment), response['status'], response['evidence_reference'], '; '.join(a['name'] for a in response['attachments']), response['owner'], response['target_date'], response['notes'], response['na_reason'], response['ia_procedure'], response['ia_notes'], response['ia_conclusion'], response['reviewer'], response['review_date'], validity(assessment, item, response) or 'No input validation gap; substantive review required', f'{assessment["template"]["source_filename"]} / {assessment["template"]["source_sheet"]}!{item["source_cell"]}', adapt(item['guidance'], assessment), assessment['sod_mode'], assessment['sod_evidence']]
            writer.writerow([safe(v) for v in values])
        buffer = io.BytesIO(('\ufeff' + stream.getvalue()).encode('utf-8'))
        return send_file(buffer, as_attachment=True, download_name=(secure_filename(assessment['title']) or 'System_Implementation') + '.csv', mimetype='text/csv; charset=utf-8')
