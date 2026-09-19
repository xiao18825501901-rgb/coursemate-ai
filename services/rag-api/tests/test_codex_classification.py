"""Classification revisions and cross-worker completion contracts, offline."""
import importlib
import importlib.util
import json

from app.cm_update import social, templates
from app.cm_update.db import Database
from test_current_change_features import UI,auth,client,make_course


def classification_module():
    name = 'app.cm_update.classification'
    assert importlib.util.find_spec(name), 'cross-worker classification publication helper is missing'
    return importlib.import_module(name)


def result(template='03'):
    return {'template_id': template, 'decision': 'classified', 'degree_level': 'graduate',
            'confidence': .9, 'alternatives': [], 'reason': 'Synthetic source evidence',
            'evidence_refs': ['document-a:page-1']}


def test_same_file_identity_changed_version_or_text_changes_revision():
    base = [{'id': 'file-a', 'name': 'lecture.txt', 'version_id': 'v1', 'text': 'old body'}]
    changed = [{'id': 'file-a', 'name': 'lecture.txt', 'version_id': 'v2', 'text': 'new body'}]
    assert social.materials_revision(base) != social.materials_revision(changed)
    assert social.materials_revision(base) != social.materials_revision([dict(base[0], text='changed only body')])
    assert social.materials_revision(base + changed) == social.materials_revision(changed + base)


def test_old_worker_cannot_overwrite_new_revision_or_failure(tmp_path):
    module = classification_module()
    first = Database(tmp_path / 'ui.sqlite3'); first.initialize()
    second = Database(first.path)
    old_bundle = {'materials_revision': 'old'}; new_bundle = {'materials_revision': 'new'}
    old_claim = module.claim(first, 'course:user', old_bundle)
    new_claim = module.claim(second, 'course:user', new_bundle)
    assert module.publish(second, 'course:user', new_claim, new_bundle, result('02'), 'synthetic') is True
    assert module.publish(first, 'course:user', old_claim, old_bundle, result('03'), 'synthetic') is False
    assert module.fail(first, 'course:user', old_claim, 'stale failure') is False
    saved = first.one('SELECT * FROM cmui_classifications WHERE course=?', ('course:user',))
    assert saved['template_id'] == '02' and saved['materials_revision'] == 'new'
    assert saved['status'] == 'CLASSIFIED'
    evidence = module.evidence(first, 'course:user')
    assert evidence['template_version'] == templates.registry()['02']['version']
    assert evidence['template_body_sha256'] == templates.registry()['02']['body_sha256']
    assert evidence['materials_revision'] == 'new'


def test_manual_choice_wins_over_inflight_automatic_completion(tmp_path):
    module = classification_module()
    db = Database(tmp_path / 'ui.sqlite3'); db.initialize()
    bundle = {'materials_revision': 'r1'}
    token = module.claim(db, 'course:user', bundle)
    db.execute("UPDATE cmui_classifications SET source='manual',template_id='04',status='CLASSIFIED' WHERE course='course:user'")
    assert module.publish(db, 'course:user', token, bundle, result(), 'synthetic') is False
    assert module.fail(db, 'course:user', token, 'failure') is False
    assert module.claim(db, 'course:user', {'materials_revision': 'r2'}) is None
    assert db.one("SELECT template_id FROM cmui_classifications WHERE course='course:user'")['template_id'] == '04'


def test_integrated_same_filename_changed_body_reclassifies_from_authorized_text(client,monkeypatch):
    import time
    make_course(client)
    captured=[]
    async def classify(bundle):
        captured.append(bundle)
        # Deterministic contract upstream: deliberately same name/length;
        # only body evidence can distinguish these synthetic disciplines.
        body=json.dumps(bundle['text_samples'])
        return json.dumps(result('02' if 'SECOND_BODY_CS' in body else '03'))
    monkeypatch.setattr(client.app.state.ui_extension_app.state.provider,'classify_course',classify)
    revisions=[]
    for text,expected in [('FIRST_BODY_DS_','03'),('SECOND_BODY_CS','02')]:
        response=client.post(f'{UI}/courses/cs3481/files',headers=auth('token-a'),
            files={'file':('same-name.txt',text.encode(),'text/plain')})
        assert response.status_code==201,response.text
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            state=client.get(f'{UI}/courses/cs3481/classification',headers=auth('token-a')).json()
            if state.get('template_id')==expected and state['status']=='CLASSIFIED': break
            time.sleep(.02)
        assert state['template_id']==expected,state
        revisions.append(state['materials_revision'])
    assert revisions[0]!=revisions[1]
    assert all(bundle['text_samples'] for bundle in captured)
    assert all(sum(len(s['text']) for s in bundle['text_samples'])<=24000 for bundle in captured)
    assert all(s['document_id'] and s['version_id'] for bundle in captured for s in bundle['text_samples'])
