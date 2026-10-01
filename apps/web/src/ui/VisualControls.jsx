import React from 'react';
import { cancelVisualJob, createVisual, fallbackVisualJob, getVisualJob, listMessageVisuals, retryVisualJob } from './api.js';
import { VisualJobStatus } from './VisualJobStatus.jsx';

const TERMINAL = new Set(['COMPLETED', 'FAILED', 'CANCELLED']);

export class VisualControls extends React.Component {
    state = { jobs: [], busy: false, error: '' };
    timers = new Map();
    revision = 0;
    componentDidMount() { this.load(); }
    componentDidUpdate(previous) {
        if (previous.message.id !== this.props.message.id || previous.pairId !== this.props.pairId || previous.courseId !== this.props.courseId) {
            this.stopAll(); this.setState({ jobs: [], error: '' }, () => this.load());
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
            this.setState({ jobs: result.items || [], error: '' });
            for (const job of result.items || []) if (!TERMINAL.has(job.status)) this.poll(job.id, revision);
        } catch (error) { if (!this.unmounted && revision === this.revision) this.setState({ error: error.message }); }
    }
    async create(action) {
        if (this.state.busy) return;
        this.setState({ busy: true, error: '' });
        try {
            const job = await createVisual(this.props.courseId, this.props.message.id, this.props.pairId, action);
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
        return <div className="visual-controls">
            <div className="visual-actions" aria-label="视觉学习操作">
                <button type="button" disabled={this.state.busy} onClick={() => this.create('diagram')}>显示图解</button>
                <button type="button" disabled={this.state.busy} onClick={() => this.create('visual')}>生成视觉</button>
                <button type="button" disabled={this.state.busy} onClick={() => this.create('animate')}>动画展示</button>
            </div>
            {this.state.error && <p className="visual-error">{this.state.error}</p>}
            {this.state.jobs.map(job => <VisualJobStatus key={job.id} job={job} onCancel={id => this.cancel(id)} onRetry={id => this.retry(id)} onFallback={id => this.fallback(id)}/>)}
        </div>;
    }
}
