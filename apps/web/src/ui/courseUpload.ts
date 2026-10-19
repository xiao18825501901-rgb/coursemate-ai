import { request } from './api.js';
import { putSignedObject, sha256 } from '../services/directUpload';
import type { DirectUploadGrant } from '../services/directUpload';

// Queue re-renders copy item objects but retain File identity. Keep an uncertain
// upload's identity so Retry confirms that session, rather than resending bytes.
const sessions = new WeakMap<File, Map<string, DirectUploadGrant>>();

export async function uploadCourseFile(
  course: string, item: { file: File; clientItemId: string }, batchId: string, folder = '',
) {
  const path = `/courses/${encodeURIComponent(course)}`;
  const batch = { batch_id: batchId, batch_item_id: item.clientItemId.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 100) };
  let byCourse = sessions.get(item.file);
  if (!byCourse) { byCourse = new Map(); sessions.set(item.file, byCourse); }
  let grant = byCourse.get(course);
  if (!grant) {
    const result = await request(`${path}/direct-uploads`, {
      method: 'POST', body: JSON.stringify({ filename: item.file.name,
        mediaType: item.file.type || 'application/octet-stream', byteSize: item.file.size,
        sha256: await sha256(item.file) }),
    });
    if (result.method === 'EXISTING') return result.file;
    if (result.method === 'FALLBACK') {
      const body = new FormData();
      body.append('file', item.file); body.append('folder', folder);
      body.append('batch_id', batch.batch_id); body.append('batch_item_id', batch.batch_item_id);
      return request(`${path}/files`, { method: 'POST', body });
    }
    grant = result as DirectUploadGrant;
    byCourse.set(course, grant);
    await putSignedObject(grant, item.file);
  }
  return request(`${path}/direct-uploads/${encodeURIComponent(grant.uploadId)}/complete`, {
    method: 'POST', body: JSON.stringify(batch),
  });
}
