"""Deterministic section/subsection parsing and traceable alignment."""
import difflib
import re
from collections import Counter

from soc_agent.review import ReviewError, normalized

FORM_ITEMS={
 '10-Q': [('I',x) for x in ('1','2','3','4')]+[('II',x) for x in ('1','1A','2','3','4','5','6')],
 '10-K': [('',x) for x in ('1','1A','1B','1C','2','3','4','5','6','7','7A','8','9','9A','9B','9C','10','11','12','13','14','15','16')]
}
FORM_URLS={'10-Q':'https://www.sec.gov/files/form10-q.pdf','10-K':'https://www.sec.gov/files/form10-k.pdf','S-1':'https://www.sec.gov/files/forms-1.pdf'}
S1_HEADINGS={'prospectus summary','risk factors','use of proceeds','capitalization','dilution','business','management','executive compensation','principal stockholders','description of capital stock','underwriting','legal matters','experts','financial statements','management discussion and analysis','dividend policy','selected financial data','principal and selling stockholders','selling stockholders','shares eligible for future sale','description of securities','plan of distribution','determination of offering price','where you can find additional information','information incorporated by reference','certain relationships and related person transactions','summary consolidated financial data'}


def slug(value):
    return re.sub(r'[^a-z0-9]+','_',value.lower()).strip('_')


def heading_text(text):
    return re.sub(r'^#{1,6}\s*','',text).strip().strip(' .:—-')


def top_heading(text,form,part,explicit=False):
    value=heading_text(text)
    if len(value)>190:
        return None
    item=re.match(r'^item\s+(\d{1,2}[a-c]?)\b[.\s:—-]*(.*)$',value,re.I)
    if item and form in ('10-Q','10-K'):
        code=item.group(1).upper()
        key=(f'part_{part.lower()}_' if form=='10-Q' and part else 'unscoped_' if form=='10-Q' else '')+'item_'+code.lower()
        return key,value,'item',code
    note=re.match(r'^(?:note|footnote)\s*(\d{1,3})\s*([.\-—:)])?\s*(.*)$',value,re.I)
    if note and (note.group(2) or explicit or not re.search(r'\b(?:see|discusses|describes|provides|explains|below|above|which)\b',note.group(3),re.I)):
        if len(value)<130 and (explicit or not value.endswith('.') or note.group(2) and len(note.group(3).split())<=10):
            return 'note_'+str(int(note.group(1))),value,'note',str(int(note.group(1)))
    if form=='S-1' and (normalized(value) in S1_HEADINGS or any(normalized(value).startswith(h+' ') for h in S1_HEADINGS) and explicit):
        return 's1_'+slug(value),value,'s1',''
    return None


def sub_heading(text,explicit=False):
    value=heading_text(text)
    if not value or len(value)>120 or value.endswith(('.',',',';')):
        return False
    if explicit:
        return True
    words=value.split()
    if len(words)>16 or len(words)<2 or not re.search('[A-Za-z]',value):
        return False
    if value.isupper():
        return True
    if re.match(r'^(?:\([a-z0-9]+\)|[a-z0-9]+[.)])\s+[A-Z]',value):
        return True
    titled=sum(word[:1].isupper() for word in words if word.lower() not in {'and','of','the','to','for','in','a','on','with'})
    return titled>=2 and titled>=len(words)*.65 and not re.search(r'[!?$%]|\d{3}',value)


def parse_filing(document,form):
    sections=[]
    current={'key':'unclassified','title':'Unclassified / front matter','kind':'other','code':'','part':'','lines':[]}
    part=''
    notes_mode=False
    for unit in document['units']:
        for line_index,line in enumerate(unit['text'].splitlines(),1):
            text=line.strip()
            if not text:
                continue
            locator=unit['locator']+(f', line {line_index}' if '\n' in unit['text'] else '')
            part_match=re.fullmatch(r'\s*PART\s+(I{1,3}|IV)\s*[.:-]?\s*(?:FINANCIAL INFORMATION|OTHER INFORMATION)?\s*',text,re.I)
            if part_match:
                part=part_match.group(1).upper()
                continue
            explicit=bool(unit.get('heading')) or text.startswith('#')
            if len(text)<160 and re.search(r'notes to (?:the )?(?:(?:condensed|consolidated|combined|unaudited) )*financial statements',text,re.I):
                notes_mode=True
            top=top_heading(text,form,part,explicit)
            numbered=re.match(r'^\(?(\d{1,3})\)?[.\s:—-]+(.+)$',heading_text(text))
            if not top and notes_mode and numbered and sub_heading(numbered.group(2),explicit) and len(text)<140:
                top=('note_'+str(int(numbered.group(1))),text,'note',str(int(numbered.group(1))))
            if top:
                if top[2]=='item':
                    notes_mode=False
                elif top[2]=='note':
                    notes_mode=True
                if current['lines']:
                    sections.append(current)
                key,title,kind,code=top
                current={'key':key,'title':title,'kind':kind,'code':code,'part':part,'lines':[{'text':text,'locator':locator,'heading':False,'top':True}]}
            else:
                current['lines'].append({'text':text,'locator':locator,'heading':sub_heading(text,explicit),'top':False})
    if current['lines']:
        sections.append(current)
    qa=[]
    # Repeated TOC headings are retained as QA evidence; choose the substantive body for analysis.
    grouped={}
    for section in sections:
        grouped.setdefault(section['key'],[]).append(section)
    selected=[]
    for key,candidates in grouped.items():
        def toc_only(candidate):
            body=[line['text'] for line in candidate['lines'] if not line['top']]
            return (not body or all(re.fullmatch(r'[.\d\s–—-]+',line) for line in body)) and candidate['kind']!='other'
        substantive=[candidate for candidate in candidates if not toc_only(candidate)]
        included=substantive or candidates
        chosen=dict(included[0])
        chosen['lines']=[]
        seen_bodies=set()
        for candidate in included:
            marker=normalized(' '.join(line['text'] for line in candidate['lines']))
            if marker not in seen_bodies:
                chosen['lines'].extend(candidate['lines'])
                seen_bodies.add(marker)
        if len(candidates)>1:
            qa.append({'check_type':'Duplicate headings / TOC','item_key':key,'item_title':chosen['title'],'status':'Pending verification','detail':f'{len(candidates)} heading occurrences. Substantive repeated/continued bodies were retained in document order; exact repeated bodies were deduplicated. TOC-only occurrences were excluded only when substantive text was present. Verify section continuity and context against the source snapshot.'})
        selected.append(chosen)
    subsections=[]
    for section in selected:
        blocks=[]
        title='Full section / fallback'
        lines=[]
        for line in section['lines']:
            if line['heading'] and not line['top']:
                if lines:
                    blocks.append((title,lines))
                title=heading_text(line['text'])
                lines=[line]
            else:
                lines.append(line)
        if lines:
            blocks.append((title,lines))
        for title,lines in blocks:
            # Continuation blocks retain full text for very large disclosures; no source data is dropped.
            parts=[]
            group=[]
            size=0
            for line in lines:
                for start in range(0,len(line['text']),20000):
                    piece=dict(line,text=line['text'][start:start+20000])
                    if group and size+len(piece['text'])>26000:
                        parts.append(group)
                        group=[];size=0
                    group.append(piece);size+=len(piece['text'])+1
            if group:
                parts.append(group)
            for index,part_lines in enumerate(parts,1):
                item={'id':f'{document["id"]}-{len(subsections)+1:04d}','parent_section_key':section['key'],'parent_section_title':section['title'],'subsection_title':title+(f' — continuation {index}/{len(parts)}' if len(parts)>1 else ''),'text':'\n'.join(l['text'] for l in part_lines),'locators':list(dict.fromkeys(l['locator'] for l in part_lines)),'heading_path':[section['title'],title],'fallback':title=='Full section / fallback','kind':section['kind'],'code':section['code'],'part':section['part']}
                subsections.append(item)
        section['subsections']=[s for s in subsections if s['parent_section_key']==section['key']]
    if not subsections:
        raise ReviewError('No readable filing subsections could be parsed.')
    if len(subsections)>650:
        raise ReviewError('More than 650 subsection blocks detected. Supply a cleaner, scoped filing; nothing was silently skipped.')
    return {'source':{k:v for k,v in document.items() if k!='units'},'sections':selected,'subsections':subsections,'qa':qa}


def title_words(text):
    text=re.sub(r'^(?:note|footnote)\s*\d+[.\s:—-]*','',text,flags=re.I)
    return set(re.findall(r'[a-z]{3,}',text.lower()))-{'the','and','for','with','item','note','notes','full','section','fallback'}


def match_parent(section,target_sections):
    if section['kind']=='note':
        # Note numbers are not assumed to mean the same topic across different companies.
        candidates=[s for s in target_sections if s['kind']=='note']
        a=title_words(section['title'])
        scored=[(len(a & title_words(s['title']))/max(1,len(a | title_words(s['title']))),s) for s in candidates]
        if scored:
            score,best=max(scored,key=lambda x:x[0])
            if score>=.55:
                return best,'Footnote topic heading'
        return None,'No comparable footnote topic'
    exact=next((s for s in target_sections if s['key']==section['key']),None)
    if exact:
        return exact,'Canonical Item/Part key'
    if section['kind'] in ('item','note'):
        return None,'No matching parent Item/Part'
    candidates=[s for s in target_sections if s['kind']==section['kind']]
    scored=[(difflib.SequenceMatcher(None,normalized(section['title']),normalized(s['title'])).ratio(),s) for s in candidates]
    if scored:
        score,best=max(scored,key=lambda x:x[0])
        if score>=.7:
            return best,'Parent heading similarity — verify'
    return None,'No comparable parent section'


def align(draft,target):
    rows=[]
    for parent in draft['sections']:
        counterpart,parent_method=match_parent(parent,target['sections']) if target else (None,'Comparison source unavailable')
        for subsection in parent['subsections']:
            match=None;method=parent_method
            if counterpart:
                candidates=counterpart['subsections']
                if len(candidates)==1 and candidates[0]['fallback'] and len(parent['subsections'])>1:
                    method+='; source is under-sectionized — alignment pending'
                else:
                    exact=[s for s in candidates if normalized(s['subsection_title'])==normalized(subsection['subsection_title'])]
                    if exact:
                        match=exact[0];method+='; exact subsection heading'
                    else:
                        scored=[]
                        words=title_words(subsection['subsection_title'])
                        for candidate in candidates:
                            other=title_words(candidate['subsection_title'])
                            similarity=len(words & other)/max(1,len(words | other))
                            body=difflib.SequenceMatcher(None,subsection['text'][:5000],candidate['text'][:5000],autojunk=True).ratio()
                            scored.append((max(similarity,body*.8),candidate))
                        if scored:
                            score,best=max(scored,key=lambda x:x[0])
                            if score>=.35:
                                match=best;method+='; topic/body similarity — verify alignment'
                    if not match:
                        method+='; no comparable subsection'
            rows.append({'draft':subsection,'comparison':match,'match_method':method})
    return rows


def coverage(draft,form):
    rows=list(draft['qa'])
    present={s['key'] for s in draft['sections']}
    for part,item in FORM_ITEMS.get(form,[]):
        key=(f'part_{part.lower()}_' if form=='10-Q' else '')+'item_'+item.lower()
        rows.append({'check_type':'Form structure','item_key':key,'item_title':('Part '+part+' / ' if part else '')+'Item '+item,'status':'Heading present — verify content' if key in present else 'High attention — heading not parsed','detail':'Structural check only; reserved, optional, incorporated-by-reference and filer-specific applicability require reviewer assessment. Source form: '+FORM_URLS[form]})
    notes=[s for s in draft['sections'] if s['kind']=='note']
    numbers={int(s['code']) for s in notes}
    rows.append({'check_type':'Footnote population','item_key':'notes','item_title':'Financial statement footnotes','status':'Pending original-document verification','detail':f'{len(notes)} unique Note/Footnote headings and {sum(len(s["subsections"]) for s in notes)} footnote subsection blocks parsed. Confirm the full footnote population; unnumbered notes may require explicit headings.'})
    if numbers:
        for missing in sorted(set(range(1,min(max(numbers),100)+1))-numbers):
            rows.append({'check_type':'Footnote sequence','item_key':f'note_{missing}','item_title':f'Note {missing}','status':'High attention — sequence gap','detail':'A numbered footnote was not parsed. Verify against the full filing; do not infer that no disclosure is required.'})
    else:
        rows.append({'check_type':'Footnotes not parsed','item_key':'notes_missing','item_title':'Financial statement notes','status':'High attention','detail':'No numbered financial statement footnotes were parsed. The financial disclosure review is incomplete.'})
    for s in draft['subsections']:
        rows.append({'check_type':'Draft subsection','item_key':s['id'],'item_title':s['parent_section_title']+' / '+s['subsection_title'],'status':'Fallback — verify granularity' if s['fallback'] else 'Parsed — human review pending','detail':f'{len(s["text"])} characters. Source: '+ '; '.join(s['locators'])})
    return rows


def cross_references(draft):
    result=[]
    sections=draft['sections']
    for unit in draft['subsections']:
        for hit in re.finditer(r'\b(?:(Note|Footnote)\s+(\d{1,3})|(Item)\s+(\d{1,2}[A-C]?))\b',unit['text'],re.I):
            kind='note' if hit.group(1) else 'item'
            code=str(int(hit.group(2))) if kind=='note' else hit.group(4).upper()
            candidates=[s for s in sections if s['kind']==kind and s['code']==code]
            if kind=='item' and len(candidates)>1:
                local=[s for s in candidates if s['part']==unit['part']]
                candidates=local if len(local)==1 else candidates
            result.append({'source_section':unit['parent_section_title']+' / '+unit['subsection_title'],'reference_text':hit.group(0),'target_section':'; '.join(s['title'] for s in candidates) or 'Not resolved','status':'Target heading found — verify meaning' if len(candidates)==1 else 'Ambiguous — human review' if candidates else 'Unresolved — high attention','comment':'Heading existence is not proof that the referenced disclosure is correct. Verify context, Part, numbering, and document location.'})
    return result or [{'source_section':'Whole draft','reference_text':'No supported Note/Item reference pattern extracted','target_section':'Pending','status':'Pending manual check','comment':'This check does not resolve page numbers, hyperlinks, exhibit references, or all textual reference forms.'}]
