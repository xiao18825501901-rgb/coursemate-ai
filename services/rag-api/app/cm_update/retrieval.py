"""Local reference retriever; production must use existing V3 hybrid/locator through DomainPort."""
import re
from fastapi import HTTPException


def get_course(db, subject: str, course_id: str):
    c=db.one('SELECT * FROM cmui_courses WHERE id=? AND (visibility=\'public\' OR owner=?)',(course_id,subject))
    if not c: raise HTTPException(404,'课程不存在或不可访问')
    return c


def file_rows(db, subject: str, course_id: str):
    get_course(db,subject,course_id)
    return db.all("SELECT * FROM cmui_files WHERE course=? AND (scope='public' OR owner=?) ORDER BY folder,name",(course_id,subject))


def context_for(db, subject: str, course_id: str, query: str, history: list):
    course=get_course(db,subject,course_id)
    # General conversation is not forced into a no-evidence refusal.
    if re.fullmatch(r'\s*(你好|谢谢|hi|hello|早上好|晚安)[！!。.?？\s]*',query,re.I): return []
    files=file_rows(db,subject,course_id)
    if not files: return []
    accessible={f['id']:f for f in files}
    question=re.search(r'(?:question|q|第)\s*(\d+)\s*(?:题)?\s*[（(]?([a-z])?',query,re.I)
    page_match=re.search(r'(?:第\s*(\d+)\s*页|page\s*(\d+))',query,re.I)
    page_number=int(next(g for g in page_match.groups() if g)) if page_match else None
    # Exact document hint takes precedence, and ambiguity is disclosed to caller.
    file_matches=[f for f in files if f['name'].lower() in query.lower()]
    terms=set(re.findall(r'[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}',query.lower()))
    if len(query)<12 and history:
        terms.update(re.findall(r'[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}',history[-2].get('text','').lower()))
    marks=','.join('?' for _ in accessible)
    # ACL is applied BEFORE candidate creation.
    rows=db.all(f'SELECT * FROM cmui_chunks WHERE file IN ({marks})',tuple(accessible))
    scored=[]
    exact_ids={f['id'] for f in file_matches}
    for row in rows:
        if exact_ids and row['file'] not in exact_ids: continue
        if page_number and row['page']!=page_number: continue
        text=row['text'].lower()
        score=sum(1 for term in terms if term in text)
        if exact_ids: score+=8
        if question and re.search(r'(?:question|q)\s*'+question.group(1)+r'\b',text): score+=8
        if score: scored.append((score,row))
    scored.sort(key=lambda x:(-x[0],x[1]['ordinal']))
    selected=[row for _,row in scored[:6]]
    budget=12000
    output=[]
    for row in selected:
        text=row['text'][:min(budget,2400)]
        if not text: break
        f=accessible[row['file']]
        output.append({'id':f'S{len(output)+1}','document_id':f['id'],'name':f['name'],'page':row['page'],'text':text})
        budget-=len(text)
    return output
