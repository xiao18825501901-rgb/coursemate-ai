from test_backup_ui_extension import _fixture, _run, BACKUP_SCRIPT, RESTORE_SCRIPT
from pathlib import Path


def test_snapshot_bytes_and_index_are_in_recovery_unit(tmp_path):
    paths=_fixture(tmp_path)
    snapshot=paths['ui_data']/'shares'/'share-synthetic'
    snapshot.mkdir(parents=True)
    (snapshot/'frozen').write_bytes(b'frozen-v1')
    (snapshot/'frozen.index.json').write_text('{"synthetic":"index"}',encoding='utf-8')
    backup=_run(BACKUP_SCRIPT,{'RAG_DATABASE_PATH':str(paths['rag']),
        'AGENT_DATABASE_PATH':str(paths['agent']),'RAG_UPLOAD_DIR':str(paths['uploads']),
        'CMUI_DATA_DIR':str(paths['ui_data']),'BACKUP_ROOT':str(paths['backups'])})
    assert backup.returncode==0,backup.stderr
    source=Path(backup.stdout.strip().splitlines()[-1])
    restored=_run(RESTORE_SCRIPT,{'RESTORE_SOURCE':str(source),'RESTORE_TARGET':str(paths['target'])})
    assert restored.returncode==0,restored.stderr
    assert (paths['target']/'ui-shares'/'share-synthetic'/'frozen').read_bytes()==b'frozen-v1'
    assert (paths['target']/'ui-shares'/'share-synthetic'/'frozen.index.json').read_text(encoding='utf-8')=='{"synthetic":"index"}'
