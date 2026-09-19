"""Operator-only frozen send recovery. No providers, source files or course imports.

Run from services/rag-api: python -m app.cm_update.share_recovery
--database <isolated ui.sqlite3> --share <id> [--apply]. Default is inspection.
All send workers must run the lock-aware version before using this tool.
"""
from contextlib import contextmanager
import asyncio
import hashlib
import json
import os
from pathlib import Path

from .db import Database, now, uid


class RecoveryBusy(RuntimeError):
    pass


async def settle(task):
    """Drain owned work before releasing file exclusion, even on repeated cancel."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        # Retrieve any child exception, then honour the caller's cancellation.
        if not task.cancelled(): task.exception()
        raise asyncio.CancelledError
    return task.result()


async def file_io(function, *args):
    # A Future, not a cancellable asyncio Task wrapping to_thread: shutdown's
    # all_tasks cancellation must not mark OS I/O complete before it really is.
    future = asyncio.get_running_loop().run_in_executor(None, function, *args)
    return await settle(future)


@contextmanager
def send_lock(root: Path):
    """OS-owned nonblocking exclusion; process exit releases it, age never does."""
    with (Path(root) / '.share-send.lock').open('a+b') as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RecoveryBusy('Send/recovery worker active; no changes made') from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def publish(db, share_id, manifest):
    """The existing atomic ready+notice boundary, with frozen recipient intent."""
    with db.connect(True) as connection:
        row = connection.execute('SELECT * FROM cmui_shares WHERE id=?', (share_id,)).fetchone()
        if row['status'] == 'ready':
            return
        connection.execute("UPDATE cmui_shares SET status='ready',manifest_json=? WHERE id=?",
                           (json.dumps(manifest, ensure_ascii=False), share_id))
        for recipient in manifest['send_recovery']['recipients']:
            connection.execute("INSERT OR IGNORE INTO cmui_share_recipients(share,recipient,status) VALUES (?,?,'notified')", (share_id, recipient))
            connection.execute('INSERT OR IGNORE INTO cmui_notifications(id,owner,actor,kind,ref,course,text,created_at) VALUES (?,?,?,?,?,?,?,?)',
                               (uid('notice_'), recipient, row['sender'], 'course_share', share_id, row['course'],
                                manifest['send_recovery']['notice'], now()))


def _check_archive(db, database, row, manifest):
    intent = manifest.get('send_recovery')
    if not isinstance(intent, dict) or intent.get('version') != 1:
        raise ValueError('Legacy send has no frozen recipient/lock protocol; manual offline review required')
    recipients = intent.get('recipients')
    if not isinstance(recipients, list) or not recipients or len(set(recipients)) != len(recipients):
        raise ValueError('Invalid frozen recipient intent')
    for recipient in recipients:
        if not db.one('SELECT id FROM cmui_users WHERE id=?', (recipient,)):
            return False
        if db.one('SELECT owner FROM cmui_blocks WHERE (owner=? AND blocked=?) OR (owner=? AND blocked=?)',
                  (row['sender'], recipient, recipient, row['sender'])):
            return False
    files = manifest['files']
    archived = db.all('SELECT * FROM cmui_share_files WHERE share=?', (row['id'],))
    if {f['id'] for f in files} != {f['file_id'] for f in archived} or len(files) != len(archived):
        return False
    root = database.parent.resolve()
    for item in files:
        receipt = next(f for f in archived if f['file_id'] == item['id'])
        path = root / receipt['archived_storage_key']
        # Never read through a sender path, symlink or a different share archive.
        archive_root = root / 'shares' / row['id']
        if not path.resolve().is_relative_to(archive_root) or any(p.is_symlink() for p in (path, *path.parents)):
            return False
        try:
            content = path.read_bytes()
            if len(content) != item['size'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                return False
            if intent['integrated']:
                index_path = Path(str(path) + '.index.json')
                if index_path.is_symlink() or hashlib.sha256(index_path.read_bytes()).hexdigest() != item.get('index_sha256'):
                    return False
        except OSError:
            return False
    return True


def recover(database: Path, share_id: str, *, apply=False):
    database = Path(database).resolve()
    if not database.is_file():
        raise ValueError('Explicit existing UI database required; initialization is forbidden')
    with send_lock(database.parent):
        db = Database(database)
        row = db.one('SELECT * FROM cmui_shares WHERE id=?', (share_id,))
        if not row:
            raise ValueError('Unknown share')
        if row['status'] == 'ready':
            return {'status': 'ready', 'action': 'ready', 'applied': False}
        manifest = json.loads(row['manifest_json'])
        complete = _check_archive(db, database, row, manifest)
        action = 'ready' if complete else 'failed'
        if apply:
            if complete:
                publish(db, share_id, manifest)
            else:
                db.execute("UPDATE cmui_shares SET status='failed' WHERE id=? AND status='preparing'", (share_id,))
        return {'status': row['status'], 'action': action, 'applied': apply,
                'reason': 'frozen_archive_complete' if complete else 'incomplete_or_invalid_no_source_fallback'}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    parser.add_argument('--share', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(recover(args.database, args.share, apply=args.apply)))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f'Recovery refused: {error}\n')


if __name__ == '__main__':
    main()
