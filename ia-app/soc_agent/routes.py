"""Background SOC review jobs and Google connection for the local Flask app."""
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from authlib.integrations.flask_client import OAuth
from flask import jsonify, redirect, request, session
from werkzeug.utils import secure_filename
from .review import ALLOWED, MAX_FILE, ReviewError, extract_document, prepare_review
from .sheets import sheet_payload


def register_soc(app, read_store, write_store, lock, activity, storage_root):
    app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1')
    app.config['MAX_CONTENT_LENGTH'] = 80 * 1024 * 1024
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='soc-review')
    job_gate = threading.BoundedSemaphore(3)
    google_tokens = {}  # Tokens stay server-side in memory; never in browser cookies or exported JSON.
    oauth = OAuth(app)
    configured = bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))
    google = oauth.register('google_soc', client_id=os.environ.get('GOOGLE_CLIENT_ID'), client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'), server_metadata_url='https://accounts.google.com/.well-known/openid-configuration', client_kwargs={'scope': 'openid email https://www.googleapis.com/auth/drive.file', 'timeout': 30})

    def stamp():
        return datetime.now(timezone.utc).isoformat()

    def token_entry():
        with lock:
            current = google_tokens.get(session.get('soc_google_session'))
            if current and current['expires_at'] > time.time() + 30:
                return current
            return None

    def update(run_id, **changes):
        with lock:
            data = read_store()
            run = next(r for r in data.get('soc_reviews', []) if r['id'] == run_id)
            run.update(changes, updated_at=stamp())
            write_store(data)

    def progress(run_id, stage, message):
        with lock:
            data = read_store()
            run = next(r for r in data['soc_reviews'] if r['id'] == run_id)
            run.update(stage=stage, updated_at=stamp())
            run['steps'].append({'at': stamp(), 'stage': stage, 'message': message})
            write_store(data)

    def worker(run_id, files, context):
        try:
            update(run_id, status='Running')
            progress(run_id, 'Reading uploaded documents', 'Extracting complete document text with PDF page and workbook cell references.')
            documents = [extract_document(path, source_id, filename) for source_id, path, filename in files]
            result = prepare_review(documents, context, lambda stage, message: progress(run_id, stage, message))
            # Validate the output layout before accepting a prepared review.
            sheet_payload(result)
            update(run_id, status='Draft ready', stage='Ready for human review', result=result, error=None)
            progress(run_id, 'Draft ready', 'Review prepared. Validate the findings, then create the Google Sheet. No human sign-off has been recorded.')
            with lock:
                data = read_store()
                activity(data, 'SOC review draft prepared', context['title'])
                write_store(data)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ReviewError) else 'Review processing failed. Check the server log and retry with readable source documents.'
            if not isinstance(exc, ReviewError):
                app.logger.exception('SOC review job failed')
            update(run_id, status='Failed', stage='Needs attention', error=message)
        finally:
            job_gate.release()

    @app.get('/api/soc/config')
    def soc_config():
        current = token_entry()
        return jsonify(ai_configured=bool(os.environ.get('OPENAI_API_KEY')), google_configured=configured, google_connected=bool(current), google_email=current['email'] if current else None, allowed_domain='opendoor.com', max_file_mb=25, formats=['PDF', 'XLSX', 'CSV', 'DOCX', 'TXT'])

    @app.get('/api/soc/reviews')
    def list_reviews():
        with lock:
            runs = read_store().get('soc_reviews', [])
        # List responses do not repeat the entire review body on every poll.
        return jsonify([{k: v for k, v in run.items() if k != 'result'} for run in runs])

    @app.get('/api/soc/reviews/<run_id>')
    def get_review(run_id):
        with lock:
            run = next((r for r in read_store().get('soc_reviews', []) if r['id'] == run_id), None)
        if not run:
            return jsonify(error='SOC review not found.'), 404
        return jsonify(run)

    @app.post('/api/soc/reviews')
    def create_review():
        if not os.environ.get('OPENAI_API_KEY'):
            return jsonify(error='AI is not configured. Set OPENAI_API_KEY on the server before uploading confidential review documents.'), 503
        if request.form.get('consent') != 'yes':
            return jsonify(error='Confirm that the uploaded content may be processed by the configured AI service.'), 400
        title = request.form.get('title', '').strip()
        year = request.form.get('review_year', '').strip()
        if not title or len(title) > 180 or not re.fullmatch(r'20\d{2}', year):
            return jsonify(error='Provide a review title (up to 180 characters) and a four-digit review year.'), 400
        context = {'title': title, 'review_year': year}
        for name in ('process', 'owner', 'usage', 'reliance_start', 'reliance_end', 'fiscal_year_end', 'notes'):
            value = request.form.get(name, '').strip()
            if len(value) > (4000 if name == 'notes' else 1500):
                return jsonify(error=f'{name} is too long.'), 400
            if name in ('reliance_start', 'reliance_end', 'fiscal_year_end') and value:
                try:
                    datetime.strptime(value, '%Y-%m-%d')
                except ValueError:
                    return jsonify(error='Use valid YYYY-MM-DD dates.'), 400
            context[name] = value
        if context['reliance_start'] and context['reliance_end'] and context['reliance_start'] > context['reliance_end']:
            return jsonify(error='The reliance end date must be on or after its start date.'), 400
        chosen = []
        for name, required in (('soc', True), ('rcm', True), ('prior', False), ('bridge', False)):
            file = request.files.get(name)
            if not file or not file.filename:
                if required:
                    return jsonify(error='Upload the current SOC report and company RCM. The prior-year review is optional.'), 400
                continue
            filename = secure_filename(file.filename)
            suffix = Path(filename).suffix.lower()
            if suffix not in ALLOWED or (name == 'soc' and suffix != '.pdf'):
                return jsonify(error='The current SOC report must be PDF. Other inputs support PDF, XLSX, CSV, DOCX, or TXT.'), 400
            if name == 'soc' and re.search(r'(^|[_\-\s])bridge([_\-\s]|$)|bridge[_\-\s]*(ltr|letter)', filename, re.IGNORECASE):
                return jsonify(error='The Current SOC report field contains a bridge letter. Upload the complete SOC report there, including the service auditor opinion, system description, tests, exceptions, and CUECs. Upload the bridge letter separately in Bridge letter or supporting evidence.'), 400
            chosen.append((name, file, filename))
        if not job_gate.acquire(blocking=False):
            return jsonify(error='Three reviews are already active or queued. Wait for one to finish before starting another.'), 429
        run_id = str(uuid.uuid4())
        directory = Path(storage_root) / run_id
        files = []
        try:
            directory.mkdir(parents=True, mode=0o700)
            for source_id, file, filename in chosen:
                content = file.stream.read(MAX_FILE + 1)
                if not content or len(content) > MAX_FILE:
                    raise ReviewError(f'{filename}: upload a nonempty file no larger than 25 MB.')
                path = directory / (source_id + Path(filename).suffix.lower())
                path.write_bytes(content)
                path.chmod(0o600)
                files.append((source_id, path, filename))
            run = {'id': run_id, 'title': title, 'context': context, 'status': 'Queued', 'stage': 'Waiting to start', 'created_at': stamp(), 'updated_at': stamp(), 'files': [{'role': source_id, 'name': filename} for source_id, _, filename in files], 'steps': [], 'error': None, 'sheet': None}
            with lock:
                data = read_store()
                data.setdefault('soc_reviews', []).insert(0, run)
                activity(data, 'SOC review started', title)
                write_store(data)
            executor.submit(worker, run_id, files, context)
            return jsonify(run), 202
        except Exception as exc:
            job_gate.release()
            shutil.rmtree(directory, ignore_errors=True)
            if isinstance(exc, ReviewError):
                return jsonify(error=str(exc)), 400
            raise

    @app.get('/auth/google/connect')
    def google_connect():
        if not configured:
            return redirect('/?google=not-configured#soc')
        callback = os.environ.get('GOOGLE_REDIRECT_URI', request.host_url.rstrip('/') + '/auth/google/callback')
        try:
            return google.authorize_redirect(callback, hd='opendoor.com', prompt='select_account')
        except Exception:
            app.logger.warning('Unable to start Google authorization')
            return redirect('/?google=failed#soc')

    @app.get('/auth/google/callback')
    def google_callback():
        try:
            token = google.authorize_access_token()
            user = token.get('userinfo', {})  # Authlib verifies signature, issuer, audience, expiry, state and nonce.
            if user.get('hd') != 'opendoor.com' or user.get('email_verified') is not True or not user.get('email', '').lower().endswith('@opendoor.com'):
                return redirect('/?google=domain-denied#soc')
            current_id = secrets.token_urlsafe(32)
            with lock:
                # Expired tokens are discarded, and a reconnect replaces the previous connection.
                for key in list(google_tokens):
                    if google_tokens[key]['expires_at'] <= time.time() or key == session.get('soc_google_session'):
                        google_tokens.pop(key, None)
                google_tokens[current_id] = {'access_token': token['access_token'], 'expires_at': float(token.get('expires_at', time.time()+int(token.get('expires_in', 3600)))), 'email': user['email']}
            session['soc_google_session'] = current_id
            return redirect('/?google=connected#soc')
        except Exception:
            app.logger.warning('Google authorization failed (details suppressed to protect credentials)')
            return redirect('/?google=failed#soc')

    @app.post('/api/soc/google/disconnect')
    def google_disconnect():
        with lock:
            google_tokens.pop(session.pop('soc_google_session', None), None)
        return jsonify(disconnected=True)

    @app.post('/api/soc/reviews/<run_id>/sheet')
    def publish_sheet(run_id):
        current = token_entry()
        if not current:
            return jsonify(error='Connect your Opendoor Google account before creating the review Google Sheet.'), 401
        with lock:
            data = read_store()
            run = next((r for r in data.get('soc_reviews', []) if r['id'] == run_id), None)
            if not run:
                return jsonify(error='SOC review not found.'), 404
            if run.get('sheet'):
                if run['sheet'].get('owner_email') != current['email']:
                    return jsonify(error='This review already has a Sheet created by another connected account. Open it with the authorized account.'), 403
                return jsonify(run['sheet'])
            if run['status'] != 'Draft ready' or not run.get('result'):
                return jsonify(error='Wait for a prepared draft before creating the Sheet.'), 409
            if run.get('exporting'):
                return jsonify(error='Google Sheet creation is already in progress.'), 409
            run['exporting'] = True
            write_store(data)
        try:
            payload = sheet_payload(run['result'])
            response = requests.post('https://sheets.googleapis.com/v4/spreadsheets', json=payload, headers={'Authorization': 'Bearer ' + current['access_token']}, timeout=(15, 90))
            if not response.ok:
                if response.status_code in (401, 403):
                    raise ReviewError('Google denied creation. Reconnect your account and check that the Sheets API and app access are allowed by your organization.')
                raise ReviewError(f'Google Sheets returned HTTP {response.status_code}. Your draft is still saved; retry the export.')
            created = response.json()
            spreadsheet_id = created.get('spreadsheetId', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]+', spreadsheet_id):
                raise ReviewError('Google did not return a valid spreadsheet ID. Check Google Drive before retrying.')
            sheet = {'id': spreadsheet_id, 'url': f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit', 'owner_email': current['email'], 'created_at': stamp(), 'verified': False}
            # Save the ID immediately so verification failures or page reloads do not create duplicates.
            update(run_id, sheet=sheet)
            try:
                verification = requests.get(f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}', params={'includeGridData': 'true'}, headers={'Authorization': 'Bearer ' + current['access_token']}, timeout=(15, 60))
                if verification.ok:
                    actual = verification.json()
                    expected_rows = payload['sheets'][0]['data'][0]['rowData']
                    actual_sheets = actual.get('sheets', [])
                    actual_rows = actual_sheets[0].get('data', [{}])[0].get('rowData', []) if len(actual_sheets) == 1 else []
                    same = len(actual_sheets) == 1 and actual_sheets[0]['properties']['title'] == 'SOC REVIEW'
                    for i, row in enumerate(expected_rows):
                        for j, cell in enumerate(row['values']):
                            expected = cell.get('userEnteredValue', {}).get('stringValue', '')
                            observed = actual_rows[i].get('values', [])[j].get('userEnteredValue', {}).get('stringValue', '') if i < len(actual_rows) and j < len(actual_rows[i].get('values', [])) else ''
                            same = same and expected == observed
                    sheet['verified'] = bool(same)
            except requests.RequestException:
                pass
            sheet['verification_note'] = 'One tab and all submitted cell text were read back and matched. Visually review wrapping, mappings, source pages, and sign-off in Google Sheets.' if sheet['verified'] else 'Sheet created; content verification is incomplete. Open it and verify the full template and populations before relying on it. Do not recreate it merely to retry verification.'
            update(run_id, sheet=sheet)
            with lock:
                data = read_store()
                activity(data, 'SOC review Google Sheet created', run['title'])
                write_store(data)
            return jsonify(sheet), 201
        except ReviewError as exc:
            return jsonify(error=str(exc)), 502
        except requests.RequestException:
            return jsonify(error='Google did not confirm the export. Your draft is saved. Check your Google Drive for a newly created Sheet before retrying to avoid duplicates.'), 502
        finally:
            update(run_id, exporting=False)

    # A server restart interrupts thread jobs. Mark them honestly instead of leaving a false spinner.
    with lock:
        data = read_store()
        changed = False
        for run in data.get('soc_reviews', []):
            if run['status'] in ('Queued', 'Running'):
                run.update(status='Failed', stage='Interrupted by server restart', error='The server restarted during processing. Start a new review with the same documents; no completed review was recorded.')
                changed = True
            if run.pop('exporting', False):
                changed = True
        if changed:
            write_store(data)
    return {'executor': executor, 'google': google, 'tokens': google_tokens, 'worker': worker}