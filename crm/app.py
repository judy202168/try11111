import hmac
import os
import secrets
from datetime import timedelta
from uuid import UUID
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request, session, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY') or secrets.token_hex(32),
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                  SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'true') == 'true',
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=16384)
limiter = Limiter(get_remote_address, app=app, default_limits=['300 per minute'], storage_uri='memory://')
STAGES = ['Lead', 'Qualified', 'Proposal', 'Negotiation', 'Won', 'Lost']
FIELDS = {
    'contacts': {'name', 'email', 'company', 'role', 'phone', 'status', 'owner', 'notes'},
    'deals': {'title', 'company', 'contact_id', 'value', 'stage', 'owner', 'close_date', 'notes'},
    'tasks': {'title', 'contact_id', 'due_date', 'priority', 'done', 'owner'},
}


def db(resource, method='GET', data=None, record_id=None, extra_params=None):
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    key = os.getenv('SUPABASE_PUBLISHABLE_KEY', '')
    if not url or not key or not os.getenv('CRM_DATABASE_TOKEN'):
        raise RuntimeError('Database is not configured. Connect Supabase to finish setup.')
    params = {'order': 'created_at.desc'} if method == 'GET' else {}
    if extra_params: params.update(extra_params)
    if record_id:
        params['id'] = f'eq.{record_id}'
    response = requests.request(method, f'{url}/rest/v1/crm_{resource}', params=params,
                                headers={'apikey': key, 'X-CRM-Token': os.environ['CRM_DATABASE_TOKEN'],
                                         'Prefer': 'return=representation'}, json=data, timeout=15)
    if not response.ok:
        app.logger.error('Database operation failed: resource=%s status=%s', resource, response.status_code)
        raise RuntimeError('The database request failed. Please try again.')
    return response.json() if response.content else []


@app.before_request
def protect():
    if request.path.startswith('/api/') and request.path not in ['/api/login', '/api/session']:
        if not session.get('authenticated'):
            return jsonify(error='Please sign in.'), 401
    if request.path.startswith('/api/') and request.method in ['POST', 'PATCH', 'DELETE']:
        origin = request.headers.get('Origin')
        if origin and urlparse(origin).netloc != request.host:
            return jsonify(error='Invalid request origin.'), 403
        if request.path != '/api/login' and not hmac.compare_digest(
                request.headers.get('X-CSRF-Token', ''), session.get('csrf', secrets.token_hex(32))):
            return jsonify(error='Session expired. Refresh and sign in again.'), 403


@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/')
def index():
    return render_template('index.html')


@app.get('/health')
def health():
    return jsonify(status='ok', database_configured=bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_PUBLISHABLE_KEY') and os.getenv('CRM_DATABASE_TOKEN')))


@app.get('/api/session')
def auth_session():
    return jsonify(authenticated=bool(session.get('authenticated')), csrf=session.get('csrf'))


@app.post('/api/login')
@limiter.limit('5 per minute')
def login():
    password = os.getenv('CRM_PASSWORD', '')
    payload = request.get_json(silent=True) or {}
    supplied = payload.get('password', '') if isinstance(payload, dict) else ''
    if not isinstance(supplied, str) or not password or not hmac.compare_digest(supplied.encode('utf-8'), password.encode('utf-8')):
        return jsonify(error='Incorrect password.'), 401
    session.clear()
    session.update(authenticated=True, csrf=secrets.token_hex(32))
    session.permanent = True
    return jsonify(csrf=session['csrf'])


@app.post('/api/logout')
def logout():
    session.clear()
    return jsonify(ok=True)


@app.get('/api/data')
def data():
    return jsonify({resource: db(resource) for resource in FIELDS})


def validate(resource, payload, creating):
    if not isinstance(payload, dict) or not payload or set(payload) - FIELDS[resource]:
        raise ValueError('Provide valid record fields.')
    required = 'name' if resource == 'contacts' else 'title'
    if creating and required not in payload:
        raise ValueError(f'{required.title()} is required.')
    for field, value in payload.items():
        if field in ['value', 'done']:
            continue
        if value is None and field in ['contact_id', 'close_date', 'due_date']:
            continue
        if not isinstance(value, str) or len(value) > (4000 if field == 'notes' else 250):
            raise ValueError(f'Invalid {field}.')
        payload[field] = value.strip()
        if field == required and not payload[field]:
            raise ValueError(f'{required.title()} is required.')
        if field == 'contact_id':
            UUID(value)
        if field in ['due_date', 'close_date']:
            from datetime import date
            date.fromisoformat(value)
    if 'email' in payload and payload['email'] and ('@' not in payload['email'] or '.' not in payload['email'].split('@')[-1]):
        raise ValueError('Enter a valid email address.')
    if 'value' in payload:
        if isinstance(payload['value'], bool) or not isinstance(payload['value'], (int, float)) or not 0 <= payload['value'] <= 1e12:
            raise ValueError('Deal value must be between 0 and 1 trillion.')
    if 'done' in payload and not isinstance(payload['done'], bool):
        raise ValueError('Done must be true or false.')
    for field, allowed in [('stage', STAGES), ('status', ['Lead', 'Active', 'Customer', 'Inactive']), ('priority', ['Low', 'Medium', 'High'])]:
        if field in payload and payload[field] not in allowed:
            raise ValueError(f'Invalid {field}.')
    return payload


@app.route('/api/<resource>', methods=['POST'])
@app.route('/api/<resource>/<record_id>', methods=['PATCH', 'DELETE'])
def mutate(resource, record_id=None):
    if resource not in FIELDS:
        return jsonify(error='Not found.'), 404
    if record_id:
        try:
            UUID(record_id)
        except ValueError:
            return jsonify(error='Invalid record ID.'), 400
    if request.method == 'DELETE':
        rows = db(resource, 'DELETE', record_id=record_id)
    else:
        try:
            payload = validate(resource, request.get_json(silent=True), request.method == 'POST')
        except (ValueError, TypeError):
            return jsonify(error='Check required fields, dates, email, and numeric values.'), 400
        rows = db(resource, request.method, payload, record_id)
    if record_id and not rows:
        return jsonify(error='Record no longer exists. Refresh the page.'), 404
    return jsonify(record=rows[0] if rows else None), 201 if request.method == 'POST' else 200


@app.errorhandler(RuntimeError)
def runtime_error(error):
    return jsonify(error=str(error)), 503


@app.errorhandler(requests.RequestException)
def network_error(error):
    return jsonify(error='Database connection interrupted. Please try again.'), 503


@app.errorhandler(429)
def rate_limited(error):
    return jsonify(error='Too many attempts. Please wait a minute.'), 429


from agent_routes import register
register(app, db)
from evaluation_routes import register as register_evaluations
register_evaluations(app, db, limiter)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '8080')))
