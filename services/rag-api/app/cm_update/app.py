from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .db import Database, now, uid
from .auth import current_user, ensure_user
from .models import Profile, CourseCreate, CommentCreate, MessageCreate, TaskCreate, TaskUpdate, ConversationCreate, Rename, Layout, RunCreate, BridgeCreate, CourseUpdate, ReceiptClaim, ReceiptFinish
from .filesystem import parse_document, valid_filename, valid_folder, file_hash
from .retrieval import get_course, file_rows, context_for
from .steps import solution_steps
from .provider import QwenProvider, DisabledProvider, TestProvider, ProviderError

User=Annotated[dict,Depends(current_user)]
TERMINAL={'completed','failed','cancelled'}


def create_app(settings: Settings|None=None, *, provider=None, domain=None, subject_resolver=None) -> FastAPI:
    cfg=settings or Settings()
    cfg.validate()
    if cfg.integration_mode=='integrated' and domain is None:
        raise ValueError('Supply the reviewed DomainPort adapter; standalone domain must not replace V3 production')
    if cfg.auth_mode=='injected' and subject_resolver is None:
        raise ValueError('Injected auth requires a verified-subject resolver')
    db=Database(cfg.data_dir/'ui.sqlite3')
    db.initialize()
    (cfg.data_dir/'uploads').mkdir(exist_ok=True)
    model=provider or (QwenProvider(cfg) if cfg.provider_mode=='qwen' else TestProvider() if cfg.provider_mode=='test' else DisabledProvider())
    jobs: dict[str,asyncio.Task]={}
    # This instance's identity for run leases. Two processes get two ids.
    worker_id=uid('worker-')
    # A run whose heartbeat is older than this has lost its owner (process died
    # without cancellation). Bounded: startup recovery and a background reaper
    # both use it, and it must be longer than the heartbeat interval below.
    lease_grace_seconds=float(os.getenv('CMUI_RUN_LEASE_GRACE','120') or 120)

    def heartbeat(run_id):
        db.execute("UPDATE cmui_runs SET lease_heartbeat=? WHERE id=? AND status IN ('queued','planning','generating')",(str(time.time()),run_id))

    def reclaim_orphaned_runs():
        cutoff=str(time.time()-lease_grace_seconds)
        db.execute("UPDATE cmui_runs SET status='failed',error='SERVER_RESTARTED',updated_at=? WHERE status IN ('queued','planning','generating') AND (lease_heartbeat IS NULL OR CAST(lease_heartbeat AS REAL)<?)",(now(),cutoff))

    @asynccontextmanager
    async def lifespan(app):
        # Only runs with provably dead owners are reclaimed. A sibling process
        # that heartbeats normally is left untouched - starting a second worker
        # must never kill the first worker's in-flight run (its model cost has
        # already been spent, so killing it would waste money AND lose the answer).
        reclaim_orphaned_runs()
        yield
        for task in list(jobs.values()): task.cancel()
        if jobs: await asyncio.gather(*jobs.values(),return_exceptions=True)

    app=FastAPI(title='CourseMate UI Update API',version='1.1.0',lifespan=lifespan)
    app.state.cfg,app.state.db,app.state.provider,app.state.domain=cfg,db,model,domain
    app.state.jobs=jobs
    app.state.subject_resolver=subject_resolver
    app.add_middleware(CORSMiddleware,allow_origins=list(cfg.allowed_origins),allow_credentials=True,
        allow_methods=['GET','POST','PATCH','PUT','DELETE','HEAD'],allow_headers=['Authorization','Content-Type','Last-Event-ID'])
    if cfg.environment!='production':
        app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','testserver'])

    @app.middleware('http')
    async def headers(request,call_next):
        result=await call_next(request)
        result.headers['X-Content-Type-Options']='nosniff'
        result.headers['Referrer-Policy']='same-origin'
        if request.url.path.startswith('/api/'):
            result.headers['Cache-Control']='private, no-store'
        return result

    r=APIRouter(prefix='/api/ui/v1')

    async def remote(operation,user,payload,request):
        return await domain.call(operation,user['id'],payload,request.headers.get('authorization',''))

    async def course(user,cid,request):
        if domain: return await remote('course.get',user,{'id':cid},request)
        return get_course(db,user['id'],cid)

    def rate(user,bucket,limit=60):
        window=int(time.time()//60)
        with db.connect(True) as c:
            c.execute('INSERT INTO cmui_limits VALUES (?,?,?,1) ON CONFLICT(owner,bucket,window) DO UPDATE SET count=count+1',(user['id'],bucket,window))
            n=c.execute('SELECT count FROM cmui_limits WHERE owner=? AND bucket=? AND window=?',(user['id'],bucket,window)).fetchone()[0]
            c.execute('DELETE FROM cmui_limits WHERE window<?',(window-10,))
        if n>limit: raise HTTPException(429,'操作太频繁，请稍后再试',headers={'Retry-After':'60'})

    def conversation(user,conversation_id):
        row=db.one('SELECT * FROM cmui_conversations WHERE id=? AND owner=?',(conversation_id,user['id']))
        if not row: raise HTTPException(404,'对话不存在')
        return row

    def owned_run(user,run_id):
        run=db.one('SELECT * FROM cmui_runs WHERE id=? AND owner=?',(run_id,user['id']))
        if not run: raise HTTPException(404,'生成记录不存在')
        return run

    def public_file(row):
        return {k:v for k,v in row.items() if k not in {'storage_key','sha256','owner'}}

    def event(run_id,kind,data):
        db.execute('INSERT INTO cmui_run_events(run,type,data) VALUES (?,?,?)',(run_id,kind,json.dumps(data,ensure_ascii=False)))

    @r.get('/config')
    def config():
        return {'auth_mode':cfg.auth_mode,'environment':cfg.environment,'api_base':cfg.api_base,
            'provider_mode':cfg.provider_mode,'model':cfg.qwen_model,'integration_mode':cfg.integration_mode,
            'clerk_publishable_key':cfg.clerk_publishable_key,'clerk_issuer':cfg.clerk_issuer,
            'max_upload_bytes':cfg.max_upload_bytes,'agent_connected':bool(domain)}

    @r.post('/dev/login')
    async def dev_login(request:Request,response:Response):
        if cfg.auth_mode!='development' or cfg.environment=='production': raise HTTPException(404)
        data=await request.json()
        account=data.get('account')
        if account not in {'alice','bob','admin'}: raise HTTPException(400,'选择本机测试账号')
        u=ensure_user(db,'local-'+account)
        name={'alice':'秋同学','bob':'林同学','admin':'课程管理员'}[account]
        db.execute('UPDATE cmui_users SET name=?,discoverable=1 WHERE id=?',(name,u['id']))
        token=secrets.token_urlsafe(32)
        db.execute('INSERT INTO cmui_sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],time.time()+86400))
        response.set_cookie('cmui_dev_session',token,httponly=True,samesite='strict',max_age=86400,path='/')
        return {'ok':True}

    @r.post('/dev/logout')
    def dev_logout(request:Request,response:Response):
        if cfg.auth_mode!='development': raise HTTPException(404)
        token=request.cookies.get('cmui_dev_session','')
        db.execute('DELETE FROM cmui_sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie('cmui_dev_session',path='/')
        return {'ok':True}

    @r.get('/me')
    def me(user:User): return user

    @r.patch('/me')
    def update_me(data:Profile,user:User):
        try:
            db.execute('UPDATE cmui_users SET name=?,bio=?,handle=?,language=?,timezone=?,discoverable=?,reply_notify=? WHERE id=?',
                (data.name,data.bio,data.handle,data.language,data.timezone,int(data.discoverable),int(data.reply_notify),user['id']))
        except sqlite3.IntegrityError: raise HTTPException(409,'这个用户名已有人使用') from None
        return ensure_user(db,user['id'])

    @r.get('/people')
    def people(user:User,q:str=Query(default='',max_length=60)):
        rate(user,'people',30)
        if len(q.strip())<2: return []
        escaped=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        return db.all("SELECT id,name,handle,bio FROM cmui_users WHERE id<>? AND discoverable=1 AND (name LIKE ? ESCAPE '\\' OR handle LIKE ? ESCAPE '\\') LIMIT 20",(user['id'],'%'+escaped+'%','%'+escaped+'%'))

    @r.get('/courses')
    async def courses(user:User,request:Request):
        if domain:
            rows=await remote('course.list',user,{},request)
        else:
            rows=db.all("SELECT * FROM cmui_courses WHERE visibility='public' OR owner=? ORDER BY official DESC,created_at",(user['id'],))
        pins={p['course'] for p in db.all('SELECT course FROM cmui_pins WHERE owner=?',(user['id'],))}
        return [dict(x,pinned=x['id'] in pins) for x in rows]

    @r.post('/courses',status_code=201)
    async def create_course(data:CourseCreate,user:User,request:Request):
        rate(user,'create-course',10)
        if domain:
            row=await remote('course.create',user,data.model_dump(),request)
            db.execute('INSERT OR IGNORE INTO cmui_pins(owner,course) VALUES (?,?)',(user['id'],row['id']))
            return row
        if db.one('SELECT COUNT(*) AS n FROM cmui_courses WHERE owner=?',(user['id'],))['n']>=20:
            raise HTTPException(409,'最多创建 20 门私人课程')
        cid=uid('course_')
        with db.connect(True) as c:
            c.execute('INSERT INTO cmui_courses(id,owner,code,name,description,color,requirements,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (cid,user['id'],data.code or '我的课程',data.name,data.description,data.color,data.requirements,now()))
            c.execute('INSERT INTO cmui_pins(owner,course) VALUES (?,?)',(user['id'],cid))
        return get_course(db,user['id'],cid)

    @r.get('/courses/{cid}')
    async def detail(cid:str,user:User,request:Request): return await course(user,cid,request)

    @r.patch('/courses/{cid}')
    async def edit_course(cid:str,data:CourseUpdate,user:User,request:Request):
        row=await course(user,cid,request)
        if domain: return await remote('course.update',user,dict(data.model_dump(),id=cid),request)
        if row['owner']!=user['id'] or row['visibility']!='private':
            raise HTTPException(403,'只能修改自己尚未公开的课程')
        db.execute('UPDATE cmui_courses SET name=?,description=?,color=?,requirements=? WHERE id=? AND owner=?',
                   (data.name,data.description,data.color,data.requirements,cid,user['id']))
        return get_course(db,user['id'],cid)

    @r.delete('/courses/{cid}')
    async def delete_course(cid:str,user:User,request:Request,confirm:str=Query(min_length=1,max_length=100)):
        row=await course(user,cid,request)
        if confirm!=row['name']: raise HTTPException(422,'请准确输入课程名称确认删除')
        if domain: return await remote('course.delete',user,{'id':cid,'confirm':confirm},request)
        if row['owner']!=user['id'] or row['visibility']!='private':
            raise HTTPException(403,'只能删除自己尚未公开的课程')
        files_to_remove=[]
        with db.connect(True) as c:
            if c.execute("SELECT r.id FROM cmui_runs r JOIN cmui_conversations v ON v.id=r.conversation WHERE v.course=? AND r.status IN ('queued','planning','generating')",(cid,)).fetchone():
                raise HTTPException(409,'请先停止该课程的生成任务')
            files_to_remove=[x[0] for x in c.execute('SELECT storage_key FROM cmui_files WHERE course=?',(cid,))]
            c.execute('DELETE FROM cmui_bridges WHERE course=?',(cid,))
            c.execute('DELETE FROM cmui_conversations WHERE course=?',(cid,))
            c.execute('DELETE FROM cmui_likes WHERE comment IN (SELECT id FROM cmui_comments WHERE course=?)',(cid,))
            c.execute('DELETE FROM cmui_notifications WHERE course=?',(cid,))
            c.execute('UPDATE cmui_comments SET parent=NULL WHERE course=?',(cid,))
            c.execute('DELETE FROM cmui_comments WHERE course=?',(cid,))
            c.execute('DELETE FROM cmui_learning WHERE node IN (SELECT id FROM cmui_nodes WHERE course=?)',(cid,))
            for table in ['cmui_nodes','cmui_files','cmui_pins','cmui_layout']:
                c.execute(f'DELETE FROM {table} WHERE course=?',(cid,))
            # Keep study tasks as personal arrangements, detach the removed course.
            c.execute('UPDATE cmui_tasks SET course=NULL,version=version+1,updated_at=? WHERE course=?',(now(),cid))
            c.execute('DELETE FROM cmui_courses WHERE id=?',(cid,))
        # Metadata removal first: any failed filesystem cleanup remains inaccessible, retryable by maintenance.
        failed=0
        for storage_key in files_to_remove:
            try: (cfg.data_dir/'uploads'/storage_key).unlink(missing_ok=True)
            except OSError: failed+=1
        return {'deleted':True,'inaccessible_files_pending_cleanup':failed}

    @r.put('/courses/{cid}/pin')
    async def pin(cid:str,user:User,request:Request):
        await course(user,cid,request)
        db.execute('INSERT OR IGNORE INTO cmui_pins(owner,course) VALUES (?,?)',(user['id'],cid))
        return {'pinned':True}

    @r.delete('/courses/{cid}/pin')
    async def unpin(cid:str,user:User,request:Request):
        await course(user,cid,request)
        db.execute('DELETE FROM cmui_pins WHERE owner=? AND course=?',(user['id'],cid))
        return {'pinned':False}

    @r.get('/courses/{cid}/files')
    async def files(cid:str,user:User,request:Request,q:str=Query(default='',max_length=150),folder:str|None=None):
        await course(user,cid,request)
        if domain: return await remote('file.list',user,{'course':cid,'q':q,'folder':folder},request)
        rows=file_rows(db,user['id'],cid)
        if q: rows=[x for x in rows if q.casefold() in x['name'].casefold()]
        elif folder is not None: rows=[x for x in rows if x['folder']==folder]
        return [public_file(x) for x in rows]

    @r.post('/courses/{cid}/files',status_code=201)
    async def upload(cid:str,user:User,request:Request,file:UploadFile=File(...),folder:str=Form(default='')):
        await course(user,cid,request)
        rate(user,'upload',15)
        content=await file.read(cfg.max_upload_bytes+1)
        await file.close()
        if not content or len(content)>cfg.max_upload_bytes: raise HTTPException(413,'空文件或超过单文件大小限制')
        try:
            name=valid_filename(file.filename or '')
            folder=valid_folder(folder)
            mime,parts,parse_error=await asyncio.to_thread(parse_document,name,content)
        except ValueError as e: raise HTTPException(422,str(e)) from None
        if domain:
            # Integration owns the real V3 upload/ingestion. Bytes stay in-process, not JSON logs.
            return await remote('file.upload',user,{'course':cid,'name':name,'folder':folder,'content':content,'mime':mime},request)
        digest=file_hash(content)
        old=db.one('SELECT * FROM cmui_files WHERE course=? AND owner=? AND sha256=?',(cid,user['id'],digest))
        if old: return dict(public_file(old),duplicate=True)
        fid=uid('file_'); storage=fid+Path(name).suffix.lower(); path=cfg.data_dir/'uploads'/storage
        try:
            with db.connect(True) as c:
                total=c.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM cmui_files WHERE owner=?',(user['id'],)).fetchone()
                if total[0]>=cfg.max_files or total[1]+len(content)>cfg.max_user_bytes: raise HTTPException(409,'文件数量或总容量配额已满')
                with path.open('xb') as dest: dest.write(content)
                c.execute('INSERT INTO cmui_files VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (fid,cid,user['id'],name,folder,len(content),mime,storage,digest,'private','indexed' if parts else 'preview_only',parse_error,now()))
                for ordinal,(page,text) in enumerate(parts):
                    c.execute('INSERT INTO cmui_chunks VALUES (?,?,?,?,?)',(uid('chunk_'),fid,page,ordinal,text))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return public_file(db.one('SELECT * FROM cmui_files WHERE id=?',(fid,)))

    @r.get('/courses/{cid}/files/{fid}/content',operation_id='get_course_file_content')
    @r.head('/courses/{cid}/files/{fid}/content',operation_id='head_course_file_content')
    async def content(cid:str,fid:str,user:User,request:Request,download:bool=False):
        await course(user,cid,request)
        if domain: return await remote('file.content',user,{'course':cid,'id':fid,'download':download,'range':request.headers.get('range')},request)
        row=db.one("SELECT * FROM cmui_files WHERE id=? AND course=? AND (scope='public' OR owner=?)",(fid,cid,user['id']))
        if not row: raise HTTPException(404,'文件不存在')
        path=cfg.data_dir/'uploads'/row['storage_key']
        if not path.is_file(): raise HTTPException(404,'文件暂时不可用')
        return FileResponse(path,media_type=row['mime'],filename=row['name'],content_disposition_type='attachment' if download else 'inline',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    @r.get('/courses/{cid}/files/{fid}/text')
    async def preview_text(cid:str,fid:str,user:User,request:Request):
        await course(user,cid,request)
        if domain: return await remote('file.text',user,{'course':cid,'id':fid},request)
        row=db.one("SELECT id FROM cmui_files WHERE id=? AND course=? AND (scope='public' OR owner=?)",(fid,cid,user['id']))
        if not row: raise HTTPException(404)
        return {'pages':db.all('SELECT page,text FROM cmui_chunks WHERE file=? ORDER BY ordinal LIMIT 150',(fid,))}

    @r.delete('/courses/{cid}/files/{fid}')
    async def delete_file(cid:str,fid:str,user:User,request:Request):
        await course(user,cid,request)
        if domain: return await remote('file.delete',user,{'course':cid,'id':fid},request)
        row=db.one('SELECT * FROM cmui_files WHERE id=? AND course=? AND owner=?',(fid,cid,user['id']))
        if not row: raise HTTPException(404)
        db.execute('DELETE FROM cmui_files WHERE id=?',(fid,))
        (cfg.data_dir/'uploads'/row['storage_key']).unlink(missing_ok=True)
        return {'deleted':True}

    @r.get('/courses/{cid}/comments')
    async def comments(cid:str,user:User,request:Request,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0)):
        await course(user,cid,request)
        # Paginate roots, include their replies; no replies lost across separate pagination windows.
        roots=db.all('SELECT id FROM cmui_comments WHERE course=? AND parent IS NULL ORDER BY created_at DESC LIMIT ? OFFSET ?',(cid,limit,offset))
        ids=[x['id'] for x in roots]
        if not ids: return []
        marks=','.join('?' for _ in ids)
        return db.all(f'''SELECT c.*,u.name,u.handle,
            (SELECT COUNT(*) FROM cmui_likes WHERE comment=c.id) likes,
            EXISTS(SELECT 1 FROM cmui_likes WHERE comment=c.id AND owner=?) liked
            FROM cmui_comments c JOIN cmui_users u ON u.id=c.author
            WHERE c.id IN ({marks}) OR c.parent IN ({marks}) ORDER BY c.created_at''',(user['id'],*ids,*ids))

    @r.post('/courses/{cid}/comments',status_code=201)
    async def comment(cid:str,data:CommentCreate,user:User,request:Request):
        await course(user,cid,request); rate(user,'comment',20)
        parent=None
        if data.parent:
            parent=db.one('SELECT * FROM cmui_comments WHERE id=? AND course=? AND deleted=0',(data.parent,cid))
            if not parent: raise HTTPException(404,'被回复的评论不存在')
        with db.connect(True) as c:
            old=c.execute('SELECT * FROM cmui_comments WHERE author=? AND request_id=?',(user['id'],data.request_id)).fetchone()
            if old:
                if old['course']!=cid or old['text']!=data.text or old['parent']!=(parent['parent'] or parent['id'] if parent else None):
                    raise HTTPException(409,'重复请求 ID 的内容不同')
                return dict(old)
            cid_new=uid('comment_'); root=(parent['parent'] or parent['id']) if parent else None
            c.execute('INSERT INTO cmui_comments(id,course,author,parent,text,request_id,created_at) VALUES (?,?,?,?,?,?,?)',
                (cid_new,cid,user['id'],root,data.text,data.request_id,now()))
            if parent and parent['author']!=user['id']:
                enabled=c.execute('SELECT reply_notify FROM cmui_users WHERE id=?',(parent['author'],)).fetchone()
                if enabled and enabled[0]:
                    c.execute('INSERT OR IGNORE INTO cmui_notifications VALUES (?,?,?,?,?,?,?,?,?)',
                        (uid('notice_'),parent['author'],user['id'],'comment_reply',cid_new,cid,data.text[:240],None,now()))
        return db.one('SELECT * FROM cmui_comments WHERE id=?',(cid_new,))

    @r.put('/courses/{cid}/comments/{comment_id}/like')
    async def like(cid:str,comment_id:str,user:User,request:Request):
        await course(user,cid,request)
        if not db.one('SELECT id FROM cmui_comments WHERE id=? AND course=? AND deleted=0',(comment_id,cid)): raise HTTPException(404)
        db.execute('INSERT OR IGNORE INTO cmui_likes VALUES (?,?)',(user['id'],comment_id))
        return {'liked':True}

    @r.delete('/courses/{cid}/comments/{comment_id}/like')
    async def unlike(cid:str,comment_id:str,user:User,request:Request):
        await course(user,cid,request)
        db.execute('DELETE FROM cmui_likes WHERE owner=? AND comment=?',(user['id'],comment_id))
        return {'liked':False}

    @r.delete('/courses/{cid}/comments/{comment_id}')
    async def remove_comment(cid:str,comment_id:str,user:User,request:Request):
        await course(user,cid,request)
        if not db.execute("UPDATE cmui_comments SET deleted=1,text='此评论已删除' WHERE id=? AND author=? AND course=?",(comment_id,user['id'],cid)): raise HTTPException(404)
        db.execute("DELETE FROM cmui_notifications WHERE ref=? AND kind='comment_reply'",(comment_id,))
        return {'deleted':True}

    @r.get('/notifications')
    async def notifications(user:User,request:Request):
        rows=db.all('SELECT n.*,u.name actor_name FROM cmui_notifications n JOIN cmui_users u ON u.id=n.actor WHERE n.owner=? ORDER BY n.created_at DESC LIMIT 100',(user['id'],))
        visible=[]
        for row in rows:
            if row['course']:
                try: await course(user,row['course'],request)
                except HTTPException: continue
            visible.append(row)
        return visible

    @r.put('/notifications/{nid}/read')
    def notice_read(nid:str,user:User):
        if not db.execute('UPDATE cmui_notifications SET read_at=? WHERE id=? AND owner=?',(now(),nid,user['id'])): raise HTTPException(404)
        return {'ok':True}

    @r.get('/threads')
    def threads(user:User):
        rows=db.all('SELECT * FROM cmui_threads WHERE a=? OR b=? ORDER BY created_at DESC',(user['id'],user['id']))
        for row in rows:
            peer=row['b'] if row['a']==user['id'] else row['a']
            row['peer']=db.one('SELECT id,name,handle FROM cmui_users WHERE id=?',(peer,))
            row['last']=db.one('SELECT text,created_at FROM cmui_direct_messages WHERE thread=? ORDER BY created_at DESC LIMIT 1',(row['id'],))
            row['unread']=db.one('SELECT COUNT(*) n FROM cmui_direct_messages WHERE thread=? AND sender<>? AND read_at IS NULL',(row['id'],user['id']))['n']
        return sorted(rows,key=lambda x:(x['last'] or {}).get('created_at',x['created_at']),reverse=True)

    def check_thread(tid,user):
        row=db.one('SELECT * FROM cmui_threads WHERE id=? AND (a=? OR b=?)',(tid,user['id'],user['id']))
        if not row: raise HTTPException(404)
        return row

    @r.get('/threads/{tid}/messages')
    def thread_messages(tid:str,user:User,limit:int=Query(100,ge=1,le=200),offset:int=Query(0,ge=0)):
        check_thread(tid,user)
        rows=db.all('SELECT m.*,u.name FROM cmui_direct_messages m JOIN cmui_users u ON u.id=m.sender WHERE thread=? ORDER BY m.created_at DESC LIMIT ? OFFSET ?',(tid,limit,offset))
        return list(reversed(rows))

    @r.put('/threads/{tid}/read')
    def thread_read(tid:str,user:User):
        check_thread(tid,user)
        db.execute('UPDATE cmui_direct_messages SET read_at=? WHERE thread=? AND sender<>? AND read_at IS NULL',(now(),tid,user['id']))
        return {'ok':True}

    @r.post('/messages',status_code=201)
    def send_message(data:MessageCreate,user:User):
        rate(user,'direct-message',20)
        peer=db.one('SELECT id FROM cmui_users WHERE id=?',(data.recipient,))
        if not peer or peer['id']==user['id']: raise HTTPException(404,'收件人不存在')
        if db.one('SELECT owner FROM cmui_blocks WHERE (owner=? AND blocked=?) OR (owner=? AND blocked=?)',(user['id'],peer['id'],peer['id'],user['id'])):
            raise HTTPException(403,'无法向此用户发送消息')
        a,b=sorted([user['id'],peer['id']]); thread=hashlib.sha256((a+'\0'+b).encode()).hexdigest()[:32]
        with db.connect(True) as c:
            old=c.execute('SELECT * FROM cmui_direct_messages WHERE sender=? AND request_id=?',(user['id'],data.request_id)).fetchone()
            if old:
                if old['text']!=data.text or old['thread']!=thread: raise HTTPException(409,'重复请求 ID 的内容不同')
                return dict(old)
            c.execute('INSERT OR IGNORE INTO cmui_threads VALUES (?,?,?,?)',(thread,a,b,now()))
            mid=uid('dm_')
            c.execute('INSERT INTO cmui_direct_messages VALUES (?,?,?,?,?,?,?)',(mid,thread,user['id'],data.text,data.request_id,None,now()))
        return db.one('SELECT * FROM cmui_direct_messages WHERE id=?',(mid,))

    @r.put('/people/{person}/block')
    def block(person:str,user:User):
        if person==user['id'] or not db.one('SELECT id FROM cmui_users WHERE id=?',(person,)): raise HTTPException(404)
        db.execute('INSERT OR IGNORE INTO cmui_blocks VALUES (?,?)',(user['id'],person)); return {'blocked':True}

    @r.delete('/people/{person}/block')
    def unblock(person:str,user:User):
        db.execute('DELETE FROM cmui_blocks WHERE owner=? AND blocked=?',(user['id'],person)); return {'blocked':False}

    @r.post('/agent-receipts/claim')
    def claim_receipt(data:ReceiptClaim,user:User):
        rate(user,'agent-receipt',20)
        digest=hashlib.sha256(json.dumps({'text':data.text,'timezone':data.timezone},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with db.connect(True) as c:
            old=c.execute('SELECT * FROM cmui_agent_receipts WHERE owner=? AND request_id=?',(user['id'],data.request_id)).fetchone()
            if old:
                if old['payload_hash']!=digest: raise HTTPException(409,'同一请求 ID 的任务内容不同')
                if old['status']=='running': raise HTTPException(409,'任务仍在执行或执行结果未确认；不会重复调用模型')
                return {'reused':True,'status':old['status'],'result':json.loads(old['result'] or '{}')}
            lease=secrets.token_urlsafe(32)
            c.execute('INSERT INTO cmui_agent_receipts VALUES (?,?,?,?,?,?,?,?)',
                (user['id'],data.request_id,digest,hashlib.sha256(lease.encode()).hexdigest(),'running',None,now(),now(),))
        return {'reused':False,'status':'running','lease':lease}

    @r.put('/agent-receipts/{request_id}')
    def finish_receipt(request_id:str,data:ReceiptFinish,user:User):
        encoded=json.dumps(data.result,ensure_ascii=False)
        if len(encoded)>40000: raise HTTPException(413,'Agent receipt 过长')
        with db.connect(True) as c:
            old=c.execute('SELECT * FROM cmui_agent_receipts WHERE owner=? AND request_id=?',(user['id'],request_id)).fetchone()
            if not old or not secrets.compare_digest(old['lease_hash'],hashlib.sha256(data.lease.encode()).hexdigest()): raise HTTPException(404)
            if old['status']!='running':
                if old['status']!=data.status or json.loads(old['result'] or '{}')!=data.result: raise HTTPException(409,'执行结果已冻结')
                return {'saved':True,'reused':True}
            c.execute('UPDATE cmui_agent_receipts SET status=?,result=?,updated_at=? WHERE owner=? AND request_id=?',
                       (data.status,encoded,now(),user['id'],request_id))
        return {'saved':True}

    @r.get('/tasks')
    async def tasks(user:User,request:Request):
        if domain: return await remote('task.list',user,{},request)
        return db.all('SELECT * FROM cmui_tasks WHERE owner=? ORDER BY due_at',(user['id'],))

    @r.post('/tasks',status_code=201)
    async def create_task(data:TaskCreate,user:User,request:Request):
        if data.course: await course(user,data.course,request)
        if domain: return await remote('task.create',user,data.model_dump(mode='json'),request)
        with db.connect(True) as c:
            old=c.execute('SELECT * FROM cmui_tasks WHERE owner=? AND request_id=?',(user['id'],data.request_id)).fetchone()
            if old:
                if old['title']!=data.title or old['due_at']!=data.due_at.astimezone(timezone.utc).isoformat() or old['course']!=data.course or old['timezone']!=data.timezone: raise HTTPException(409,'重复请求 ID 的内容不同')
                return dict(old)
            tid=uid('task_')
            c.execute('INSERT INTO cmui_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)',(tid,user['id'],data.course,data.title,data.due_at.astimezone(timezone.utc).isoformat(),data.timezone,'todo',1,data.request_id,now(),now()))
        return db.one('SELECT * FROM cmui_tasks WHERE id=?',(tid,))

    @r.patch('/tasks/{tid}')
    async def update_task(tid:str,data:TaskUpdate,user:User,request:Request):
        if domain: return await remote('task.update',user,dict(data.model_dump(mode='json'),id=tid),request)
        row=db.one('SELECT * FROM cmui_tasks WHERE id=? AND owner=?',(tid,user['id']))
        if not row: raise HTTPException(404)
        if row['version']!=data.version: raise HTTPException(409,'此安排已被修改，请刷新后重试')
        due=data.due_at.astimezone(timezone.utc).isoformat() if data.due_at else row['due_at']
        n=db.execute('UPDATE cmui_tasks SET title=?,due_at=?,status=?,version=version+1,updated_at=? WHERE id=? AND owner=? AND version=?',
            (data.title or row['title'],due,data.status or row['status'],now(),tid,user['id'],data.version))
        if not n: raise HTTPException(409,'版本冲突')
        return db.one('SELECT * FROM cmui_tasks WHERE id=?',(tid,))

    @r.delete('/tasks/{tid}')
    async def remove_task(tid:str,user:User,request:Request,version:int|None=Query(None,ge=1)):
        if domain: return await remote('task.delete',user,{'id':tid,'version':version},request)
        row=db.one('SELECT version FROM cmui_tasks WHERE id=? AND owner=?',(tid,user['id']))
        if not row: raise HTTPException(404)
        if version is not None and row['version']!=version: raise HTTPException(409,'版本冲突')
        if not db.execute('DELETE FROM cmui_tasks WHERE id=? AND owner=? AND version=?',(tid,user['id'],row['version'])): raise HTTPException(409,'版本冲突')
        return {'deleted':True}

    @r.post('/tasks/plan')
    async def task_plan(data:RunCreate,user:User,request:Request):
        rate(user,'task-agent',10)
        if domain: return await remote('task.plan',user,data.model_dump(),request)
        # This is a real Node tool-agent endpoint, separately launched, not a regex pretending to be an agent.
        import os, httpx
        node_url=os.getenv('CMUI_TASK_AGENT_URL','')
        if node_url not in {'http://127.0.0.1:8788','http://localhost:8788'}:
            raise HTTPException(503,'学习计划 Agent 未连接；可以先使用右侧手动安排。DSH 需接入现有 Node Task Agent。')
        try:
            async with httpx.AsyncClient(timeout=180,follow_redirects=False) as client:
                answer=await client.post(node_url+'/chat',json={'text':data.text,'request_id':data.request_id,'timezone':user['timezone']},
                    headers={'Cookie':request.headers.get('cookie',''),'Authorization':request.headers.get('authorization','')})
                if answer.status_code!=200: raise HTTPException(answer.status_code,answer.json().get('detail','任务 Agent 暂不可用'))
                return answer.json()
        except httpx.HTTPError: raise HTTPException(503,'任务 Agent 连接失败') from None

    @r.get('/conversations')
    async def histories(user:User,request:Request,course_id:str,lane:str=Query(pattern='^(teach|problem)$'),limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0)):
        await course(user,course_id,request)
        return db.all('SELECT * FROM cmui_conversations WHERE owner=? AND course=? AND lane=? ORDER BY updated_at DESC LIMIT ? OFFSET ?',
            (user['id'],course_id,lane,limit,offset))

    @r.post('/conversations',status_code=201)
    async def new_conversation(data:ConversationCreate,user:User,request:Request):
        await course(user,data.course,request)
        cid=uid('conv_')
        db.execute('INSERT INTO cmui_conversations VALUES (?,?,?,?,?,?,?)',(cid,user['id'],data.course,data.lane,data.title,now(),now()))
        return conversation(user,cid)

    @r.get('/conversations/{conv_id}')
    async def restore_conversation(conv_id:str,user:User,request:Request):
        row=conversation(user,conv_id); await course(user,row['course'],request)
        messages=db.all('SELECT * FROM cmui_messages WHERE conversation=? ORDER BY created_at,rowid',(conv_id,))
        # Re-check document access before returning historical snippets/citation names.
        accessible = (await remote('file.list',user,{'course':row['course'],'q':'','folder':None},request)) if domain else file_rows(db,user['id'],row['course'])
        accessible_ids={x['id'] for x in accessible}
        for m in messages:
            m['steps']=solution_steps(m['text']) if row['lane']=='problem' and m['role']=='assistant' else []
            attachment_row=db.one('SELECT attachments FROM cmui_run_inputs WHERE run=?',(m['run'],))
            m['attachments']=[x for x in json.loads(attachment_row['attachments']) if x['id'] in accessible_ids] if attachment_row and m['role']=='user' else []
            m['citations']=[x for x in json.loads(m['citations']) if x.get('document_id') in accessible_ids]
        row['messages']=messages
        row['active_run']=db.one("SELECT id,status,partial_text,error FROM cmui_runs WHERE conversation=? ORDER BY created_at DESC LIMIT 1",(conv_id,))
        return row

    @r.patch('/conversations/{conv_id}')
    async def rename_conversation(conv_id:str,data:Rename,user:User,request:Request):
        row=conversation(user,conv_id); await course(user,row['course'],request)
        db.execute('UPDATE cmui_conversations SET title=? WHERE id=?',(data.title,conv_id)); return conversation(user,conv_id)

    @r.delete('/conversations/{conv_id}')
    async def delete_conversation(conv_id:str,user:User,request:Request):
        row=conversation(user,conv_id); await course(user,row['course'],request)
        active=db.one("SELECT id FROM cmui_runs WHERE conversation=? AND status IN ('queued','planning','generating')",(conv_id,))
        if active: raise HTTPException(409,'请先停止当前生成')
        with db.connect(True) as c:
            c.execute('DELETE FROM cmui_bridges WHERE problem_message IN (SELECT id FROM cmui_messages WHERE conversation=?)',(conv_id,))
            c.execute('UPDATE cmui_layout SET teach_conversation=NULL WHERE owner=? AND teach_conversation=?',(user['id'],conv_id))
            c.execute('UPDATE cmui_layout SET problem_conversation=NULL WHERE owner=? AND problem_conversation=?',(user['id'],conv_id))
            c.execute('DELETE FROM cmui_conversations WHERE id=?',(conv_id,))
        return {'deleted':True}

    @r.get('/courses/{cid}/layout')
    async def get_layout(cid:str,user:User,request:Request):
        await course(user,cid,request)
        result=db.one('SELECT * FROM cmui_layout WHERE owner=? AND course=?',(user['id'],cid)) or {'ratio':.5,'teach_conversation':None,'problem_conversation':None,'active_node':None}
        result['bridge']=db.one("SELECT * FROM cmui_bridges WHERE owner=? AND course=? AND status='open' ORDER BY created_at DESC LIMIT 1",(user['id'],cid))
        return result

    @r.put('/courses/{cid}/layout')
    async def save_layout(cid:str,data:Layout,user:User,request:Request):
        await course(user,cid,request)
        for key,lane in [('teach_conversation','teach'),('problem_conversation','problem')]:
            value=getattr(data,key)
            if value:
                conv=conversation(user,value)
                if conv['course']!=cid or conv['lane']!=lane: raise HTTPException(422,'对话与面板不匹配')
        if data.active_node and not domain:
            if not db.one('SELECT id FROM cmui_nodes WHERE id=? AND course=?',(data.active_node,cid)): raise HTTPException(404,'知识点不存在')
        db.execute('INSERT INTO cmui_layout VALUES (?,?,?,?,?,?) ON CONFLICT(owner,course) DO UPDATE SET ratio=excluded.ratio,teach_conversation=excluded.teach_conversation,problem_conversation=excluded.problem_conversation,active_node=excluded.active_node',
            (user['id'],cid,data.ratio,data.teach_conversation,data.problem_conversation,data.active_node))
        return data.model_dump()

    @r.get('/courses/{cid}/knowledge')
    async def tree(cid:str,user:User,request:Request):
        await course(user,cid,request)
        if domain: return await remote('knowledge.tree',user,{'course':cid},request)
        return db.all("SELECT n.*,COALESCE(l.progress,'NOT_STARTED') progress,l.grade FROM cmui_nodes n LEFT JOIN cmui_learning l ON l.node=n.id AND l.owner=? WHERE n.course=? ORDER BY n.position",(user['id'],cid))

    @r.get('/courses/{cid}/knowledge/{node_id}/assessment')
    async def assessment(cid:str,node_id:str,user:User,request:Request):
        await course(user,cid,request)
        if domain: return await remote('knowledge.assessment',user,{'course':cid,'node':node_id},request)
        raise HTTPException(501,'正式测评沿用 V3 评分引擎；本更新包不伪造 GPA。请由 DSH 接入原服务。')

    @r.post('/courses/{cid}/knowledge/{node_id}/assessment/session',status_code=201)
    async def assessment_start(cid:str,node_id:str,user:User,request:Request):
        await course(user,cid,request)
        if not domain: raise HTTPException(501,'正式测评沿用 V3 评分引擎；本更新包不伪造 GPA。')
        body=await request.json()
        return await remote('knowledge.assessment.start',user,{'course':cid,'node':node_id,'request_id':str(body.get('request_id',''))},request)

    @r.get('/courses/{cid}/knowledge/assessment/{session_id}')
    async def assessment_view(cid:str,session_id:str,user:User,request:Request):
        await course(user,cid,request)
        if not domain: raise HTTPException(501,'正式测评沿用 V3 评分引擎；本更新包不伪造 GPA。')
        return await remote('knowledge.assessment.view',user,{'course':cid,'session':session_id},request)

    @r.post('/courses/{cid}/knowledge/assessment/{session_id}/submit')
    async def assessment_submit(cid:str,session_id:str,user:User,request:Request):
        await course(user,cid,request)
        if not domain: raise HTTPException(501,'正式测评沿用 V3 评分引擎；本更新包不伪造 GPA。')
        body=await request.json()
        return await remote('knowledge.assessment.submit',user,{'course':cid,'session':session_id,'request_id':str(body.get('request_id','')),'answers':body.get('answers') or []},request)

    @r.post('/courses/{cid}/knowledge/assessment/{session_id}/abandon')
    async def assessment_abandon(cid:str,session_id:str,user:User,request:Request):
        await course(user,cid,request)
        if not domain: raise HTTPException(501,'正式测评沿用 V3 评分引擎；本更新包不伪造 GPA。')
        body=await request.json()
        return await remote('knowledge.assessment.abandon',user,{'course':cid,'session':session_id,'request_id':str(body.get('request_id',''))},request)

    @r.post('/courses/{cid}/bridges',status_code=201)
    async def bridge(cid:str,data:BridgeCreate,user:User,request:Request):
        await course(user,cid,request)
        m=db.one("SELECT m.* FROM cmui_messages m JOIN cmui_conversations c ON c.id=m.conversation WHERE m.id=? AND c.owner=? AND c.course=? AND c.lane='problem' AND m.role='assistant'",(data.problem_message,user['id'],cid))
        if not m: raise HTTPException(404,'原题解法不存在')
        if not any(x['number']==data.step for x in solution_steps(m['text'])):
            raise HTTPException(422,'原解法中不存在这个编号步骤')
        if data.node and not domain and not db.one('SELECT id FROM cmui_nodes WHERE id=? AND course=?',(data.node,cid)): raise HTTPException(404)
        old=db.one('SELECT * FROM cmui_bridges WHERE owner=? AND problem_message=? AND step=? AND question=?',(user['id'],data.problem_message,data.step,data.question))
        if old: return old
        bid=uid('bridge_')
        db.execute('INSERT INTO cmui_bridges VALUES (?,?,?,?,?,?,?,?,?)',(bid,user['id'],cid,data.problem_message,data.step,data.question,data.node,'open',now(),))
        return db.one('SELECT * FROM cmui_bridges WHERE id=?',(bid,))

    @r.patch('/bridges/{bid}/return')
    async def return_bridge(bid:str,user:User,request:Request):
        b=db.one('SELECT * FROM cmui_bridges WHERE id=? AND owner=?',(bid,user['id']))
        if not b: raise HTTPException(404)
        await course(user,b['course'],request)
        if not db.execute("UPDATE cmui_bridges SET status='returned' WHERE id=? AND owner=?",(bid,user['id'])): raise HTTPException(404)
        return db.one('SELECT * FROM cmui_bridges WHERE id=?',(bid,))

    async def generate_run(run_id,user,course_data,conv,sources,history,data,bridge_data,images=None):
        output=''; usages=[]; last_beat=0.0
        try:
            heartbeat(run_id)
            async for item in model.generate(course_data,data.text,{k:user[k] for k in ['language','timezone','bio']},sources,history,conv['lane'],bridge_data,**({'attachments':images} if images else {})):
                # A cancel from ANOTHER process cannot reach this loop through the
                # local job map; the database is the coordination point. The row's
                # status is re-read so a cancelled run stops promptly instead of
                # streaming to completion and charging more.
                state=db.one('SELECT status FROM cmui_runs WHERE id=?',(run_id,))
                if state and state['status'] in TERMINAL: raise asyncio.CancelledError()
                if time.time()-last_beat>5:
                    heartbeat(run_id); last_beat=time.time()
                kind=item['kind']
                if kind=='status':
                    db.execute('UPDATE cmui_runs SET status=?,updated_at=? WHERE id=?',(item['status'],now(),run_id))
                    event(run_id,'status',item)
                elif kind=='prompt':
                    db.execute('UPDATE cmui_runs SET generated_prompt=? WHERE id=?',(item['text'],run_id))
                    event(run_id,'prompt_ready',{'characters':len(item['text'])})
                elif kind=='delta':
                    output+=item['text']
                    if len(output)>100000: raise ProviderError('ANSWER_TOO_LONG')
                    db.execute('UPDATE cmui_runs SET partial_text=?,updated_at=? WHERE id=?',(output,now(),run_id))
                    event(run_id,'delta',{'text':item['text']})
                elif kind=='usage':
                    usages.append(item)
                    db.execute('UPDATE cmui_runs SET usage=? WHERE id=?',(json.dumps(usages),run_id))
            if not output.strip(): raise ProviderError('EMPTY_MODEL_ANSWER')
            # Only referenced, existing source IDs become citation cards; existence is NOT entailment proof.
            import re
            mentioned=set(re.findall(r'\[(S\d+)\]',output))
            citations=[{k:v for k,v in s.items() if k!='text'} for s in sources if s['id'] in mentioned]
            message_id=uid('message_')
            with db.connect(True) as c:
                # The final write is a conditional transition: if a cancel won the
                # race (same or another process), the message is NOT inserted and
                # the row keeps its cancelled/failed state.
                claimed=c.execute("UPDATE cmui_runs SET status='completed',partial_text=?,citations=?,usage=?,updated_at=? WHERE id=? AND status IN ('queued','planning','generating')",(output,json.dumps(citations,ensure_ascii=False),json.dumps(usages),now(),run_id)).rowcount
                if claimed==1:
                    c.execute('INSERT INTO cmui_messages VALUES (?,?,?,?,?,?,?)',(message_id,conv['id'],'assistant',output,json.dumps(citations,ensure_ascii=False),run_id,now()))
                    c.execute('UPDATE cmui_conversations SET updated_at=? WHERE id=?',(now(),conv['id']))
                else:
                    raise asyncio.CancelledError()
            event(run_id,'done',{'message_id':message_id,'citations':citations,'provider_mode':cfg.provider_mode})
        except asyncio.CancelledError:
            # Terminal already? Keep whatever state won; otherwise mark cancelled.
            db.execute("UPDATE cmui_runs SET status='cancelled',error=CASE WHEN status IN ('queued','planning','generating') THEN 'CANCELLED' ELSE error END,updated_at=? WHERE id=? AND status NOT IN ('completed','failed')",(now(),run_id))
            event(run_id,'error',{'code':'CANCELLED','message':'已停止，已生成的部分仍可查看'})
        except Exception as error:
            code=str(error) if isinstance(error,ProviderError) else 'GENERATION_FAILED'
            db.execute("UPDATE cmui_runs SET status='failed',error=?,usage=?,updated_at=? WHERE id=? AND status NOT IN ('completed','cancelled')",(code,json.dumps(usages),now(),run_id))
            event(run_id,'error',{'code':code,'message':'生成未完成；不会自动重试或重复扣费。请检查模型配置或已批准的预算。'})
        finally: jobs.pop(run_id,None)

    @r.post('/conversations/{conv_id}/runs',status_code=202)
    async def run(conv_id:str,data:RunCreate,user:User,request:Request):
        conv=conversation(user,conv_id)
        course_data=await course(user,conv['course'],request)
        digest=hashlib.sha256(json.dumps({'conv':conv_id,**data.model_dump()},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        old=db.one('SELECT * FROM cmui_runs WHERE owner=? AND request_id=?',(user['id'],data.request_id))
        if old:
            if old['conversation']!=conv_id or old['user_text']!=data.text: raise HTTPException(409,'重复请求 ID 的内容不同')
            recorded=db.one('SELECT payload_hash FROM cmui_run_inputs WHERE run=?',(old['id'],))
            if recorded and recorded['payload_hash']!=digest: raise HTTPException(409,'重复请求 ID 的附件或上下文不同')
            return {'id':old['id'],'status':old['status'],'reused':True}
        rate(user,'model-runs',8)
        if cfg.provider_mode=='disabled' and provider is None: raise HTTPException(503,'模型尚未配置；数据功能可用，不会返回预设答案冒充千问。')
        if cfg.provider_mode=='qwen' and not cfg.allow_billable: raise HTTPException(402,'尚未授权模型调用费用')
        history=db.all('SELECT role,text FROM cmui_messages WHERE conversation=? ORDER BY created_at DESC,rowid DESC LIMIT 12',(conv_id,))[::-1]
        remaining=20000; bounded=[]
        for h in reversed(history):
            if remaining<=0: break
            t=h['text'][-min(6000,remaining):]; bounded.append({'role':h['role'],'text':t}); remaining-=len(t)
        history=list(reversed(bounded))
        sources=(await remote('context.retrieve',user,{'course':conv['course'],'query':data.text,'history':history},request)) if domain else context_for(db,user['id'],conv['course'],data.text,history)
        images=[]; attachment_meta=[]
        if data.attachment_ids:
            if len(data.attachment_ids)!=len(set(data.attachment_ids)): raise HTTPException(422,'重复附件')
            if domain:
                prepared=await remote('attachments.prepare',user,{'course':conv['course'],'ids':data.attachment_ids},request)
                images=prepared.get('images',[])
                attachment_meta=prepared.get('metadata',[])
                sources.extend(prepared.get('sources',[]))
            else:
                for fid in data.attachment_ids:
                    f=db.one("SELECT * FROM cmui_files WHERE id=? AND course=? AND (scope='public' OR owner=?)",(fid,conv['course'],user['id']))
                    if not f: raise HTTPException(404,'附件不存在')
                    attachment_meta.append({'id':fid,'name':f['name'],'mime':f['mime']})
                    if f['mime'].startswith('image/'):
                        path=cfg.data_dir/'uploads'/f['storage_key']
                        if not path.is_file(): raise HTTPException(404,'附件不可用')
                        if f['size']>5*1024*1024: raise HTTPException(413,'单张题目图片最多 5 MB')
                        images.append({'id':fid,'data_url':f"data:{f['mime']};base64,"+base64.b64encode(path.read_bytes()).decode()})
                    else:
                        parts=db.all('SELECT page,text FROM cmui_chunks WHERE file=? ORDER BY ordinal LIMIT 5',(fid,))
                        if not parts: raise HTTPException(422,'附件暂时没有可读取文字，请改用清晰题目图片或完成解析')
                        sources.extend({'id':f'S{len(sources)+i+1}','document_id':fid,'name':f['name'],'page':x['page'],'text':x['text']} for i,x in enumerate(parts))
                # Keep source labels unambiguous after selected-file context is appended.
                sources=[dict(src,id=f'S{i+1}') for i,src in enumerate(sources)]
        bridge_data=None
        if data.bridge_id:
            bridge_data=db.one('SELECT * FROM cmui_bridges WHERE id=? AND owner=? AND course=?',(data.bridge_id,user['id'],conv['course']))
            if not bridge_data: raise HTTPException(404)
            message=db.one('SELECT text FROM cmui_messages WHERE id=?',(bridge_data['problem_message'],))
            original=db.one('SELECT r.user_text FROM cmui_messages m JOIN cmui_runs r ON r.id=m.run WHERE m.id=?',(bridge_data['problem_message'],))
            bridge_data=dict(bridge_data,original_question=original['user_text'] if original else '',solution_excerpt=message['text'][:15000] if message else '')
        if data.node_id and not domain:
            if not db.one('SELECT id FROM cmui_nodes WHERE id=? AND course=?',(data.node_id,conv['course'])): raise HTTPException(404)
        v3_link=None
        if data.node_id and domain:
            # Start (or continue) the authoritative V3 learning journey for this
            # node BEFORE the run rows exist, so a missing node never leaves a
            # queued run behind. Coverage is NOT claimed here: V3 teach() owns
            # REQUIRED-item coverage, and the journey stays LEARNING forever until
            # real delivery evidence exists.
            v3_link=await remote('knowledge.begin_learning',user,{'course':conv['course'],'node':data.node_id},request)
        rid=uid('run_')
        try:
            with db.connect(True) as c:
                c.execute('INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,lease_worker,lease_heartbeat,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(rid,user['id'],conv_id,data.request_id,'queued',data.text,worker_id,str(time.time()),now(),now()))
                c.execute('INSERT INTO cmui_run_inputs VALUES (?,?,?)',(rid,digest,json.dumps(attachment_meta,ensure_ascii=False)))
                c.execute('INSERT INTO cmui_messages VALUES (?,?,?,?,?,?,?)',(uid('message_'),conv_id,'user',data.text,'[]',rid,now()))
                c.execute("UPDATE cmui_conversations SET title=CASE WHEN title='新对话' THEN ? ELSE title END,updated_at=? WHERE id=?",(data.text[:40],now(),conv_id))
                if data.node_id and not domain:
                    c.execute("INSERT INTO cmui_learning(owner,node,progress) VALUES (?,?,'LEARNING') ON CONFLICT(owner,node) DO UPDATE SET progress=CASE WHEN progress='LEARNED' THEN progress ELSE 'LEARNING' END",(user['id'],data.node_id))
                if v3_link is not None:
                    c.execute('INSERT INTO cmui_run_v3(run,workspace_id,journey_id,node_id,spec_version,created_at) VALUES (?,?,?,?,?,?)',(rid,v3_link['workspace_id'],v3_link['journey_id'],v3_link['node_id'],v3_link['spec_version'],now()))
        except sqlite3.IntegrityError: raise HTTPException(409,'该对话已有任务正在生成，请先等待或停止') from None
        event(rid,'status',{'status':'queued'})
        task=asyncio.create_task(generate_run(rid,user,course_data,conv,sources,history,data,bridge_data,images))
        jobs[rid]=task
        return {'id':rid,'status':'queued'}

    @r.get('/runs/{rid}')
    async def get_run(rid:str,user:User,request:Request):
        row=owned_run(user,rid)
        conv=conversation(user,row['conversation']); await course(user,conv['course'],request)
        row['citations']=json.loads(row['citations']); row['usage']=json.loads(row['usage'])
        return row

    @r.get('/runs/{rid}/events')
    async def events(rid:str,user:User,request:Request,after:int=Query(0,ge=0)):
        run_row=owned_run(user,rid)
        conv=conversation(user,run_row['conversation']); await course(user,conv['course'],request)
        async def produce():
            seq=after
            idle=0
            while True:
                if await request.is_disconnected(): break
                rows=db.all('SELECT * FROM cmui_run_events WHERE run=? AND seq>? ORDER BY seq',(rid,seq))
                for e in rows:
                    seq=e['seq']
                    yield f'id: {seq}\nevent: {e["type"]}\ndata: {e["data"]}\n\n'
                current=db.one('SELECT status FROM cmui_runs WHERE id=?',(rid,))
                if not current or current['status'] in TERMINAL: break
                idle+=1
                if idle%40==0: yield ': keepalive\n\n'
                await asyncio.sleep(.2)
        return StreamingResponse(produce(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no','Cache-Control':'no-store'})

    @r.post('/runs/{rid}/cancel')
    async def cancel(rid:str,user:User,request:Request):
        row=owned_run(user,rid)
        conv=conversation(user,row['conversation']); await course(user,conv['course'],request)
        if row['status'] in TERMINAL: return {'status':row['status']}
        # The database is the coordination point for cross-process cancel: write
        # the terminal state FIRST, so the generating process's next heartbeat
        # check stops it even when the job map is on another worker. The local
        # task cancellation only shortens the wait for same-process runs.
        db.execute("UPDATE cmui_runs SET status='cancelled',error='CANCELLED',updated_at=? WHERE id=? AND status IN ('queued','planning','generating')",(now(),rid))
        task=jobs.get(rid)
        if task: task.cancel()
        return {'status':'cancelled'}

    app.include_router(r)

    @app.get('/health')
    def health():
        try:
            with sqlite3.connect(db.path.as_uri()+'?mode=ro',uri=True) as check:
                if not check.execute("SELECT value FROM cmui_meta WHERE key='schema_version'").fetchone():raise ValueError('Not initialized')
        except Exception:raise HTTPException(503,'Service is not ready') from None
        return {'status':'ok','service':'coursemate-ui-update','mode':cfg.integration_mode,'provider':cfg.provider_mode}

    if cfg.web_dir.is_dir():
        app.mount('/',StaticFiles(directory=cfg.web_dir,html=True),name='web')
    return app
