"""Local, immutable knowledge copies. Never transfers grades or teaching coverage."""
import hashlib
import json

from app.errors import ApiError
from app.learning.knowledge import KnowledgeService
from app.learning.models import TreeMembershipInput
from app.learning.workspaces import workspace_for


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _id(*parts):
    return hashlib.sha256(_json(parts).encode()).hexdigest()


def export_snapshot(learning, workspace, owner):
    scope = workspace_for(learning.db, workspace, owner)
    with learning.db.connect() as db:
        db.execute('BEGIN')
        nodes = []
        for row in KnowledgeService._accessible_nodes(db, scope):
            node = dict(row)
            node.pop('owner_user_id', None)
            node['specs'] = [dict(s) for s in db.execute(
                'SELECT s.version,s.content_json,m.status,m.change_reason FROM teaching_specs s '
                'JOIN teaching_spec_metadata m ON m.node_id=s.node_id AND m.version=s.version '
                "WHERE s.node_id=? AND m.status IN ('PRIVATE_ACTIVE','PUBLISHED') ORDER BY s.version", (row['id'],))]
            node['aliases'] = [dict(a) for a in db.execute(
                'SELECT alias,normalized_alias,locale FROM knowledge_node_aliases WHERE node_id=?', (row['id'],))]
            nodes.append(node)
        tree = db.execute("SELECT * FROM knowledge_tree_versions WHERE workspace_id=? AND status='ACTIVE' AND tree_kind='PERSONALIZED'", (workspace,)).fetchone()
        if tree is None:
            tree = db.execute("SELECT * FROM knowledge_tree_versions WHERE course_id=? AND status='PUBLISHED' AND tree_kind='OFFICIAL'", (scope['course_id'],)).fetchone()
        projection = None
        if tree:
            projection = {'id': tree['id'], 'title': tree['title'], 'memberships': [dict(m) for m in db.execute(
                'SELECT node_id,parent_node_id,ordinal,teaching_spec_version AS spec_version FROM knowledge_tree_memberships WHERE tree_version_id=? ORDER BY ordinal,node_id', (tree['id'],))],
                'prerequisites': [dict(p) for p in db.execute('SELECT node_id,prerequisite_node_id FROM knowledge_prerequisite_edges WHERE tree_version_id=?', (tree['id'],))]}
    allowed = {n['id'] for n in nodes}
    if projection and any(m['node_id'] not in allowed for m in projection['memberships']):
        raise ApiError(403, 'SNAPSHOT_SCOPE', 'Tree contains unavailable nodes.')
    return {'version': 1, 'nodes': nodes, 'tree': projection}


def import_snapshot(learning, workspace, owner, snapshot, file_mapping, share_id):
    scope = workspace_for(learning.db, workspace, owner)
    if snapshot.get('version') != 1 or not share_id:
        raise ApiError(422, 'SNAPSHOT_INVALID', 'Unsupported knowledge snapshot.')
    nodes = snapshot['nodes']
    mapping = {n['id']: 'node_' + _id(owner, workspace, share_id, n['id']) for n in nodes}
    if len(mapping) != len(nodes):
        raise ApiError(422, 'SNAPSHOT_INVALID', 'Duplicate snapshot nodes.')
    chunks = dict(file_mapping.get('chunks', {}))
    for entry in file_mapping.values():
        if isinstance(entry, dict):
            chunks.update(entry.get('chunks', {}))
    unavailable = []
    prepared = []
    for node in nodes:
        specs = []
        for spec in node.get('specs', []):
            items = json.loads(spec['content_json'])
            for item in items:
                retained = []
                for source in item.get('evidence_ids', []):
                    destination = chunks.get(source)
                    try:
                        if not destination:
                            raise ApiError(410, 'SOURCE_UNAVAILABLE', 'No imported reference.')
                        learning.evidence_version(scope, destination)
                    except ApiError:
                        unavailable.append({'node_id': node['id'], 'spec_version': spec['version'], 'source_chunk_id': source, 'status': 'UNAVAILABLE'})
                    else:
                        retained.append(destination)
                item['evidence_ids'] = retained
            specs.append((spec, _json(items)))
        prepared.append((node, specs))
    tree = snapshot.get('tree')
    tree_id = 'tree_' + _id(owner, workspace, share_id, 'tree') if tree else None
    provenance = {'share_id': share_id, 'snapshot_hash': _id(snapshot), 'unavailable_evidence': unavailable}
    with learning.db.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for node, specs in prepared:
            node_id = mapping[node['id']]
            existing_node = db.execute('SELECT title,description,major,kind FROM knowledge_nodes WHERE id=?', (node_id,)).fetchone()
            if existing_node and tuple(existing_node) != tuple(node[key] for key in ('title', 'description', 'major', 'kind')):
                raise ApiError(409, 'SNAPSHOT_CHANGED', 'An imported snapshot cannot change on retry.')
            db.execute("INSERT OR IGNORE INTO knowledge_nodes(id,course_id,owner_user_id,title,description,major,kind,status) VALUES(?,?,?,?,?,?,?,'PRIVATE')",
                       (node_id, scope['course_id'], owner, node['title'], node['description'], node['major'], node['kind']))
            for alias in node.get('aliases', []):
                db.execute('INSERT OR IGNORE INTO knowledge_node_aliases(node_id,alias,normalized_alias,locale) VALUES(?,?,?,?)', (node_id, alias['alias'], alias['normalized_alias'], alias['locale']))
            for spec, content in specs:
                existing = db.execute('SELECT content_json FROM teaching_specs WHERE node_id=? AND version=?', (node_id, spec['version'])).fetchone()
                if existing and existing[0] != content:
                    raise ApiError(409, 'SNAPSHOT_CHANGED', 'An imported snapshot cannot change on retry.')
                db.execute('INSERT OR IGNORE INTO teaching_specs VALUES(?,?,?,?)', (node_id, spec['version'], content, hashlib.sha256(content.encode()).hexdigest()))
                db.execute('UPDATE teaching_spec_metadata SET change_reason=? WHERE node_id=? AND version=?', (_json({**provenance, 'source_reason': spec['change_reason']}), node_id, spec['version']))
        if tree and not db.execute('SELECT 1 FROM knowledge_tree_versions WHERE id=?', (tree_id,)).fetchone():
            if any(m['node_id'] not in mapping or (m['parent_node_id'] is not None and m['parent_node_id'] not in mapping) for m in tree['memberships']):
                raise ApiError(422, 'SNAPSHOT_INVALID', 'Tree references missing snapshot nodes.')
            members = [TreeMembershipInput(node_id=mapping[m['node_id']], parent_node_id=mapping.get(m['parent_node_id']), ordinal=m['ordinal'], spec_version=m['spec_version']) for m in tree['memberships']]
            edges = {(mapping[e['node_id']], mapping[e['prerequisite_node_id']]) for e in tree['prerequisites']}
            registry = {mapping[n['id']]: n for n in nodes if n['id'] in {m['node_id'] for m in tree['memberships']}}
            valid = True
            try:
                if not members:
                    raise ApiError(422, 'TREE_INVALID', 'An empty tree cannot be activated.')
                KnowledgeService._validate_graph(registry, members, edges)
                for member in members:
                    if registry[member.node_id]['kind'] == 'ATOMIC' and (member.spec_version is None or not db.execute('SELECT 1 FROM teaching_specs WHERE node_id=? AND version=?', (member.node_id, member.spec_version)).fetchone()):
                        raise ApiError(422, 'SPEC_UNAVAILABLE', 'Snapshot node lacks a teaching specification.')
            except ApiError as error:
                valid = False
                provenance['tree_error'] = error.code
            version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM knowledge_tree_versions WHERE workspace_id=? AND tree_kind='PERSONALIZED'", (workspace,)).fetchone()[0]
            db.execute("INSERT INTO knowledge_tree_versions(id,course_id,workspace_id,owner_user_id,tree_kind,version,status,title,change_reason,content_hash) VALUES(?,?,?,?,'PERSONALIZED',?,'DRAFT',?,?,?)",
                       (tree_id, scope['course_id'], workspace, owner, version, tree['title'], _json({**provenance, 'source_tree': tree}), _id(tree)))
            if valid:
                for member in members:
                    db.execute('INSERT INTO knowledge_tree_memberships VALUES(?,?,?,?,?)', (tree_id, member.node_id, member.parent_node_id, member.ordinal, member.spec_version))
                for node_id, prerequisite in edges:
                    db.execute('INSERT INTO knowledge_prerequisite_edges VALUES(?,?,?)', (tree_id, node_id, prerequisite))
                db.execute("UPDATE knowledge_tree_versions SET status='RETIRED' WHERE workspace_id=? AND status='ACTIVE'", (workspace,))
                db.execute("UPDATE knowledge_tree_versions SET status='ACTIVE' WHERE id=?", (tree_id,))
        status = db.execute('SELECT status FROM knowledge_tree_versions WHERE id=?', (tree_id,)).fetchone() if tree_id else None
    return {'nodes': mapping, 'tree_id': tree_id, 'tree_status': status[0] if status else None, 'unavailable_evidence': unavailable}
