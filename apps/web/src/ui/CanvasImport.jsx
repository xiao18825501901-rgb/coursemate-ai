import React from 'react';

import { Icon } from './icons.jsx';
import {
    cancelImport,
    connectUrl,
    connectableInstitutions,
    connections as listConnections,
    courses as listCourses,
    disconnect,
    importStatus,
    institutions as listInstitutions,
    outcomeFromSearch,
    OUTCOME_MESSAGES,
    reasonFor,
    setCanvasTokenGetter,
    startImport,
} from './canvasImport.js';

/**
 * The Canvas import wizard (task B2's UI half).
 *
 * Three things it must never do, because the server refuses them anyway but a UI that pretended
 * otherwise would be lying to the student:
 *
 *   * it never asks for a personal access token — the only route to a school is that school's own
 *     authorisation page, opened as a full-page navigation;
 *   * it never offers a school that the server says is not `connectable`; it shows why, and puts
 *     the local upload path in front of the student instead;
 *   * it never claims an import is done. Progress comes from the job the server owns, and a job
 *     that finished with warnings or needs re-authorisation says so.
 */

const POLL_MS = 1500;

export function CanvasImportLink({ onClick, className = '' }) {
    return <button type="button" className={('canvas-import-link ' + className).trim()} onClick={onClick}>
        <Icon name="upload"/><span className="canvas-import-link-label">从 Canvas 导入</span>
    </button>;
}

export class CanvasImport extends React.Component {
    state = {
        step: 'loading', institutions: [], credentialsReady: null, connections: [],
        connection: null, courses: [], selected: [], saveConnection: false,
        job: null, error: '', busy: false,
    };
    poll = null;

    async componentDidMount() {
        setCanvasTokenGetter(() => window.CourseMateAuth?.getToken?.() || null);
        const outcome = outcomeFromSearch(window.location.search);
        if (outcome) this.props.toast?.(OUTCOME_MESSAGES[outcome]);
        await this.load();
    }

    componentWillUnmount() { if (this.poll) clearTimeout(this.poll); }

    async load() {
        this.setState({ error: '' });
        try {
            const [body, existing] = await Promise.all([listInstitutions(), listConnections()]);
            const connectable = connectableInstitutions(body);
            const connection = existing.connections[0] || null;
            this.setState({
                institutions: body.institutions || [],
                credentialsReady: body.credentialsReady,
                connections: existing.connections || [],
                connection,
                step: connectable.length ? (connection ? 'select' : 'connect') : 'unavailable',
            }, () => { if (this.state.step === 'select' && connection) this.loadCourses(connection); });
        }
        catch (error) {
            this.setState({ step: 'unavailable', error: error.message });
        }
    }

    async loadCourses(connection) {
        this.setState({ busy: true, error: '' });
        try {
            const body = await listCourses(connection.connectionId);
            this.setState({ courses: body.courses || [], busy: false });
        }
        catch (error) {
            this.setState({ busy: false, error: error.message });
        }
    }

    async connect(key) {
        // A full-page navigation: the school must redirect the browser itself, and the server
        // brings the user back to this page with the outcome in the query string.
        window.location.assign(connectUrl(key));
    }

    toggleCourse(id) {
        const selected = this.state.selected.includes(id)
            ? this.state.selected.filter(x => x !== id)
            : [...this.state.selected, id];
        this.setState({ selected });
    }

    async start() {
        const { connection, selected, saveConnection } = this.state;
        if (!connection || !selected.length) return;
        this.setState({ busy: true, error: '' });
        try {
            const job = await startImport(connection.connectionId, selected, saveConnection);
            this.setState({ busy: false, step: 'job', job: { ...job, files: 0, byStatus: {} } });
            this.watch(job.jobId);
        }
        catch (error) {
            this.setState({ busy: false, error: error.message });
        }
    }

    async watch(jobId) {
        try {
            const status = await importStatus(jobId);
            this.setState({ job: status });
            if (!['COMPLETED', 'COMPLETED_WITH_WARNINGS', 'NEEDS_REAUTH', 'FAILED', 'CANCELLED'].includes(status.status)) {
                this.poll = setTimeout(() => this.watch(jobId), POLL_MS);
            }
            else {
                this.props.onFinished?.();
            }
        }
        catch (error) {
            this.setState({ error: error.message });
        }
    }

    async cancel() {
        try {
            await cancelImport(this.state.job.jobId);
            await this.watch(this.state.job.jobId);
        }
        catch (error) {
            this.setState({ error: error.message });
        }
    }

    async disconnect() {
        const { connection } = this.state;
        if (!connection || !window.confirm('断开这所学校？已导入的资料会保留。')) return;
        try {
            await disconnect(connection.connectionId);
            this.setState({ connection: null, courses: [], selected: [] }, () => this.load());
        }
        catch (error) {
            this.setState({ error: error.message });
        }
    }

    /* ------------------------------------------------------------------ rendering */
    renderUnavailable() {
        const { institutions, error } = this.state;
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">学校连接尚未开通</p>
            <ul className="canvas-import-schools">
                {institutions.map(item => <li key={item.key}>
                    <strong>{item.label}</strong>
                    <small>{reasonFor(item.reason) || '暂时无法连接'}</small>
                </li>)}
            </ul>
            {error && <p className="error-text">{error}</p>}
            <p className="helper-note">在开通之前，可以先在本地创建课程并上传资料；导入功能开通后，这里会出现连接按钮。</p>
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                <button type="button" className="btn primary" onClick={() => { this.props.close?.(); this.props.localUpload?.(); }}>
                    <Icon name="plus"/>上传本地资料
                </button>
                <button type="button" className="btn" onClick={() => this.load()}>重新检查</button>
            </div>
        </div>;
    }

    renderConnect() {
        const connectable = connectableInstitutions({ institutions: this.state.institutions });
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">连接你的学校账号</p>
            <p className="helper-note">只读取你本人的课程与资料，不会上传、提交作业或改动学校数据；授权随时可以断开。</p>
            <div className="canvas-import-actions">
                {connectable.map(item => <button type="button" key={item.key} className="btn primary" onClick={() => this.connect(item.key)}>
                    连接 {item.label}
                </button>)}
            </div>
            <p className="helper-note">本站不接收个人访问令牌；只能用学校的官方授权页面。</p>
        </div>;
    }

    renderSelect() {
        const { courses, selected, busy, error, saveConnection, connection } = this.state;
        const readable = courses.filter(course => course.readable);
        return <div className="canvas-import-step">
            <div className="row between">
                <p className="canvas-import-lead">选择要导入的课程</p>
                <button type="button" className="btn small" onClick={() => this.disconnect()}>断开连接</button>
            </div>
            <p className="helper-note">{connection?.canvasName ? `已连接：${connection.canvasName}` : '已连接学校账号'} · 只显示你作为学生已加入且可读的课程。</p>
            {error && <p className="error-text">{error}</p>}
            {busy && <p className="helper-note">正在读取课程…</p>}
            {!busy && !readable.length && <div className="empty-state">这所学校账号下暂时没有可导入的课程。</div>}
            <div className="canvas-import-courses">
                {readable.map(course => <label key={course.id} className="canvas-import-course">
                    <input type="checkbox" checked={selected.includes(course.id)} onChange={() => this.toggleCourse(course.id)}/>
                    <span><strong>{course.name}</strong><small>{course.courseCode}{course.term ? ' · ' + course.term : ''}</small></span>
                </label>)}
            </div>
            {readable.length > 0 && <>
                <label className="check-line"><input type="checkbox" checked={saveConnection} onChange={e => this.setState({ saveConnection: e.target.checked })}/>保存这次连接，之后可以继续同步新资料</label>
                <p className="helper-note">不勾选时，导入作业结束并过了重试窗口后就会清除凭据；已导入的资料不受影响。</p>
                <button type="button" className="btn primary" disabled={busy || !selected.length} onClick={() => this.start()}>
                    开始导入{selected.length ? `（${selected.length} 门课程）` : ''}
                </button>
            </>}
        </div>;
    }

    statusLine() {
        const labels = {
            QUEUED: '排队中', DISCOVERING: '正在读取课程', AWAITING_SELECTION: '等待选择',
            DOWNLOADING: '正在下载资料', VERIFYING: '正在校验文件', INGESTING: '正在建立课程资料',
            INDEXING: '正在生成索引', COMPLETED: '导入完成',
            COMPLETED_WITH_WARNINGS: '导入完成，但有需要你留意的文件',
            NEEDS_REAUTH: '学校授权已失效，需要重新连接', FAILED: '导入失败', CANCELLED: '已取消',
        };
        return labels[this.state.job?.status] || this.state.job?.status || '';
    }

    renderJob() {
        const { job, error } = this.state;
        if (!job) return null;
        const finished = ['COMPLETED', 'COMPLETED_WITH_WARNINGS', 'NEEDS_REAUTH', 'FAILED', 'CANCELLED'].includes(job.status);
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">{this.statusLine()}</p>
            <p className="helper-note">共 {job.files || 0} 个文件{job.courses ? ` · ${job.courses} 门课程` : ''}{job.errorCode ? ` · ${job.errorCode}` : ''}</p>
            {job.byStatus && Object.keys(job.byStatus).length > 0 && <ul className="canvas-import-progress">
                {Object.entries(job.byStatus).map(([status, count]) => <li key={status}><span>{status}</span><strong>{count}</strong></li>)}
            </ul>}
            {job.errorMessage && <p className="helper-note">{job.errorMessage}</p>}
            {job.status === 'COMPLETED_WITH_WARNINGS' && <p className="helper-note">有些文件没有被读取（例如图片或扫描件）：原件已经保存在课程里，但不会计入可学习资料。</p>}
            {job.status === 'NEEDS_REAUTH' && <p className="helper-note">请重新连接学校账号，未完成的文件会继续导入。</p>}
            {error && <p className="error-text">{error}</p>}
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                {!finished && <button type="button" className="btn" onClick={() => this.cancel()}>取消导入</button>}
                <button type="button" className="btn primary" onClick={() => { this.props.close?.(); this.props.onFinished?.(); }}>完成</button>
            </div>
        </div>;
    }

    render() {
        const { step } = this.state;
        return <div className="canvas-import">
            {step === 'loading' && <p className="helper-note">正在检查学校连接状态…</p>}
            {step === 'unavailable' && this.renderUnavailable()}
            {step === 'connect' && this.renderConnect()}
            {step === 'select' && this.renderSelect()}
            {step === 'job' && this.renderJob()}
        </div>;
    }
}
