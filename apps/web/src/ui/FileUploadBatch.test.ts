import { afterEach, describe, expect, it, vi } from 'vitest';

import { runUploadBatch } from './FileUploadQueue.jsx';

describe('durable multi-file corpus batch', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('opens once, uploads each item, and seals every terminal result', async () => {
    window.COURSEMATE_CONFIG = { apiBase: '/api/ui/v1' };
    const requests: Array<{ url: string; init: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
      requests.push({ url, init });
      return new Response(JSON.stringify({ status: requests.length === 1 ? 'OPEN' : 'SEALED' }), {
        status: requests.length === 1 ? 201 : 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }));
    const items = [
      { clientItemId: 'item-one', file: {}, name: 'one.md', size: 1, status: 'queued' },
      { clientItemId: 'item-two', file: {}, name: 'two.md', size: 1, status: 'queued' },
    ];
    const batchIds: string[] = [];

    const result = await runUploadBatch(
      'course one',
      items,
      async (item: { clientItemId: string }, batchId: string) => {
        batchIds.push(batchId);
        if (item.clientItemId === 'item-two') throw Object.assign(new Error('nope'), { code: 'BAD' });
        return { id: 'doc-one', status: 'indexed' };
      },
      () => undefined,
      2,
    );

    expect(result.failed).toBe(1);
    expect(new Set(batchIds).size).toBe(1);
    expect(requests).toHaveLength(2);
    expect(requests[0]!.url).toBe('/api/ui/v1/courses/course%20one/file-batches');
    expect(JSON.parse(String(requests[0]!.init.body))).toMatchObject({ expected_items: 2 });
    expect(requests[1]!.url).toContain(`/file-batches/${batchIds[0]}/seal`);
    expect(JSON.parse(String(requests[1]!.init.body)).items).toEqual([
      { item_key: 'item-one', status: 'INDEXED', document_id: 'doc-one', error_code: null },
      { item_key: 'item-two', status: 'FAILED', document_id: null, error_code: 'BAD' },
    ]);
  });
});
