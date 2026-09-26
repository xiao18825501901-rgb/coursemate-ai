import React from 'react';

import { formatBytes } from './utils.js';

const STATUS_LABELS = {
    queued: '等待上传',
    uploading: '正在上传',
    succeeded: '已完成',
    failed: '上传失败',
};

function resultLabel(item) {
    if (item.result?.duplicate) return '已存在，未重复索引';
    return {
        indexed: '可检索',
        processing: '文件已接收，处理中',
        preview_only: '原文件已保存，无可检索文字',
        failed: '原文件已保存，处理失败',
        unavailable: '文件状态不可用',
    }[item.result?.status] || STATUS_LABELS[item.status];
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
    const worker = async () => {
        while (next < items.length) {
            const item = items[next++];
            onChange(item.clientItemId, { status: 'uploading', error: '' });
            try {
                const result = await upload(item);
                onChange(item.clientItemId, { status: 'succeeded', error: '', result });
            }
            catch (error) {
                failed += 1;
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
    return { failed, succeeded: items.length - failed };
}

export function FileUploadQueue({ items, busy = false, onRemove, onRetry }) {
    if (!items.length) return null;
    const succeeded = items.filter(item => item.status === 'succeeded').length;
    const processing = items.filter(item => item.status === 'uploading').length;
    const failed = items.filter(item => item.status === 'failed').length;
    return <div className="upload-queue" aria-label="文件上传队列">
        <p className="upload-queue-summary" aria-live="polite">
            已完成 {succeeded}/{items.length} · 处理中 {processing} 个{failed ? ` · 失败 ${failed} 个` : ''}
        </p>
        {items.map(item => <div className={`upload-queue-item ${item.status}`} key={item.clientItemId}>
            <div className="upload-queue-copy">
                <strong title={item.name}>{item.name}</strong>
                <small>{formatBytes(item.size)} · {resultLabel(item)}</small>
                {item.error && <span className="upload-queue-error" role="alert">{item.error}</span>}
            </div>
            <div className="upload-queue-actions">
                {item.status === 'failed' && <button type="button" className="btn small" disabled={busy} onClick={() => onRetry?.(item.clientItemId)}>只重试此项</button>}
                {['queued', 'failed'].includes(item.status) && <button type="button" className="icon-btn" aria-label={`移除 ${item.name}`} title="从队列移除" disabled={busy} onClick={() => onRemove?.(item.clientItemId)}>×</button>}
            </div>
        </div>)}
    </div>;
}
