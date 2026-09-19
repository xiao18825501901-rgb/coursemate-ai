"""Explicit, offline-testable identity projection. Never sync on a page request.

Only an operator-approved sync invokes the external client. The public directory
contains no contact details, credentials or upstream subject identifiers.
"""
from datetime import datetime, timezone
import hashlib
import json
import math

from .db import uid


class ClerkDirectoryClient:
    def __init__(self, http_client):
        self.http = http_client

    async def fetch_users(self):
        users = {}
        offset = 0
        for _ in range(1000):
            response = await self.http.get('users', params={'limit': 100, 'offset': offset})
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, list) or len(page)>100:
                raise ValueError('Invalid identity directory response')
            for row in page:
                if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
                    raise ValueError('Invalid identity record')
                if not isinstance(row.get('updated_at'), (int,float)):
                    raise ValueError('Identity update timestamp is required')
                old = users.get(row['id'])
                if old is None or row['updated_at']>old['updated_at']:
                    users[row['id']] = row
            offset += len(page)
            if len(page)<100:
                return list(users.values())
        raise ValueError('Directory exceeds bounded sync size; no partial sync applied')


def sync_directory(db, records, *, complete=False, snapshot_at_ms=None):
    """Atomic projection; older events cannot resurrect a deleted identity.

    Complete is only used with a successfully fetched full upstream snapshot.
    Local discoverability/block preferences and student verification are retained.
    Capture snapshot_at_ms before fetching pages. Its observation watermark
    protects both present records and absent tombstones against stale replay.
    """
    if complete:
        if snapshot_at_ms is None:
            snapshot_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if not isinstance(snapshot_at_ms, int) or isinstance(snapshot_at_ms, bool) or snapshot_at_ms < 0:
            raise ValueError('A nonnegative integer snapshot timestamp is required')
    latest = {}
    for row in records:
        prior = latest.get(row['id'])
        if prior is None or int(row['updated_at']) > int(prior['updated_at']):
            latest[row['id']] = row
    seen = set()
    with db.connect(True) as c:
        for row in latest.values():
            subject = row['id']
            seen.add(subject)
            upstream_updated = int(row['updated_at'])
            updated = max(upstream_updated, snapshot_at_ms) if complete else upstream_updated
            old = c.execute('SELECT * FROM cmui_directory WHERE subject=?',(subject,)).fetchone()
            if old and old['updated_ms']>=updated:
                continue
            created = datetime.fromtimestamp(row.get('created_at',updated)/1000,timezone.utc).isoformat(timespec='milliseconds')
            name = (' '.join(str(row.get(k) or '') for k in ('first_name','last_name')).strip() or row.get('username') or 'CourseMate 同学')[:120]
            handle = str(row.get('username') or 'student-'+hashlib.sha256(subject.encode()).hexdigest()[:12])[:80]
            collision = c.execute('SELECT id FROM cmui_users WHERE handle=? AND id<>?',(handle,subject)).fetchone()
            if collision: handle='student-'+hashlib.sha256(subject.encode()).hexdigest()[:20]
            c.execute('INSERT INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,handle=excluded.handle',(subject,name,handle,created))
            public_id=old['public_id'] if old else uid('person_')
            active=not (row.get('banned') or row.get('deleted') or row.get('locked'))
            avatar=row.get('image_url') or ''
            if not isinstance(avatar,str) or not avatar.startswith('https://'): avatar=''
            c.execute('INSERT INTO cmui_directory(subject,public_id,active,updated_ms,created_ms,avatar) VALUES(?,?,?,?,?,?) ON CONFLICT(subject) DO UPDATE SET active=excluded.active,updated_ms=excluded.updated_ms,avatar=excluded.avatar',
                (subject,public_id,int(active),updated,int(row.get('created_at',updated)),avatar))
        if complete:
            for row in c.execute('SELECT subject FROM cmui_directory').fetchall():
                if row['subject'] not in seen:
                    c.execute('UPDATE cmui_directory SET active=0,updated_ms=? WHERE subject=? AND updated_ms<=?',
                              (snapshot_at_ms,row['subject'],snapshot_at_ms))


def resolve_recipient(db, public_id):
    row=db.one('SELECT subject,active FROM cmui_directory WHERE public_id=? OR subject=?',(public_id,public_id))
    if row:
        return row['subject'] if row['active'] else None
    return public_id  # legacy local relationships remain valid


def project_local_ids(db):
    with db.connect(True) as c:
        for row in c.execute('SELECT id FROM cmui_users WHERE id NOT IN (SELECT subject FROM cmui_directory)').fetchall():
            c.execute('INSERT INTO cmui_directory(subject,public_id,active,updated_ms,created_ms) VALUES(?,?,1,-1,-1)',
                      (row['id'],uid('person_')))


async def approved_sync(db, secret):
    import httpx
    snapshot_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    async with httpx.AsyncClient(base_url='https://api.clerk.com/v1/',
            headers={'Authorization':f'Bearer {secret}'},timeout=30,follow_redirects=False) as http:
        records=await ClerkDirectoryClient(http).fetch_users()
    sync_directory(db,records,complete=True,snapshot_at_ms=snapshot_at_ms)
    return len(records)


_GRANDFATHER_RECEIPT = 'verification_grandfather_registered_snapshot'


def grandfather_candidates(records, *, cutoff_ms, complete):
    """Select from a complete trusted registration snapshot, never UI timestamps."""
    if not complete:
        raise ValueError('A complete registered-user snapshot is required')
    if not isinstance(cutoff_ms, int) or isinstance(cutoff_ms, bool) or cutoff_ms < 0:
        raise ValueError('A nonnegative integer cutoff is required')
    latest = {}
    for row in records:
        subject = row.get('id')
        updated = row.get('updated_at')
        if not isinstance(subject, str) or not subject or not isinstance(updated, (int, float)) or isinstance(updated, bool) or not math.isfinite(updated):
            raise ValueError('Invalid trusted registration record')
        previous = latest.get(subject)
        if previous is None or updated > previous['updated_at']:
            latest[subject] = row
    candidates = []
    unknown = 0
    evidence_rows = []
    for subject, row in sorted(latest.items()):
        created = row.get('created_at')
        known = isinstance(created, (int, float)) and not isinstance(created, bool) and math.isfinite(created) and created >= 0
        active = not (row.get('banned') or row.get('deleted') or row.get('locked'))
        if not known:
            unknown += 1
        elif created <= cutoff_ms and active:
            candidates.append(subject)
        evidence_rows.append({'subject': subject, 'created_ms': created if known else None,
                              'updated_ms': row['updated_at'], 'active': active})
    digest = hashlib.sha256(json.dumps(evidence_rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'candidates': candidates, 'evidence': {'complete': True, 'cutoff_ms': cutoff_ms,
            'registered_count': len(latest), 'candidate_count': len(candidates),
            'unknown_created_at': unknown, 'snapshot_sha256': digest}}


def _grandfather_receipt(db, cutoff_ms, status):
    # Pin the operator-selected boundary before fetching, including failed runs.
    if not isinstance(cutoff_ms, int) or isinstance(cutoff_ms, bool) or cutoff_ms < 0:
        raise ValueError('A nonnegative integer cutoff is required')
    with db.connect(True) as c:
        cutoff = c.execute("SELECT value FROM cmui_meta WHERE key='verification_grandfather_cutoff'").fetchone()
        if cutoff:
            existing_ms = int(datetime.fromisoformat(cutoff['value'].replace('Z', '+00:00')).timestamp() * 1000)
            if existing_ms != cutoff_ms:
                raise ValueError('Registered snapshot cutoff conflicts with the fixed application cutoff')
        old = c.execute('SELECT value FROM cmui_meta WHERE key=?', (_GRANDFATHER_RECEIPT,)).fetchone()
        receipt = json.loads(old['value']) if old else None
        if receipt and receipt['cutoff_ms'] != cutoff_ms:
            raise ValueError('Registered snapshot cutoff cannot change across retries')
        if receipt and receipt['status'] == 'COMPLETED':
            return receipt
        value = {'status': status, 'cutoff_ms': cutoff_ms}
        c.execute('INSERT INTO cmui_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (_GRANDFATHER_RECEIPT, json.dumps(value)))
        if not cutoff:
            fixed = datetime.fromtimestamp(cutoff_ms / 1000, timezone.utc).isoformat(timespec='milliseconds')
            c.execute("INSERT INTO cmui_meta(key,value) VALUES('verification_grandfather_cutoff',?)", (fixed,))
        return value


def apply_grandfather_snapshot(db, records, *, cutoff_ms, complete):
    """Apply a separately approved registered-user correction once, atomically.

    A legacy local-only boundary is preserved, but cannot suppress this missing
    upstream coverage. Existing qualification methods are never overwritten.
    """
    receipt = _grandfather_receipt(db, cutoff_ms, 'VALIDATING')
    if receipt['status'] == 'COMPLETED':
        return receipt
    try:
        result = grandfather_candidates(records, cutoff_ms=cutoff_ms, complete=complete)
        at = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        receipt = {'status': 'COMPLETED', 'cutoff_ms': cutoff_ms, 'completed_at': at, **result}
        with db.connect(True) as c:
            latest = c.execute('SELECT value FROM cmui_meta WHERE key=?', (_GRANDFATHER_RECEIPT,)).fetchone()
            current = json.loads(latest['value'])
            if current['status'] == 'COMPLETED':
                return current
            for subject in result['candidates']:
                handle = 'student-' + hashlib.sha256(subject.encode()).hexdigest()[:20]
                c.execute('INSERT OR IGNORE INTO cmui_users(id,name,handle,created_at) VALUES(?,?,?,?)',
                          (subject, 'CourseMate 同学', handle, at))
                c.execute("INSERT INTO cmui_verification(owner,verified,method,verified_at,boundary_notes,updated_at) VALUES(?,1,'grandfathered',?,?,?) ON CONFLICT(owner) DO UPDATE SET verified=1,method='grandfathered',verified_at=excluded.verified_at,boundary_notes=excluded.boundary_notes,updated_at=excluded.updated_at WHERE cmui_verification.verified=0",
                          (subject, at, 'protected registered snapshot ' + result['evidence']['snapshot_sha256'], at))
            c.execute('UPDATE cmui_meta SET value=? WHERE key=?', (json.dumps(receipt), _GRANDFATHER_RECEIPT))
        return receipt
    except Exception:
        _grandfather_receipt(db, cutoff_ms, 'FAILED_RETRYABLE')
        raise


async def approved_grandfather(db, secret, *, cutoff_ms, http_client=None):
    receipt = _grandfather_receipt(db, cutoff_ms, 'FETCHING')
    if receipt['status'] == 'COMPLETED':
        return receipt
    try:
        if http_client is None:
            import httpx
            async with httpx.AsyncClient(base_url='https://api.clerk.com/v1/',
                    headers={'Authorization': f'Bearer {secret}'}, timeout=30, follow_redirects=False) as http:
                records = await ClerkDirectoryClient(http).fetch_users()
        else:
            records = await ClerkDirectoryClient(http_client).fetch_users()
        return apply_grandfather_snapshot(db, records, cutoff_ms=cutoff_ms, complete=True)
    except Exception:
        _grandfather_receipt(db, cutoff_ms, 'FAILED_RETRYABLE')
        raise


if __name__=='__main__':
    import argparse
    import asyncio
    import os
    from pathlib import Path
    from .db import Database
    parser=argparse.ArgumentParser(description='Explicit approved Clerk operations; directory sync alone grants no verification')
    parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--approved-clerk-sync',action='store_true',required=True)
    parser.add_argument('--approved-grandfather',action='store_true',help='Separate explicit approval to grant old registration eligibility')
    parser.add_argument('--cutoff-ms',type=int,help='Fixed trusted registration cutoff in Unix milliseconds; required for grandfather approval')
    args=parser.parse_args()
    if not args.database.is_file() or not os.getenv('CLERK_SECRET_KEY'):
        parser.error('An existing UI database and backend CLERK_SECRET_KEY are required')
    if args.approved_grandfather:
        if args.cutoff_ms is None or args.cutoff_ms < 0:
            parser.error('--approved-grandfather requires an explicit nonnegative --cutoff-ms')
        result=asyncio.run(approved_grandfather(Database(args.database),os.environ['CLERK_SECRET_KEY'],cutoff_ms=args.cutoff_ms))
        print(f"Registered snapshot: {result['status']}; qualified candidates: {result['evidence']['candidate_count']}")
    else:
        if args.cutoff_ms is not None:
            parser.error('--cutoff-ms requires --approved-grandfather')
        count=asyncio.run(approved_sync(Database(args.database),os.environ['CLERK_SECRET_KEY']))
        print(f'Directory synchronization complete: {count} records; no verification grants applied')
