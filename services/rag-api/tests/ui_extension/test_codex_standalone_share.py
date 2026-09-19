from conftest import P, login


def test_standalone_share_owns_bytes_and_retrievable_chunks(client,env):
    course=client.post(P+'/courses',json={'name':'Synthetic share source'}).json()['id']
    body=b'STANDALONE_FROZEN_CANARY is a searchable definition.'
    upload=client.post(P+f'/courses/{course}/files',files={'file':('source.txt',body,'text/plain')})
    assert upload.status_code==201,upload.text
    sent=client.post(P+'/shares',json={'course':course,'recipients':['local-bob'],
        'history_scope':'none','request_id':'standalone-snapshot'} )
    assert sent.status_code==201,sent.text
    login(client,'bob')
    joined=client.post(P+f"/shares/{sent.json()['id']}/join")
    assert joined.status_code==200,joined.text
    cid=joined.json()['joined_course_id']
    files=client.get(P+f'/courses/{cid}/files').json()
    assert len(files)==1,files
    assert files[0]['id']!=upload.json()['id']
    assert client.get(P+f"/courses/{cid}/files/{files[0]['id']}/content").content==body
    assert env[0].state.db.one('SELECT text FROM cmui_chunks WHERE file=?',(files[0]['id'],))['text'].find('STANDALONE_FROZEN_CANARY')>=0
    repeat=client.post(P+f"/shares/{sent.json()['id']}/join")
    assert repeat.json()['joined_course_id']==cid
