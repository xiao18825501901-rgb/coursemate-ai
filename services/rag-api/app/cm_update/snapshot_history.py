"""Frozen exercise histories, excluding run internals and learning/grade state."""
import json

from .db import now


class SnapshotReader:
    """Read-only query adapter sharing the caller's SQLite transaction."""

    def __init__(self, connection):
        self.connection = connection

    def all(self, query, parameters=()):
        return [dict(row) for row in self.connection.execute(query,parameters).fetchall()]

    def one(self, query, parameters=()):
        row = self.connection.execute(query,parameters).fetchone()
        return dict(row) if row is not None else None


def export_exercises(db, owner, pair_id):
    rows=db.all('SELECT id,node,target_node,question,answer_steps,references_json,verification_status,generation_version,created_at FROM cmui_exercises WHERE owner=? AND pair=? ORDER BY created_at,id',(owner,pair_id))
    for row in rows:
        row['revealed']=bool(db.one('SELECT exercise FROM cmui_answer_reveals WHERE owner=? AND exercise=?',(owner,row['id'])))
        row['explanations']=[]
        if row['revealed']:
            explanations=db.all('SELECT id,step_id,answer_version,question,text,status,created_at,updated_at FROM cmui_step_explanations WHERE owner=? AND exercise=?',(owner,row['id']))
            for item in explanations:
                item['messages']=db.all('SELECT id,role,text,created_at FROM cmui_explanation_messages WHERE explanation=? ORDER BY created_at,rowid',(item['id'],))
            row['explanations']=explanations
    return rows


def import_exercises(c, exercises, *, owner, course, pair, stable, remap_citations, node_mapping):
    mapping={}
    for row in exercises:
        eid=stable('exercise_',row['id'])
        mapping[row['id']]=eid
        c.execute('INSERT INTO cmui_exercises(id,owner,course,pair,node,target_node,question,answer_steps,references_json,verification_status,generation_version,run,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,?)',
            (eid,owner,course,pair,node_mapping.get(row.get('node')),row.get('target_node'),row['question'],
             row['answer_steps'],remap_citations(row.get('references_json') or '[]'),
             row['verification_status'],row['generation_version'],row['created_at']))
        if row['revealed']:
            c.execute('INSERT INTO cmui_answer_reveals VALUES(?,?,?)',(owner,eid,now()))
        for exp in row.get('explanations') or []:
            xid=stable('explanation_',exp['id'])
            conversation=stable('conv_',exp['id'])
            c.execute('INSERT INTO cmui_conversations(id,owner,course,lane,title,created_at,updated_at,hidden) VALUES(?,?,?,\'problem\',?,?,?,1)',
                      (conversation,owner,course,'详解：'+exp['question'][:40],exp['created_at'],exp['updated_at']))
            status=exp['status'] if exp['status']!='generating' else 'cancelled'
            c.execute('INSERT INTO cmui_step_explanations(id,owner,exercise,step_id,answer_version,question,text,run,status,created_at,updated_at,conversation) VALUES(?,?,?,?,?,?,?,NULL,?,?,?,?)',
                (xid,owner,eid,exp['step_id'],exp['answer_version'],exp['question'],exp['text'],status,
                 exp['created_at'],exp['updated_at'],conversation))
            for message in exp['messages']:
                c.execute('INSERT INTO cmui_explanation_messages(id,explanation,role,text,run,created_at) VALUES(?,?,?,?,NULL,?)',
                    (stable('message_',message['id']),xid,message['role'],message['text'],message['created_at']))
    return mapping
