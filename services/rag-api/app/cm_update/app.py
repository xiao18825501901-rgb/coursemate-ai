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
from .models import (Profile, CourseCreate, CommentCreate, MessageCreate, TaskCreate,
    TaskUpdate, ConversationCreate, Rename, Layout, RunCreate, BridgeCreate, CourseUpdate,
    ReceiptClaim, ReceiptFinish, PairCreate, PairBind, ClassificationCorrection,
    VerificationRedeem, VerificationIssue, VerificationDisable, ShareCreate,
    ExerciseCreate, ExplanationCreate, ExplanationMessage)
from .filesystem import parse_document, valid_filename, valid_folder, file_hash
from .retrieval import get_course, file_rows, context_for
from .steps import solution_steps, answer_steps_parse
from .provider import QwenProvider, DisabledProvider, TestProvider, ProviderError
from . import templates
from . import social

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

    async def submit_delivery(*, run_id, user, conv, data, v3_link, spec_items, content):
        """Submit a completed teaching into the V3 evidence ledger.

        Bookkeeping only: never calls a provider. The same run id is the
        operation id, and `teaching_units(journey_id, operation_id)` is unique,
        so a retry after a cross-database interruption replays the same rows.
        Failures are recorded on the receipt without failing the run; the
        teaching stays visible either way.
        """

        if domain is None or v3_link is None or not content.strip():
            return
        payload = {
            'course': conv['course'], 'node': v3_link['node_id'],
            'spec_version': v3_link['spec_version'], 'run_id': run_id,
            'content': content, 'bridge_id': data.bridge_id,
            'question': data.text,
        }
        try:
            result = await domain.call('knowledge.submit_delivery', user['id'], payload, '')
            covered = json.dumps(result.get('covered') or [], ensure_ascii=False)
            db.execute(
                "INSERT INTO cmui_delivery_submissions(run,unit_id,journey_id,status,"
                "covered_items,created_at,updated_at) VALUES(?,?,?,'submitted',?,?,?) "
                "ON CONFLICT(run) DO UPDATE SET unit_id=excluded.unit_id,"
                "journey_id=excluded.journey_id,status='submitted',"
                "covered_items=excluded.covered_items,error=NULL,updated_at=excluded.updated_at",
                (run_id, result.get('unit_id'), result.get('journey_id'), covered, now(), now()),
            )
            if data.bridge_id:
                db.execute(
                    "UPDATE cmui_bridges SET delivery_unit_id=? WHERE id=? AND owner=?",
                    (result.get('unit_id'), data.bridge_id, user['id']),
                )
            event(run_id, 'coverage', {
                'unit_id': result.get('unit_id'),
                'covered': result.get('covered'),
                'progress': result.get('progress'),
            })
        except Exception as error:
            db.execute(
                "INSERT INTO cmui_delivery_submissions(run,status,error,created_at,updated_at) "
                "VALUES(?,'failed',?,?,?) ON CONFLICT(run) DO UPDATE SET status='failed',"
                "error=excluded.error,updated_at=excluded.updated_at",
                (run_id, str(error)[:500], now(), now()),
            )

    async def recover_delivery_submissions():
        """Restart recovery: resume interrupted coverage bookkeeping.

        Only completed runs whose receipt row is missing are retried - the
        process died between the final write and the receipt. The retry replays
        the same operation id and never touches the provider; a run whose
        submission genuinely failed keeps its recorded failure.
        """

        if domain is None:
            return
        rows = db.all(
            "SELECT r.id AS run, r.conversation, v.workspace_id, v.journey_id, "
            "v.node_id, v.spec_version FROM cmui_runs r "
            "JOIN cmui_run_v3 v ON v.run=r.id "
            "LEFT JOIN cmui_delivery_submissions s ON s.run=r.id "
            "WHERE r.status='completed' AND s.run IS NULL"
        )
        for row in rows:
            try:
                message = db.one("SELECT text FROM cmui_messages WHERE run=?", (row['run'],))
                conv = db.one('SELECT * FROM cmui_conversations WHERE id=?', (row['conversation'],))
                owner = db.one('SELECT owner FROM cmui_runs WHERE id=?', (row['run'],))
                if not message or not conv or not owner:
                    continue
                payload = {
                    'course': conv['course'], 'node': row['node_id'],
                    'spec_version': row['spec_version'], 'run_id': row['run'],
                    'content': message['text'],
                }
                result = await domain.call('knowledge.submit_delivery', owner['owner'], payload, '')
                covered = json.dumps(result.get('covered') or [], ensure_ascii=False)
                db.execute(
                    "INSERT INTO cmui_delivery_submissions(run,unit_id,journey_id,status,"
                    "covered_items,created_at,updated_at) VALUES(?,?,?,'submitted',?,?,?) "
                    "ON CONFLICT(run) DO UPDATE SET unit_id=excluded.unit_id,"
                    "journey_id=excluded.journey_id,status='submitted',"
                    "covered_items=excluded.covered_items,error=NULL,updated_at=excluded.updated_at",
                    (row['run'], result.get('unit_id'), result.get('journey_id'), covered, now(), now()),
                )
            except Exception as error:
                db.execute(
                    "INSERT INTO cmui_delivery_submissions(run,status,error,created_at,updated_at) "
                    "VALUES(?,'failed',?,?,?) ON CONFLICT(run) DO UPDATE SET status='failed',"
                    "error=excluded.error,updated_at=excluded.updated_at",
                    (row['run'], str(error)[:500], now(), now()),
                )

    @asynccontextmanager
    async def lifespan(app):
        # Only runs with provably dead owners are reclaimed. A sibling process
        # that heartbeats normally is left untouched - starting a second worker
        # must never kill the first worker's in-flight run (its model cost has
        # already been spent, so killing it would waste money AND lose the answer).
        reclaim_orphaned_runs()
        await recover_delivery_submissions()
        # One-time grandfathered student verification for pre-existing users.
        candidates=[u['id'] for u in db.all('SELECT id FROM cmui_users')]
        if domain is not None:
            try:
                extra=await domain.call('verification.grandfather_candidates', '', {}, '')
                for uid_extra in (extra or []):
                    if uid_extra not in candidates: candidates.append(uid_extra)
            except Exception:
                pass
        try:
            social.grandfather_existing_users(db, candidates)
        except Exception:
            pass
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

    def pair_for_conversation(user, conversation_id):
        """The unified dual-pane session containing a conversation, if any."""
        row=db.one(
            "SELECT * FROM cmui_pairs WHERE owner=? AND (teach_conversation=? OR problem_conversation=?)",
            (user['id'],conversation_id,conversation_id))
        return row

    def verified(user):
        return bool(social.verification_status(db,user['id'])['verified'])

    def is_admin(user):
        return user['id'] in cfg.admin_ids

    def course_gate(course_dto, user):
        """Campus courses require student verification for CONTENT access.
        Directory metadata (name/type) stays visible; this gate is applied to
        every content-bearing endpoint. Admins keep access for operations."""
        if is_admin(user):
            return
        requires = course_dto.get('requires_student_verification') or course_dto.get('display_type')=='campus'
        if requires and not verified(user):
            raise HTTPException(403,'此课程为校园课程：请先在账户中完成学生认证（7 位认证码）')

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
            c.execute('INSERT INTO cmui_courses(id,owner,code,name,description,color,requirements,display_type,created_at) VALUES (?,?,?,?,?,?,?,\'private\',?)',
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
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
        db.execute('INSERT OR IGNORE INTO cmui_pins(owner,course) VALUES (?,?)',(user['id'],cid))
        return {'pinned':True}

    @r.delete('/courses/{cid}/pin')
    async def unpin(cid:str,user:User,request:Request):
        await course(user,cid,request)
        db.execute('DELETE FROM cmui_pins WHERE owner=? AND course=?',(user['id'],cid))
        return {'pinned':False}

    @r.get('/courses/{cid}/files')
    async def files(cid:str,user:User,request:Request,q:str=Query(default='',max_length=150),folder:str|None=None):
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
        if domain: return await remote('file.list',user,{'course':cid,'q':q,'folder':folder},request)
        rows=file_rows(db,user['id'],cid)
        if q: rows=[x for x in rows if q.casefold() in x['name'].casefold()]
        elif folder is not None: rows=[x for x in rows if x['folder']==folder]
        return [public_file(x) for x in rows]

    @r.post('/courses/{cid}/files',status_code=201)
    async def upload(cid:str,user:User,request:Request,file:UploadFile=File(...),folder:str=Form(default='')):
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
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
            result=await remote('file.upload',user,{'course':cid,'name':name,'folder':folder,'content':content,'mime':mime},request)
            try:
                file_list=await remote('file.list',user,{'course':cid,'q':'','folder':None},request)
                bundle={'course_name':course_data.get('name',cid),'course_code':course_data.get('code',''),
                    'description':course_data.get('description',''),
                    'files':[{'name':f.get('name'),'size':f.get('size')} for f in file_list][:40],
                    'text_samples':[],'materials_revision':social.materials_revision([{'id':f.get('id'),'sha256':f.get('sha256','')} for f in file_list])}
                schedule_classification(cid,bundle)
            except Exception:
                pass
            return result
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
        try:
            file_list=file_rows(db,user['id'],cid)
            bundle={'course_name':course_data.get('name',cid),'course_code':course_data.get('code',''),
                'description':course_data.get('description',''),
                'files':[{'name':f.get('name'),'size':f.get('size')} for f in file_list][:40],
                'text_samples':[t['text'][:600] for t in parts[:6]],
                'materials_revision':social.materials_revision([{'id':f.get('id'),'sha256':f.get('sha256','')} for f in file_list])}
            schedule_classification(cid,bundle)
        except Exception:
            pass
        return public_file(db.one('SELECT * FROM cmui_files WHERE id=?',(fid,)))

    @r.get('/courses/{cid}/files/{fid}/content',operation_id='get_course_file_content')
    @r.head('/courses/{cid}/files/{fid}/content',operation_id='head_course_file_content')
    async def content(cid:str,fid:str,user:User,request:Request,download:bool=False):
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
        if domain: return await remote('file.content',user,{'course':cid,'id':fid,'download':download,'range':request.headers.get('range')},request)
        row=db.one("SELECT * FROM cmui_files WHERE id=? AND course=? AND (scope='public' OR owner=?)",(fid,cid,user['id']))
        if not row: raise HTTPException(404,'文件不存在')
        path=cfg.data_dir/'uploads'/row['storage_key']
        if not path.is_file(): raise HTTPException(404,'文件暂时不可用')
        return FileResponse(path,media_type=row['mime'],filename=row['name'],content_disposition_type='attachment' if download else 'inline',headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff'})

    @r.get('/courses/{cid}/files/{fid}/text')
    async def preview_text(cid:str,fid:str,user:User,request:Request):
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
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
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
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
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
        rate(user,'comment',20)
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
        return db.all('SELECT * FROM cmui_conversations WHERE owner=? AND course=? AND lane=? AND hidden=0 ORDER BY updated_at DESC LIMIT ? OFFSET ?',
            (user['id'],course_id,lane,limit,offset))

    @r.post('/conversations',status_code=201)
    async def new_conversation(data:ConversationCreate,user:User,request:Request):
        await course(user,data.course,request)
        cid=uid('conv_')
        db.execute('INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at,hidden) VALUES (?,?,?,?,?,?,?,0)',(cid,user['id'],data.course,data.lane,data.title,now(),now()))
        # Pair-aware creation (back-compat for per-lane clients): attach the new
        # lane to the newest pair that still misses it, creating a pair when
        # none exists, so unified history lists the conversation immediately.
        lane_column=f"{data.lane}_conversation"
        pair=db.one(f"SELECT * FROM cmui_pairs WHERE owner=? AND course=? AND {lane_column} IS NULL ORDER BY updated_at DESC LIMIT 1",(user['id'],data.course))
        if pair is None:
            pid=uid('pair_')
            with db.connect(True) as c:
                c.execute('INSERT INTO cmui_pairs(id,owner,course,teach_conversation,problem_conversation,title,bound_node,created_at,updated_at) VALUES (?,?,?,?,?,?,NULL,?,?)',
                    (pid,user['id'],data.course,
                     cid if data.lane=='teach' else None,
                     cid if data.lane=='problem' else None,
                     data.title,now(),now()))
        else:
            db.execute(f'UPDATE cmui_pairs SET {lane_column}=?,updated_at=? WHERE id=?',(cid,now(),pair['id']))
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
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
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

    @r.get('/courses/{cid}/bridges')
    async def bridges(cid:str,user:User,request:Request):
        await course(user,cid,request)
        return db.all('SELECT * FROM cmui_bridges WHERE owner=? AND course=? ORDER BY created_at DESC',(user['id'],cid))

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
        # Map the completed problem run into the V3 versioned problem ledger so
        # the bridge carries verifiable ids; failure never blocks the bridge.
        link={}
        if domain:
            try:
                original=db.one('SELECT r.user_text FROM cmui_messages m JOIN cmui_runs r ON r.id=m.run WHERE m.id=?',(data.problem_message,))
                steps=[{'number':x['number'],'title':x['title']} for x in solution_steps(m['text'])]
                if original:
                    link=await remote('knowledge.record_problem',user,{'course':cid,'run_id':str(m['run']),'question':original['user_text'],'steps':steps},request)
            except HTTPException: pass
        bid=uid('bridge_')
        db.execute('INSERT INTO cmui_bridges (id,owner,course,problem_message,step,question,node,status,created_at,teach_run,journey_id,spec_version,delivery_unit_id,problem_revision_id,solution_id,step_ids_json) VALUES (?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,?,?)',
            (bid,user['id'],cid,data.problem_message,data.step,data.question,data.node,'open',now(),link.get('problem_revision_id'),link.get('solution_id'),json.dumps(link.get('step_ids') or [],ensure_ascii=False)))
        return db.one('SELECT * FROM cmui_bridges WHERE id=?',(bid,))

    @r.patch('/bridges/{bid}/return')
    async def return_bridge(bid:str,user:User,request:Request):
        b=db.one('SELECT * FROM cmui_bridges WHERE id=? AND owner=?',(bid,user['id']))
        if not b: raise HTTPException(404)
        await course(user,b['course'],request)
        if not db.execute("UPDATE cmui_bridges SET status='returned' WHERE id=? AND owner=?",(bid,user['id'])): raise HTTPException(404)
        return db.one('SELECT * FROM cmui_bridges WHERE id=?',(bid,))

    async def generate_run(run_id,user,course_data,conv,sources,history,data,bridge_data,images=None,v3_link=None,spec_items=None,teaching_mode='normal',template_id='OTHER'):
        output=''; usages=[]; last_beat=0.0
        try:
            heartbeat(run_id)
            generate_kwargs={'attachments':images} if images else {}
            if spec_items: generate_kwargs['spec_items']=spec_items
            generate_kwargs['teaching_mode']=teaching_mode
            generate_kwargs['template_id']=template_id

            async def consume():
                nonlocal output, usages, last_beat
                async for item in model.generate(course_data,data.text,{k:user[k] for k in ['language','timezone','bio']},sources,history,conv['lane'],bridge_data,**generate_kwargs):
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

            # A provider that goes silent (no SSE events) must not suspend
            # cancellation: the watchdog polls the database and stops the
            # consumer when the run reached a terminal state, so a cancel or a
            # sibling-process failure takes effect within a bounded interval.
            consume_task=asyncio.create_task(consume())
            async def watchdog():
                while True:
                    await asyncio.sleep(2)
                    state=db.one('SELECT status FROM cmui_runs WHERE id=?',(run_id,))
                    if state and state['status'] in TERMINAL:
                        consume_task.cancel()
                        return
                    if consume_task.done(): return
            watchdog_task=asyncio.create_task(watchdog())
            try:
                await asyncio.gather(consume_task, watchdog_task, return_exceptions=True)
                exception=consume_task.exception()
                if exception is not None: raise exception
                if consume_task.cancelled(): raise asyncio.CancelledError()
            finally:
                watchdog_task.cancel()

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
                    c.execute('INSERT INTO cmui_messages(id,conversation,role,text,citations,run,created_at,provenance,exercise) VALUES (?,?,?,?,?,?,?,?,NULL)',(message_id,conv['id'],'assistant',output,json.dumps(citations,ensure_ascii=False),run_id,now(),''))
                    c.execute('UPDATE cmui_conversations SET updated_at=? WHERE id=?',(now(),conv['id']))
                else:
                    raise asyncio.CancelledError()
            event(run_id,'done',{'message_id':message_id,'citations':citations,'provider_mode':cfg.provider_mode})
            # A run that claimed 'completed' and persisted its message may now
            # contribute coverage. Submission is bookkeeping only: it never
            # calls a provider, and a cancel after the claim cannot happen
            # because the conditional write above owns the terminal state.
            await submit_delivery(
                run_id=run_id, user=user, conv=conv, data=data,
                v3_link=v3_link, spec_items=spec_items, content=output,
            )
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
        course_gate(course_data,user)
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
        teaching_mode=data.teaching_mode
        # Node binding semantics: the FIRST teaching bound to a node uses the
        # Thinking flow automatically and exactly once. Later runs on the same
        # binding restore without forcing Thinking. An atomic claim decides
        # between concurrent first clicks, so double-clicks cannot double-charge.
        if data.node_id and not domain:
            if not db.one('SELECT id FROM cmui_nodes WHERE id=? AND course=?',(data.node_id,conv['course'])): raise HTTPException(404)
        if data.node_id:
            pair=pair_for_conversation(user,conv_id)
            if pair is not None:
                if pair['bound_node']!=data.node_id:
                    conflict=db.one(
                        "SELECT id FROM cmui_pairs WHERE owner=? AND course=? AND bound_node=? AND id<>?",
                        (user['id'],conv['course'],data.node_id,pair['id']))
                    if conflict is None:
                        # Atomic claim for the FIRST teaching on this binding;
                        # a concurrent loser must never crash a valid run.
                        try:
                            claimed=db.execute(
                                "UPDATE cmui_pairs SET bound_node=?,updated_at=? WHERE id=? AND bound_node IS NULL",
                                (data.node_id,now(),pair['id']))
                        except sqlite3.IntegrityError:
                            claimed=0
                        if claimed==1 and conv['lane']=='teach':
                            teaching_mode='thinking'
                    # else: the node already belongs to another pair — teaching
                    # proceeds here; the binding stays with the original pair
                    # (the UI opens that pair on tree clicks).
        template_id='OTHER'
        classification=db.one('SELECT * FROM cmui_classifications WHERE course=?',(conv['course'],))
        if classification and classification['status']=='CLASSIFIED' and classification['template_id'] in templates.registry():
            template_id=classification['template_id']
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
        spec_items=None
        if data.node_id and domain:
            # Bind the run to the authoritative V3 learning journey BEFORE the
            # run rows exist, so a missing node never leaves a queued run behind.
            # Coverage is claimed only after completion through the reviewed
            # delivery submission (knowledge.submit_delivery); the spec's
            # REQUIRED items are carried into stage-one planning as requirements,
            # never as database authority for the model.
            v3_link=await remote('knowledge.begin_learning',user,{'course':conv['course'],'node':data.node_id},request)
            spec_items=v3_link.get('required_items') or None
        rid=uid('run_')
        try:
            with db.connect(True) as c:
                c.execute('INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,teaching_mode,lease_worker,lease_heartbeat,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(rid,user['id'],conv_id,data.request_id,'queued',data.text,teaching_mode,worker_id,str(time.time()),now(),now()))
                c.execute('INSERT INTO cmui_run_inputs VALUES (?,?,?)',(rid,digest,json.dumps(attachment_meta,ensure_ascii=False)))
                c.execute('INSERT INTO cmui_messages(id,conversation,role,text,citations,run,created_at,provenance,exercise) VALUES (?,?,?,?,?,?,?,?,NULL)',(uid('message_'),conv_id,'user',data.text,'[]',rid,now(),''))
                c.execute("UPDATE cmui_conversations SET title=CASE WHEN title='新对话' THEN ? ELSE title END,updated_at=? WHERE id=?",(data.text[:40],now(),conv_id))
                pair=pair_for_conversation(user,conv_id)
                if pair is not None:
                    c.execute('UPDATE cmui_pairs SET updated_at=? WHERE id=?',(now(),pair['id']))
                if data.node_id and not domain:
                    c.execute("INSERT INTO cmui_learning(owner,node,progress) VALUES (?,?,'LEARNING') ON CONFLICT(owner,node) DO UPDATE SET progress=CASE WHEN progress='LEARNED' THEN progress ELSE 'LEARNING' END",(user['id'],data.node_id))
                if v3_link is not None:
                    c.execute('INSERT INTO cmui_run_v3(run,workspace_id,journey_id,node_id,spec_version,created_at) VALUES (?,?,?,?,?,?)',(rid,v3_link['workspace_id'],v3_link['journey_id'],v3_link['node_id'],v3_link['spec_version'],now()))
                    if data.bridge_id:
                        c.execute('UPDATE cmui_bridges SET teach_run=?,journey_id=?,spec_version=? WHERE id=? AND owner=?',(rid,v3_link['journey_id'],v3_link['spec_version'],data.bridge_id,user['id']))
        except sqlite3.IntegrityError: raise HTTPException(409,'该对话已有任务正在生成，请先等待或停止') from None
        event(rid,'status',{'status':'queued','label':'正在思考中'})
        task=asyncio.create_task(generate_run(rid,user,course_data,conv,sources,history,data,bridge_data,images,v3_link,spec_items,teaching_mode,template_id))
        jobs[rid]=task
        return {'id':rid,'status':'queued','teaching_mode':teaching_mode}

    @r.get('/runs/{rid}')
    async def get_run(rid:str,user:User,request:Request):
        row=owned_run(user,rid)
        conv=conversation(user,row['conversation']); await course(user,conv['course'],request)
        # Response whitelist: the internal plan (generated_prompt) and worker
        # lease bookkeeping never leave the server, for old and new records alike.
        public={k:row[k] for k in ('id','status','user_text','partial_text','citations',
            'usage','error','teaching_mode','created_at','updated_at','conversation') if k in row}
        public['citations']=json.loads(public['citations']); public['usage']=json.loads(public['usage'])
        public['coverage']=db.one('SELECT unit_id,journey_id,status,covered_items,error FROM cmui_delivery_submissions WHERE run=?',(rid,))
        return public

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

    async def classify_course_task(course_id, bundle):
        """Background template classification for a course. Never overwrites a
        manual selection; a billing-disabled provider records FAILED_RETRYABLE
        instead of pretending to classify. One task per course at a time."""
        job_key=f'classify-{course_id}'
        try:
            existing=db.one('SELECT * FROM cmui_classifications WHERE course=?',(course_id,))
            if existing and existing['source']=='manual':
                return
            db.execute("INSERT INTO cmui_classifications(course,status,template_id,decision,degree_level,confidence,alternatives,reason,evidence_refs,materials_revision,model,source,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,'auto',?,?) ON CONFLICT(course) DO UPDATE SET status='CLASSIFYING',updated_at=excluded.updated_at",
                (course_id,'CLASSIFYING',None,None,None,None,'[]','','[]',bundle.get('materials_revision'),None,now(),now()))
            if cfg.provider_mode=='qwen' and not cfg.allow_billable:
                db.execute("UPDATE cmui_classifications SET status='FAILED_RETRYABLE',reason='未授权模型调用费用',updated_at=? WHERE course=?",(now(),course_id))
                return
            raw=await model.classify_course(bundle)
            result=json.loads(raw)
            validated=social.validate_classification(db,result)
            status='CLASSIFIED' if validated['decision']=='classified' else 'OTHER'
            db.execute("UPDATE cmui_classifications SET status=?,template_id=?,decision=?,degree_level=?,confidence=?,alternatives=?,reason=?,evidence_refs=?,materials_revision=?,model=?,updated_at=? WHERE course=? AND source='auto'",
                (status,validated['template_id'],validated['decision'],validated['degree_level'],
                 validated['confidence'],json.dumps(validated['alternatives'],ensure_ascii=False),
                 validated['reason'],json.dumps(validated['evidence_refs'],ensure_ascii=False),
                 bundle.get('materials_revision'),cfg.qwen_model,now(),course_id))
        except Exception:
            db.execute("UPDATE cmui_classifications SET status='FAILED_RETRYABLE',updated_at=? WHERE course=? AND source='auto'",(now(),course_id))
        finally:
            jobs.pop(job_key,None)

    def schedule_classification(course_id, bundle):
        job_key=f'classify-{course_id}'
        if job_key not in jobs:
            jobs[job_key]=asyncio.create_task(classify_course_task(course_id, bundle))

    # ================================================================ pairs

    @r.get('/pairs')
    async def pair_list(user:User,request:Request,course_id:str,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0)):
        await course(user,course_id,request)
        rows=db.all('SELECT * FROM cmui_pairs WHERE owner=? AND course=? ORDER BY updated_at DESC LIMIT ? OFFSET ?',
            (user['id'],course_id,limit,offset))
        for p in rows:
            p.pop('owner',None)
        return rows

    @r.post('/pairs',status_code=201)
    async def pair_create(data:PairCreate,user:User,request:Request):
        await course(user,data.course,request)
        pid=uid('pair_')
        with db.connect(True) as c:
            c.execute('INSERT INTO cmui_pairs(id,owner,course,teach_conversation,problem_conversation,title,bound_node,created_at,updated_at) VALUES (?,?,?,NULL,NULL,?,NULL,?,?)',
                (pid,user['id'],data.course,'新对话',now(),now()))
        return pair_payload(user,pid)

    def pair_payload(user,pair_id):
        pair=db.one('SELECT * FROM cmui_pairs WHERE id=? AND owner=?',(pair_id,user['id']))
        if not pair: raise HTTPException(404,'双栏会话不存在')
        out={'id':pair['id'],'course':pair['course'],'title':pair['title'],
             'bound_node':pair['bound_node'],'created_at':pair['created_at'],
             'updated_at':pair['updated_at'],'teach':None,'problem':None}
        for key,lane in (('teach','teach'),('problem','problem')):
            conv_id=pair.get(f'{lane}_conversation')
            if conv_id:
                out[key]=db.one('SELECT id,lane,title,created_at,updated_at FROM cmui_conversations WHERE id=?',(conv_id,))
        return out

    @r.get('/pairs/{pair_id}')
    async def pair_get(pair_id:str,user:User,request:Request):
        pair=pair_payload(user,pair_id)
        await course(user,pair['course'],request)
        for key in ('teach','problem'):
            lane=pair[key]
            if lane is None: continue
            conv=conversation(user,lane['id'])
            messages=db.all('SELECT id,role,text,citations,created_at,provenance,exercise FROM cmui_messages WHERE conversation=? ORDER BY created_at,rowid',(conv['id'],))
            accessible=(await remote('file.list',user,{'course':pair['course'],'q':'','folder':None},request)) if domain else file_rows(db,user['id'],pair['course'])
            accessible_ids={x['id'] for x in accessible}
            for m in messages:
                m['steps']=solution_steps(m['text']) if key=='problem' and m['role']=='assistant' else []
                m['citations']=[x for x in json.loads(m['citations']) if x.get('document_id') in accessible_ids]
            pair[key]={'conversation':conv,'messages':messages,
                       'active_run':db.one("SELECT id,status,partial_text,error FROM cmui_runs WHERE conversation=? ORDER BY created_at DESC LIMIT 1",(conv['id'],))}
        return pair

    @r.patch('/pairs/{pair_id}')
    async def pair_rename(pair_id:str,data:Rename,user:User,request:Request):
        pair=pair_payload(user,pair_id)
        await course(user,pair['course'],request)
        db.execute('UPDATE cmui_pairs SET title=?,updated_at=? WHERE id=?',(data.title,now(),pair_id))
        for key in ('teach','problem'):
            lane=pair[key]
            if lane: db.execute('UPDATE cmui_conversations SET title=? WHERE id=?',(data.title,lane['id']))
        return pair_payload(user,pair_id)

    @r.delete('/pairs/{pair_id}')
    async def pair_delete(pair_id:str,user:User,request:Request):
        pair=pair_payload(user,pair_id)
        await course(user,pair['course'],request)
        for key in ('teach','problem'):
            lane=pair[key]
            if not lane: continue
            active=db.one("SELECT id FROM cmui_runs WHERE conversation=? AND status IN ('queued','planning','generating')",(lane['id'],))
            if active: raise HTTPException(409,'请先停止当前生成')
        with db.connect(True) as c:
            for key in ('teach','problem'):
                lane=pair[key]
                if not lane: continue
                c.execute('DELETE FROM cmui_bridges WHERE problem_message IN (SELECT id FROM cmui_messages WHERE conversation=?)',(lane['id'],))
                c.execute('UPDATE cmui_layout SET teach_conversation=NULL WHERE owner=? AND teach_conversation=?',(user['id'],lane['id']))
                c.execute('UPDATE cmui_layout SET problem_conversation=NULL WHERE owner=? AND problem_conversation=?',(user['id'],lane['id']))
                c.execute('DELETE FROM cmui_conversations WHERE id=?',(lane['id'],))
            c.execute('DELETE FROM cmui_pairs WHERE id=?',(pair_id,))
        return {'deleted':True}

    @r.post('/pairs/{pair_id}/bind')
    async def pair_bind(pair_id:str,data:PairBind,user:User,request:Request):
        pair=pair_payload(user,pair_id)
        await course(user,pair['course'],request)
        if data.node is not None and not domain:
            if not db.one('SELECT id FROM cmui_nodes WHERE id=? AND course=?',(data.node,pair['course'])): raise HTTPException(404,'知识点不存在')
        if data.node is None:
            db.execute('UPDATE cmui_pairs SET bound_node=NULL,updated_at=? WHERE id=?',(now(),pair_id))
            return pair_payload(user,pair_id)
        with db.connect(True) as c:
            conflict=c.execute(
                'SELECT id,title FROM cmui_pairs WHERE owner=? AND course=? AND bound_node=? AND id<>?',
                (user['id'],pair['course'],data.node,pair_id)).fetchone()
            if conflict:
                raise HTTPException(409,{'code':'NODE_ALREADY_BOUND',
                    'pair':{'id':conflict['id'],'title':conflict['title']}})
            c.execute('UPDATE cmui_pairs SET bound_node=?,updated_at=? WHERE id=?',
                (data.node,now(),pair_id))
        return pair_payload(user,pair_id)

    # ========================================================= classification

    @r.get('/courses/{cid}/classification')
    async def classification_get(cid:str,user:User,request:Request):
        await course(user,cid,request)
        row=db.one('SELECT * FROM cmui_classifications WHERE course=?',(cid,))
        if not row: return {'status':'WAITING_FOR_MATERIALS','template_id':None,'decision':None,
            'degree_level':None,'confidence':None,'alternatives':[],'reason':'','evidence_refs':[],
            'materials_revision':None,'model':None,'source':'auto','manual_allowed':True}
        row['alternatives']=json.loads(row['alternatives']); row['evidence_refs']=json.loads(row['evidence_refs'])
        row['manual_allowed']=True
        return row

    @r.post('/courses/{cid}/classification')
    async def classification_correct(cid:str,data:ClassificationCorrection,user:User,request:Request):
        """Owner-side manual correction. Never silently overwritten by a later
        automatic job: auto classification only applies while source='auto'."""
        course_data=await course(user,cid,request)
        if course_data.get('owner')!=user['id'] and not is_admin(user):
            raise HTTPException(403,'只有课程所有者可以纠正分类')
        template_id=data.template_id if data.template_id in templates.registry() else 'OTHER'
        decision='classified' if template_id!='OTHER' else 'other'
        db.execute('INSERT INTO cmui_classifications(course,status,template_id,decision,degree_level,confidence,alternatives,reason,evidence_refs,materials_revision,model,source,created_at,updated_at) VALUES (?,?,?,?,NULL,NULL,\'[]\',?,?,NULL,NULL,\'manual\',?,?) ON CONFLICT(course) DO UPDATE SET status=excluded.status,template_id=excluded.template_id,decision=excluded.decision,degree_level=NULL,confidence=NULL,alternatives=\'[]\',reason=excluded.reason,evidence_refs=excluded.evidence_refs,materials_revision=excluded.materials_revision,model=NULL,source=\'manual\',updated_at=excluded.updated_at',
            (cid,'CLASSIFIED' if decision=='classified' else 'OTHER',template_id,decision,
             '手动选择（课程所有者）','[]',now(),now()))
        row=db.one('SELECT * FROM cmui_classifications WHERE course=?',(cid,))
        row['alternatives']=json.loads(row['alternatives']); row['evidence_refs']=json.loads(row['evidence_refs'])
        row['manual_allowed']=True
        return row

    # ====================================================== student verification

    @r.get('/me/verification')
    async def me_verification(user:User):
        return social.verification_status(db,user['id'])

    @r.post('/me/verification/redeem')
    async def me_verification_redeem(data:VerificationRedeem,user:User):
        rate(user,'code-redeem',5)
        result=social.redeem_code(db,cfg,user['id'],data.code,data.request_id)
        if not result['ok']:
            raise HTTPException(400,{'code':result['reason'],'message':'认证码无效或已被使用'})
        return {'verified':True,'reason':result['reason']}

    @r.post('/admin/verification-codes',status_code=201)
    async def admin_issue_codes(data:VerificationIssue,user:User):
        if not is_admin(user): raise HTTPException(403,'仅课程管理员可以发行认证码')
        codes=social.generate_codes(db,cfg,data.count,user['id'])
        return {'issued':len(codes),'codes':codes}

    @r.get('/admin/verification-codes')
    async def admin_list_codes(user:User):
        if not is_admin(user): raise HTTPException(403,'仅课程管理员可以查看认证码状态')
        rows=db.all("SELECT code,status,issued_at,redeemed_at,issued_by FROM cmui_verification_codes ORDER BY issued_at DESC LIMIT 200")
        # Codes are redacted here by policy: status is visible, plaintext never.
        return [{'code':r['code'][:2]+'*****','status':r['status'],'issued_at':r['issued_at'],
                 'redeemed_at':r['redeemed_at']} for r in rows]

    @r.post('/admin/verification-codes/disable')
    async def admin_disable_code(data:VerificationDisable,user:User):
        if not is_admin(user): raise HTTPException(403,'仅课程管理员可以停用认证码')
        db.execute("UPDATE cmui_verification_codes SET status='disabled' WHERE code=? AND status='issued'",(data.code,))
        return {'disabled':True}

    # ================================================================ shares

    @r.post('/shares',status_code=201)
    async def share_create(data:ShareCreate,user:User,request:Request):
        course_data=await course(user,data.course,request)
        course_gate(course_data,user)
        existing=db.one('SELECT * FROM cmui_shares WHERE sender=? AND request_id=?',(user['id'],data.request_id))
        if existing: return {'id':existing['id'],'status':existing['status'],'reused':True}
        recipients=[]
        for rid in set(data.recipients):
            if rid==user['id']: continue
            if not db.one('SELECT id FROM cmui_users WHERE id=?',(rid,)): raise HTTPException(404,'接收者不存在')
            recipients.append(rid)
        if not recipients: raise HTTPException(422,'请选择至少一位接收者')
        files = (await remote('file.list',user,{'course':data.course,'q':'','folder':None},request)) if domain else file_rows(db,user['id'],data.course)
        if data.history_scope=='selected':
            pair_ids=[p for p in set(data.selected_pair_ids) if db.one('SELECT id FROM cmui_pairs WHERE id=? AND owner=? AND course=?',(p,user['id'],data.course))]
        else:
            pair_ids=[]
        pair_payloads=social.snapshot_pair_payload(db,user['id'],data.course,pair_ids) if data.history_scope!='none' else []
        manifest=social.build_share_manifest(db,cfg,user['id'],course_data,files,data.history_scope,pair_payloads)
        sid=uid('share_')
        try:
            copied=social.copy_share_files(db,cfg,sid,[dict(f,course=data.course) for f in files])
        except OSError:
            raise HTTPException(503,'文件快照准备失败，本次共享未完成；不会假装“完整可加入”') from None
        db.execute('INSERT INTO cmui_shares(id,sender,course,snapshot_at,source_course_version,history_scope,selected_pair_ids,manifest_json,status,requires_student_verification,request_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            (sid,user['id'],data.course,now(),str(course_data.get('updated_at','') or ''),data.history_scope,
             json.dumps(pair_ids,ensure_ascii=False),json.dumps(manifest,ensure_ascii=False),'ready',
             1 if manifest['requires_student_verification'] else 0,data.request_id,now()))
        for rid in recipients:
            db.execute('INSERT OR IGNORE INTO cmui_share_recipients(share,recipient,status) VALUES (?,?,\'notified\')',(sid,rid))
            db.execute('INSERT OR IGNORE INTO cmui_notifications(id,owner,actor,kind,ref,course,text,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (uid('notice_'),rid,user['id'],'course_share',sid,data.course,
                 f'{user["name"]} 向你共享课程「{course_data.get("name","")}」（{len(files)} 个文件' + (f'，含历史：{data.history_scope}' if data.history_scope!='none' else '，不含历史') + '）',now()))
        return {'id':sid,'status':'ready','files_copied':copied}

    @r.get('/shares')
    async def share_list(user:User,q:str=Query(default='received',pattern='^(received|sent)$')):
        if q=='sent':
            rows=db.all('SELECT * FROM cmui_shares WHERE sender=? ORDER BY created_at DESC LIMIT 100',(user['id'],))
        else:
            rows=db.all('SELECT s.*,r.status AS recipient_status,r.joined_course_id,r.joined_at FROM cmui_shares s JOIN cmui_share_recipients r ON r.share=s.id WHERE r.recipient=? ORDER BY s.created_at DESC LIMIT 100',(user['id'],))
        out=[]
        for row in rows:
            manifest=json.loads(row['manifest_json'])
            out.append({'id':row['id'],'sender':row['sender'],'sender_name':db.one('SELECT name FROM cmui_users WHERE id=?',(row['sender'],))['name'],
                'course_name':(manifest.get('course') or {}).get('name',''),'snapshot_at':row['snapshot_at'],
                'history_scope':row['history_scope'],'file_count':len(manifest.get('files') or []),
                'status':row['status'],'requires_student_verification':bool(row['requires_student_verification']),
                'recipient_status':row.get('recipient_status'),'joined_course_id':row.get('joined_course_id'),
                'joined_at':row.get('joined_at')})
        return out

    @r.get('/shares/{share_id}')
    async def share_detail(share_id:str,user:User):
        row=db.one('SELECT * FROM cmui_shares WHERE id=?',(share_id,))
        if not row: raise HTTPException(404,'共享不存在')
        recipient=db.one('SELECT * FROM cmui_share_recipients WHERE share=? AND recipient=?',(share_id,user['id']))
        if row['sender']!=user['id'] and not recipient: raise HTTPException(404,'共享不存在')
        manifest=json.loads(row['manifest_json'])
        return {'id':row['id'],'sender':row['sender'],'sender_name':db.one('SELECT name FROM cmui_users WHERE id=?',(row['sender'],))['name'],
            'course_name':(manifest.get('course') or {}).get('name',''),'snapshot_at':row['snapshot_at'],
            'history_scope':row['history_scope'],'files':manifest.get('files') or [],
            'pair_count':len(manifest.get('pairs') or []),'status':row['status'],
            'requires_student_verification':bool(row['requires_student_verification']),
            'recipient_status':recipient['status'] if recipient else None,
            'joined_course_id':recipient['joined_course_id'] if recipient else None}

    @r.post('/shares/{share_id}/join')
    async def share_join(share_id:str,user:User,request:Request):
        row=db.one('SELECT * FROM cmui_shares WHERE id=? AND status=\'ready\'',(share_id,))
        if not row: raise HTTPException(404,'共享不存在或尚未准备完成')
        recipient=db.one('SELECT * FROM cmui_share_recipients WHERE share=? AND recipient=?',(share_id,user['id']))
        if not recipient: raise HTTPException(404,'共享不存在')
        if row['requires_student_verification'] and not verified(user):
            raise HTTPException(403,'该共享来自校园课程：请先在账户中完成学生认证（7 位认证码）')
        joined_row=db.one('SELECT joined_course_id FROM cmui_share_recipients WHERE share=? AND recipient=?',(share_id,user['id']))
        if joined_row and joined_row['joined_course_id']:
            return {'joined_course_id':joined_row['joined_course_id'],'reused':True}
        if domain:
            manifest=json.loads(row['manifest_json'])
            course_meta=manifest.get('course') or {}
            joined=await remote('course.create_shared',user,{
                'share_id':share_id,'name':course_meta.get('name') or '共享课程',
                'description':course_meta.get('description') or '',
                'requires_student_verification':row['requires_student_verification']},request)
            joined_course_id=joined['id']
        else:
            joined_course_id=social.join_share(db,cfg,row,user['id'])['joined_course_id']
        social.record_join(db,row,user['id'],joined_course_id)
        social.import_share_history(db,row,user['id'],joined_course_id)
        return {'joined_course_id':joined_course_id,'reused':False}

    # =============================================================== exercises

    def pick_exercise_node(user,course_id,knowledge):
        """做一题 target selection: bound node first, else the earliest
        NOT_STARTED/LEARNING atomic node in tree order, else review of the
        first node. Never invents nodes."""
        pair_row=db.one('SELECT bound_node FROM cmui_pairs WHERE owner=? AND course=? AND bound_node IS NOT NULL ORDER BY updated_at DESC LIMIT 1',(user['id'],course_id))
        if pair_row: return pair_row['bound_node'],'当前绑定知识点'
        nodes=knowledge if isinstance(knowledge,list) else []
        for n in nodes:
            if n.get('kind')=='ATOMIC' and n.get('progress') in ('NOT_STARTED','LEARNING'):
                return n['id'],n.get('title','')
        for n in nodes:
            if n.get('kind')=='ATOMIC':
                return n['id'],'复习：'+n.get('title','')
        return None,''

    async def generate_exercise_run(run_id,user,course_data,pair,node,node_title,sources):
        visible=''; full=''; usages=[]; marker='【标准答案】'; marker_seen=False
        try:
            heartbeat(run_id)
            async for item in model.generate_exercise(course_data,node,{k:user[k] for k in ['language','timezone','bio']},sources,target_label=node_title):
                state=db.one('SELECT status FROM cmui_runs WHERE id=?',(run_id,))
                if state and state['status'] in TERMINAL: raise asyncio.CancelledError()
                kind=item['kind']
                if kind=='status':
                    db.execute('UPDATE cmui_runs SET status=?,updated_at=? WHERE id=?',(item['status'],now(),run_id))
                    event(run_id,'status',item)
                elif kind=='delta':
                    full+=item['text']
                    if not marker_seen:
                        if marker in full:
                            before,after=full.split(marker,1)
                            full=before+marker+after
                            tail=item['text']
                            cut=tail.find(marker)
                            piece=tail[:cut] if cut>=0 else tail
                            marker_seen=True
                            if piece:
                                visible+=piece
                                db.execute('UPDATE cmui_runs SET partial_text=?,updated_at=? WHERE id=?',(visible,now(),run_id))
                                event(run_id,'delta',{'text':piece})
                            continue
                        visible+=item['text']
                        db.execute('UPDATE cmui_runs SET partial_text=?,updated_at=? WHERE id=?',(visible,now(),run_id))
                        event(run_id,'delta',{'text':item['text']})
                elif kind=='usage':
                    usages.append(item)
                    db.execute('UPDATE cmui_runs SET usage=? WHERE id=?',(json.dumps(usages),run_id))
                elif kind=='complete':
                    full=item['text']
            if not visible.strip(): raise ProviderError('EMPTY_EXERCISE')
            question_text=full.split(marker,1)[0].strip() if marker in full else full.strip()
            answer_text=full.split(marker,1)[1].strip() if marker in full else ''
            steps=answer_steps_parse(answer_text)
            exercise_id=uid('exercise_')
            with db.connect(True) as c:
                claimed=c.execute("UPDATE cmui_runs SET status='completed',usage=?,updated_at=? WHERE id=? AND status IN ('queued','planning','generating')",(json.dumps(usages),now(),run_id)).rowcount
                if claimed!=1: raise asyncio.CancelledError()
                c.execute('INSERT INTO cmui_exercises(id,owner,course,pair,node,target_node,question,answer_steps,references_json,verification_status,generation_version,run,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (exercise_id,user['id'],course_data['id'],pair['id'],(node or {}).get('id') if isinstance(node,dict) else node,
                     node_title,question_text,json.dumps(steps,ensure_ascii=False),'[]','unverified','V1',run_id,now()))
                message_id=uid('message_')
                conv_id=pair['problem_conversation']
                if not conv_id:
                    conv_id=social._lane_conversation(db,pair['id'],user['id'],course_data['id'],'problem',{'title':pair['title']})
                    db.execute('UPDATE cmui_pairs SET problem_conversation=? WHERE id=?',(conv_id,pair['id']))
                c.execute('INSERT INTO cmui_messages(id,conversation,role,text,citations,run,created_at,provenance,exercise) VALUES (?,?,?,?,?,?,?,?,?)',
                    (message_id,conv_id,'assistant',question_text,'[]',run_id,now(),'',exercise_id))
                c.execute('UPDATE cmui_pairs SET updated_at=? WHERE id=?',(now(),pair['id']))
            event(run_id,'done',{'message_id':message_id,'exercise_id':exercise_id,'step_count':len(steps),'provider_mode':cfg.provider_mode})
        except asyncio.CancelledError:
            db.execute("UPDATE cmui_runs SET status='cancelled',error=CASE WHEN status IN ('queued','planning','generating') THEN 'CANCELLED' ELSE error END,updated_at=? WHERE id=? AND status NOT IN ('completed','failed')",(now(),run_id))
            event(run_id,'error',{'code':'CANCELLED','message':'已停止'})
        except Exception as error:
            code=str(error) if isinstance(error,ProviderError) else 'GENERATION_FAILED'
            db.execute("UPDATE cmui_runs SET status='failed',error=?,usage=?,updated_at=? WHERE id=? AND status NOT IN ('completed','cancelled')",(code,json.dumps(usages),now(),run_id))
            event(run_id,'error',{'code':code,'message':'出题未完成；不会自动重试或重复扣费。'})
        finally: jobs.pop(run_id,None)

    @r.post('/courses/{cid}/exercises',status_code=202)
    async def exercise_create(cid:str,data:ExerciseCreate,user:User,request:Request):
        course_data=await course(user,cid,request)
        course_gate(course_data,user)
        old=db.one('SELECT * FROM cmui_runs WHERE owner=? AND request_id=?',(user['id'],data.request_id))
        if old: return {'id':old['id'],'status':old['status'],'reused':True}
        rate(user,'model-runs',8)
        if cfg.provider_mode=='disabled' and provider is None: raise HTTPException(503,'模型尚未配置')
        if cfg.provider_mode=='qwen' and not cfg.allow_billable: raise HTTPException(402,'尚未授权模型调用费用')
        pair=pair_for_course_open(user,cid)
        if pair is None: raise HTTPException(409,'请先在该课程建立对话')
        if data.node and not domain:
            if not db.one('SELECT id FROM cmui_nodes WHERE id=? AND course=?',(data.node,cid)): raise HTTPException(404,'知识点不存在')
        knowledge=(await remote('knowledge.tree',user,{'course':cid},request)) if domain else db.all("SELECT n.*,COALESCE(l.progress,'NOT_STARTED') progress FROM cmui_nodes n LEFT JOIN cmui_learning l ON l.node=n.id AND l.owner=? WHERE n.course=? ORDER BY n.position",(user['id'],cid))
        node_id,node_title=pick_exercise_node(user,cid,knowledge)
        if data.node:
            node_id=data.node; node_title='指定知识点'
        node={'id':node_id,'title':node_title} if node_id else None
        sources=(await remote('context.retrieve',user,{'course':cid,'query':node_title or '课程知识点','history':[]},request)) if domain else context_for(db,user['id'],cid,node_title or '课程知识点',[])
        rid=uid('run_')
        conv_id=pair['problem_conversation']
        if not conv_id:
            conv_id=social._lane_conversation(db,pair['id'],user['id'],cid,'problem',{'title':pair['title']})
            db.execute('UPDATE cmui_pairs SET problem_conversation=? WHERE id=?',(conv_id,pair['id']))
            pair=db.one('SELECT * FROM cmui_pairs WHERE id=?',(pair['id'],))
        with db.connect(True) as c:
            c.execute('INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,teaching_mode,lease_worker,lease_heartbeat,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (rid,user['id'],conv_id,data.request_id,'queued','做一题','normal',worker_id,str(time.time()),now(),now()))
        event(rid,'status',{'status':'queued','label':'正在思考中'})
        task=asyncio.create_task(generate_exercise_run(rid,user,course_data,pair,node,node_title,sources))
        jobs[rid]=task
        return {'id':rid,'status':'queued'}

    def pair_for_course_open(user,course_id):
        """The user's most recent open pair for the course (layout-first)."""
        layout=db.one('SELECT * FROM cmui_layout WHERE owner=? AND course=?',(user['id'],course_id))
        if layout:
            conv_id=layout['problem_conversation'] or layout['teach_conversation']
            if conv_id:
                p=pair_for_conversation(user,conv_id)
                if p: return p
        return db.one('SELECT * FROM cmui_pairs WHERE owner=? AND course=? ORDER BY updated_at DESC LIMIT 1',(user['id'],course_id))

    @r.get('/exercises/{exercise_id}')
    async def exercise_get(exercise_id:str,user:User,request:Request):
        row=db.one('SELECT * FROM cmui_exercises WHERE id=? AND owner=?',(exercise_id,user['id']))
        if not row: raise HTTPException(404,'题目不存在')
        course_data=await course(user,row['course'],request)
        course_gate(course_data,user)
        revealed=bool(db.one('SELECT revealed_at FROM cmui_answer_reveals WHERE owner=? AND exercise=?',(user['id'],exercise_id)))
        return {'id':row['id'],'course':row['course'],'node':row['node'],'target_node':row['target_node'],
            'question':row['question'],'revealed':revealed,'verification_status':row['verification_status'],
            'generation_version':row['generation_version'],'created_at':row['created_at'],
            'steps':json.loads(row['answer_steps']) if revealed else []}

    @r.post('/exercises/{exercise_id}/reveal')
    async def exercise_reveal(exercise_id:str,user:User,request:Request):
        row=db.one('SELECT * FROM cmui_exercises WHERE id=? AND owner=?',(exercise_id,user['id']))
        if not row: raise HTTPException(404,'题目不存在')
        course_data=await course(user,row['course'],request)
        course_gate(course_data,user)
        db.execute('INSERT OR IGNORE INTO cmui_answer_reveals(owner,exercise,revealed_at) VALUES (?,?,?)',(user['id'],exercise_id,now()))
        steps=json.loads(row['answer_steps'])
        return {'id':row['id'],'revealed':True,'steps':steps,'verification_status':row['verification_status']}

    # =========================================================== explanations

    async def generate_explanation_run(run_id,user,explanation,row,question_text,answer_context,step_text,course_data,sources):
        output=''; usages=[]
        try:
            heartbeat(run_id)
            async for item in model.generate_explanation(course_data,question_text,answer_context,step_text,{k:user[k] for k in ['language','timezone','bio']},sources):
                state=db.one('SELECT status FROM cmui_runs WHERE id=?',(run_id,))
                if state and state['status'] in TERMINAL: raise asyncio.CancelledError()
                kind=item['kind']
                if kind=='status':
                    db.execute('UPDATE cmui_runs SET status=?,updated_at=? WHERE id=?',(item['status'],now(),run_id))
                    event(run_id,'status',item)
                elif kind=='delta':
                    output+=item['text']
                    db.execute('UPDATE cmui_runs SET partial_text=?,updated_at=? WHERE id=?',(output,now(),run_id))
                    event(run_id,'delta',{'text':item['text']})
                elif kind=='usage':
                    usages.append(item)
                    db.execute('UPDATE cmui_runs SET usage=? WHERE id=?',(json.dumps(usages),run_id))
            if not output.strip(): raise ProviderError('EMPTY_EXPLANATION')
            with db.connect(True) as c:
                claimed=c.execute("UPDATE cmui_runs SET status='completed',usage=?,updated_at=? WHERE id=? AND status IN ('queued','planning','generating')",(json.dumps(usages),now(),run_id)).rowcount
                if claimed!=1: raise asyncio.CancelledError()
                c.execute("UPDATE cmui_step_explanations SET text=?,status='completed',updated_at=? WHERE id=?",(output,now(),explanation))
                c.execute('INSERT INTO cmui_explanation_messages(id,explanation,role,text,run,created_at) VALUES (?,?,?,?,?,?)',(uid('message_'),explanation,'assistant',output,run_id,now()))
            event(run_id,'done',{'explanation_id':explanation,'provider_mode':cfg.provider_mode})
        except asyncio.CancelledError:
            db.execute("UPDATE cmui_runs SET status='cancelled',error=CASE WHEN status IN ('queued','planning','generating') THEN 'CANCELLED' ELSE error END,updated_at=? WHERE id=? AND status NOT IN ('completed','failed')",(now(),run_id))
            event(run_id,'error',{'code':'CANCELLED','message':'已停止'})
        except Exception as error:
            code=str(error) if isinstance(error,ProviderError) else 'GENERATION_FAILED'
            db.execute("UPDATE cmui_runs SET status='failed',error=?,usage=?,updated_at=? WHERE id=? AND status NOT IN ('completed','cancelled')",(code,json.dumps(usages),now(),run_id))
            db.execute("UPDATE cmui_step_explanations SET status='failed',updated_at=? WHERE id=?",(now(),explanation))
            event(run_id,'error',{'code':code,'message':'详解生成未完成；不会自动重试或重复扣费。'})
        finally: jobs.pop(run_id,None)

    @r.post('/exercises/{exercise_id}/steps/{step_id}/explanation',status_code=202)
    async def explanation_create(exercise_id:str,step_id:str,data:ExplanationCreate,user:User,request:Request):
        row=db.one('SELECT * FROM cmui_exercises WHERE id=? AND owner=?',(exercise_id,user['id']))
        if not row: raise HTTPException(404,'题目不存在')
        course_data=await course(user,row['course'],request)
        course_gate(course_data,user)
        steps=json.loads(row['answer_steps'])
        step=next((s for s in steps if s['step_id']==step_id),None)
        if not step: raise HTTPException(404,'该步骤不存在')
        existing=db.one("SELECT * FROM cmui_step_explanations WHERE owner=? AND exercise=? AND step_id=? AND answer_version=?",(user['id'],exercise_id,step_id,row['generation_version']))
        if existing and existing['status']=='completed' and existing['text']:
            return {'id':existing['id'],'status':'completed','reused':True}
        old=db.one('SELECT * FROM cmui_runs WHERE owner=? AND request_id=?',(user['id'],data.request_id))
        if old: return {'id':old['id'],'status':old['status'],'reused':True}
        rate(user,'model-runs',8)
        if cfg.provider_mode=='disabled' and provider is None: raise HTTPException(503,'模型尚未配置')
        if cfg.provider_mode=='qwen' and not cfg.allow_billable: raise HTTPException(402,'尚未授权模型调用费用')
        if existing is None:
            eid=uid('explanation_')
            db.execute('INSERT INTO cmui_step_explanations(id,owner,exercise,step_id,answer_version,question,text,run,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,\'generating\',?,?)',
                (eid,user['id'],exercise_id,step_id,row['generation_version'],step['title'],None,None,now(),now()))
        else:
            eid=existing['id']
        conv_id=db.one('SELECT conversation FROM cmui_step_explanations WHERE id=?',(eid,))['conversation']
        if not conv_id:
            # A hidden conversation carries the explanation's run rows without
            # ever appearing in the pair history list.
            conv_id=uid('conv_')
            db.execute('INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at,hidden) VALUES (?,?,?,?,?,?,?,1)',
                (conv_id,user['id'],row['course'],'problem','详解：'+step['title'][:40],now(),now()))
            db.execute('UPDATE cmui_step_explanations SET conversation=? WHERE id=?',(conv_id,eid))
        answer_context='\n\n'.join(s['text'] for s in steps)
        sources=(await remote('context.retrieve',user,{'course':row['course'],'query':step['text'][:400],'history':[]},request)) if domain else context_for(db,user['id'],row['course'],step['text'][:400],[])
        rid=uid('run_')
        with db.connect(True) as c:
            c.execute('INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,teaching_mode,lease_worker,lease_heartbeat,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (rid,user['id'],conv_id,data.request_id,'queued',step['title'],'normal',worker_id,str(time.time()),now(),now()))
            c.execute('UPDATE cmui_step_explanations SET run=?,status=\'generating\',updated_at=? WHERE id=?',(rid,now(),eid))
        event(rid,'status',{'status':'queued','label':'正在思考中'})
        task=asyncio.create_task(generate_explanation_run(rid,user,eid,row,row['question'],answer_context,step['text'],course_data,sources))
        jobs[rid]=task
        return {'id':eid,'run':rid,'status':'generating'}

    @r.get('/explanations/{explanation_id}')
    async def explanation_get(explanation_id:str,user:User,request:Request):
        row=db.one('SELECT * FROM cmui_step_explanations WHERE id=? AND owner=?',(explanation_id,user['id']))
        if not row: raise HTTPException(404,'详解不存在')
        exercise=db.one('SELECT course,question,generation_version FROM cmui_exercises WHERE id=?',(row['exercise'],))
        course_data=await course(user,exercise['course'],request)
        course_gate(course_data,user)
        messages=db.all('SELECT id,role,text,created_at FROM cmui_explanation_messages WHERE explanation=? ORDER BY created_at,rowid',(explanation_id,))
        return {'id':row['id'],'exercise':row['exercise'],'step_id':row['step_id'],
            'answer_version':row['answer_version'],'status':row['status'],'text':row['text'],
            'messages':messages,'run':row['run']}

    @r.post('/explanations/{explanation_id}/messages',status_code=202)
    async def explanation_followup(explanation_id:str,data:ExplanationMessage,user:User,request:Request):
        row=db.one('SELECT * FROM cmui_step_explanations WHERE id=? AND owner=?',(explanation_id,user['id']))
        if not row or row['status']!='completed': raise HTTPException(404,'详解尚未完成，不能追问')
        exercise=db.one('SELECT * FROM cmui_exercises WHERE id=?',(row['exercise'],))
        course_data=await course(user,exercise['course'],request)
        course_gate(course_data,user)
        rate(user,'model-runs',8)
        if cfg.provider_mode=='disabled' and provider is None: raise HTTPException(503,'模型尚未配置')
        if cfg.provider_mode=='qwen' and not cfg.allow_billable: raise HTTPException(402,'尚未授权模型调用费用')
        db.execute('INSERT INTO cmui_explanation_messages(id,explanation,role,text,run,created_at) VALUES (?,?,?,?,?,?)',(uid('message_'),explanation_id,'user',data.text,None,now()))
        prior='\n\n'.join(m['text'] for m in db.all('SELECT text FROM cmui_explanation_messages WHERE explanation=? ORDER BY created_at,rowid',(explanation_id,)))
        sources=(await remote('context.retrieve',user,{'course':exercise['course'],'query':data.text,'history':[]},request)) if domain else context_for(db,user['id'],exercise['course'],data.text,[])
        conv_id=row['conversation']
        rid=uid('run_')
        with db.connect(True) as c:
            c.execute('INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,teaching_mode,lease_worker,lease_heartbeat,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (rid,user['id'],conv_id,data.request_id,'queued',data.text,'normal',worker_id,str(time.time()),now(),now()))
        event(rid,'status',{'status':'queued','label':'正在思考中'})
        task=asyncio.create_task(generate_explanation_run(rid,user,explanation_id,row,exercise['question'],prior,data.text,course_data,sources))
        jobs[rid]=task
        return {'run':rid,'status':'generating'}

    @r.post('/explanations/{explanation_id}/cancel')
    async def explanation_cancel(explanation_id:str,user:User):
        row=db.one('SELECT * FROM cmui_step_explanations WHERE id=? AND owner=?',(explanation_id,user['id']))
        if not row or not row['run']: raise HTTPException(404)
        db.execute("UPDATE cmui_runs SET status='cancelled',error='CANCELLED',updated_at=? WHERE id=? AND status IN ('queued','planning','generating')",(now(),row['run']))
        task=jobs.get(row['run'])
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
