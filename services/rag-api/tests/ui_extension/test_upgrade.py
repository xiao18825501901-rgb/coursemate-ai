import asyncio
import base64
import io
import json
import time

import httpx
import pytest
from PIL import Image
from app.cm_update.app import create_app
from app.cm_update.db import Database
from app.cm_update.steps import solution_steps
from app.cm_update.provider import QwenProvider, ProviderError
from app.cm_update.sse import events
from conftest import P, login
from test_provider import cfg, chat


def finish(client,run_id):
    for _ in range(100):
        row=client.get(P+'/runs/'+run_id).json()
        if row['status'] in {'completed','failed','cancelled'}: return row
        time.sleep(.01)
    raise AssertionError('run timeout')


def test_private_course_edit_delete_and_task_retention(client,env):
    course=client.post(P+'/courses',json={'name':'Private Physics','code':'MYPHY'}).json()
    cid=course['id']
    f=client.post(P+f'/courses/{cid}/files',files={'file':('note.md',b'# Private note\nOnly owner','text/plain')}).json()
    task=client.post(P+'/tasks',json={'title':'Review physics','due_at':'2026-09-20T14:00:00+08:00','course':cid,'request_id':'task-retain-001'}).json()
    client.post(P+f'/courses/{cid}/comments',json={'text':'Discussion','request_id':'comment-001'})
    c=client.post(P+'/conversations',json={'course':cid,'lane':'teach'}).json()
    run=client.post(P+f"/conversations/{c['id']}/runs",json={'text':'Explain physics','request_id':'learn-delete-001'}).json()
    assert finish(client,run['id'])['status']=='completed'
    login(client,'bob')
    assert client.patch(P+f'/courses/{cid}',json={'name':'Stolen'}).status_code==404
    assert client.delete(P+f'/courses/{cid}',params={'confirm':'Private Physics'}).status_code==404
    login(client,'alice')
    assert client.patch(P+f'/courses/{cid}',json={'name':'My Physics','requirements':'中文教我'}).status_code==200
    assert client.delete(P+f'/courses/{cid}',params={'confirm':'wrong'}).status_code==422
    assert client.delete(P+f'/courses/{cid}',params={'confirm':'My Physics'}).json()['deleted']
    assert client.get(P+f'/courses/{cid}').status_code==404
    assert client.get(P+f"/conversations/{c['id']}").status_code==404
    assert client.get(P+'/tasks').json()[0]['course'] is None
    db=env[0].state.db
    assert db.all('PRAGMA foreign_key_check')==[]
    assert db.one('SELECT * FROM cmui_files WHERE id=?',(f['id'],)) is None


def test_official_course_cannot_edit_or_delete(client):
    assert client.patch(P+'/courses/cs3481',json={'name':'hijack'}).status_code==403
    name=client.get(P+'/courses/cs3481').json()['name']
    assert client.delete(P+'/courses/cs3481',params={'confirm':name}).status_code==403


def test_durable_agent_receipts_scoped_conflict_freeze_and_restart(client,env):
    data={'request_id':'plan-new-001','text':'tomorrow review','timezone':'Asia/Hong_Kong'}
    a=client.post(P+'/agent-receipts/claim',json=data).json()
    assert not a['reused'] and a['lease']
    assert client.post(P+'/agent-receipts/claim',json=data).status_code==409
    assert client.put(P+'/agent-receipts/plan-new-001',json={'lease':'x'*32,'status':'completed','result':{}}).status_code==404
    final={'lease':a['lease'],'status':'completed','result':{'text':'arranged'}}
    assert client.put(P+'/agent-receipts/plan-new-001',json=final).status_code==200
    assert client.put(P+'/agent-receipts/plan-new-001',json=final).json()['reused']
    assert client.put(P+'/agent-receipts/plan-new-001',json=dict(final,result={'text':'changed'})).status_code==409
    assert client.post(P+'/agent-receipts/claim',json=dict(data,text='different')).status_code==409
    assert client.post(P+'/agent-receipts/claim',json=data).json()['result']=={'text':'arranged'}
    login(client,'bob')
    assert client.post(P+'/agent-receipts/claim',json=data).json()['reused'] is False
    login(client,'alice')
    db=Database(env[3].data_dir/'ui.sqlite3');db.initialize();db.initialize()
    owner=client.get(P+'/me').json()['id']
    assert db.one('SELECT status FROM cmui_agent_receipts WHERE owner=? AND request_id=?',(owner,'plan-new-001'))['status']=='completed'
    assert db.one("SELECT value FROM cmui_meta WHERE key='schema_version'")['value']=='2'
    assert db.all('PRAGMA foreign_key_check')==[]


def test_step_locator_is_server_derived_not_fake(client):
    c=client.post(P+'/conversations',json={'course':'cs3481','lane':'problem'}).json()
    r=client.post(P+f"/conversations/{c['id']}/runs",json={'text':'Solve Question 2','request_id':'steps-verify-001'}).json()
    assert finish(client,r['id'])['status']=='completed'
    m=client.get(P+f"/conversations/{c['id']}").json()['messages'][-1]
    assert [s['number'] for s in m['steps']]==[1,2]
    assert client.post(P+'/courses/cs3481/bridges',json={'problem_message':m['id'],'step':99,'question':'fake step'}).status_code==422
    ok=client.post(P+'/courses/cs3481/bridges',json={'problem_message':m['id'],'step':2,'question':'why'});assert ok.status_code==201
    assert client.post(P+'/courses/cs3481/bridges',json={'problem_message':m['id'],'step':2,'question':'why'}).json()['id']==ok.json()['id']


def test_steps_ignore_fenced_code_and_duplicate_numbers():
    text='## Step 3 概率\n```\nStep 4 fake\n```\n## 第 5 步 计算\n## Step 3 repeat'
    steps=solution_steps(text)
    assert [s['number'] for s in steps]==[3,5]
    assert steps==solution_steps(text)


def test_text_attachment_persists_and_changes_idempotent_signature(client):
    f=client.post(P+'/courses/cs3481/files',files={'file':('myq.md',b'# Question 91\nFind 8 plus 4.','text/markdown')}).json()
    c=client.post(P+'/conversations',json={'course':'cs3481','lane':'problem'}).json()
    data={'text':'Please solve the selected file','request_id':'attachment-req-001','attachment_ids':[f['id']]}
    run=client.post(P+f"/conversations/{c['id']}/runs",json=data).json();finish(client,run['id'])
    m=client.get(P+f"/conversations/{c['id']}").json()['messages'][0]
    assert m['attachments'][0]['id']==f['id']
    assert client.post(P+f"/conversations/{c['id']}/runs",json=dict(data,attachment_ids=[])).status_code==409
    assert client.post(P+f"/conversations/{c['id']}/runs",json=data).json()['reused']


def test_other_user_attachment_never_reaches_model(client,env):
    f=client.post(P+'/courses/cs3481/files',files={'file':('private.md',b'SECRET private question','text/markdown')}).json()
    login(client,'bob');c=client.post(P+'/conversations',json={'course':'cs3481','lane':'problem'}).json()
    n=len(env[2].calls)
    assert client.post(P+f"/conversations/{c['id']}/runs",json={'text':'read','request_id':'steal-files-001','attachment_ids':[f['id']]}).status_code==404
    assert len(env[2].calls)==n


@pytest.mark.parametrize('protocol',['chat_completions','responses'])
@pytest.mark.asyncio
async def test_image_two_phase_actual_transport_contract(protocol):
    img=io.BytesIO();Image.new('RGB',(4,4),'white').save(img,format='PNG')
    image={'id':'img1','data_url':'data:image/png;base64,'+base64.b64encode(img.getvalue()).decode()}
    bodies=[]
    def transport(req):
        data=json.loads(req.content);bodies.append(data)
        txt='请根据所给图片用中文讲解，保留英文术语，给出逐步计算与完整参考答案。' if len(bodies)==1 else '## Step 1 读取图片\n这是传输测试，不是视觉模型验证。'
        if protocol=='responses':
            return httpx.Response(200,text='data: '+json.dumps({'type':'response.output_text.delta','delta':txt})+'\n\ndata: '+json.dumps({'type':'response.completed','response':{'status':'completed','usage':{}}})+'\n\n')
        return httpx.Response(200,text=chat(txt))
    p=QwenProvider(cfg(qwen_protocol=protocol),httpx.MockTransport(transport))
    items=[x async for x in p.generate({'name':'x','code':'x'},'图片题',{},[],[],'problem',attachments=[image])]
    assert len(bodies)==2
    for body in bodies:
        parts=body['input' if protocol=='responses' else 'messages'][-1]['content']
        assert parts[-1]['type']==('input_image' if protocol=='responses' else 'image_url')
    assert any(x['kind']=='delta' for x in items)


@pytest.mark.asyncio
async def test_sse_multiline_comments_bom_and_incomplete_event():
    async def lines():
        for x in ['\ufeff:event heartbeat','event: content','data: {','data: "ok":true','data: }','','data: ignored-no-blank']:
            yield x
    actual=[x async for x in events(lines())]
    assert len(actual)==1 and json.loads(actual[0][1])=={'ok':True}


@pytest.mark.asyncio
async def test_done_sentinel_without_finish_reason_is_not_success():
    def mock(r):return httpx.Response(200,text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\ndata: [DONE]\n\n')
    with pytest.raises(ProviderError,match='DISCONNECTED'):
        async for _ in QwenProvider(cfg(),httpx.MockTransport(mock)).stream([],512):pass


@pytest.mark.asyncio
async def test_remote_error_event_never_leaks_raw_message():
    def mock(r):return httpx.Response(200,text='data: {"error":{"message":"api-key-secret"}}\n\n')
    with pytest.raises(ProviderError) as e:
        async for _ in QwenProvider(cfg(),httpx.MockTransport(mock)).stream([],512):pass
    assert 'api-key-secret' not in str(e.value)

def test_host_mount_preserves_host_lifespan_and_endpoints(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from contextlib import asynccontextmanager
    from app.cm_update.config import Settings
    from app.cm_update.integration import install_ui_extension
    from pathlib import Path
    seen=[]
    @asynccontextmanager
    async def lifespan(app):
        seen.append('started');yield;seen.append('stopped')
    host=FastAPI(lifespan=lifespan)
    @host.get('/existing-v3')
    async def original():return {'old':'retained'}
    class Domain:
        async def call(self,operation,subject,payload,credential=''):
            assert subject=='verified-clerk-user'
            if operation=='course.list':return []
            raise AssertionError(operation)
    async def identity(request):return 'verified-clerk-user'
    settings=Settings(data_dir=tmp_path/'ext',environment='test',auth_mode='injected',integration_mode='integrated',web_dir=Path('/not-serving-preview'))
    install_ui_extension(host,settings,Domain(),identity)
    with TestClient(host) as c:
        assert c.get('/existing-v3').json()=={'old':'retained'}
        assert c.get('/ui-extension/api/ui/v1/me').json()['id']=='verified-clerk-user'
        assert c.get('/ui-extension/api/ui/v1/courses').json()==[]
        assert seen==['started']
    assert seen==['started','stopped']


def test_actual_image_attachment_reaches_both_phase_provider_arguments(client,env):
    class ImageAware:
        def __init__(self):self.received=[]
        async def generate(self,*args,attachments=None,**kwargs):
            self.received.append(attachments)
            yield {'kind':'prompt','text':'只用图片和上下文生成的测试 Prompt，没有真实模型调用。'}
            yield {'kind':'delta','text':'## Step 1\n图像输入传输测试'}
    # The original app closes over model; create an isolated app with this explicit test provider.
    from fastapi.testclient import TestClient
    p=ImageAware();app=create_app(env[3],provider=p)
    with TestClient(app) as c:
        login(c,'alice');bio=io.BytesIO();Image.new('RGB',(8,8),'white').save(bio,format='PNG')
        f=c.post(P+'/courses/cs3481/files',files={'file':('question.png',bio.getvalue(),'image/png')}).json()
        conv=c.post(P+'/conversations',json={'course':'cs3481','lane':'problem'}).json()
        result=c.post(P+f"/conversations/{conv['id']}/runs",json={'text':'读取这张图片','request_id':'img-e2e-local','attachment_ids':[f['id']]}).json()
        run=finish(c,result['id']);assert run['status']=='completed'
        assert p.received[0][0]['data_url'].startswith('data:image/png;base64,')
        assert 'base64,' not in json.dumps(run)
        assert 'base64,' not in json.dumps(app.state.db.all('SELECT * FROM cmui_run_inputs'))


def test_task_request_replay_checks_course_not_just_title_and_time(client):
    task={'title':'review','due_at':'2026-09-18T13:00:00+08:00','request_id':'same-task-with-course','course':'cs3481'}
    assert client.post(P+'/tasks',json=task).status_code==201
    assert client.post(P+'/tasks',json=dict(task,course='ge2324')).status_code==409


@pytest.mark.parametrize('status',['incomplete','failed','cancelled'])
@pytest.mark.asyncio
async def test_responses_terminal_status_must_be_completed(status):
    def mock(r):return httpx.Response(200,text='data: '+json.dumps({'type':'response.completed','response':{'status':status}})+'\n\n')
    with pytest.raises(ProviderError,match='INCOMPLETE'):
        async for _ in QwenProvider(cfg(qwen_protocol='responses'),httpx.MockTransport(mock)).stream([],512):pass

def test_ui_schema_never_downgrades_newer_database(tmp_path):
    db=Database(tmp_path/'test.sqlite3');db.initialize()
    db.execute("UPDATE cmui_meta SET value='999' WHERE key='schema_version'")
    with pytest.raises(ValueError,match='Newer'):db.initialize()
    assert db.one("SELECT value FROM cmui_meta WHERE key='schema_version'")['value']=='999'
