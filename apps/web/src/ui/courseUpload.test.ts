import { afterEach, expect, it, vi } from 'vitest';
import { uploadCourseFile } from './courseUpload';
import { request } from './api.js';
import { putSignedObject, sha256 } from '../services/directUpload';

vi.mock('./api.js', () => ({ request: vi.fn() }));
vi.mock('../services/directUpload', () => ({ sha256: vi.fn(), putSignedObject: vi.fn() }));
afterEach(() => vi.clearAllMocks());

it('uses one grant and retries only completion after uncertain PUT', async () => {
  vi.mocked(sha256).mockResolvedValue('a'.repeat(64));
  vi.mocked(request).mockResolvedValueOnce({ method: 'PUT', uploadId: 'u1' })
    .mockResolvedValueOnce({ id: 'doc1', status: 'indexed' });
  vi.mocked(putSignedObject).mockRejectedValueOnce(new Error('connection lost'));
  const item = { file: new File(['source'], 'course.md'), clientItemId: 'item1' };
  await expect(uploadCourseFile('course1', item, 'batch1')).rejects.toThrow('connection lost');
  await expect(uploadCourseFile('course1', item, 'batch2')).resolves.toMatchObject({ id: 'doc1' });
  expect(putSignedObject).toHaveBeenCalledTimes(1);
  expect(request).toHaveBeenCalledTimes(2);
  expect(vi.mocked(request).mock.calls[1]?.[0]).toBe('/courses/course1/direct-uploads/u1/complete');
});

it('uses the old multipart route only when the host explicitly returns FALLBACK', async () => {
  vi.mocked(sha256).mockResolvedValue('b'.repeat(64));
  vi.mocked(request).mockResolvedValueOnce({ method: 'FALLBACK' }).mockResolvedValueOnce({ id: 'local' });
  await uploadCourseFile('c', { file: new File(['x'], 'x.md'), clientItemId: 'i' }, 'batch', 'folder');
  expect(putSignedObject).not.toHaveBeenCalled();
  expect(vi.mocked(request).mock.calls[1]?.[0]).toBe('/courses/c/files');
});

it('confirms an existing file without sending its bytes again', async () => {
  vi.mocked(sha256).mockResolvedValue('c'.repeat(64));
  vi.mocked(request).mockResolvedValueOnce({ method: 'EXISTING', file: { id: 'existing', duplicate: true, status: 'indexed' } });
  const result = await uploadCourseFile('c', { file: new File(['known'], 'known.md'), clientItemId: 'new-selection' }, 'batch');
  expect(result).toMatchObject({ id: 'existing', duplicate: true });
  expect(putSignedObject).not.toHaveBeenCalled();
  expect(request).toHaveBeenCalledTimes(1);
});
