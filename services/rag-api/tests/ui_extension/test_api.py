import json,time,sqlite3
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.cm_update.app import create_app
from app.cm_update.config import Settings
from app.cm_update.db import Database
from app.cm_update.seed import seed
from tests.ui_extension.conftest import P,login,ContractProvider

def k():return uuid4().hex
def create(c,name='私人机器学习'):
 r=c.post(P+'/courses',json={'name':name,'code':'ML101'});assert r.status_code==201,r.text;return r.json()
def upload(c,cid='cs3481',name='notes.md',text='DBSCAN core point 核心点由邻域与 MinPts 定义。'):
 r=c.post(P+f'/courses/{cid}/files',files={'file':(name,text.encode(),'text/markdown')});assert r.status_code==201,r.text;return r.json()
def convo(c,lane='teach',course='cs3481'):
 r=c.post(P+'/conversations',json={'course':course,'lane':lane});assert r.status_code==201,r.text;return r.json()
def run(c,conv,text='解释 DBSCAN',**kwargs):
 request={'text':text,'request_id':k(),**kwargs};r=c.post(P+f'/conversations/{conv}/runs',json=request);assert r.status_code==202,r.text
 rid=r.json()['id'];sse=c.get(P+f'/runs/{rid}/events');assert sse.status_code==200
 return rid,c.get(P+f'/runs/{rid}').json(),sse.text,request

def test_auth_required(env):assert env[1].get(P+'/courses').status_code==401

def test_two_defaults_but_initial_dashboard_empty(client):
 rows=client.get(P+'/courses').json();assert {r['id'] for r in rows}=={'cs3481','ge2324'};assert not any(r['pinned'] for r in rows)

def test_pin_persists_relogin_and_is_per_user(client):
 assert client.put(P+'/courses/cs3481/pin').status_code==200
 login(client,'bob');assert not any(c['pinned'] for c in client.get(P+'/courses').json())
 login(client,'alice');assert client.get(P+'/courses').json()[0]['pinned']
 client.delete(P+'/courses/cs3481/pin');assert client.get(P+'/courses/cs3481').status_code==200

def test_private_course_autopin_invisible_and_all_routes_guarded(client):
 cid=create(client)['id'];assert next(x for x in client.get(P+'/courses').json() if x['id']==cid)['pinned']
 login(client,'bob')
 assert cid not in [x['id'] for x in client.get(P+'/courses').json()]
 for suffix in ['', '/files','/comments','/knowledge','/layout']:assert client.get(P+'/courses/'+cid+suffix).status_code==404
 assert client.put(P+'/courses/'+cid+'/pin').status_code==404

def test_upload_metadata_is_private_and_no_storage_key(client):
 f=upload(client);assert f['scope']=='private';assert 'storage_key' not in f;assert 'owner' not in f;assert f['status']=='indexed'
 assert any(x['id']==f['id'] for x in client.get(P+'/courses/cs3481/files?q=notes').json())
 login(client,'bob');assert f['id'] not in [x['id'] for x in client.get(P+'/courses/cs3481/files').json()]
 for suffix in ['/content','/text']:assert client.get(P+f"/courses/cs3481/files/{f['id']}"+suffix).status_code==404
 assert client.delete(P+f"/courses/cs3481/files/{f['id']}").status_code==404

def test_upload_dedup(client):
 a=upload(client);b=upload(client);assert a['id']==b['id'];assert b['duplicate']

def test_download_preview_and_range(client):
 f=client.get(P+'/courses/cs3481/files').json()[0];url=P+f"/courses/cs3481/files/{f['id']}/content"
 r=client.get(url);assert r.content.startswith(b'%PDF');assert 'inline' in r.headers['content-disposition']
 r=client.get(url+'?download=true');assert 'attachment' in r.headers['content-disposition']
 r=client.get(url,headers={'Range':'bytes=0-9'});assert r.status_code==206;assert len(r.content)==10
 assert client.head(url).content==b''
 assert 'private' in client.get(url).headers['cache-control']

@pytest.mark.parametrize('name,body',[('script.exe',b'xyz'),('fake.pdf',b'notpdf'),('notes.md',b'\xff\xfe')])
def test_upload_invalid_formats(client,name,body):assert client.post(P+'/courses/cs3481/files',files={'file':(name,body)}).status_code==422

def test_upload_size_limit(client,env):
 env[3].max_upload_bytes=5;assert client.post(P+'/courses/cs3481/files',files={'file':('big.txt',b'123456')}).status_code==413

def test_quota_atomic(client,env):
 env[3].max_files=1;upload(client)
 assert client.post(P+'/courses/cs3481/files',files={'file':('two.md',b'different')}).status_code==409
 assert len(env[0].state.db.all("SELECT * FROM cmui_files WHERE owner='local-alice'"))==1

def test_delete_upload_cleans_chunks(client,env):
 f=upload(client);assert client.delete(P+f"/courses/cs3481/files/{f['id']}").status_code==200
 assert not env[0].state.db.all('SELECT * FROM cmui_chunks WHERE file=?',(f['id'],))
 assert client.get(P+f"/courses/cs3481/files/{f['id']}/content").status_code==404

def test_comment_reply_notification_and_idempotency(client):
 a=client.post(P+'/courses/cs3481/comments',json={'text':'请问如何理解密度？','request_id':k()}).json()
 login(client,'bob');body={'text':'可以从邻域内的样本数理解。','parent':a['id'],'request_id':k()}
 b=client.post(P+'/courses/cs3481/comments',json=body);assert b.status_code==201,b.text
 assert client.post(P+'/courses/cs3481/comments',json=body).json()['id']==b.json()['id']
 login(client,'alice');notices=client.get(P+'/notifications').json();assert len(notices)==1;assert '邻域' in notices[0]['text']
 assert client.put(P+'/notifications/'+notices[0]['id']+'/read').status_code==200;assert client.get(P+'/notifications').json()[0]['read_at']

def test_comment_like_delete_and_foreign_author(client):
 a=client.post(P+'/courses/cs3481/comments',json={'text':'中文评论','request_id':k()}).json()
 login(client,'bob');url=P+'/courses/cs3481/comments/'+a['id']
 client.put(url+'/like');client.put(url+'/like');assert client.get(P+'/courses/cs3481/comments').json()[0]['likes']==1
 assert client.delete(url).status_code==404
 login(client,'alice');assert client.delete(url).status_code==200;assert client.get(P+'/courses/cs3481/comments').json()[0]['deleted']==1

def test_comment_dedup_conflict(client):
 data={'text':'a','request_id':k()};client.post(P+'/courses/cs3481/comments',json=data);data['text']='b';assert client.post(P+'/courses/cs3481/comments',json=data).status_code==409

def test_direct_message_read_unread_and_third_user(client):
 body={'text':'一起复习吗？','recipient':'local-bob','request_id':k()};r=client.post(P+'/messages',json=body);assert r.status_code==201,r.text
 assert client.post(P+'/messages',json=body).json()['id']==r.json()['id'];tid=r.json()['thread']
 login(client,'bob');assert client.get(P+'/threads').json()[0]['unread']==1
 assert client.get(P+f'/threads/{tid}/messages').json()[0]['text']=='一起复习吗？'
 client.put(P+f'/threads/{tid}/read');assert client.get(P+'/threads').json()[0]['unread']==0
 login(client,'admin');assert client.get(P+f'/threads/{tid}/messages').status_code==404;assert client.get(P+'/threads').json()==[]

def test_direct_message_block(client):
 client.put(P+'/people/local-bob/block');assert client.post(P+'/messages',json={'text':'hi','recipient':'local-bob','request_id':k()}).status_code==403
 login(client,'bob');assert client.post(P+'/messages',json={'text':'hi','recipient':'local-alice','request_id':k()}).status_code==403

def test_people_minimum_query_and_profile(client):
 assert client.get(P+'/people?q=林').json()==[]
 assert client.get(P+'/people?q=林同').json()[0]['name']=='林同学'
 r=client.patch(P+'/me',json={'name':'新同学','handle':'new-student','timezone':'Asia/Shanghai','discoverable':False});assert r.status_code==200
 login(client,'bob');assert client.get(P+'/people?q=new-student').json()==[]

@pytest.mark.parametrize('field,value',[('handle','BAD SPACE'),('timezone','Mars/Olympus'),('language','bad')])
def test_profile_validation(client,field,value):
 data={'name':'同学','handle':'student-test'};data[field]=value;assert client.patch(P+'/me',json=data).status_code==422

def test_task_crud_timezone_versions_and_ownership(client):
 data={'title':'复习聚类','due_at':'2026-09-16T14:00:00+08:00','timezone':'Asia/Hong_Kong','course':'cs3481','request_id':k()}
 r=client.post(P+'/tasks',json=data);assert r.status_code==201,r.text;t=r.json();assert t['due_at']=='2026-09-16T06:00:00+00:00'
 assert client.post(P+'/tasks',json=data).json()['id']==t['id']
 url=P+'/tasks/'+t['id'];r=client.patch(url,json={'version':1,'status':'done'});assert r.json()['version']==2
 assert client.patch(url,json={'version':1,'title':'旧版本'}).status_code==409
 login(client,'bob');assert client.get(P+'/tasks').json()==[];assert client.patch(url,json={'version':2,'status':'todo'}).status_code==404;assert client.delete(url).status_code==404
 login(client,'alice');assert client.delete(url).status_code==200

def test_naive_task_time_rejected(client):assert client.post(P+'/tasks',json={'title':'test','due_at':'2026-09-16T14:00:00','request_id':k()}).status_code==422

def test_history_restore_new_login_and_isolation(client):
 c=convo(client);rid,r,sse,_=run(client,c['id']);assert r['status']=='completed';assert 'event: delta' in sse;assert r['generated_prompt']
 login(client,'bob');assert client.get(P+'/conversations/'+c['id']).status_code==404;assert client.get(P+'/runs/'+rid).status_code==404
 login(client,'alice');rest=client.get(P+'/conversations/'+c['id']).json();assert len(rest['messages'])==2;assert rest['messages'][0]['role']=='user'
 assert client.patch(P+'/conversations/'+c['id'],json={'title':'我的复习'}).json()['title']=='我的复习'
 assert client.delete(P+'/conversations/'+c['id']).status_code==200

def test_multiturn_history_passed_to_provider(client,env):
 c=convo(client);run(client,c['id']);run(client,c['id'],'为什么？');assert len(env[2].calls[-1]['history'])==2

def test_run_idempotency_no_second_provider_call(client,env):
 c=convo(client);rid,r,_,body=run(client,c['id']);n=len(env[2].calls)
 again=client.post(P+f"/conversations/{c['id']}/runs",json=body);assert again.json()['id']==rid;assert len(env[2].calls)==n
 body['text']='changed';assert client.post(P+f"/conversations/{c['id']}/runs",json=body).status_code==409

def test_partial_failure_not_assistant_completed(client):
 c=convo(client);rid,r,sse,_=run(client,c['id'],'force-fail');assert r['status']=='failed';assert r['partial_text']=='未完成的答案';assert r['error']=='TEST_FAILURE'
 assert len(client.get(P+'/conversations/'+c['id']).json()['messages'])==1
 assert 'event: done' not in sse

def test_stream_replay_after_cursor(client):
 c=convo(client);rid,r,sse,_=run(client,c['id']);ids=[int(x[4:]) for x in sse.splitlines() if x.startswith('id: ')]
 replay=client.get(P+f'/runs/{rid}/events?after={ids[-2]}').text;assert f'id: {ids[-1]}' in replay;assert f'id: {ids[0]}\n' not in replay

def test_layout_pin_bridge_and_return(client,env):
 c=convo(client,'problem');rid,r,sse,_=run(client,c['id']);message=client.get(P+'/conversations/'+c['id']).json()['messages'][-1]
 payload={'problem_message':message['id'],'step':1,'question':'为什么先判断邻域？','node':'core'}
 b=client.post(P+'/courses/cs3481/bridges',json=payload);assert b.status_code==201,b.text;b=b.json()
 assert client.post(P+'/courses/cs3481/bridges',json=payload).json()['id']==b['id']
 teach=convo(client);_,result,_,_=run(client,teach['id'],'帮我理解这一步',bridge_id=b['id'],node_id='core');assert result['status']=='completed'
 assert env[2].calls[-1]['bridge']['original_question'];assert env[2].calls[-1]['bridge']['solution_excerpt']
 layout={'ratio':.63,'teach_conversation':teach['id'],'problem_conversation':c['id'],'active_node':'core'}
 assert client.put(P+'/courses/cs3481/layout',json=layout).status_code==200
 assert client.get(P+'/courses/cs3481/layout').json()['bridge']['id']==b['id']
 nodes=client.get(P+'/courses/cs3481/knowledge').json();node=next(n for n in nodes if n['id']=='core');assert node['progress']=='LEARNING' and node['grade'] is None
 assert client.patch(P+'/bridges/'+b['id']+'/return').json()['status']=='returned'
 login(client,'bob');assert client.get(P+'/courses/cs3481/layout').json()['ratio']==.5;assert client.patch(P+'/bridges/'+b['id']+'/return').status_code==404

def test_wrong_lane_layout_rejected(client):
 c=convo(client,'teach');assert client.put(P+'/courses/cs3481/layout',json={'problem_conversation':c['id']}).status_code==422

def test_no_fake_assessment(client):assert client.get(P+'/courses/cs3481/knowledge/core/assessment').status_code==501

def test_data_survives_application_restart(client,env):
 cid=create(client)['id'];app,c,p,cfg=env
 app2=create_app(cfg,provider=ContractProvider())
 with TestClient(app2) as second:
  login(second,'alice');assert second.get(P+'/courses/'+cid).status_code==200
  assert app2.state.db.one('PRAGMA integrity_check')['integrity_check']=='ok';assert app2.state.db.all('PRAGMA foreign_key_check')==[]

def test_no_disabled_model_fake_answer(tmp_path):
 cfg=Settings(data_dir=tmp_path/'x');seed(cfg)
 with TestClient(create_app(cfg)) as c:
  login(c,'alice');cv=convo(c);r=c.post(P+f"/conversations/{cv['id']}/runs",json={'text':'你好','request_id':k()});assert r.status_code==503

@pytest.mark.parametrize('kwargs',[{'environment':'production'},{'environment':'production','auth_mode':'injected','integration_mode':'standalone'},{'provider_mode':'qwen','qwen_key':'test','qwen_base_url':'http://evil.example/v1'},{'provider_mode':'qwen','qwen_key':'test','qwen_base_url':'https://user:pass@example.test'},{'auth_mode':'clerk'}])
def test_config_fail_closed(tmp_path,kwargs):
 with pytest.raises(ValueError):Settings(data_dir=tmp_path,**kwargs).validate()

def test_refuse_legacy_db(tmp_path):
 path=tmp_path/'legacy.sqlite3'
 with sqlite3.connect(path) as c:c.execute('CREATE TABLE chunks (id TEXT)')
 with pytest.raises(ValueError):Database(path).initialize()

def test_no_store_api_headers(client):
 r=client.get(P+'/me');assert r.headers['cache-control']=='private, no-store';assert r.headers['x-content-type-options']=='nosniff'


def test_upload_strips_client_path(client):
 f=upload(client,name='../secret.txt',text='safe plain text');assert f['name']=='secret.txt';assert '..' not in f['name']
