"""UI course IDs mapped to the existing owner's private direct-upload host."""
from threading import BoundedSemaphore

from app.errors import ApiError
from app.models import DirectUploadCreate

_parse_slot = BoundedSemaphore(1)

def _workspace(adapter, subject, payload):
    course = str(payload['course'])
    adapter._course_row(course, subject, write=False)
    workspace = adapter._workspace_row(course, subject)
    if workspace is None:
        raise ApiError(409, 'WORKSPACE_UNAVAILABLE', 'No upload workspace is available.')
    return workspace


def begin_upload(adapter, subject, payload):
    workspace = _workspace(adapter, subject, payload)
    try:
        grant = adapter.ingestion.begin_direct_upload(
            course_id=workspace['private_course_id'],
            payload=DirectUploadCreate.model_validate({k: v for k, v in payload.items() if k != 'course'}),
            owner_user_id=subject, is_admin=False,
        )
    except ApiError as error:
        if error.code != 'DUPLICATE_DOCUMENT':
            raise
        document_id = str(error.details.get('documentId') or '')
        existing = next((row for row in adapter._file_rows(str(payload['course']), subject)
                         if row['id'] == document_id), None)
        if existing is None:
            raise
        return {'method': 'EXISTING', 'file': {**existing, 'duplicate': True}}
    return grant.model_dump(mode='json', by_alias=True)


def complete_upload(adapter, subject, payload):
    workspace = _workspace(adapter, subject, payload)
    upload_id = str(payload['upload_id'])
    with adapter.database.connect() as db:
        session = db.execute(
            'SELECT course_id FROM storage_upload_sessions WHERE id=? AND owner_user_id=?',
            (upload_id, subject),
        ).fetchone()
    if session is None or session['course_id'] != workspace['private_course_id']:
        raise ApiError(404, 'UPLOAD_NOT_FOUND', 'Upload not found in this course.')
    batch = str(payload.get('batch_id') or '')
    item = str(payload.get('batch_item_id') or '')
    if bool(batch) != bool(item):
        raise ApiError(422, 'AUTO_BATCH_INVALID', 'Both batch identifiers are required.')
    if batch:
        if adapter.auto_knowledge_map is None:
            raise ApiError(503, 'AUTO_BATCH_UNAVAILABLE', 'Batch coordinator unavailable.')
        adapter.auto_knowledge_map.record_upload_batch_item(
            batch_id=batch, item_key=item, course_id=payload['course'],
            owner_user_id=subject, status='ACCEPTED',
        )
    accepted = adapter.ingestion.finalize_direct_upload(
        upload_id=upload_id, owner_user_id=subject, is_admin=False,
    )
    # One parser in the supported single-worker host; never hold a DB transaction
    # while waiting. Re-read after acquisition so repeated completion cannot
    # index the same document twice. The existing cache guard handles capacity.
    with _parse_slot:
        document = adapter._document_row(accepted.document.id)
        if document['status'] not in {'ready', 'processing'}:
            adapter.ingestion.process_document(accepted.document.id, accepted.job.id)
    result = next((row for row in adapter._file_rows(str(payload['course']), subject)
                   if row['id'] == accepted.document.id), None)
    if result is None:
        raise ApiError(500, 'UPLOAD_LOST', 'Uploaded document could not be confirmed.')
    if batch:
        adapter.auto_knowledge_map.record_upload_batch_item(
            batch_id=batch, item_key=item, course_id=payload['course'], owner_user_id=subject,
            status='INDEXED' if result['status'] == 'indexed' else 'FAILED',
            document_id=accepted.document.id,
            error_code=None if result['status'] == 'indexed' else 'INGESTION_PENDING_OR_FAILED',
        )
    return result
