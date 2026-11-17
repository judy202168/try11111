"""Railway hourly cron, gated by local wall-clock hour to handle daylight saving."""
from datetime import datetime
from zoneinfo import ZoneInfo
from app import db
from followup_agent import run

if __name__ == '__main__':
    now=datetime.now(ZoneInfo('America/Los_Angeles'))
    if now.hour != 8:
        print('Outside morning window; skipped.')
    else:
        print(run(db))
