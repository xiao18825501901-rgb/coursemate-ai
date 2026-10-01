import React from 'react';
import { VisualAssetCard } from './VisualAssetCard.jsx';

const LABELS = {
    QUEUED: '等待生成', PLANNING: '正在规划', RENDERING: '正在生成',
    VALIDATING: '正在校验', COMPLETED: '已完成', FAILED: '生成失败',
    CANCELLED: '已取消', RETRYING: '正在重试',
};

export function VisualJobStatus({ job, onCancel, onRetry, onFallback }) {
    const active = ['QUEUED', 'PLANNING', 'RENDERING', 'VALIDATING', 'RETRYING'].includes(job.status);
    return <section className={'visual-job visual-' + job.status.toLowerCase()} aria-live="polite" aria-busy={active}>
        <div className="visual-job-head"><strong>{job.cache_hit ? '已从安全缓存恢复' : (LABELS[job.status] || job.status)}</strong>
            {active && <button type="button" onClick={() => onCancel(job.id)}>取消</button>}
            {job.status === 'FAILED' && job.retry_count < 1 && <button type="button" onClick={() => onRetry(job.id)}>重试</button>}
            {job.status === 'FAILED' && job.fallback_available && <button type="button" onClick={() => onFallback(job.id)}>使用确定性图解</button>}
        </div>
        {job.status === 'FAILED' && <p className="visual-error">视觉生成未完成（{job.error_code || '诊断信息已保存'}），文字回答仍可正常使用。</p>}
        {job.assets?.map(asset => <VisualAssetCard key={asset.id} asset={asset}/>)}
    </section>;
}
