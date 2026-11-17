"""Generate deterministic, repeat-safe synthetic seed SQL. No network calls."""
import json
import random
from datetime import date, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

random.seed(31)
TODAY = date(2026, 11, 16)
first = ['Avery','Jordan','Taylor','Morgan','Riley','Cameron','Quinn','Reese','Parker','Sage','Rowan','Blake','Finley','Hayden','Skyler','Emerson','Dakota','Charlie','Jamie','Robin','Drew','Casey','Kendall','Alex']
last = ['Bennett','Chen','Rivera','Patel','Brooks','Kim','Foster','Reed','Hayes','Ellis','Park','Sullivan','Nguyen','Morris','Shaw','Diaz','Clarke','Wells','Lane','Ortiz','Gray','Price','James','Cooper']
companies = ['Canopy Studio','Northstar Labs','Juniper Works','Fieldwork Co.','Meridian Systems','Cedar & Stone','Goodwell Design','Lumen Analytics','Evergreen Digital','Forma Collective','Daybreak Health','Waypoint Ventures']
owners = ['Alex Morgan','Sam Rivera','Jordan Lee']
roles = ['Head of Operations','VP of Growth','Founder','Product Director','Partnerships Lead','CEO']
stages = ['Lead','Qualified','Proposal','Negotiation','Won','Lost']

def uid(kind,i): return str(uuid5(NAMESPACE_URL,f'orbit-crm-synthetic/{kind}/{i}'))
def val(v):
    if v is None: return 'null'
    if isinstance(v,bool): return str(v).lower()
    if isinstance(v,(int,float)): return str(v)
    return "'"+str(v).replace("'","''")+"'"
def sql(table,rows):
    keys=list(rows[0])
    return f"insert into public.crm_{table} ({', '.join(keys)}) values\n"+',\n'.join('('+', '.join(val(r[k]) for k in keys)+')' for r in rows)+'\non conflict (id) do nothing;\n'
contacts=[]
for i in range(24):
    contacts.append(dict(id=uid('contact',i),name=first[i]+' '+last[i],email=f'{first[i].lower()}.{last[i].lower()}@example.com',company=companies[i%12],role=roles[i%6],phone=f'+1 202-555-{100+i:04d}',status=['Active','Customer','Lead','Active','Lead','Customer'][i%6],owner=owners[i%3],notes='Synthetic demo contact. Discuss growth plans and partnership opportunities.',created_at=f'{TODAY-timedelta(days=i*2)}T10:00:00Z'))
deals=[]
for i in range(22):
    deals.append(dict(id=uid('deal',i),title=['Platform partnership','Annual workspace plan','Enterprise rollout','Growth package','Team expansion','Strategic collaboration'][i%6],company=companies[i%12],contact_id=contacts[i%24]['id'],value=random.choice([6500,12000,18500,24000,32000,48000,65000,85000]),stage=stages[i%6],owner=owners[i%3],close_date=str(TODAY+timedelta(days=(i-5)*3)),notes='Synthetic opportunity for product demonstration.',created_at=f'{TODAY-timedelta(days=i+1)}T11:00:00Z'))
tasks=[]
for i,title in enumerate(['Send partnership proposal','Follow up on discovery call','Share the enterprise demo','Confirm renewal timeline','Schedule stakeholder intro','Prepare pricing options','Check in after product trial','Review contract feedback','Send onboarding checklist','Book a quarterly review','Share customer success plan','Confirm pilot requirements','Follow up on expansion','Send meeting recap','Review security questionnaire','Plan launch workshop']):
    tasks.append(dict(id=uid('task',i),title=title,contact_id=contacts[i]['id'],due_date=str(TODAY+timedelta(days=i-3)),priority=['High','Medium','Low'][i%3],done=i in [5,9,14],owner=owners[i%3],created_at=f'{TODAY-timedelta(days=i+2)}T12:00:00Z'))
root=Path(__file__).parent
(root/'seed.sql').write_text('-- Synthetic demo data; example.com email addresses; repeat-safe IDs.\n'+sql('contacts',contacts)+sql('deals',deals)+sql('tasks',tasks))
print(json.dumps({'contacts':len(contacts),'deals':len(deals),'tasks':len(tasks)}))
