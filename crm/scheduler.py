"""Hourly Railway cron: morning agent, plus Monday's closed-week quality report."""
from datetime import datetime
from zoneinfo import ZoneInfo
from app import db
from followup_agent import run
from prompt_registry import active_prompts,use_prompts
from feedback_reporting import weekly_summary

if __name__ == '__main__':
    now=datetime.now(ZoneInfo('America/Los_Angeles'))
    if now.hour != 8:
        print('Outside morning window; skipped.')
    else:
        try:
            with use_prompts(active_prompts(db)):print(run(db))
        finally:
            if now.weekday()==0:
                summary=weekly_summary(db,closed=True,now=now)
                print('Weekly quality summary saved:',summary['id'])
