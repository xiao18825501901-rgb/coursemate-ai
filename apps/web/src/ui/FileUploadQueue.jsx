import React from 'react';

import { formatBytes } from './utils.js';
import { request } from './api.js';
import { UiLocaleContext } from './UiLocale';

const STATUS_KEYS = {
    queued: 'fileQueue.queued',
    uploading: 'courses.uploading',
    succeeded: 'fileQueue.completed',
    failed: 'courses.uploadFailed',
};

function resultLabel(item, t) {
    if (item.result?.duplicate) return t('fileQueue.duplicate');
    const key = {
        indexed: 'fileQueue.indexed',
        processing: 'fileQueue.processing',
        preview_only: 'fileQueue.previewOnly',
        failed: 'fileQueue.processingFailed',
        unavailable: 'fileQueue.unavailable',
    }[item.result?.status] || STATUS_KEYS[item.status] || 'common.unknown';
    return t(key);
}

function clientItemId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** Keep every selected File as its own queue item, including same-name files. */
export function uploadItemsFrom(fileList) {
    return Array.from(fileList || [], file => ({
        clientItemId: clientItemId(),
        file,
        name: file.name,
        size: file.size,
        status: 'queued',
        error: '',
        result: null,
    }));
}

/** A small bounded worker pool shared by create-course and append-files. */
export async function runUploadItems(items, upload, onChange, concurrency = 2) {
    let next = 0;
    let failed = 0;
    const completed = [];
    const worker = async () => {
        while (next < items.length) {
            const item = items[next++];
            onChange(item.clientItemId, { status: 'uploading', error: '' });
            try {
                const result = await upload(item);
                completed.push({ item, result, error: null });
                onChange(item.clientItemId, { status: 'succeeded', error: '', result });
            }
            catch (error) {
                failed += 1;
                completed.push({ item, result: null, error });
                onChange(item.clientItemId, {
                    status: 'failed',
                    error: error instanceof Error ? error.message : String(error),
                    result: null,
                });
            }
        }
    };
    const count = Math.min(Math.max(1, concurrency), items.length);
    await Promise.all(Array.from({ length: count }, () => worker()));
    return { failed, succeeded: items.length - failed, completed };
}

/**
 * One browser selection is one durable corpus revision. Files still travel
 * through the existing single-file API with the existing two-worker pool; the
 * begin/seal envelope only prevents a partial course map between items.
 */
export async function runUploadBatch(courseId, items, upload, onChange, concurrency = 2) {
    if (!items.length) return { failed: 0, succeeded: 0, completed: [] };
    const suffix = clientItemId().replace(/[^A-Za-z0-9_-]/g, '_');
    const batchId = `upload_${suffix}`.slice(0, 100);
    await request(`/courses/${encodeURIComponent(courseId)}/file-batches`, {
        method: 'POST',
        body: JSON.stringify({ batch_id: batchId, expected_items: items.length }),
    });
    const outcome = await runUploadItems(
        items,
        item => upload(item, batchId),
        onChange,
        concurrency,
    );
    const manifest = outcome.completed.map(({ item, result, error }) => ({
        item_key: item.clientItemId.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 100),
        status: error || result?.status === 'failed' ? 'FAILED' : 'INDEXED',
        document_id: result?.id || null,
        error_code: error ? (error.code || 'UPLOAD_FAILED') : (result?.status === 'failed' ? 'INGESTION_FAILED' : null),
    }));
    await request(`/courses/${encodeURIComponent(courseId)}/file-batches/${encodeURIComponent(batchId)}/seal`, {
        method: 'POST',
        body: JSON.stringify({ items: manifest }),
    });
    return { ...outcome, batchId };
}

export function FileUploadQueue({ items, busy = false, onRemove, onRetry }) {
    const { t } = React.useContext(UiLocaleContext);
    if (!items.length) return null;
    const succeeded = items.filter(item => item.status === 'succeeded').length;
    const processing = items.filter(item => item.status === 'uploading').length;
    const failed = items.filter(item => item.status === 'failed').length;
    return <div className="upload-queue" aria-label={t('courses.queue')}>
        <p className="upload-queue-summary" aria-live="polite">
            {t('fileQueue.summary', {done:succeeded,total:items.length,processing})}
            {failed ? t('fileQueue.failedSummary', {count:failed}) : ''}
        </p>
        {items.map(item => <div className={`upload-queue-item ${item.status}`} key={item.clientItemId}>
            <div className="upload-queue-copy">
                <strong title={item.name}>{item.name}</strong>
                <small>{formatBytes(item.size)} · {resultLabel(item, t)}</small>
                {item.error && <span className="upload-queue-error" role="alert">{item.error}</span>}
            </div>
            <div className="upload-queue-actions">
                {item.status === 'failed' && <button type="button" className="btn small" disabled={busy} onClick={() => onRetry?.(item.clientItemId)}>{t('fileQueue.retryItem')}</button>}
                {['queued', 'failed'].includes(item.status) && <button type="button" className="icon-btn" aria-label={t('fileQueue.removeItem', {name:item.name})} title={t('fileQueue.removeTitle')} disabled={busy} onClick={() => onRemove?.(item.clientItemId)}>×</button>}
            </div>
        </div>)}
    </div>;
}
