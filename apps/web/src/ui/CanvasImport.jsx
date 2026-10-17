import React from 'react';

import { Icon } from './icons.jsx';
import { UiLocaleContext, defaultUiTranslate } from './UiLocale';
import {
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
    loadBridgeReleaseManifest,
    localBridgeTicket,
    openLocalSession,
    outcomeFromSearch,
    resumeTaskCredential,
    selectLocalCourses,
    setCanvasTokenGetter,
    startImport,
    bridgeCommand,
    forgetTaskCredential,
    needsCredentialMessage,
    openTaskCredential,
    taskCourses,
    taskCredentialOf,
    taskCredentialState,
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
 *     The user runs a tool on their own machine; a Personal Access Token is read by its password
 *     field and kept only in that process memory. It sits behind a secondary entry, and the page
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

/** The steps a user follows in Canvas, shown only under the local-token entry. */
export function LocalTokenSteps({ t = defaultUiTranslate } = {}) {
    const steps = [0, 1, 2, 3, 4].map(index => t(`canvas.localTokenSteps.${index}`));
    return <div className="canvas-import-token">
        <ol className="canvas-import-token-steps">
            {steps.map(step => <li key={step}>{step}</li>)}
        </ol>
        <p className="canvas-import-warning">{t('canvas.localTokenWarning')}</p>
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
export function TaskCredentialSteps({ t = defaultUiTranslate } = {}) {
    const steps = [0, 1, 2, 3, 4].map(index => t(`canvas.taskSteps.${index}`));
    return <div className="canvas-import-token">
        <ol className="canvas-import-token-steps">
            {steps.map(step => <li key={step}>{step}</li>)}
        </ol>
        <p className="canvas-import-warning">{t('canvas.taskWarning')}</p>
        <p className="canvas-import-policy">{t('canvas.taskPolicy')}</p>
    </div>;
}

export class CanvasImport extends React.Component {
    static contextType = UiLocaleContext;
    t = (id, params) => (this.context?.t || defaultUiTranslate)(id, params);
    state = {
        step: 'loading', institutions: [], credentialsReady: null, connections: [],
        connection: null, courses: [], selected: [], saveConnection: false,
        job: null, error: '', busy: false, localOpen: false, otherSchool: '',
        bridge: null, bridgeCourses: [], bridgeSelected: [],
        bridgeTicket: '', bridgeInstitutionKey: '', bridgeRelease: null,
        bridgeReleaseError: '', bridgeNow: Date.now(),
        // The one-off task credential: what the server offers this account, the pasted value while
        // it is being submitted, the reference the server returned and the stage of the flow.
        taskCredential: { available: false, reason: 'TASK_CREDENTIAL_DISABLED', ownerOnly: true },
        taskOpen: false, taskStage: 'paste', taskToken: '', taskPicked: '', task: null,
        canvasAddress: '', resumeJobId: '',
    };
    poll = null;
    bridgePoll = null;
    bridgeClock = null;

    async componentDidMount() {
        setCanvasTokenGetter(() => window.CourseMateAuth?.getToken?.() || null);
        const outcome = outcomeFromSearch(window.location.search);
        if (outcome) this.props.toast?.(this.localizedEnum('canvas.outcome', outcome));
        this.loadBridgeRelease();
        this.bridgeClock = setInterval(() => this.setState({ bridgeNow: Date.now() }), 1_000);
        await this.load();
    }

    async loadBridgeRelease() {
        try {
            const bridgeRelease = await loadBridgeReleaseManifest();
            this.setState({ bridgeRelease, bridgeReleaseError: '' });
        }
        catch (error) {
            this.setState({ bridgeRelease: null, bridgeReleaseError: error.message });
        }
    }

    componentWillUnmount() {
        if (this.poll) clearTimeout(this.poll);
        if (this.bridgePoll) clearTimeout(this.bridgePoll);
        if (this.bridgeClock) clearInterval(this.bridgeClock);
    }

    async load() {
        this.setState({ error: '' });
        try {
            const [body, existing] = await Promise.all([listInstitutions(), listConnections()]);
            const connectable = connectableInstitutions(body);
            const connection = existing.connections[0] || null;
            const taskCredential = taskCredentialOf(body);
            this.setState({
                institutions: body.institutions || [],
                credentialsReady: body.credentialsReady,
                connections: existing.connections || [],
                connection,
                taskCredential,
                step: taskCredential.available
                    ? 'taskToken'
                    : (connectable.length ? (connection ? 'select' : 'connect') : 'unavailable'),
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
                    error: this.t('canvas.schoolNotRegistered'),
                });
                return;
            }
            key = match.key;
        }
        if (!key) {
            this.setState({ error: this.t('canvas.chooseSchoolFirst') });
            return;
        }
        this.setState({
            step: 'bridge', bridgeInstitutionKey: key, bridge: null, bridgeTicket: '',
            bridgeCourses: [], bridgeSelected: [], error: '',
        });
    }

    async generateBridge() {
        const { bridgeInstitutionKey } = this.state;
        if (!bridgeInstitutionKey) {
            this.setState({ error: this.t('canvas.chooseSchoolAgain') });
            return;
        }
        if (this.bridgePoll) clearTimeout(this.bridgePoll);
        this.setState({ busy: true, error: '' });
        try {
            const capability = await localBridgeCapability();
            if (!capability.localBridgeEnabled) {
                this.setState({ busy: false, error: this.t('canvas.bridgeDisabled') });
                return;
            }
            const opened = await openLocalSession(bridgeInstitutionKey);
            this.setState({
                busy: false, step: 'bridge', bridge: opened,
                bridgeCourses: [], bridgeSelected: [], bridgeTicket: localBridgeTicket(opened),
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
            if (this.state.bridge?.sessionId !== sessionId) return;
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
            this.setState({ step: 'connect', bridge: null, bridgeTicket: '' });
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
        const { canvasAddress, taskToken, resumeJobId } = this.state;
        const token = (taskToken || '').trim();
        if (!token) {
            this.setState({ error: this.t('canvas.tokenRequired') });
            return;
        }
        const baseUrl = (canvasAddress || '').trim();
        if (!baseUrl) {
            this.setState({ error: this.t('canvas.addressRequired') });
            return;
        }
        this.setState({ busy: true, error: '' });
        try {
            if (resumeJobId) {
                const resumed = await resumeTaskCredential(
                    resumeJobId, token, { canvasBaseUrl: baseUrl });
                this.setState({
                    busy: false,
                    step: 'job',
                    taskToken: '',
                    resumeJobId: '',
                    task: { ...this.state.task, credentialRef: resumed.credentialRef, state: resumed.credentialState },
                    job: { ...this.state.job, status: resumed.status, credentialState: resumed.credentialState, needsCredential: false },
                });
                this.watch(resumeJobId);
                return;
            }
            const opened = await openTaskCredential(token, { canvasBaseUrl: baseUrl });
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
        if (!connection || !window.confirm(this.t('canvas.disconnectConfirm'))) return;
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
            <legend>{this.t('canvas.chooseSchool')}</legend>
            {institutions.map(item => <label key={item.key} className="canvas-import-school">
                <input type="radio" name="canvas-school" checked={picked === item.key} onChange={() => this.pickSchool(item.key)}/>
                <span><strong>{item.label}</strong><small>{item.origin}</small></span>
            </label>)}
            <label className="canvas-import-school">
                <input type="radio" name="canvas-school" checked={picked === 'other'} onChange={() => this.pickSchool('other')}/>
                <span><strong>{this.t('canvas.otherSchool')}</strong><small>{this.t('canvas.enterSchoolUrl')}</small></span>
            </label>
            {picked === 'other' && <input
                type="url"
                className="canvas-import-address"
                placeholder="https://canvas.example.edu"
                aria-label={this.t('canvas.schoolUrl')}
                value={otherSchool}
                onChange={event => this.setState({ otherSchool: event.target.value })}
            />}
        </fieldset>;
    }

    localizedEnum(namespace, value, fallback = '') {
        if (!value) return fallback;
        const key = `${namespace}.${value}`;
        const translated = this.t(key);
        return translated === key ? (fallback || value) : translated;
    }

    renderUnavailable() {
        const { institutions, error } = this.state;
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">{this.t('canvas.unavailableTitle')}</p>
            <ul className="canvas-import-schools">
                {institutions.map(item => <li key={item.key}>
                    <strong>{item.label}</strong>
                    <small>{this.localizedEnum('canvas.unavailableReason', item.reason, this.t('canvas.temporarilyUnavailable'))}</small>
                </li>)}
            </ul>
            {this.renderSchoolPicker()}
            {error && <p className="error-text">{error}</p>}
            <p className="helper-note">{this.t('canvas.unavailableHelp')}</p>
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                <button type="button" className="btn primary" onClick={() => { this.props.close?.(); this.props.localUpload?.(); }}>
                    <Icon name="plus"/>{this.t('canvas.uploadLocalMaterials')}
                </button>
                <button type="button" className="btn" onClick={() => this.openBridge()}>{this.t('canvas.localImport')}</button>
                <button type="button" className="btn" onClick={() => this.load()}>{this.t('canvas.recheck')}</button>
            </div>
            <button type="button" className="canvas-import-secondary" onClick={() => this.setState({ localOpen: !this.state.localOpen })}>
                {this.t('canvas.localHelp')}
            </button>
            {this.state.localOpen && <LocalTokenSteps t={this.t}/>}
            {this.renderTaskEntry()}
        </div>;
    }

    renderConnect() {
        const { busy, picked } = this.state;
        const connectable = connectableInstitutions({ institutions: this.state.institutions });
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">{this.t('canvas.title')}</p>
            <p className="helper-note">{this.t('canvas.privateImportScope')}</p>
            {this.renderSchoolPicker()}
            {connectable.length > 0
                ? <button type="button" className="btn primary" disabled={busy || !picked} onClick={() => this.connect(picked)}>
                    {this.t('canvas.connectCanvas')}
                </button>
                : <p className="helper-note">{this.t('canvas.notOpen')}</p>}
            <p className="helper-note">{this.t('canvas.publicCredentialBoundary')}</p>
            <button type="button" className="canvas-import-secondary" onClick={() => this.setState({ localOpen: !this.state.localOpen })}>
                {this.t('canvas.localHelp')}
            </button>
            {this.state.localOpen && <>
                <LocalTokenSteps t={this.t}/>
                <button type="button" className="btn" disabled={busy || !picked} onClick={() => this.openBridge()}>
                    {this.t('canvas.localImport')}
                </button>
            </>}
            {this.renderTaskEntry()}
        </div>;
    }

    renderBridge() {
        const {
            bridge, bridgeTicket, bridgeRelease, bridgeReleaseError,
            bridgeCourses, bridgeSelected, busy, error,
        } = this.state;
        const status = bridge?.status || '';
        const selectable = status === 'CLAIMED';
        const expiry = bridge?.expiresAt ? Date.parse(bridge.expiresAt) : Number.NaN;
        const remaining = Number.isFinite(expiry) ? Math.max(0, expiry - this.state.bridgeNow) : null;
        const expiryText = Number.isFinite(expiry) ? new Date(expiry).toLocaleString() : '';
        const countdown = remaining == null ? '' : `${Math.floor(remaining / 60_000)}:${String(Math.floor((remaining % 60_000) / 1_000)).padStart(2, '0')}`;
        const waitingExpired = status === 'OPEN' && remaining === 0;
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">{this.t('canvas.bridgeTitle')}</p>
            {error && <p className="error-text">{error}</p>}
            <ol className="canvas-import-token-steps">
                {[0, 1, 2, 3].map(index => <li key={index}>{this.t(`canvas.bridgeSteps.${index}`)}</li>)}
            </ol>
            {bridgeRelease
                ? <a className="btn primary canvas-bridge-download" href={bridgeRelease.publicPath} download>
                    {this.t('canvas.bridgeDownloadVersion', { version: bridgeRelease.version })}
                </a>
                : <p className="error-text">{bridgeReleaseError || this.t('canvas.bridgeReleaseLoading')}</p>}
            {!bridge && <button type="button" className="btn" disabled={busy} onClick={() => this.generateBridge()}>
                {busy ? this.t('canvas.bridgeGenerating') : this.t('canvas.bridgeGenerate')}
            </button>}
            {bridge && <p className="helper-note">{this.localizedEnum('canvas.bridgeStatus', waitingExpired ? 'EXPIRED' : status)}</p>}
            {status === 'OPEN' && !waitingExpired && <>
                <label className="canvas-bridge-ticket">
                    <span>{this.t('canvas.connectionDetails')}</span>
                    <textarea readOnly rows={5} value={bridgeTicket}/>
                </label>
                <button
                    type="button"
                    className="btn"
                    onClick={async () => {
                        try {
                            await navigator.clipboard.writeText(bridgeTicket);
                            this.props.toast?.(this.t('canvas.connectionCopied'));
                        }
                        catch {
                            this.setState({ error: this.t('canvas.connectionCopyFailed') });
                        }
                    }}
                >{this.t('canvas.copyConnectionDetails')}</button>
                <p className="helper-note">{this.t('canvas.connectionExpiry', { time: expiryText, remaining: countdown })}</p>
                <details className="canvas-token-help">
                    <summary>{this.t('canvas.bridgeAdvanced')}</summary>
                    <code className="canvas-import-code">{bridgeCommand(bridgeTicket)}</code>
                </details>
            </>}
            {(status === 'EXPIRED' || waitingExpired) && <button type="button" className="btn primary" disabled={busy} onClick={() => this.generateBridge()}>
                {this.t('canvas.bridgeExpired')}
            </button>}
            {selectable && <>
                <p className="helper-note">{this.t('canvas.bridgeChooseCourses')}</p>
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
                                {course.fileCount ? ` · ${this.t('canvas.fileCount', { count: course.fileCount })}` : ''}
                            </small>
                        </span>
                    </label>)}
                </div>
                <p className="helper-note">{this.t('canvas.bridgePrivateScope')}</p>
                <button type="button" className="btn primary" disabled={busy || !bridgeSelected.length} onClick={() => this.confirmBridgeSelection()}>
                    {bridgeSelected.length ? this.t('canvas.importSelected', { count: bridgeSelected.length }) : this.t('canvas.import')}
                </button>
            </>}
            {['SELECTED', 'IMPORTING'].includes(status) && <>
                <p className="helper-note">{this.t('canvas.bridgeImportingHelp')}</p>
                <ul className="canvas-import-progress">
                    {Object.entries(bridge?.counts || {}).map(([state, count]) => <li key={state}><span>{state}</span><strong>{count}</strong></li>)}
                </ul>
            </>}
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                {bridge && !FINISHED.includes(status) && <button type="button" className="btn" onClick={() => this.cancelBridge()}>{this.t('canvas.cancelImport')}</button>}
                <button type="button" className="btn" onClick={() => this.setState({ step: 'connect', bridge: null, bridgeTicket: '' })}>{this.t('canvas.back')}</button>
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
                {this.t('canvas.taskEntry')}
            </button>
            {taskOpen && <>
                <p className="canvas-import-policy">{this.t('canvas.taskPolicy')}</p>
                <button type="button" className="btn" onClick={() => this.setState({ step: 'taskToken', taskStage: 'paste', error: '' })}>
                    {this.t('canvas.taskEntryButton')}
                </button>
            </>}
        </>;
    }

    renderTaskToken() {
        const { task, taskStage, taskToken, canvasAddress, courses, selected, busy, error, resumeJobId } = this.state;
        if (taskStage === 'paste') {
            return <div className="canvas-import-step canvas-task">
                <p className="canvas-import-lead">{this.t('canvas.title')}</p>
                <p className="helper-note">{this.t('canvas.taskAddressHelp')}</p>
                <label className="canvas-task-token">
                    <span>{this.t('canvas.schoolUrl')}</span>
                    <input
                        type="url"
                        autoComplete="url"
                        aria-label={this.t('canvas.schoolUrl')}
                        placeholder="https://canvas.cityu.edu.hk/courses"
                        value={canvasAddress}
                        onChange={event => this.setState({ canvasAddress: event.target.value })}
                    />
                </label>
                <label className="canvas-task-token">
                    <span>{this.t('canvas.taskAccessToken')}</span>
                    <input
                        type="password"
                        autoComplete="off"
                        spellCheck={false}
                        aria-label={this.t('canvas.taskAccessToken')}
                        placeholder={this.t('canvas.taskTokenPlaceholder')}
                        value={taskToken}
                        onChange={event => this.setState({ taskToken: event.target.value })}
                    />
                </label>
                <p className="helper-note">{this.t('canvas.taskTokenUse')}</p>
                <details className="canvas-token-help">
                    <summary>{this.t('canvas.taskTokenHelp')}</summary>
                    <TaskCredentialSteps t={this.t}/>
                </details>
                {error && <p className="error-text">{error}</p>}
                <div className="row" style={{ gap: 10, marginTop: 14 }}>
                    <button type="button" className="btn primary" disabled={busy || !taskToken || !canvasAddress} onClick={() => this.openTask()}>
                        {resumeJobId ? this.t('canvas.resumeImport') : this.t('canvas.confirmAndChoose')}
                    </button>
                    <button type="button" className="btn" onClick={() => this.setState({ step: 'connect', error: '' })}>
                        {this.t('canvas.back')}
                    </button>
                </div>
            </div>;
        }
        const readable = courses.filter(course => course.readable);
        const byTerm = readable.reduce((groups, course) => {
            const term = course.term || this.t('canvas.unknownTerm');
            groups[term] = [...(groups[term] || []), course];
            return groups;
        }, {});
        return <div className="canvas-import-step canvas-task">
            <p className="canvas-import-lead">{this.t('canvas.chooseCourses')}</p>
            <p className="helper-note">
                {this.t('canvas.accountRead', { name: task?.canvasName || this.t('canvas.unnamedAccount') })}
                {task?.canvasUserId ? ` (ID ${task.canvasUserId})` : ''} · {this.t('canvas.readableOnly')}
            </p>
            <p className="canvas-import-policy">
                {this.t('canvas.credentialStatus', { state: this.credentialStateLabel(task?.state) })}
                {task?.readCalls ? ` · ${this.t('canvas.readCalls', { count: task.readCalls })}` : ''}
            </p>
            {error && <p className="error-text">{error}</p>}
            {busy && <p className="helper-note">{this.t('canvas.readingCourses')}</p>}
            {!busy && !readable.length && <div className="empty-state">{this.t('canvas.emptyCourses')}</div>}
            <div className="canvas-import-courses">
                {Object.entries(byTerm).map(([term, termCourses]) => <section className="canvas-import-term" key={term}>
                    <h4>{term}</h4>
                    {termCourses.map(course => <label key={course.id} className="canvas-import-course">
                        <input type="checkbox" checked={selected.includes(course.id)} onChange={() => this.toggleCourse(course.id)}/>
                        <span><strong>{course.courseCode ? `${course.courseCode} · ` : ''}{course.name}</strong><small>
                            {this.t('canvas.fileCount', { count: course.fileCount ?? 0 })} · {course.expectedBytes != null ? this.formatBytes(course.expectedBytes) : this.t('canvas.sizePending')} · {course.accessibility || this.t('canvas.readable')} · {course.importStatus || this.t('canvas.notImported')}
                        </small></span>
                    </label>)}
                </section>)}
            </div>
            {readable.length > 0 && <button type="button" className="btn primary" disabled={busy || !selected.length} onClick={() => this.start()}>
                {selected.length ? this.t('canvas.importSelected', { count: selected.length }) : this.t('canvas.import')}
            </button>}
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                <button type="button" className="btn" onClick={() => this.forgetTask('user_disconnected')}>
                    {this.t('canvas.destroyToken')}
                </button>
                <button type="button" className="btn" onClick={() => this.refreshTaskState()}>{this.t('canvas.refreshCredential')}</button>
                <button type="button" className="btn" onClick={() => this.backToPaste()}>{this.t('canvas.changeToken')}</button>
            </div>
        </div>;
    }

    renderSelect() {
        const { courses, selected, busy, error, saveConnection, connection } = this.state;
        const readable = courses.filter(course => course.readable);
        return <div className="canvas-import-step">
            <div className="row between">
                <p className="canvas-import-lead">{this.t('canvas.chooseCourses')}</p>
                <button type="button" className="btn small" onClick={() => this.disconnect()}>{this.t('canvas.disconnect')}</button>
            </div>
            <p className="helper-note">{connection?.canvasName ? this.t('canvas.connectedName', { name: connection.canvasName }) : this.t('canvas.connectedAccount')} · {this.t('canvas.readableOnly')}</p>
            {error && <p className="error-text">{error}</p>}
            {busy && <p className="helper-note">{this.t('canvas.readingCourses')}</p>}
            {!busy && !readable.length && <div className="empty-state">{this.t('canvas.emptyCourses')}</div>}
            <div className="canvas-import-courses">
                {readable.map(course => <label key={course.id} className="canvas-import-course">
                    <input type="checkbox" checked={selected.includes(course.id)} onChange={() => this.toggleCourse(course.id)}/>
                    <span><strong>{course.name}</strong><small>{course.courseCode}{course.term ? ' · ' + course.term : ''}</small></span>
                </label>)}
            </div>
            {readable.length > 0 && <>
                <label className="check-line"><input type="checkbox" checked={saveConnection} onChange={e => this.setState({ saveConnection: e.target.checked })}/>{this.t('canvas.saveConnection')}</label>
                <p className="helper-note">{this.t('canvas.unsavedCredentialScope')}</p>
                <button type="button" className="btn primary" disabled={busy || !selected.length} onClick={() => this.start()}>
                    {selected.length ? this.t('canvas.importSelected', { count: selected.length }) : this.t('canvas.import')}
                </button>
            </>}
        </div>;
    }

    statusLine() {
        const status = this.state.job?.status;
        return this.localizedEnum('canvas.jobStatus', status);
    }

    credentialStateLabel(state) {
        return this.localizedEnum('canvas.credentialState', state || 'UNKNOWN', this.t('canvas.credentialState.UNKNOWN'));
    }

    renderJob() {
        const { job, error } = this.state;
        if (!job) return null;
        const finished = FINISHED.includes(job.status);
        return <div className="canvas-import-step">
            <p className="canvas-import-lead">{this.statusLine()}</p>
            <p className="helper-note">{this.t('canvas.fileCount', { count: job.files || 0 })}{job.courses ? ` · ${this.t('canvas.courseCount', { count: job.courses })}` : ''}{job.errorCode ? ` · ${job.errorCode}` : ''}</p>
            {job.byStatus && Object.keys(job.byStatus).length > 0 && <ul className="canvas-import-progress">
                {Object.entries(job.byStatus).map(([status, count]) => <li key={status}><span>{status}</span><strong>{count}</strong></li>)}
            </ul>}
            {job.errorMessage && <p className="helper-note">{job.errorMessage}</p>}
            {job.status === 'COMPLETED_WITH_WARNINGS' && <p className="helper-note">{this.t('canvas.jobWarnings')}</p>}
            {job.status === 'NEEDS_REAUTH' && <p className="helper-note">{this.t('canvas.jobReauth')}</p>}
            {/* A job that borrowed a one-off credential says what happened to it, and asks for a
                new one when the imports it still has to do cannot proceed without it. */}
            {job.credentialKind === 'transient_task' && <p className="canvas-import-policy">
                {this.t('canvas.jobCredential', { state: this.credentialStateLabel(job.credentialState) })}
                {job.credentialState === 'DESTROYED' ? this.t('canvas.jobCredentialDestroyed') : ''}
            </p>}
            {needsCredentialMessage(job) && <p className="helper-note">{this.t('canvas.credentialNeeded')}</p>}
            {error && <p className="error-text">{error}</p>}
            <div className="row" style={{ gap: 10, marginTop: 14 }}>
                {!finished && <button type="button" className="btn" onClick={() => this.cancel()}>{this.t('canvas.cancelImport')}</button>}
                {job.credentialKind === 'transient_task' && this.state.task?.state === 'PRESENT_TRANSIENTLY'
                    && <button type="button" className="btn" onClick={() => this.forgetTask('task_cancelled')}>
                        {this.t('canvas.destroyToken')}
                    </button>}
                {job.needsCredential && <button type="button" className="btn primary" onClick={() => this.setState({ step: 'taskToken', taskStage: 'paste', resumeJobId: job.jobId, error: '' })}>
                    {this.t('canvas.repasteToken')}
                </button>}
                <button type="button" className="btn primary" onClick={() => { this.props.close?.(); this.props.onFinished?.(); }}>{this.t('canvas.done')}</button>
            </div>
        </div>;
    }

    render() {
        const { step } = this.state;
        return <div className="canvas-import">
            {step === 'loading' && <p className="helper-note">{this.t('canvas.checkingConnection')}</p>}
            {step === 'unavailable' && this.renderUnavailable()}
            {step === 'connect' && this.renderConnect()}
            {step === 'bridge' && this.renderBridge()}
            {step === 'taskToken' && this.renderTaskToken()}
            {step === 'select' && this.renderSelect()}
            {step === 'job' && this.renderJob()}
        </div>;
    }

    formatBytes(value) {
        const bytes = Number(value || 0);
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
}
