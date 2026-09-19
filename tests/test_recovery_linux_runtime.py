"""Opt-in stdlib Linux restore acceptance; retains all synthetic artifacts.

Run: python3 tests/test_recovery_linux_runtime.py --artifact-root PROJECT/work/NEW_DIR
No providers, installations, production paths, or real application databases.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import tarfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'ops' / 'restore_v2.py'
SPEC = importlib.util.spec_from_file_location('linux_restore_under_test', SCRIPT)
RESTORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESTORE)
ARTIFACT_ROOT = None
BINARY = bytes(range(256)) + b'\x00synthetic-not-user-data\xff'


def checksums(source):
    names = ['rag.sqlite3', 'agent.sqlite3', 'ui.sqlite3', 'uploads.tar.gz',
             'ui-uploads.tar.gz', 'manifest.json', 'sqlite-check.txt']
    (source / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256((source / name).read_bytes()).hexdigest() + '  ' + name + '\n'
        for name in names), encoding='ascii')


def synthetic_backup(parent):
    source = parent / 'backup'
    source.mkdir()
    for name in ['rag.sqlite3', 'agent.sqlite3', 'ui.sqlite3']:
        with sqlite3.connect(source / name) as db:
            db.execute('CREATE TABLE synthetic_reference(id TEXT PRIMARY KEY, owner TEXT, document TEXT)')
            db.execute('INSERT INTO synthetic_reference VALUES(?,?,?)', ('record-1', 'synthetic-owner', 'synthetic-document'))
    for name, member, content in [('uploads.tar.gz', 'originals/binary.bin', BINARY),
                                  ('ui-uploads.tar.gz', 'attachment.bin', b'isolated-attachment\x00')]:
        with tarfile.open(source / name, 'w:gz') as archive:
            info = tarfile.TarInfo(member)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    manifest = {'formatVersion': 1, 'uploadFileCount': 1, 'uploadTotalBytes': len(BINARY),
                'uiUploadFileCount': 1, 'uiUploadTotalBytes': len(b'isolated-attachment\x00'),
                'artifacts': {'ui': 'ui.sqlite3', 'attachments': 'ui-uploads.tar.gz'}}
    (source / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (source / 'sqlite-check.txt').write_text('Synthetic fixture databases: integrity_check=ok\n', encoding='ascii')
    checksums(source)
    return source


class LinuxRuntimeRestore(unittest.TestCase):
    def setUp(self):
        if ARTIFACT_ROOT is None or not sys.platform.startswith('linux'):
            self.skipTest('Opt-in real Linux runtime runner requires --artifact-root; no platform simulation.')
        self.root = ARTIFACT_ROOT / self._testMethodName
        self.root.mkdir()

    def cli(self, source, target, *, resume=None, label='cli'):
        env = os.environ.copy()
        env.update(RESTORE_SOURCE=str(source), RESTORE_TARGET=str(target))
        env.pop('RESTORE_RESUME_PARTIAL', None)
        if resume:
            env['RESTORE_RESUME_PARTIAL'] = str(resume)
        command = [sys.executable, str(SCRIPT)]
        result = subprocess.run(command, env=env, cwd=REPO, text=True,
                                capture_output=True, timeout=30)
        (self.root / f'{label}.json').write_text(json.dumps({
            'command': command, 'RESTORE_SOURCE': str(source), 'RESTORE_TARGET': str(target),
            'RESTORE_RESUME_PARTIAL': str(resume) if resume else None,
            'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
        }, indent=2), encoding='utf-8')
        return result

    def assert_contents(self, target):
        self.assertEqual((target / 'uploads/originals/binary.bin').read_bytes(), BINARY)
        self.assertEqual((target / 'ui-uploads/attachment.bin').read_bytes(), b'isolated-attachment\x00')
        references = []
        for name in ['rag.sqlite3', 'agent.sqlite3', 'ui.sqlite3']:
            connection = sqlite3.connect(f'file:{target / name}?mode=ro', uri=True)
            try:
                self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                references.append(connection.execute('SELECT owner,document FROM synthetic_reference').fetchone())
            finally:
                connection.close()
        self.assertEqual(references, [('synthetic-owner', 'synthetic-document')] * 3)

    def test_native_renameat2_refuses_empty_and_nonempty_targets(self):
        for occupied in [False, True]:
            source = self.root / f'source-{occupied}'
            target = self.root / f'target-{occupied}'
            source.mkdir(); target.mkdir()
            (source / 'source-marker').write_bytes(b'source')
            if occupied:
                (target / 'target-marker').write_bytes(b'keep-me')
            with self.assertRaises(OSError) as caught:
                RESTORE._rename_no_replace(source, target)
            self.assertEqual(caught.exception.errno, errno.EEXIST)
            self.assertTrue((source / 'source-marker').is_file())
            self.assertFalse((target / 'source-marker').exists())
            if occupied:
                self.assertEqual((target / 'target-marker').read_bytes(), b'keep-me')

    def test_native_concurrent_publication_has_one_winner(self):
        sources = [self.root / 'source-a', self.root / 'source-b']
        for index, source in enumerate(sources):
            source.mkdir()
            (source / 'winner').write_text(str(index))
        target = self.root / 'target'
        barrier = threading.Barrier(2)
        def publish(source):
            barrier.wait(timeout=10)
            try:
                RESTORE._rename_no_replace(source, target)
                return 'published'
            except OSError as error:
                return error.errno
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(publish, sources))
        self.assertCountEqual(outcomes, ['published', errno.EEXIST])
        self.assertEqual(sum(source.exists() for source in sources), 1)
        self.assertIn((target / 'winner').read_text(), {'0', '1'})
        (self.root / 'native-race.json').write_text(json.dumps(outcomes))

    def test_fresh_top_level_restore_three_independent_targets(self):
        source = synthetic_backup(self.root)
        for number in range(1, 4):
            target = self.root / f'fresh-{number}'
            result = self.cli(source, target, label=f'fresh-{number}')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_contents(target)

    def test_top_level_refuses_existing_target(self):
        source = synthetic_backup(self.root)
        target = self.root / 'existing'
        target.mkdir()
        (target / 'keep').write_bytes(b'unchanged')
        result = self.cli(source, target)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Refusing to overwrite', result.stderr)
        self.assertEqual((target / 'keep').read_bytes(), b'unchanged')
        self.assertFalse(list(self.root.glob('.existing.*.partial')))

    def failed_publication(self):
        source = synthetic_backup(self.root)
        target = self.root / 'restored'
        native = RESTORE._rename_no_replace
        def racing_target(partial, destination):
            destination.mkdir()
            native(partial, destination)
        with patch.dict(os.environ, {'RESTORE_SOURCE': str(source), 'RESTORE_TARGET': str(target),
                                     'RESTORE_RESUME_PARTIAL': ''}), patch.object(RESTORE, '_rename_no_replace', racing_target):
            with self.assertRaises(FileExistsError):
                RESTORE.restore_backup()
        partials = list(self.root.glob('.restored.*.partial'))
        self.assertEqual(len(partials), 1)
        self.assert_contents(partials[0])
        self.assertEqual(list(target.iterdir()), [])
        # Only the exact empty racing target created above is removed; staging is retained.
        target.rmdir()
        (self.root / 'failed-publication.json').write_text(json.dumps({
            'fault': 'test-created racing target; real renameat2 returned EEXIST',
            'preserved_staging': str(partials[0]), 'target': str(target),
        }, indent=2))
        return source, target, partials[0]

    def test_failed_publication_retains_staging_then_explicit_resume(self):
        source, target, partial = self.failed_publication()
        result = self.cli(source, target, resume=partial, label='explicit-resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(partial.exists())
        self.assert_contents(target)

    def test_resume_rejects_staging_hash_change_and_preserves_evidence(self):
        source, target, partial = self.failed_publication()
        (partial / 'uploads/originals/binary.bin').write_bytes(b'tampered-synthetic-data')
        result = self.cli(source, target, resume=partial, label='reject-staged-hash')
        self.assertEqual(result.returncode, 2)
        self.assertIn('differs from verified archive', result.stderr)
        self.assertTrue(partial.is_dir())
        self.assertFalse(target.exists())

    def test_source_hash_and_invalid_manifest_are_rejected(self):
        source = synthetic_backup(self.root)
        (source / 'sqlite-check.txt').write_text('tampered synthetic checksum metadata')
        result = self.cli(source, self.root / 'bad-hash', label='reject-source-hash')
        self.assertEqual(result.returncode, 2)
        self.assertIn('checksum mismatch', result.stderr)
        manifest = json.loads((source / 'manifest.json').read_text())
        manifest['uploadFileCount'] = -1
        (source / 'manifest.json').write_text(json.dumps(manifest))
        checksums(source)
        result = self.cli(source, self.root / 'bad-manifest', label='reject-manifest')
        self.assertEqual(result.returncode, 2)
        self.assertIn('manifest is invalid', result.stderr)
        self.assertFalse(list(self.root.glob('.*.partial')))


def main():
    global ARTIFACT_ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact-root', required=True, type=Path)
    args = parser.parse_args()
    if not sys.platform.startswith('linux'):
        parser.error('Real Linux runtime required; do not simulate platform flags.')
    ARTIFACT_ROOT = args.artifact_root.resolve()
    native_project = (Path.home() / 'CourseMate-recovery-gate-20260919').resolve()
    if not (ARTIFACT_ROOT.is_relative_to((REPO / 'work').resolve()) or
            (ARTIFACT_ROOT != native_project and ARTIFACT_ROOT.is_relative_to(native_project))):
        parser.error('Artifacts must remain beneath repository work or the explicit native project test directory.')
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=False)
    filesystem = subprocess.run(['findmnt', '-T', str(ARTIFACT_ROOT), '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS', '-n'],
                                text=True, capture_output=True, check=True).stdout.strip()
    head = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True, capture_output=True).stdout.strip()
    metadata = {'kernel': platform.platform(), 'uname': list(os.uname()), 'python': sys.version,
                'filesystem': filesystem, 'artifact_root': str(ARTIFACT_ROOT), 'repository_head': head,
                'restore_script_sha256': hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                'test_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'scope': 'synthetic local WSL Linux on recorded filesystem, not production or general ext4 proof'}
    (ARTIFACT_ROOT / 'environment.json').write_text(json.dumps(metadata, indent=2))
    with (ARTIFACT_ROOT / 'unittest.log').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LinuxRuntimeRestore))
    summary = {'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
               'successful': result.wasSuccessful(), 'artifact_root': str(ARTIFACT_ROOT)}
    (ARTIFACT_ROOT / 'result.json').write_text(json.dumps(summary, indent=2))
    print((ARTIFACT_ROOT / 'unittest.log').read_text())
    print(json.dumps(summary))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
