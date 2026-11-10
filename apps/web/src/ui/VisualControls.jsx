import React from 'react';
import { cancelVisualJob, createVisual, fallbackVisualJob, getVisualJob, listMessageVisuals, retryVisualJob } from './api.js';
import { VisualJobStatus } from './VisualJobStatus.jsx';
import { defaultUiTranslate } from './UiLocale';

const TERMINAL = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'UNKNOWN']);
const LEGACY_PLACEHOLDER_ALT_TEXT = new Set(['main concept', 'show the supported concept.']);

function isLegacyPlaceholderJob(job) {
    const assets = Array.isArray(job.assets) ? job.assets : [];
    return job.status === 'COMPLETED'
        && assets.length > 0
        && assets.every(asset => asset.mime_type === 'image/svg+xml'
            && LEGACY_PLACEHOLDER_ALT_TEXT.has(String(asset.alt_text || '').trim().toLowerCase()));
}

function partitionJobsByFreshness(jobs) {
    const latest = new Map();
    const legacyIds = new Set(jobs.filter(isLegacyPlaceholderJob).map(job => job.id));
    const currentJobs = jobs.filter(job => !legacyIds.has(job.id));
    for (let index = currentJobs.length - 1; index >= 0; index -= 1) {
        const job = currentJobs[index];
        const key = job.action || `job:${job.id}`;
        if (!latest.has(key)) latest.set(key, job);
    }
    const latestIds = new Set([...latest.values()].map(job => job.id));
    return {
        latest: [...latest.values()],
        older: jobs.filter(job => legacyIds.has(job.id) || !latestIds.has(job.id)),
    };
}

export class VisualControls extends React.Component {
    state = { jobs: [], busy: false, error: '', historyOpen: false };
    timers = new Map();
    revision = 0;
    componentDidMount() { this.load(); }
    componentDidUpdate(previous) {
        if (previous.message.id !== this.props.message.id || previous.pairId !== this.props.pairId || previous.courseId !== this.props.courseId) {
            this.stopAll(); this.setState({ jobs: [], error: '', historyOpen: false }, () => this.load());
        } else if (!previous.assistanceEnabled && this.props.assistanceEnabled) {
            this.load();
        }
    }
    componentWillUnmount() { this.unmounted = true; this.stopAll(); }
    stopAll() { this.revision += 1; for (const timer of this.timers.values()) clearTimeout(timer); this.timers.clear(); }
    replace = job => this.setState(state => ({ jobs: state.jobs.some(item => item.id === job.id) ? state.jobs.map(item => item.id === job.id ? job : item) : [...state.jobs, job] }));
    async load() {
        if (!this.props.enabled || !this.props.pairId) return;
        const revision = ++this.revision;
        try {
            const result = await listMessageVisuals(this.props.courseId, this.props.message.id);
            if (this.unmounted || revision !== this.revision) return;
            const jobs = result.items || [];
            this.setState({ jobs, error: '' });
            for (const job of result.items || []) if (!TERMINAL.has(job.status)) this.poll(job.id, revision);
            if (this.props.autoEnabled && this.props.assistanceEnabled && jobs.length === 0) {
                const autoKey = `visual-auto-${this.props.message.id}`.slice(0, 200);
                if (this.autoStartedFor !== autoKey) {
                    this.autoStartedFor = autoKey;
                    await this.create('auto', autoKey);
                }
            }
        } catch (error) { if (!this.unmounted && revision === this.revision) this.setState({ error: error.message }); }
    }
    async create(action, requestId = null) {
        if (this.state.busy) return;
        if (['visual', 'animate'].includes(action) && !this.props.assistanceEnabled) {
            this.props.requestAssistance?.(() => this.create(action, requestId));
            return;
        }
        this.setState({ busy: true, error: '' });
        try {
            const job = requestId
                ? await createVisual(this.props.courseId, this.props.message.id, this.props.pairId, action, requestId)
                : await createVisual(this.props.courseId, this.props.message.id, this.props.pairId, action);
            this.replace(job); this.poll(job.id, this.revision);
        } catch (error) { this.setState({ error: error.message }); this.props.toast?.(error.message); }
        finally { if (!this.unmounted) this.setState({ busy: false }); }
    }
    poll(jobId, revision) {
        if (this.timers.has(jobId)) return;
        const tick = async () => {
            this.timers.delete(jobId);
            try {
                const job = await getVisualJob(jobId);
                if (this.unmounted || revision !== this.revision) return;
                this.replace(job);
                if (!TERMINAL.has(job.status)) this.timers.set(jobId, setTimeout(tick, 1000));
            } catch (error) { if (!this.unmounted && revision === this.revision) this.setState({ error: error.message }); }
        };
        this.timers.set(jobId, setTimeout(tick, 300));
    }
    async cancel(jobId) {
        this.setState(state => ({ jobs: state.jobs.map(job => job.id === jobId ? { ...job, status: 'CANCELLED' } : job) }));
        try { this.replace(await cancelVisualJob(jobId)); } catch (error) { this.setState({ error: error.message }); await this.load(); }
    }
    async retry(jobId) {
        try { const job = await retryVisualJob(jobId); this.replace(job); this.poll(job.id, this.revision); }
        catch (error) { this.setState({ error: error.message }); }
    }
    async fallback(jobId) {
        try { const job = await fallbackVisualJob(jobId); this.replace(job); this.poll(job.id, this.revision); }
        catch (error) { this.setState({ error: error.message }); }
    }
    render() {
        if (!this.props.enabled || !this.props.pairId) return null;
        const t = this.props.t || defaultUiTranslate;
        const { latest, older } = partitionJobsByFreshness(this.state.jobs);
        return <div className="visual-controls">
            <div className="visual-actions" aria-label={t('visual.actions')}>
                <button type="button" disabled={this.state.busy} onClick={() => this.create('diagram')}>{t('visual.diagram')}</button>
                <button type="button" disabled={this.state.busy} onClick={() => this.create('visual')}>{t('visual.image')}</button>
                <button type="button" disabled={this.state.busy} onClick={() => this.create('animate')}>{t('visual.animation')}</button>
            </div>
            {this.state.error && <p className="visual-error">{this.state.error}</p>}
            {latest.map(job => <VisualJobStatus key={job.id} job={job} t={t} onCancel={id => this.cancel(id)} onRetry={id => this.retry(id)} onFallback={id => this.fallback(id)}/>)}
            {older.length > 0 && <button type="button" className="visual-history-toggle" aria-expanded={this.state.historyOpen} onClick={() => this.setState(state => ({ historyOpen: !state.historyOpen }))}>
                {t('visual.history', { count: older.length })}
            </button>}
            {this.state.historyOpen && older.map(job => <VisualJobStatus key={job.id} job={job} t={t} onCancel={id => this.cancel(id)} onRetry={id => this.retry(id)} onFallback={id => this.fallback(id)}/>)}
        </div>;
    }
}
