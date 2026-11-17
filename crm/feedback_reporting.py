"""Deterministic reporting and weekly recommendations; never alters prompts."""
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from hashlib import sha256
import json
from zoneinfo import ZoneInfo
from feedback_constants import REASONS,HIGH_RISK,RECOMMENDATIONS

TZ=ZoneInfo('America/Los_Angeles')

def all_rows(db,resource,params=None):
    rows=[]
    for offset in range(0,100000,1000):
        page=db(resource,extra_params={**(params or {}),'limit':1000,'offset':offset});rows.extend(page)
        if len(page)<1000:return rows
    raise RuntimeError('Report exceeds the lightweight reporting limit; narrow the date range.')

def rate_group(rows):
    counts=Counter(r['action'] for r in rows);total=len(rows)
    return {'total':total,'approvals':counts['approve'],'rejections':counts['reject'],'edits':counts['edit_approve'],'approval_rate':round(100*counts['approve']/total,1) if total else None,'rejection_rate':round(100*counts['reject']/total,1) if total else None,'edit_rate':round(100*counts['edit_approve']/total,1) if total else None}

def report(rows):
    failures=[r for r in rows if r['action'] in ('reject','edit_approve')]
    reasons=Counter(r['reason'] for r in failures)
    dimensions={}
    for dimension in ('workflow','team','model','prompt_label'):
        grouped=defaultdict(list)
        for row in rows:grouped[row.get(dimension) or 'Unknown'].append(row)
        dimensions[dimension]=[{'label':name,**rate_group(items)} for name,items in sorted(grouped.items())]
    weeks=defaultdict(list)
    for row in rows:
        day=datetime.fromisoformat(row['reviewed_at'].replace('Z','+00:00')).astimezone(TZ).date();monday=day-timedelta(days=day.weekday());weeks[str(monday)].append(row)
    return {'overall':rate_group(rows),'reasons':[{'reason':reason,'count':count,'high_risk':reason in HIGH_RISK} for reason,count in reasons.most_common()],
            'high_risk_count':sum(r['reason'] in HIGH_RISK for r in failures),'dimensions':dimensions,
            'trends':[{'week':week,**rate_group(items)} for week,items in sorted(weeks.items())],
            'recent_failures':sorted(failures,key=lambda r:r['reviewed_at'],reverse=True)[:30]}

def weekly_summary(db,reviewer_id=None,closed=False,now=None):
    now=now or datetime.now(TZ);today=now.astimezone(TZ).date();monday=today-timedelta(days=today.weekday())
    start=monday-timedelta(days=7) if closed else monday;end=start+timedelta(days=7)
    rows=all_rows(db,'suggestion_reviews',{'reviewed_at':'gte.'+datetime.combine(start,datetime.min.time(),TZ).isoformat()})
    rows=[r for r in rows if datetime.fromisoformat(r['reviewed_at'].replace('Z','+00:00')).astimezone(TZ).date()<end]
    digest=sha256(json.dumps(sorted(r['id'] for r in rows)).encode()).hexdigest();kind='closed_week' if closed else 'week_to_date'
    existing=db('weekly_quality_summaries',extra_params={'week_start':'eq.'+str(start),'report_kind':'eq.'+kind,'evidence_hash':'eq.'+digest})
    if existing:return existing[0]
    failures=[r for r in rows if r['action'] in ('reject','edit_approve')];counts=Counter(r['reason'] for r in failures)
    patterns=[]
    for reason,count in sorted(counts.items(),key=lambda pair:(-pair[1],pair[0]))[:3]:
        risk,prompt,context,evaluation=RECOMMENDATIONS[reason]
        patterns.append({'reason':reason,'count':count,'business_risk':risk,'recommended_prompt_change':prompt,'recommended_context_rule':context,'recommended_evaluation_case':evaluation,'evidence_review_ids':[r['id'] for r in failures if r['reason']==reason]})
    return db('weekly_quality_summaries','POST',{'week_start':str(start),'week_end':str(end),'review_count':len(rows),'patterns':patterns,'evidence_hash':digest,'generated_by':reviewer_id,'report_kind':kind})[0]
