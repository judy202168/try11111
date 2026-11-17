"""Request-scoped model telemetry. Never stores credentials or provider headers."""
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation

_calls=ContextVar('evaluation_model_calls',default=None)

@contextmanager
def collect_calls():
    parent=_calls.get();calls=[]; token=_calls.set(calls)
    try: yield calls
    finally:
        _calls.reset(token)
        if parent is not None:parent.extend(calls)

def record_response(response, seconds, requested_model):
    calls=_calls.get()
    if calls is None:return
    try:data=response.json()
    except ValueError:data={}
    if not isinstance(data,dict):data={}
    usage=data.get('usage') or {}
    if not isinstance(usage,dict):usage={}
    calls.append({'model':data.get('model') or requested_model,'http_status':response.status_code,'duration_ms':round(seconds*1000),'usage':{k:usage.get(k) for k in ['prompt_tokens','completion_tokens','cost']}})

def cost_summary(calls, pricing=None):
    if not calls:return 0.0,'no_model_calls'
    total=Decimal(0); source='provider_reported'
    try:
        for call in calls:
            usage=call['usage']; value=usage.get('cost')
            if value is not None:total+=Decimal(str(value))
            elif pricing and usage.get('prompt_tokens') is not None and usage.get('completion_tokens') is not None:
                total+=Decimal(str(usage['prompt_tokens']))*Decimal(pricing['prompt'])+Decimal(str(usage['completion_tokens']))*Decimal(pricing['completion']);source='token_estimate'
            else:return None,'unavailable'
        if not total.is_finite() or total<0:return None,'unavailable'
        return float(total),source
    except (InvalidOperation,TypeError,KeyError):return None,'unavailable'


def record_failure(seconds, model, error):
    calls=_calls.get()
    if calls is not None:
        calls.append({'model':model,'http_status':None,'duration_ms':round(seconds*1000),'usage':{},'error':type(error).__name__})
