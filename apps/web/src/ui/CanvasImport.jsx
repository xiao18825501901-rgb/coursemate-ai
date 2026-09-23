import React from 'react';

import { Icon } from './icons.jsx';
import {
    BRIDGE_STEPS,
    cancelImport,
    cancelLocalSession,
    connectUrl,
    connectableInstitutions,
    connections as listConnections,
    courses as listCourses,
    disconnect,
    importStatus,
    institutionForAddress,
    institutions as listInstitutions,
    localBridgeCapability,
    localSession,
    LOCAL_STATUS_LABELS,
    openLocalSession,
    outcomeFromSearch,
    OUTCOME_MESSAGES,
    reasonFor,
    selectLocalCourses,
    setCanvasTokenGetter,
    startImport,
    TOKEN_STEPS,
    TOKEN_WARNING,
    bridgeCommand,
    forgetTaskCredential,
    needsCredentialMessage,
    openTaskCredential,
    taskCourses,
    taskCredentialOf,
    taskCredentialReasonFor,
    taskCredentialState,
    taskCredentialStateLabel,
    TASK_CREDENTIAL_POLICY_NOTE,
    TASK_CREDENTIAL_STEPS,
    TASK_CREDENTIAL_WARNING,
} from './canvasImport.js';

/**
 * The Canvas import wizard.
 *
 * The product goal is "connect your own school Canvas → choose your courses → CourseJesus builds you
 * a private course". Two ways reach a school, and the difference is not cosmetic:
 *
 *   * **OAuth** is the path for every user: the school's own authorisation page, opened as a
 *     full-page navigation. It is the primary button.
 *   * **The local bridge** is the fallback for a school that has not issued a Developer Key yet.
 *     The user runs a tool on their own machine; a Personal Access Token is read there through a
 *     hidden prompt and kept by the operating system. It sits behind a secondary entry, and the page
 *     says plainly what not to do.
 *
 * Three things this screen must never do, because the server refuses them anyway but a UI that
 * pretended otherwise would be lying to the student:
 *
 *   * it never asks for a personal access token in a form field **on the public path** — the OAuth
 *     screen and the local bridge have no input for one anywhere, and a token pasted there has
 *     nowhere to go. The single exception is the one-off task credential below, which the server
 *     offers only to listed accounts on a deployment that enables it, and which says on the step
 *     where the token is pasted that the token does reach the server;
 *   * it never offers a school the server says is not `connectable`; it shows why and puts the local
 *     paths in front of the student instead;
 *   * it never claims an import is done. Progress comes from the job the server owns.
 *
 * The third way to a school — the one-off task credential — is the owner's testing route: a token is
 * pasted for exactly one import, the server holds it in memory, and it is destroyed once the Canvas
 * reads are finished. The screen shows the lifecycle state the server reports (`PRESENT_TRANSIENTLY`,
 * `DESTROYED`, `EXPIRED`, `LOST_ON_RESTART`) rather than claiming the token is gone.
 */

const POLL_MS = 1500;
const FINISHED = ['COMPLETED', 'COMPLETED_WITH_WARNINGS', 'NEEDS_REAUTH', 'FAILED', 'CANCELLED'];

export function CanvasImportLink({ onClick, className = '' }) {
    return <button type="button" className={('canvas-import-link ' + className).trim()} onClick={onClick}>
        <Icon name="upload"/><span className="canvas-import-link-label">从 Canvas 导入</span>
    </button>;
}

/** The steps a user follows in Canvas, shown only under the local-token entry. */
export function LocalTokenSteps() {
    return <div className="canvas-import-token">
        <ol className="canvas-import-token-steps">
            {TOKEN_STEPS.map(step => <li key={step}>{step}</li>)}
        </ol>
        <p className="canvas-import-warning">{TOKEN_WARNING}</p>
    </div>;
}

/**
 * The five steps of the one-off task credential, and what makes it different.
 *
 * This is the only place in the product where a Canvas token is meant to be pasted into the page,
 * so it is also the only place that has to say so: the warning states that the token reaches the
 * server, the policy note states that no school has approved it for students, and the lifecycle
 * label below the form reports what the server says happened to the credential afterwards.
 */
export function TaskCredentialSteps() {
    return <div className="canvas-import-token">
        <ol className="canvas-import-token-steps">
            {TASK_CREDENTIAL_STEPS.map(step => <li key={step}>{step}</li>)}
        </ol>
        <p className="canvas-import-warning">{TASK_CREDENTIAL_WARNING}</p>
        <p className="canvas-import-policy">{TASK_CREDENTIAL_POLICY_NOTE}</p>
    </div>;
}

export class CanvasImport extends React.Component {
    state = {
        step: 'loading', institutions: [], credentialsReady: null, connections: [],
        connection: null, courses: [], selected: [], saveConnection: false,
        job: null, error: '', busy: false, localOpen: false, otherSchool: '',
        bridge: null, bridgeCode: '', bridgeCourses: [], bridgeSelected: [],
        // The one-off task credential: what the server offers this account, the pasted value while
        // it is being submitted, the reference the server returned and the stage of the flow.
        taskCredential: { available: false, reason: 'TASK_CREDENTIAL_DISABLED', ownerOnly: true },
        taskOpen: false, taskStage: 'paste', taskToken: '', taskPicked: '', task: null,
    };
    poll = null;
    bridgePoll = null;

    async componentDidMount() {
        setCanvasTokenGetter(() => window.CourseMateAuth?.getToken?.() || null);
        const outcome = outcomeFromSearch(window.location.search);
        if (outcome) this.props.toast?.(OUTCOME_MESSAGES[outcome]);
        await this.load();
    }

    componentWillUnmount() {
        if (this.poll) clearTimeout(this.poll);
        if (this.bridgePoll) clearTimeout(this.bridgePoll);
    }

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
                taskCredential: taskCredentialOf(body),
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

    /** The school the user picked, whether from the list or by typing an address. */
    pickSchool(key) {
        this.setState({ picked: key, error: '' });
    }

    async openBridge() {
        const { picked, otherSchool, institutions } = this.state;
        let key = picked;
        if (key === 'other') {
            const match = institutionForAddress({ institutions }, otherSchool);
            if (!match) {
                this.setState({
                    error: '这所学校还没有在 CourseJesus 开通，请先按下面的方式在本地导入，' +
                        '或把学校地址告诉我们以便申请开通。',
                });
                return;
            }
            key = match.key;
        }
        if (!key) {
            this.setState({ error: '请先选择一所学校。' });
            return;
        }
        this.setState({ busy: true, error: '' });
        try {
            const capability = await localBridgeCapability();
            if (!capability.localBridgeEnabled) {
                this.setState({ busy: false, error: '本地导入工具在当前部署里没有开启。' });
                return;
            }
            const opened = await openLocalSession(key);
            this.setState({
                busy: false, step: 'bridge', bridge: opened, bridgeCode: opened.code,
                bridgeCourses: [], bridgeSelected: [],
            });
            this.watchBridge(opened.sessionId);
        }
        catch (error) {
            this.setState({ busy: false, error: error.message });
        }
    }

    async watchBridge(sessionId) {
        try {
            const status = await localSession(sessionId);
            this.setState({ bridge: status, bridgeCourses: status.courses || [] });
            if (!FINISHED.includes(status.status) && status.status !== 'EXPIRED') {
                this.bridgePoll = setTimeout(() => this.watchBridge(sessionId), POLL_MS);
            }
            else {
                this.props.onFinished?.();
            }
        }
        catch (error) {
            this.setState({ error: error.message });
        }
    }

    async confirmBridgeSelection() {
        const { bridge, bridgeSelected } = this.state;
        if (!bridge || !bridgeSelected.length) return;
        this.setState({ busy: true, error: '' });
        try {
            await selectLocalCourses(bridge.sessionId, bridgeSelected);
            const status = await localSession(bridge.sessionId);
            this.setState({ busy: false, bridge: status });
            this.watchBridge(bridge.sessionId);
        }
        catch (error) {
            this.setState({ busy: false, error: error.message });
        }
    }

    async cancelBridge() {
        const { bridge } = this.state;
        if (!bridge) return;
        try {
            await cancelLocalSession(bridge.sessionId);
            this.setState({ step: 'connect', bridge: null, bridgeCode: '' });
        }
        catch (error) {
            this.setState({ error: error.message });
        }
    }

    toggleCourse(id) {
        const selected = this.state.selected.includes(id)
            ? this.state.selected.filter(x => x !== id)
            : [...this.state.selected, id];
        this.setState({ selected });
    }

    toggleBridgeCourse(id) {
        const selected = this.state.bridgeSelected.includes(id)
            ? this.state.bridgeSelected.filter(x => x !== id)
            : [...this.state.bridgeSelected, id];
        this.setState({ bridgeSelected: selected });
    }

    async start() {
        const { connection, selected, saveConnection, task } = this.state;
        if (!connection || !selected.length) return;
        this.setState({ busy: true, error: '' });
        try {
            // A task credential is never "saved for reuse": the server accepts it for one job and
            // destroys it. The flag is therefore false whenever a reference is used, whatever the
            // screen was showing before.
            const credentialRef = task?.credentialRef || '';
            const job = await startImport(
                connection.connectionId, selected, credentialRef ? false : saveConnection, credentialRef);
            this.setState({ busy: false, step: 'job', job: { ...job, files: 0, byStatus: {} } });
            this.watch(job.jobId);
        }
        catch (error) {
            this.setState({ busy: false, error: error.message });
        }
    }

    /* ------------------------------------------------- the one-off task credential (owner mode) */

    /** Paste a token for one task: the server reads the Canvas identity before holding anything. */
    async openTask() {
        const { picked, otherSchool, institutions, taskToken } = this.state;
        const token = (taskToken || '').trim();
        if (!token) {
            this.setState({ error: '请先粘贴 Canvas Token。' });
            return;
        }
        let key = picked;
        let baseUrl = '';
        if (key === 'other') {
            const match = institutionForAddress({ institutions }, otherSchool);
            if (!match) {
                this.setState({
                    error: '这所学校还没有在 CourseJesus 登记，无法确认它的地址；请选择列表里的学校。',
                });
                return;
            }
            key = match.key;
            baseUrl = otherSchool;
        }
        if (!key) {
            this.setState({ error: '请先选择一所学校。' });
            return;
        }
        this.setState({ busy: true, error: '' });
        try {
            const opened = await openTaskCredential(token, { institutionKey: key, canvasBaseUrl: baseUrl });
            const list = await taskCourses(opened.connectionId, opened.credentialRef);
            this.setState({
                busy: false, taskStage: 'select', task: opened, courses: list.courses || [],
                selected: [], connection: null,
                // The pasted value is not kept in component state once the server has it.
                taskToken: '',
            });
        }
        catch (error) {
            this.setState({ busy: false, error: error.message, taskToken: '' });
        }
    }

    /** Ask what the server says happened to the credential, rather than assuming. */
    async refreshTaskState() {
        const ref = this.state.task?.credentialRef;
        if (!ref) return;
        try {
            const state = await taskCredentialState(ref);
            this.setState({ task: { ...this.state.task, ...state } });
        }
        catch (error) {
            this.setState({ error: error.message });
        }
    }

    /** Destroy it now. The user does not have to wait for the task to finish. */
    async forgetTask(reason) {
        const ref = this.state.task?.credentialRef;
        if (!ref) return;
        try {
            const result = await forgetTaskCredential(ref, reason);
            this.setState({
                task: { ...this.state.task, state: result.state, readCalls: result.readCalls },
                job: this.state.job ? { ...this.state.job, credentialState: result.state } : null,
            });
        }
        catch (error) {
            this.setState({ error: error.message });
        }
    }

    backToPaste() {
        this.setState({ taskStage: 'paste', task: null, courses: [], selected: [], error: '' });
    }

    async watch(jobId) {
        try {
            const status = await importStatus(jobId);
            this.setState({ job: status });
            if (!FINISHED.includes(status.status)) {
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
    /**
     * The school choice, shared by both screens.
     *
     * It is a radio list plus an address field rather than a set of per-school buttons, because the
     * revised flow needs the user to name their school once and then choose how to reach it: the
     * school's own authorisation page, or the local bridge when the school has no Developer Key yet.
     * A typed address is matched against the registry and never used to contact anything: an
     * unregistered host is reported as not open rather than being tried.
     */
    renderSchoolPicker() {
        const { institutions, picked, otherSchool } = this.state;
        return <fieldset className="canvas-import-picker">
            <legend>选择你的学校</legend>
            {institutions.map(item => <label key={item.key} className="canvas-import-school">
                <input type="radio" name="canvas-school" checked={picked === item.key} onChange={() => this.pickSchool(item.key)}/>
                <span><strong>{item.label}</strong><small>{item.origin}</small></span>
            </label>)}
            <label className="canvas-import-school">
                <input type="radio" name="canvas-school" checked={picked === 'other'} onChange={() => this.pickSchool('other')}/>
                <span><strong>其他 Canvas 学校</strong><small>输入学校 Canvas 地址</small></span>
            </label>
            {picked === 'other' && <input
                type="url"
                className="canvas-import-address"
                placeholder="https://canvas.example.edu"
                aria-label="学校 Canvas 地址"
                value={otherSchool}
                onChange={event => this.setState({ otherSchool: event.target.value })}
            />}
        </fieldset>;
    }

    renderUnavailable() {
        const { institutions, error } = this.state;
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">等待学校开通 Canvas 连接</p>
            <ul className="canvas-import-schools">
                {institutions.map(item => <li key={item.key}>
                    <strong>{item.label}</strong>
                    <small>{reasonFor(item.reason) || '暂时无法连接'}</small>
                </li>)}
            </ul>
            {this.renderSchoolPicker()}
            {error && <p className="error-text">{error}</p>}
            <p className="helper-note">在开通之前，可以用下面的本地方式导入，或者直接在本地创建课程并上传资料。</p>
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                <button type="button" className="btn primary" onClick={() => { this.props.close?.(); this.props.localUpload?.(); }}>
                    <Icon name="plus"/>上传本地资料
                </button>
                <button type="button" className="btn" onClick={() => this.openBridge()}>用本地 Token 导入</button>
                <button type="button" className="btn" onClick={() => this.load()}>重新检查</button>
            </div>
            <button type="button" className="canvas-import-secondary" onClick={() => this.setState({ localOpen: !this.state.localOpen })}>
                无法连接？查看本地 Token 导入方式
            </button>
            {this.state.localOpen && <LocalTokenSteps/>}
            {this.renderTaskEntry()}
        </div>;
    }

    renderConnect() {
        const { busy, picked } = this.state;
        const connectable = connectableInstitutions({ institutions: this.state.institutions });
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">从 Canvas 导入课程</p>
            <p className="helper-note">连接你的学校 Canvas 后，CourseJesus 只会读取你选择导入的课程资料，并把它们创建为你自己的私人课程。</p>
            {this.renderSchoolPicker()}
            {connectable.length > 0
                ? <button type="button" className="btn primary" disabled={busy || !picked} onClick={() => this.connect(picked)}>
                    连接 Canvas
                </button>
                : <p className="helper-note">这所学校还没有开通官方授权连接；可以先用下面的本地方式导入。</p>}
            <p className="helper-note">本站不接收个人访问令牌，也不会保存它；只能用学校的官方授权页面。</p>
            <button type="button" className="canvas-import-secondary" onClick={() => this.setState({ localOpen: !this.state.localOpen })}>
                无法连接？查看本地 Token 导入方式
            </button>
            {this.state.localOpen && <>
                <LocalTokenSteps/>
                <button type="button" className="btn" disabled={busy || !picked} onClick={() => this.openBridge()}>
                    用本地 Token 导入
                </button>
            </>}
            {this.renderTaskEntry()}
        </div>;
    }

    renderBridge() {
        const { bridge, bridgeCode, bridgeCourses, bridgeSelected, busy, error } = this.state;
        const status = bridge?.status || 'OPEN';
        const selectable = status === 'CLAIMED';
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">用本地 Token 导入</p>
            <p className="helper-note">{LOCAL_STATUS_LABELS[status] || status}</p>
            {error && <p className="error-text">{error}</p>}
            {status === 'OPEN' && <>
                <p className="helper-note">在你的电脑上运行下面的命令，然后按提示隐藏输入 Canvas Token：</p>
                <code className="canvas-import-code">{bridgeCommand(bridgeCode)}</code>
                <p className="helper-note">这个连接码 {bridge?.expiresAt ? `在 ${bridge.expiresAt} 前有效，` : ''}只能使用一次，而且只属于你；它不含任何 Token。</p>
            </>}
            {selectable && <>
                <p className="helper-note">工具已经读到你的课程。选择要导入的课程：</p>
                <div className="canvas-import-courses">
                    {bridgeCourses.map(course => <label key={course.canvasCourseId} className="canvas-import-course">
                        <input
                            type="checkbox"
                            checked={bridgeSelected.includes(course.canvasCourseId)}
                            onChange={() => this.toggleBridgeCourse(course.canvasCourseId)}
                        />
                        <span>
                            <strong>{course.name || course.canvasCourseId}</strong>
                            <small>
                                {course.courseCode}{course.term ? ' · ' + course.term : ''}
                                {course.enrollmentState ? ' · ' + course.enrollmentState : ''}
                                {course.fileCount ? ` · ${course.fileCount} 个文件` : ''}
                            </small>
                        </span>
                    </label>)}
                </div>
                <p className="helper-note">默认不勾选任何课程；只有你勾选的课程会被下载和导入。课程会建成你自己的私人课程。</p>
                <button type="button" className="btn primary" disabled={busy || !bridgeSelected.length} onClick={() => this.confirmBridgeSelection()}>
                    开始导入{bridgeSelected.length ? `（${bridgeSelected.length} 门课程）` : ''}
                </button>
            </>}
            {['SELECTED', 'IMPORTING'].includes(status) && <>
                <p className="helper-note">本地工具正在下载并上传你选择的课程资料，这一页会持续显示进度。</p>
                <ul className="canvas-import-progress">
                    {Object.entries(bridge?.counts || {}).map(([state, count]) => <li key={state}><span>{state}</span><strong>{count}</strong></li>)}
                </ul>
            </>}
            {status === 'EXPIRED' && <p className="helper-note">连接码已经过期，请回到上一步重新生成一个。</p>}
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                {!FINISHED.includes(status) && <button type="button" className="btn" onClick={() => this.cancelBridge()}>取消导入</button>}
                <button type="button" className="btn" onClick={() => this.setState({ step: 'connect', bridge: null })}>返回</button>
            </div>
        </div>;
    }

    /* ---------------------------------------------- the one-off task credential, rendered */

    /** The secondary entry, offered only when the server says this account may use it. */
    renderTaskEntry() {
        const { taskCredential, taskOpen } = this.state;
        if (!taskCredential?.available) {
            // A deployment that has not enabled it shows nothing at all: not a disabled button,
            // which would advertise a path nobody can take.
            return null;
        }
        return <>
            <button type="button" className="canvas-import-secondary" onClick={() => this.setState({ taskOpen: !taskOpen })}>
                一次性 Token 导入（站长模式）
            </button>
            {taskOpen && <>
                <p className="canvas-import-policy">{TASK_CREDENTIAL_POLICY_NOTE}</p>
                <button type="button" className="btn" onClick={() => this.setState({ step: 'taskToken', taskStage: 'paste', error: '' })}>
                    用一次性 Token 导入
                </button>
            </>}
        </>;
    }

    renderTaskToken() {
        const { task, taskStage, taskToken, courses, selected, busy, error } = this.state;
        if (taskStage === 'paste') {
            return <div className="canvas-import-step canvas-task">
                <p className="canvas-import-lead">一次性 Token 导入</p>
                <TaskCredentialSteps/>
                {this.renderSchoolPicker()}
                <label className="canvas-task-token">
                    <span>Canvas Token（个人访问令牌）</span>
                    <input
                        type="password"
                        autoComplete="off"
                        spellCheck={false}
                        aria-label="Canvas Token"
                        placeholder="粘贴仅用于本次导入的 Token"
                        value={taskToken}
                        onChange={event => this.setState({ taskToken: event.target.value })}
                    />
                </label>
                <p className="helper-note">
                    这个 Token 只用于读取你选择的课程资料；服务器读完文件后会立即销毁它，
                    之后的解析与索引不再使用它。
                </p>
                {error && <p className="error-text">{error}</p>}
                <div className="row" style={{ gap: 10, marginTop: 14 }}>
                    <button type="button" className="btn primary" disabled={busy || !taskToken} onClick={() => this.openTask()}>
                        确认学校账号
                    </button>
                    <button type="button" className="btn" onClick={() => this.setState({ step: 'connect', error: '' })}>
                        返回
                    </button>
                </div>
            </div>;
        }
        const readable = courses.filter(course => course.readable);
        return <div className="canvas-import-step canvas-task">
            <p className="canvas-import-lead">选择要导入的课程</p>
            <p className="helper-note">
                已读取到 Canvas 账号：{task?.canvasName || '（未命名）'}
                {task?.canvasUserId ? `（ID ${task.canvasUserId}）` : ''} · 只显示你作为学生已加入且可读的课程。
            </p>
            <p className="canvas-import-policy">
                本次凭据状态：{taskCredentialStateLabel(task?.state)}
                {task?.readCalls ? ` · 已读取 ${task.readCalls} 次` : ''}
            </p>
            {error && <p className="error-text">{error}</p>}
            {busy && <p className="helper-note">正在读取课程…</p>}
            {!busy && !readable.length && <div className="empty-state">这所学校账号下暂时没有可导入的课程。</div>}
            <div className="canvas-import-courses">
                {readable.map(course => <label key={course.id} className="canvas-import-course">
                    <input type="checkbox" checked={selected.includes(course.id)} onChange={() => this.toggleCourse(course.id)}/>
                    <span><strong>{course.name}</strong><small>{course.courseCode}{course.term ? ' · ' + course.term : ''}</small></span>
                </label>)}
            </div>
            {readable.length > 0 && <button type="button" className="btn primary" disabled={busy || !selected.length} onClick={() => this.start()}>
                开始导入{selected.length ? `（${selected.length} 门课程）` : ''}
            </button>}
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                <button type="button" className="btn" onClick={() => this.forgetTask('user_disconnected')}>
                    立即销毁 Token
                </button>
                <button type="button" className="btn" onClick={() => this.refreshTaskState()}>刷新凭据状态</button>
                <button type="button" className="btn" onClick={() => this.backToPaste()}>换一个 Token</button>
            </div>
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
        const finished = FINISHED.includes(job.status);
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">{this.statusLine()}</p>
            <p className="helper-note">共 {job.files || 0} 个文件{job.courses ? ` · ${job.courses} 门课程` : ''}{job.errorCode ? ` · ${job.errorCode}` : ''}</p>
            {job.byStatus && Object.keys(job.byStatus).length > 0 && <ul className="canvas-import-progress">
                {Object.entries(job.byStatus).map(([status, count]) => <li key={status}><span>{status}</span><strong>{count}</strong></li>)}
            </ul>}
            {job.errorMessage && <p className="helper-note">{job.errorMessage}</p>}
            {job.status === 'COMPLETED_WITH_WARNINGS' && <p className="helper-note">有些文件没有被读取（例如图片或扫描件）：原件已经保存在课程里，但不会计入可学习资料。</p>}
            {job.status === 'NEEDS_REAUTH' && <p className="helper-note">请重新连接学校账号，未完成的文件会继续导入。</p>}
            {/* A job that borrowed a one-off credential says what happened to it, and asks for a
                new one when the imports it still has to do cannot proceed without it. */}
            {job.credentialKind === 'transient_task' && <p className="canvas-import-policy">
                本次导入使用一次性 Token：{taskCredentialStateLabel(job.credentialState)}
                {job.credentialState === 'DESTROYED' ? '（文件读取完成后已销毁，索引不再使用它）' : ''}
            </p>}
            {needsCredentialMessage(job) && <p className="helper-note">{needsCredentialMessage(job)}</p>}
            {error && <p className="error-text">{error}</p>}
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                {!finished && <button type="button" className="btn" onClick={() => this.cancel()}>取消导入</button>}
                {job.credentialKind === 'transient_task' && this.state.task?.state === 'PRESENT_TRANSIENTLY'
                    && <button type="button" className="btn" onClick={() => this.forgetTask('task_cancelled')}>
                        立即销毁 Token
                    </button>}
                {job.needsCredential && <button type="button" className="btn primary" onClick={() => this.setState({ step: 'taskToken', taskStage: 'paste', error: '' })}>
                    重新粘贴 Token
                </button>}
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
            {step === 'bridge' && this.renderBridge()}
            {step === 'taskToken' && this.renderTaskToken()}
            {step === 'select' && this.renderSelect()}
            {step === 'job' && this.renderJob()}
        </div>;
    }
}
