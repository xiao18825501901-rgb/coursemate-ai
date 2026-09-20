"""Transactional classification claims shared across application workers.

Claim at enqueue time, not when a delayed model task starts. In-process queues
can coalesce work, but only the persisted token decides who may publish.
"""
import json

from . import social, templates
from .db import now, uid


def _key(course):
    return 'classification_claim:' + course


def claim(db, course, bundle):
    revision = bundle.get('materials_revision')
    if not isinstance(revision, str) or not revision:
        raise ValueError('Classification requires a frozen materials revision')
    token = uid('classification_')
    with db.connect(True) as c:
        row = c.execute('SELECT source FROM cmui_classifications WHERE course=?', (course,)).fetchone()
        if row and row['source'] == 'manual':
            return None
        c.execute("INSERT INTO cmui_classifications(course,status,materials_revision,source,created_at,updated_at) VALUES(?,'CLASSIFYING',?,'auto',?,?) ON CONFLICT(course) DO UPDATE SET status='CLASSIFYING',materials_revision=excluded.materials_revision,updated_at=excluded.updated_at WHERE source='auto'",
                  (course, revision, now(), now()))
        c.execute('INSERT INTO cmui_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (_key(course), json.dumps({'token': token, 'materials_revision': revision})))
    return token


def _owns(c, course, token, revision=None):
    row = c.execute('SELECT value FROM cmui_meta WHERE key=?', (_key(course),)).fetchone()
    if row is None:
        return False
    data = json.loads(row['value'])
    if not token or data['token'] != token or (revision is not None and data['materials_revision'] != revision):
        return False
    state = c.execute('SELECT source,materials_revision FROM cmui_classifications WHERE course=?', (course,)).fetchone()
    return bool(state and state['source'] == 'auto' and state['materials_revision'] == data['materials_revision'])


def publish(db, course, token, bundle, result, model, *, billing=None):
    validated = social.validate_classification(db, result)
    revision = bundle['materials_revision']
    template = templates.registry()[validated['template_id']]
    metadata = {'template_id': template['id'], 'template_version': template['version'],
                'template_body_sha256': template['body_sha256'], 'materials_revision': revision,
                'model': model, 'source': 'auto'}
    if billing is not None:
        # Pricing and usage are operation metadata only: never persist the
        # classified course body, uploaded document text, or credential data.
        metadata['billing'] = billing
    with db.connect(True) as c:
        if not _owns(c, course, token, revision):
            return False
        c.execute("UPDATE cmui_classifications SET status=?,template_id=?,decision=?,degree_level=?,confidence=?,alternatives=?,reason=?,evidence_refs=?,model=?,updated_at=? WHERE course=? AND source='auto'",
                  ('CLASSIFIED' if validated['decision'] == 'classified' else 'OTHER',
                   validated['template_id'], validated['decision'], validated['degree_level'],
                   validated['confidence'], json.dumps(validated['alternatives'], ensure_ascii=False),
                   validated['reason'], json.dumps(validated['evidence_refs'], ensure_ascii=False), model, now(), course))
        c.execute('INSERT INTO cmui_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  ('classification_evidence:' + course, json.dumps(metadata)))
    return True


def fail(db, course, token, reason):
    with db.connect(True) as c:
        if not _owns(c, course, token):
            return False
        c.execute("UPDATE cmui_classifications SET status='FAILED_RETRYABLE',reason=?,updated_at=? WHERE course=? AND source='auto'",
                  (reason, now(), course))
    return True


def record_billing_attempt(db, course, token, bundle, billing, outcome):
    """Keep a non-content audit of a Qwen classification request.

    A worker can lose its claim after the outbound request begins. The result
    must then not overwrite the newer classification, but the charged or
    unknown attempt still needs an audit record. ``token`` is a one-time claim
    ID, so it gives each frozen attempt a stable, non-overwriting key.
    """
    revision = bundle.get('materials_revision')
    if not isinstance(revision, str) or not revision:
        raise ValueError('Classification billing requires a frozen materials revision')
    payload = {
        'materials_revision': revision,
        'outcome': outcome,
        'billing': billing,
    }
    db.execute(
        'INSERT INTO cmui_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING',
        ('classification_billing_attempt:' + course + ':' + token, json.dumps(payload)),
    )


def evidence(db, course):
    row = db.one('SELECT value FROM cmui_meta WHERE key=?', ('classification_evidence:' + course,))
    if row is None:
        return None
    saved = json.loads(row['value'])
    current = db.one('SELECT template_id,materials_revision,source FROM cmui_classifications WHERE course=?', (course,))
    if not current or any(current[key] != saved[key] for key in ('template_id', 'materials_revision', 'source')):
        return None
    return saved


def record_manual_evidence(db, course):
    """Call after owner correction. Recheck state under lock before recording."""
    with db.connect(True) as c:
        row = c.execute("SELECT template_id,materials_revision FROM cmui_classifications WHERE course=? AND source='manual'", (course,)).fetchone()
        if not row:
            return
        template = templates.registry()[row['template_id']]
        saved = {'template_id': template['id'], 'template_version': template['version'],
                 'template_body_sha256': template['body_sha256'], 'materials_revision': row['materials_revision'],
                 'model': None, 'source': 'manual'}
        c.execute('INSERT INTO cmui_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  ('classification_evidence:' + course, json.dumps(saved)))


def import_snapshot(db, course, manifest, mapping, share_id):
    """Copy the frozen classification, not a fresh model decision.

    Internal provenance retains original version IDs. Public evidence refers
    only to the recipient's documents; missing references are explicitly absent.
    Retry never overwrites a recipient's subsequent manual correction.
    """
    source = manifest.get('classification')
    if not source:
        return
    refs = []
    unavailable = 0
    for ref in json.loads(source.get('evidence_refs') or '[]'):
        source_id = ref.split(':', 1)[0] if isinstance(ref, str) else ref.get('document_id')
        target = mapping.get(source_id)
        if target and target.get('document_id'):
            suffix = ref[len(source_id):] if isinstance(ref, str) else ''
            refs.append(target['document_id'] + suffix)
        else:
            unavailable += 1
    fields = ('status','template_id','decision','degree_level','confidence','alternatives',
              'reason','materials_revision','model','source','created_at','updated_at')
    values = {key: source[key] for key in fields}
    if values['status'] == 'CLASSIFYING':
        values.update(status='FAILED_RETRYABLE', reason='共享时分类尚未完成，请重新分类')
    with db.connect(True) as c:
        if c.execute('SELECT 1 FROM cmui_classifications WHERE course=?', (course,)).fetchone():
            return
        c.execute('INSERT INTO cmui_classifications(course,evidence_refs,' + ','.join(fields) +
                  ') VALUES(' + ','.join('?' for _ in range(len(fields)+2)) + ')',
                  (course,json.dumps(refs,ensure_ascii=False),*(values[key] for key in fields)))
        saved = manifest.get('classification_evidence')
        if saved:
            c.execute('INSERT INTO cmui_meta(key,value) VALUES(?,?)',
                      ('classification_evidence:' + course,json.dumps(saved)))
        c.execute('INSERT INTO cmui_meta(key,value) VALUES(?,?)',
                  ('classification_snapshot:' + course,json.dumps({'share_id':share_id,
                    'unavailable_evidence_count':unavailable,'source_materials_revision':source.get('materials_revision')})))
