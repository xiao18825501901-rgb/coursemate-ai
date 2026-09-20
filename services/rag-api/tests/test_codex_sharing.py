from test_current_change_features import UI, auth, client
import json
from app.cm_update.db import now
from app.errors import ApiError
from test_current_change_features import SUBJECTS, make_course
from test_current_change_features import wait_terminal


def private_course(client):
    for token in ('token-a','token-b'):
        assert client.get(f'{UI}/me',headers=auth(token)).status_code == 200
    return client.post(f'{UI}/courses',headers=auth('token-a'),json={'name':'Private snapshot'}).json()['id']


def test_private_share_invitation_visible_without_source_access(client):
    course=private_course(client)
    sent=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':course,'recipients':['user-b'],'history_scope':'none','request_id':'private-invitation-1'})
    assert sent.status_code == 201,sent.text
    assert client.get(f'{UI}/courses/{course}',headers=auth('token-b')).status_code==404
    notices=client.get(f'{UI}/notifications',headers=auth('token-b')).json()
    assert any(n['ref']==sent.json()['id'] for n in notices)


def test_invalid_selected_share_does_not_fall_back_to_all(client):
    course=private_course(client)
    sent=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':course,'recipients':['user-b'],'history_scope':'selected',
        'selected_pair_ids':['nonexistent'],'request_id':'invalid-selected-1'})
    assert sent.status_code in (404,422),sent.text


def test_selected_snapshot_rejects_unbound_history(client):
    course=private_course(client)
    pair=client.post(f'{UI}/pairs',headers=auth('token-a'),json={'course':course}).json()
    response=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':course,'recipients':['user-b'],'history_scope':'selected',
        'selected_pair_ids':[pair['id']],'request_id':'unbound-selected'})
    assert response.status_code==422,response.text


def test_history_snapshot_excludes_concurrent_new_message(client,monkeypatch):
    from app.cm_update import social,snapshot_history
    course=private_course(client)
    pair=client.post(f'{UI}/pairs',headers=auth('token-a'),json={'course':course}).json()
    db=client.app.state.ui_extension_app.state.db
    lane=client.post(f'{UI}/conversations',headers=auth('token-a'),
        json={'course':course,'lane':'teach','pair_id':pair['id']})
    assert lane.status_code==201,lane.text
    conversation=lane.json()['id']
    original=snapshot_history.export_exercises
    def concurrent_write(reader,owner,pair_id):
        db.execute('INSERT INTO cmui_messages(id,conversation,role,text,citations,created_at) VALUES(?,?,?,?,?,?)',
            ('after-snapshot',conversation,'user','MUST_NOT_ENTER_FROZEN_HISTORY','[]',now()))
        return original(reader,owner,pair_id)
    monkeypatch.setattr(snapshot_history,'export_exercises',concurrent_write)
    frozen=social.snapshot_pair_payload(db,'user-a',course,[])
    assert db.one('SELECT id FROM cmui_messages WHERE id=?',('after-snapshot',))
    assert all(m['id']!='after-snapshot' for p in frozen for m in p['teach'])


def test_shared_classification_is_frozen_and_recipient_owned(client):
    course=private_course(client)
    selected=client.post(f'{UI}/courses/{course}/classification',headers=auth('token-a'),
        json={'template_id':'11'} )
    assert selected.status_code==200,selected.text
    original=selected.json()
    assert original['template_id']=='11'
    sent=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':course,'recipients':['user-b'],'history_scope':'none','request_id':'classification-copy'}).json()
    client.post(f'{UI}/courses/{course}/classification',headers=auth('token-a'),json={'template_id':'OTHER'})
    joined=client.post(f"{UI}/shares/{sent['id']}/join",headers=auth('token-b')).json()['joined_course_id']
    copied=client.get(f'{UI}/courses/{joined}/classification',headers=auth('token-b')).json()
    assert copied['template_id']==original['template_id']
    assert copied['source']==original['source']
    assert copied['template_evidence']['template_body_sha256']==original['template_evidence']['template_body_sha256']
    assert copied['course']==joined


def test_integrated_share_imports_real_file_without_embedding_call(client,monkeypatch):
    course=private_course(client)
    raw=b'# Source\nSNAPSHOT_BODY_CANARY preserved course evidence.'
    uploaded=client.post(f'{UI}/courses/{course}/files',headers=auth('token-a'),
        files={'file':('snapshot.md',raw,'text/markdown')})
    assert uploaded.status_code==201,uploaded.text
    def deny_embedding(*args,**kwargs):
        raise AssertionError('Snapshot copy must not invoke embeddings')
    monkeypatch.setattr(client.app.state.ingestion_service.embedding_provider,'embed_texts',deny_embedding)
    sent=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':course,'recipients':['user-b'],'history_scope':'none','request_id':'file-snapshot-1'})
    assert sent.status_code==201,sent.text
    assert sent.json()['files_copied']==1
    joined=client.post(f"{UI}/shares/{sent.json()['id']}/join",headers=auth('token-b'))
    assert joined.status_code==200,joined.text
    target=joined.json()['joined_course_id']
    files=client.get(f'{UI}/courses/{target}/files',headers=auth('token-b')).json()
    assert len(files)==1,files
    assert files[0]['id'] != uploaded.json()['id']


def test_frozen_three_file_history_retrieval_and_isolation(client,monkeypatch):
    monkeypatch.setitem(SUBJECTS,'Bearer token-c','user-c')
    course=private_course(client)
    client.get(f'{UI}/me',headers=auth('token-c'))
    source=[]
    expected={}
    for index,name in enumerate(('a.txt','b.txt','c.md')):
        raw=f'SNAPSHOT_UNIQUE_{index} frozen original lesson evidence'.encode()
        expected[name]=raw
        response=client.post(f'{UI}/courses/{course}/files',headers=auth('token-a'),
            files={'file':(name,raw,'text/markdown' if name.endswith('.md') else 'text/plain')})
        assert response.status_code==201,response.text
        source.append(response.json())
    db=client.app.state.ui_extension_app.state.db
    stamp=now()
    db.execute('INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
               ('source-conv','user-a',course,'teach','frozen lesson',stamp,stamp))
    db.execute('INSERT INTO cmui_pairs(id,owner,course,teach_conversation,title,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
               ('source-pair','user-a',course,'source-conv','frozen lesson',stamp,stamp))
    db.execute('INSERT INTO cmui_messages(id,conversation,role,text,citations,created_at) VALUES(?,?,?,?,?,?)',
               ('source-message','source-conv','assistant','Visible lesson',json.dumps([
                   {'document_id':source[0]['id'],'version_id':source[0]['version_id'],'name':'a.txt'},
                   {'document_id':'unmappable-private-file','url':'/private/source'}]),stamp))
    db.execute("INSERT INTO cmui_runs(id,owner,conversation,request_id,status,user_text,created_at,updated_at) VALUES(?,?,?,?,'completed','attached question',?,?)",
               ('attachment-run','user-a','source-conv','attachment-receipt',stamp,stamp))
    db.execute('INSERT INTO cmui_run_inputs VALUES(?,?,?)',('attachment-run','synthetic',json.dumps([
        {'id':source[0]['id'],'name':'a.txt','mime':'text/plain'}])))
    db.execute('INSERT INTO cmui_messages(id,conversation,role,text,citations,run,created_at) VALUES(?,?,?,?,?,?,?)',
               ('attached-message','source-conv','user','Read the attachment','[]','attachment-run',stamp))
    sent=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':course,'recipients':['user-b'],'history_scope':'all','request_id':'three-files-frozen'})
    assert sent.status_code==201,sent.text
    sid=sent.json()['id']
    assert sent.json()['files_copied']==3
    assert client.get(f'{UI}/shares/{sid}',headers=auth('token-c')).status_code==404
    assert not db.one('SELECT joined_course_id FROM cmui_share_recipients WHERE share=? AND recipient=?',(sid,'user-b'))['joined_course_id']
    # Delete all original versions before joining: the receiver must not depend on them.
    for original in source:
        response=client.delete(f"{UI}/courses/{course}/files/{original['id']}",headers=auth('token-a'))
        assert response.status_code==200,response.text
    joined=client.post(f'{UI}/shares/{sid}/join',headers=auth('token-b'))
    assert joined.status_code==200,joined.text
    target=joined.json()['joined_course_id']
    assert client.get(f'{UI}/courses/{target}',headers=auth('token-b')).json()['display_type']=='shared'
    files=client.get(f'{UI}/courses/{target}/files',headers=auth('token-b')).json()
    assert len(files)==3
    new_ids={f['id'] for f in files}
    assert not new_ids.intersection(f['id'] for f in source)
    for f in files:
        path=f"{UI}/courses/{target}/files/{f['id']}/content"
        for suffix in ('','?download=true'):
            response=client.get(path+suffix,headers=auth('token-b'))
            assert response.status_code==200,response.text
            assert response.content==expected[f['name']]
        assert client.get(path,headers=auth('token-c')).status_code==404
        assert client.get(path,headers=auth('token-a')).status_code==404
    domain=client.app.state.ui_extension_app.state.domain
    hits=client.portal.call(domain.call,'context.retrieve','user-b',{'course':target,'query':'SNAPSHOT_UNIQUE_0'})
    assert hits and any('SNAPSHOT_UNIQUE_0' in hit['text'] for hit in hits)
    assert all(hit['document_id'] in new_ids for hit in hits)
    pairs=db.all('SELECT * FROM cmui_pairs WHERE owner=? AND course=?',('user-b',target))
    assert len(pairs)==1
    history=client.get(f"{UI}/pairs/{pairs[0]['id']}",headers=auth('token-b'))
    assert history.status_code==200,history.text
    assert 'Visible lesson' in history.text
    assert source[0]['id'] not in history.text and '/private/source' not in history.text
    assert '原共享来源当前不可用' in history.text
    attached=next(m for m in history.json()['teach']['messages'] if m['role']=='user')
    assert len(attached['attachments'])==1
    assert attached['attachments'][0]['id'] in new_ids
    legacy=client.get(f"{UI}/conversations/{pairs[0]['teach_conversation']}",headers=auth('token-b'))
    assert '原共享来源当前不可用' in legacy.text
    assert next(m for m in legacy.json()['messages'] if m['role']=='user')['attachments'][0]['id'] in new_ids
    assert client.get(f"{UI}/pairs/{pairs[0]['id']}",headers=auth('token-c')).status_code==404
    again=client.post(f'{UI}/shares/{sid}/join',headers=auth('token-b'))
    assert again.json()['joined_course_id']==target and again.json()['reused']
    assert len(db.all('SELECT id FROM cmui_pairs WHERE owner=? AND course=?',('user-b',target)))==1


def test_snapshot_import_failure_is_retryable_and_not_joined(client,monkeypatch):
    course=private_course(client)
    for i in range(3):
        assert client.post(f'{UI}/courses/{course}/files',headers=auth('token-a'),
            files={'file':(f'{i}.txt',f'unique lesson {i}'.encode(),'text/plain')}).status_code==201
    sid=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':course,'recipients':['user-b'],'history_scope':'none','request_id':'retry-snapshot'}).json()['id']
    service=client.app.state.ingestion_service
    original=service.import_snapshot
    calls=0
    def intermittent(**kwargs):
        nonlocal calls
        calls+=1
        if calls==3: raise ApiError(503,'SYNTHETIC_INTERRUPT','Synthetic import interruption')
        return original(**kwargs)
    monkeypatch.setattr(service,'import_snapshot',intermittent)
    failed=client.post(f'{UI}/shares/{sid}/join',headers=auth('token-b'))
    assert failed.status_code==503,failed.text
    db=client.app.state.ui_extension_app.state.db
    receipt=db.one('SELECT * FROM cmui_share_imports WHERE share=? AND recipient=?',(sid,'user-b'))
    assert receipt['status']=='FAILED_RETRYABLE'
    assert db.one('SELECT status FROM cmui_share_recipients WHERE share=?',(sid,))['status']=='notified'
    retried=client.post(f'{UI}/shares/{sid}/join',headers=auth('token-b'))
    assert retried.status_code==200,retried.text
    assert retried.json()['joined_course_id']==receipt['course']
    assert len(client.get(f"{UI}/courses/{receipt['course']}/files",headers=auth('token-b')).json())==3


def test_campus_snapshot_requires_verification_before_import(client):
    make_course(client)
    sid=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':'cs3481','recipients':['user-b'],'history_scope':'none','request_id':'campus-snapshot'}).json()['id']
    assert client.get(f'{UI}/shares/{sid}',headers=auth('token-b')).status_code==200
    assert client.post(f'{UI}/shares/{sid}/join',headers=auth('token-b')).status_code==403
    db=client.app.state.ui_extension_app.state.db
    assert not db.one('SELECT * FROM cmui_share_imports WHERE share=?',(sid,))


def test_share_request_id_rejects_different_payload(client):
    course=private_course(client)
    data={'course':course,'recipients':['user-b'],'history_scope':'none','request_id':'immutable-request'}
    first=client.post(f'{UI}/shares',headers=auth('token-a'),json=data)
    assert first.status_code==201
    repeated=client.post(f'{UI}/shares',headers=auth('token-a'),json=data)
    assert repeated.json()['id']==first.json()['id']
    changed=client.post(f'{UI}/shares',headers=auth('token-a'),json={**data,'history_scope':'all'})
    assert changed.status_code==409


def test_share_restores_exercise_answer_and_cached_explanation(client):
    make_course(client)
    # A node without a teaching specification correctly stays SPEC_UNAVAILABLE.
    # This case checks a usable copied contract starts without sender coverage.
    with client.app.state.database.connect() as connection:
        content=json.dumps([{'item_id':'snapshot-required','requirement':'REQUIRED',
            'objective':'Explain the solution','acceptance':'Connect the steps','evidence_ids':[]}])
        connection.execute('INSERT INTO teaching_specs VALUES(?,?,?,?)',('node-x',1,content,'a'*64))
    pair=client.post(f'{UI}/pairs',headers=auth('token-a'),json={'course':'cs3481'}).json()
    assert client.post(f"{UI}/pairs/{pair['id']}/bind",headers=auth('token-a'),json={'node':'node-x'}).status_code==200
    started=client.post(f'{UI}/courses/cs3481/exercises',headers=auth('token-a'),
        json={'pair_id':pair['id'],'request_id':'snapshot-exercise'}).json()
    wait_terminal(client,started['id'])
    db=client.app.state.ui_extension_app.state.db
    exercise=db.one('SELECT id FROM cmui_exercises WHERE run=?',(started['id'],))['id']
    reveal=client.post(f'{UI}/exercises/{exercise}/reveal',headers=auth('token-a')).json()
    step=reveal['steps'][0]['step_id']
    explanation=client.post(f'{UI}/exercises/{exercise}/steps/{step}/explanation',headers=auth('token-a'),
        json={'request_id':'snapshot-explanation'}).json()
    wait_terminal(client,explanation['run'])
    sent=client.post(f'{UI}/shares',headers=auth('token-a'),json={
        'course':'cs3481','recipients':['user-b'],'history_scope':'all','request_id':'exercise-history-share'}).json()
    issued=client.post(f'{UI}/admin/verification-codes',headers=auth('admin-token'),json={'count':1}).json()
    client.post(f'{UI}/me/verification/redeem',headers=auth('token-b'),json={'code':issued['codes'][0],'request_id':'verify-history-recipient'})
    joined=client.post(f"{UI}/shares/{sent['id']}/join",headers=auth('token-b'))
    assert joined.status_code==200,joined.text
    copied=db.one('SELECT * FROM cmui_exercises WHERE owner=? AND course=?',('user-b',joined.json()['joined_course_id']))
    assert copied, 'Frozen exercise and answer version must be copied with visible history'
    assert copied['id']!=exercise and copied['run'] is None
    assert copied['node'] and copied['node']!='node-x'
    copied_pair=db.one('SELECT * FROM cmui_pairs WHERE id=?',(copied['pair'],))
    assert copied_pair['bound_node']==copied['node']
    nodes=client.get(f"{UI}/courses/{joined.json()['joined_course_id']}/knowledge",headers=auth('token-b')).json()
    assert any(n['id']==copied['node'] and n['progress']=='NOT_STARTED' for n in nodes), nodes
    assert any(n['title']=='node-y' and n['progress']=='SPEC_UNAVAILABLE' for n in nodes)
    restored=client.get(f"{UI}/exercises/{copied['id']}",headers=auth('token-b')).json()
    assert restored['source']=='generated'
    assert restored['revealed'] and restored['steps']==reveal['steps']
    cached=client.post(f"{UI}/exercises/{copied['id']}/steps/{step}/explanation",headers=auth('token-b'),
        json={'request_id':'cached-shared-explanation'})
    assert cached.status_code==202 and cached.json()['reused']
    assert cached.json()['status']=='completed'


def test_file_read_cannot_substitute_another_owned_course_path(client):
    course=private_course(client)
    other=client.post(f'{UI}/courses',headers=auth('token-a'),json={'name':'Other private course'}).json()['id']
    uploaded=client.post(f'{UI}/courses/{course}/files',headers=auth('token-a'),
        files={'file':('scoped.txt',b'Course-specific file content','text/plain')}).json()
    for suffix in ('content','text'):
        response=client.get(f"{UI}/courses/{other}/files/{uploaded['id']}/{suffix}",headers=auth('token-a'))
        assert response.status_code==404,response.text
    deleted=client.delete(f"{UI}/courses/{other}/files/{uploaded['id']}",headers=auth('token-a'))
    assert deleted.status_code==404,deleted.text
    assert client.get(f"{UI}/courses/{course}/files/{uploaded['id']}/content",headers=auth('token-a')).status_code==200
