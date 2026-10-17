import React from 'react';
import { VisualAssetCard } from './VisualAssetCard.jsx';
import { defaultUiTranslate } from './UiLocale';

export function VisualJobStatus({ job, onCancel, onRetry, onFallback, t = defaultUiTranslate }) {
    const active = ['QUEUED', 'PLANNING', 'WAITING_FOR_RENDERER', 'RENDERING', 'VALIDATING', 'RETRYING'].includes(job.status);
    const statusKey = `visual.status.${job.status}`;
    const translatedStatus = t(statusKey);
    const statusLabel = translatedStatus === statusKey ? job.status : translatedStatus;
    return <section className={'visual-job visual-' + job.status.toLowerCase()} aria-live="polite" aria-busy={active}>
        <div className="visual-job-head"><strong>{job.cache_hit ? t('visual.cacheHit') : statusLabel}</strong>
            {active && <button type="button" onClick={() => onCancel(job.id)}>{t('visual.cancel')}</button>}
            {job.status === 'FAILED' && job.retry_count < 1 && <button type="button" onClick={() => onRetry(job.id)}>{t('visual.retry')}</button>}
            {job.status === 'FAILED' && job.fallback_available && <button type="button" onClick={() => onFallback(job.id)}>{t('visual.fallback')}</button>}
        </div>
        {job.status === 'FAILED' && <p className="visual-error">{t('visual.failure', { code: job.error_code || t('visual.diagnosticSaved') })}</p>}
        {job.assets?.map(asset => <VisualAssetCard key={asset.id} asset={asset} t={t}/>)}
    </section>;
}
