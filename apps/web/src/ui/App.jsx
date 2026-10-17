import { BRAND } from "../brand";
import React from 'react';
import { request, send, remove, setTokenGetter, key, getVerification } from './api.js';
import { route, goto } from './utils.js';
import { Icon, IconButton, Avatar } from './icons.jsx';
import { CourseFiles, Discussion, Inbox, Calendar, Learn } from './pages.jsx';
import { CanvasImport } from './CanvasImport.jsx';
import { FileUploadQueue, runUploadBatch, uploadItemsFrom } from './FileUploadQueue.jsx';
import { UiLocaleContext, LanguageControl, defaultUiTranslate } from './UiLocale';
import { ProfileForm } from './ProfileForm.jsx';
const COLORS = ['#38585b', '#756480', '#95657b', '#5b7793', '#a18b58', '#558b7a'];
export const campusVerificationRequired = (config, course, verification) =>
    !!config?.student_verification_required_for_campus &&
    (course?.display_type === 'campus' || course?.requires_student_verification) &&
    !verification?.verified;
const HELPS = ['start', 'create', 'files', 'learn', 'explanations', 'history', 'calendar', 'messages'];
export class App extends React.Component {
    static contextType = UiLocaleContext;
    t = (id, params) => (this.context?.t || defaultUiTranslate)(id, params);
    state = { loading: true, error: '', config: null, user: null, verification: null, courses: [], route: route(), drawer: null, modal: null, unread: 0, toast: '', theme: 'light' };
    componentDidMount() { this.onHash = () => this.setState({ route: route(), drawer: null, modal: null }); window.addEventListener('hashchange', this.onHash); this.onEsc = e => { if (e.key === 'Escape')
        this.setState({ drawer: null, modal: null }); }; window.addEventListener('keydown', this.onEsc); this.boot(); this.timer = setInterval(() => { if (!document.hidden && this.state.user)
        this.loadUnread(); }, 15000); }
    componentWillUnmount() { this.authUnsubscribe?.(); window.removeEventListener('hashchange', this.onHash); window.removeEventListener('keydown', this.onEsc); clearInterval(this.timer); clearTimeout(this.toastTimer); }
    async boot() {
        try {
            const config = await request('/config');
            this.setState({ config });
            if (['clerk', 'injected'].includes(config.auth_mode)) {
                if (window.CourseMateAuth) {
                    setTokenGetter(() => window.CourseMateAuth.getToken());
                    if (!this.authUnsubscribe && window.CourseMateAuth.subscribe)
                        this.authUnsubscribe = window.CourseMateAuth.subscribe(() => this.authChanged());
                }
                else {
                    if (config.auth_mode === 'injected')
                        throw new Error(this.t('auth.injectedBridgeRequired'));
                    if (!window.Clerk) {
                        if (!config.clerk_publishable_key || !config.clerk_issuer)
                            throw new Error(this.t('auth.clerkNotConfigured'));
                        await new Promise((resolve, reject) => { const s = document.createElement('script'); s.src = config.clerk_issuer.replace(/\/$/, '') + '/npm/@clerk/clerk-js@5/dist/clerk.browser.js'; s.crossOrigin = 'anonymous'; s.dataset.clerkPublishableKey = config.clerk_publishable_key; s.onload = resolve; s.onerror = () => reject(new Error(this.t('auth.clerkLoadFailed'))); document.head.appendChild(s); });
                    }
                    await window.Clerk.load();
                    setTokenGetter(() => window.Clerk.session?.getToken() || null);
                    if (!this.authUnsubscribe)
                        this.authUnsubscribe = window.Clerk.addListener(() => this.authChanged());
                }
                const token = window.CourseMateAuth
                    ? await window.CourseMateAuth.getToken()
                    : await window.Clerk.session?.getToken?.();
                if (!token) {
                    this.context?.setOwner(null);
                    this.setState({ user: null, verification: null, courses: [], loading: false, error: '' });
                    return;
                }
            }
            const user = await request('/me');
            const theme = await this.loadTheme(user);
            let verification = null;
            try { verification = await getVerification(); } catch { }
            this.setState({ user, verification, theme, loading: false }, () => this.applyTheme(theme));
            await this.refresh();
        }
        catch (e) {
            this.setState({ loading: false, error: e.message });
        }
    }
    async authChanged() { try {
        if (['clerk', 'injected'].includes(this.state.config?.auth_mode)) {
            const token = window.CourseMateAuth
                ? await window.CourseMateAuth.getToken()
                : await window.Clerk.session?.getToken?.();
            if (!token) {
                this.context?.setOwner(null);
                if (this.state.user)
                    this.setState({ user: null, courses: [], drawer: null, modal: null, unread: 0 });
                return;
            }
        }
        const user = await request('/me');
        if (user.id !== this.state.user?.id) {
            const theme = await this.loadTheme(user);
            this.setState({ user, verification: null, courses: [], drawer: null, modal: null, error: '', loading: false, theme }, () => this.applyTheme(theme));
            await this.refresh();
            await this.loadVerification();
        }
    }
    catch {
        if (this.state.user)
            this.setState({ user: null, courses: [], drawer: null, modal: null, unread: 0 });
    } }
    themeKey = (user) => `coursemate.theme.${user.id}`;
    applyTheme = (theme) => { document.documentElement.dataset.theme = theme; };
    loadTheme = async (user) => {
        this.context?.setOwner(user.id);
        let cached = null;
        try { cached = localStorage.getItem(this.themeKey(user)); } catch { }
        try {
            const preference = await request('/me/preferences');
            this.context?.setOwner(user.id, preference.ui_locale);
            const theme = preference.theme === 'dark' ? 'dark' : 'light';
            try { localStorage.setItem(this.themeKey(user), theme); } catch { }
            return theme;
        } catch {
            return cached === 'dark' ? 'dark' : 'light';
        }
    };
    setTheme = async (theme) => {
        if (!this.state.user || (theme !== 'light' && theme !== 'dark')) return;
        this.applyTheme(theme);
        this.setState({ theme });
        try {
            await send('/me/preferences', { theme }, 'PUT');
            try { localStorage.setItem(this.themeKey(this.state.user), theme); } catch { }
        } catch (error) {
            this.toast(this.t('dashboard.themeSaveFailed', { error: error.message }));
        }
    };
    async refresh() { try {
        const courses = await request('/courses');
        this.setState({ courses });
        await this.loadUnread();
    }
    catch (e) {
        this.toast(e.message);
    } }
    async loadUnread() { try {
        const [n, t] = await Promise.all([request('/notifications'), request('/threads')]);
        this.setState({ unread: n.filter(x => !x.read_at).length + t.reduce((a, x) => a + x.unread, 0) });
    }
    catch { } }
    toast = (message) => { this.setState({ toast: message }); clearTimeout(this.toastTimer); this.toastTimer = setTimeout(() => this.setState({ toast: '' }), 5000); };
    modal = (title, body) => this.setState({ modal: { body, ...(title?.titleKey ?
        { titleKey: title.titleKey, titleParams: title.params || {} } : { title }) } });
    close = () => this.setState({ modal: null });
    providerStatusKey = (mode) => mode === 'test' ? 'auth.testModel' : mode && mode !== 'none' && mode !== 'disabled'
        ? 'auth.modelConfigured' : 'auth.modelDisconnected';
    courseTypeLabel = (c) => this.t(c.display_type === 'campus' ? 'courses.campus' : c.display_type === 'shared' ? 'courses.shared' : 'courses.private');
    courseTypeClass = (c) => c.display_type === 'campus' ? 'course-type-badge campus' : c.display_type === 'shared' ? 'course-type-badge shared' : 'course-type-badge private';
    isCampusUnverified = (c) => campusVerificationRequired(this.state.config, c, this.state.verification);
    loadVerification = async () => { try { const verification = await getVerification(); this.setState({ verification }); } catch { } };
    renderVerification() {
        const v = this.state.verification, verified = !!v?.verified;
        const gateRequired = !!this.state.config?.student_verification_required_for_campus;
        const methodLabel = ['registered', 'code', 'grandfathered'].includes(v?.method)
            ? this.t(`account.methods.${v.method}`) : v?.method ? this.t('common.unknown') : '';
        const status = this.t(verified ? 'account.verified' : gateRequired ? 'account.notVerified' : 'account.notRequired');
        return <div className="verification-box"><div className="row between">
            <span className="verification-status">{this.t('account.studentVerification')}</span>
            <span className={'verification-status' + (verified || !gateRequired ? ' done' : '')}>
                {verified && methodLabel ? this.t('account.verifiedMethod', { status, method: methodLabel }) : status}
            </span>
        </div><p className={'helper-note' + (gateRequired && !verified ? ' campus-hint' : '')}>
            {this.t(gateRequired && !verified ? 'account.campusVerificationRequired' : 'account.campusVerificationOptional')}
        </p></div>;
    }
    async login(account) { try {
        await send('/dev/login', { account });
        this.setState({ error: '' });
        await this.boot();
    }
    catch (e) {
        this.toast(e.message);
    } }
    async logout() { if (this.state.config.auth_mode === 'development')
        await send('/dev/logout', {});
    else if (window.CourseMateAuth)
        await window.CourseMateAuth.signOut();
    else
        await window.Clerk.signOut(); this.context?.setOwner(null); location.hash = '#/dashboard'; this.setState({ user: null, drawer: null, courses: [] }); }
    async togglePin(c) { try {
        if (c.pinned)
            await remove(`/courses/${c.id}/pin`);
        else
            await send(`/courses/${c.id}/pin`, {}, 'PUT');
        await this.refresh();
        this.toast(this.t(c.pinned ? 'courses.removedDashboardToast' : 'courses.addedDashboardToast'));
    }
    catch (e) {
        this.toast(e.message);
    } }
    createCourse = () => this.modal({ titleKey: 'courseForm.title' }, <CourseForm onCreate={async data => { const result = await send('/courses', data); await this.refresh(); return result; }} onFinish={course => { this.close(); goto(`course/${course.id}/files`); this.toast(this.t('courseForm.saved')); }}/>);
    canvasImport = () => this.modal({ titleKey: 'canvas.title' }, <CanvasImport toast={this.toast} closeModal={this.close} close={this.close} localUpload={this.createCourse} onFinished={() => this.refresh()}/>);
    profile = () => this.modal({ titleKey: 'profile.title' }, <ProfileForm user={this.state.user} onSubmit={async (data) => { const user = await send('/me', data, 'PATCH'); this.setState({ user }); this.close(); this.toast(this.t('profile.saved')); }}/>);
    renderNav() { const { route: r, drawer, unread } = this.state; return <nav className="global-nav" aria-label={this.t('navigation.mainLabel')}><button className="brand" onClick={() => goto('dashboard')} title={`${BRAND.name} ${this.t('dashboard.title')}`}><img className="brand-mark" src={BRAND.logoPath} alt={BRAND.logoAlt} width={32} height={32} decoding="async"/><span>{BRAND.name}</span></button><div className="nav-items">{[['account', 'user'], ['dashboard', 'dashboard'], ['courses', 'courses'], ['calendar', 'calendar'], ['inbox', 'inbox'], ['help', 'help']].map(([id, icon]) => <button key={id} className={'global-item ' + ((drawer === id || r.page === id || (id === 'courses' && r.page === 'course')) ? 'active' : '')} onClick={() => ['account', 'courses', 'help'].includes(id) ? this.setState({ drawer: drawer === id ? null : id }) : goto(id)}><Icon name={icon}/><span>{this.t(`navigation.${id}`)}</span>{id === 'inbox' && unread > 0 && <span className="badge">{unread > 99 ? '99+' : unread}</span>}</button>)}</div><div className="nav-bottom"><span className="demo-mark">{this.state.config?.environment === 'production' ? 'LEARN' : 'DEV'}</span></div></nav>; }
    renderDrawer() { const { drawer, courses, user } = this.state; if (!drawer)
        return null; return <><div className="drawer-backdrop" onClick={() => this.setState({ drawer: null })}/><aside className="drawer" role="dialog" aria-label={this.t(`navigation.${drawer}Panel`)}><IconButton name="close" title={this.t('navigation.closeSidebar')} className="icon-btn drawer-close" onClick={() => this.setState({ drawer: null })}/>{drawer === 'account' ? <><div className="account-hero"><Avatar name={user.name}/><h2>{user.name}</h2><p>@{user.handle}</p><button className="btn small" onClick={() => this.logout()}>{this.t('auth.signOut')}</button></div><div className="divider"/>{[['bell', 'notifications', () => goto('inbox')], ['user', 'profile', this.profile], ['folder', 'files', () => goto('courses')], ['settings', 'settings', this.profile]].map(([icon, title, fn]) => <button className="drawer-link" key={title} onClick={() => { this.setState({ drawer: null }); fn(); }}><Icon name={icon}/>{this.t(`account.${title}`)}</button>)}<LanguageControl />{this.renderVerification()}</> : drawer === 'courses' ? <><h2 className="drawer-title">{this.t('navigation.courses')}</h2><div className="divider"/><button className="drawer-link" onClick={() => goto('courses')}>{this.t('courses.all')} <Icon name="arrow"/></button><div className="divider"/>{courses.filter(c => c.pinned).map(c => <button key={c.id} className="drawer-course" onClick={() => goto(`course/${c.id}/learn`)}><strong><i className="color-dot" style={{ background: c.color }}/>{c.code} {c.name}</strong><p>{this.t('courses.addedToDashboard')}</p></button>)}<p className="helper-note" style={{ marginTop: 24 }}>{this.t('courses.drawerPinHelp')}</p></> : <><h2 className="drawer-title">{this.t('help.title')}</h2><div className="help-art"><img className="brand-mark" src={BRAND.logoPath} alt={BRAND.logoAlt} width={32} height={32} decoding="async"/></div><div className="help-intro"><h3>{this.t('help.direction')}</h3><p>{this.t('help.brandGuide', { brand: BRAND.name })}</p></div>{HELPS.map(id => <details key={id} className="help-link"><summary>{this.t(`help.articles.${id}.title`)}</summary><p className="helper-note" style={{ marginTop: 10 }}>{this.t(`help.articles.${id}.body`)}</p></details>)}</>}</aside></>; }
    renderDashboard() { const rows = this.state.courses.filter(c => c.pinned); const dark = this.state.theme === 'dark'; const themeLabel = this.t(dark ? 'dashboard.lightTheme' : 'dashboard.darkTheme'); return <div className="page"><header className="page-heading dashboard-heading"><div><h1>{this.t('dashboard.title')}</h1><p>{this.t('dashboard.addFromAll')}</p></div><div className="dashboard-controls"><button type="button" className="theme-toggle" aria-label={themeLabel} title={themeLabel} aria-pressed={dark} onClick={() => this.setTheme(dark ? 'light' : 'dark')}><Icon name={dark ? 'sun' : 'moon'}/><span>{themeLabel}</span></button><LanguageControl /></div></header><div className="dashboard-grid"><button type="button" className="add-course-card" onClick={this.canvasImport}><span className="add-plus"><Icon name="upload"/></span><strong>{this.t('dashboard.importCanvas')}</strong></button><button type="button" className="add-course-card" onClick={this.createCourse}><span className="add-plus"><Icon name="plus"/></span><strong>{this.t('dashboard.createCourse')}</strong></button>{rows.map(c => <article className="course-card" key={c.id}><button className="course-card-menu icon-btn" title={this.t('courses.unpin')} aria-label={`${this.t('courses.unpin')} ${c.code}`} onClick={() => this.togglePin(c)}><Icon name="more"/></button><div className="course-cover" style={{ background: c.color }} onClick={() => goto(`course/${c.id}/learn`)}><span className="cover-code">{c.code}</span></div><div className="course-card-body" onClick={() => goto(`course/${c.id}/learn`)}><h3 title={c.name}>{c.name}</h3><p><span className={this.courseTypeClass(c)}>{this.courseTypeLabel(c)}</span></p></div><div className="card-tools">{[['comment', 'comments'], ['folder', 'files'], ['book', 'learn']].map(([icon, tab]) => <button key={tab} className={tab === 'learn' ? 'learn-tool' : ''} title={this.t(`courses.${tab}`)} aria-label={`${c.code} ${this.t(`courses.${tab}`)}`} onClick={() => goto(`course/${c.id}/${tab}`)}><Icon name={icon}/>{tab === 'learn' && <span>{this.t('courses.learn')}</span>}</button>)}</div></article>)}</div><p className="dashboard-guide"><button className="link" onClick={() => goto('courses')}>{this.t('courses.all')} <span>→</span></button></p></div>; }
    renderCourses() { return <div className="page">
        <header className="page-heading"><h1>{this.t('courses.all')}</h1></header>
        <div className="course-banner"><div className="row">
            <div className="banner-icon"><Icon name="plus"/></div>
            <div><h2>{this.t('courses.materialsToCourse')}</h2><p>{this.t('courses.materialsToCourseHint')}</p></div>
        </div><div className="course-banner-actions">
            <button type="button" className="btn primary" onClick={this.createCourse}><Icon name="plus"/>{this.t('courses.create')}</button>
            <button type="button" className="btn primary" onClick={this.canvasImport}><Icon name="upload"/>{this.t('dashboard.importCanvas')}</button>
        </div></div>
        <div className="table-wrap"><table><thead><tr>
            <th>{this.t('courses.courseColumn')}</th><th>{this.t('courses.typeColumn')}</th>
            <th>{this.t('courses.visibilityColumn')}</th><th>{this.t('dashboard.title')}</th>
        </tr></thead><tbody>{this.state.courses.map(c => <tr key={c.id}>
            <td><button className="course-name" onClick={() => goto(`course/${c.id}/learn`)}>
                <i className="color-dot" style={{ background: c.color }}/>
                <span><strong>{c.name}</strong><small>{c.code}{c.description ? ' · ' + c.description : ''}</small></span>
            </button></td>
            <td><span className={this.courseTypeClass(c)}>{this.courseTypeLabel(c)}</span></td>
            <td><span className={'chip ' + (c.visibility === 'public' ? 'neutral' : '')}>
                {this.t(c.visibility === 'public' ? 'courses.publicVisibility' : 'courses.onlyMe')}
            </span></td>
            <td>{this.isCampusUnverified(c) && !c.pinned
                ? <span className="helper-note campus-hint" title={this.t('courses.verificationRequired')}>{this.t('courses.verifyFirst')}</span>
                : <button className={'add-toggle ' + (c.pinned ? 'added' : '')}
                    aria-label={`${this.t(c.pinned ? 'courses.unpin' : 'courses.pin')} ${c.code}`}
                    title={this.t(c.pinned ? 'courses.unpin' : 'courses.pin')} onClick={() => this.togglePin(c)}>
                    <Icon name={c.pinned ? 'check' : 'plus'}/>
                </button>}</td>
        </tr>)}</tbody></table></div>
        <p className="helper-note" style={{ marginTop: 20 }}>{this.t('courses.pinHelp')}</p>
    </div>; }
    renderCourse() {
        const { cid, tab } = this.state.route;
        const c = this.state.courses.find(x => x.id === cid);
        if (!c)
            return <div className="page"><h2>{this.t('courses.noAccess')}</h2><button className="btn" onClick={() => goto('courses')}>{this.t('courses.returnAll')}</button></div>;
        const common = { course: c, user: this.state.user, config: this.state.config, toast: this.toast, modal: this.modal, closeModal: this.close, refresh: () => this.refresh() };
        return <div className="course-shell"><aside className="course-side"><button className="course-back" onClick={() => goto('courses')}><Icon name="back"/>{this.t('courses.all')}</button><div className="side-name" title={c.name} tabIndex={0}>{c.name}</div><div className="side-code" title={c.code} tabIndex={0}>{c.code}</div><div className="side-nav">{[['comment', 'comments', 'courses.comments'], ['folder', 'files', 'courses.files'], ['book', 'learn', 'courses.learn']].map(([icon, id, label]) => <button className={'course-nav-link ' + (tab === id ? 'active' : '')} key={id} onClick={() => goto(`course/${cid}/${id}`)}><Icon name={icon}/>{this.t(label)}</button>)}</div><div className="side-course-meta">{this.t(c.official ? 'courses.sharedMaterialsPrivateHistory' : c.visibility === 'private' ? 'courses.privateCourseNote' : 'courses.publicCourse')}<br />{BRAND.name} {this.t('courses.learningSpace')}</div></aside><main className="course-main"><header className="course-top"><Icon name="courses"/><span>{c.code}</span><Icon name="arrow"/><span className="crumb-weak">{this.t(tab === 'files' ? 'courses.files' : tab === 'comments' ? 'courses.comments' : 'courses.learn')}</span></header>{tab === 'files' ? <CourseFiles key={cid} {...common}/> : tab === 'comments' ? <Discussion key={cid} {...common}/> : <Learn key={cid} {...common}/>}</main></div>;
    }
    render() {
        const { user, loading, config, route: r, modal, error, toast } = this.state;
        const modalTitle = modal?.titleKey ? this.t(modal.titleKey, modal.titleParams) : modal?.title;
        if (loading)
            return <div className="login-page"><img className="brand-mark" src={BRAND.logoPath} alt={BRAND.logoAlt} width={32} height={32} decoding="async"/><p>{this.t('auth.connectingBrand', { brand: BRAND.name })}</p></div>;
        if (!user)
            return <div className="login-page"><div className="login-card"><div className="login-brand"><img className="brand-mark" src={BRAND.logoPath} alt={BRAND.logoAlt} width={32} height={32} decoding="async"/>{BRAND.name}</div><p className="login-tagline">{this.t('auth.slogan')}</p>{config?.auth_mode === 'development' ? <><div className="notice">{this.t('auth.localIntegration')}<br />{this.t(this.providerStatusKey(config.provider_mode))}<br />{this.t('auth.developmentAccounts')}</div>{[['alice', 'auth.signInQiu'], ['bob', 'auth.signInLin'], ['admin', 'auth.signInAdmin']].map(([a, label]) => <button key={a} className="btn primary" onClick={() => this.login(a)}>{this.t(label)}</button>)}</> : <button className="btn primary" onClick={() => window.CourseMateAuth?.signIn?.() || window.Clerk?.openSignIn()}>{this.t('auth.signIn')} / {this.t('auth.signUp')}</button>}{error && error !== '请登录' && !error.includes('请先选择') && <p className="error-text">{error}</p>}</div></div>;
        return <>{this.renderNav()}<div className="app" key={user.id}>{r.page === 'courses' ? this.renderCourses() : r.page === 'course' ? this.renderCourse() : r.page === 'calendar' ? <Calendar user={user} courses={this.state.courses} toast={this.toast} modal={this.modal} closeModal={this.close}/> : r.page === 'inbox' ? <Inbox onJoined={() => this.refresh()} user={user} config={config} toast={this.toast} modal={this.modal} closeModal={this.close} onRead={() => this.loadUnread()}/> : this.renderDashboard()}</div>{this.renderDrawer()}{modal && <div className="modal-layer" onClick={e => { if (e.target === e.currentTarget)
            this.close(); }}><section className="modal" role="dialog" aria-modal="true" aria-label={modalTitle}><header className="modal-header"><h2>{modalTitle}</h2><IconButton name="close" title={this.t('common.closeWindow')} onClick={this.close}/></header><div className="modal-body">{modal.body}</div></section></div>}{toast && <div className="toast" role="status">{toast}</div>}</>;
    }
}
class CourseForm extends React.Component {
    static contextType = UiLocaleContext;
    t = (id, params) => (this.context?.t || defaultUiTranslate)(id, params);
    state = { color: COLORS[0], busy: false, error: '', uploadQueue: [], course: null };
    updateUpload = (clientItemId, patch) => this.setState(state => ({ uploadQueue: state.uploadQueue.map(item => item.clientItemId === clientItemId ? { ...item, ...patch } : item) }));
    selectFiles(e) { const input = e.currentTarget; const added = uploadItemsFrom(input.files); input.value = ''; if (added.length) this.setState(state => ({ uploadQueue: [...state.uploadQueue, ...added] })); }
    removeFile(clientItemId) { this.setState(state => ({ uploadQueue: state.uploadQueue.filter(item => item.clientItemId !== clientItemId) })); }
    async uploadFiles(course, items) {
        if (!items.length) return;
        this.setState({ busy: true, error: '' });
        try {
            await runUploadBatch(course.id, items, async (item, batchId) => { const body = new FormData(); body.append('file', item.file); body.append('folder', ''); body.append('batch_id', batchId); body.append('batch_item_id', item.clientItemId.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 100)); return request(`/courses/${course.id}/files`, { method: 'POST', body }); }, this.updateUpload, 2);
        }
        catch (error) {
            this.setState({ error: error instanceof Error ? error.message : String(error) });
            throw error;
        }
        finally {
            this.setState({ busy: false });
        }
    }
    retryFile(clientItemId) { const item = this.state.uploadQueue.find(row => row.clientItemId === clientItemId && row.status === 'failed'); if (item && this.state.course) this.uploadFiles(this.state.course, [item]); }
    retryFailed() { if (this.state.course) this.uploadFiles(this.state.course, this.state.uploadQueue.filter(item => item.status === 'failed')); }
    async submit(e) { e.preventDefault(); if (this.state.course) return; const f = new FormData(e.currentTarget); this.setState({ busy: true, error: '' }); try {
        const course = await this.props.onCreate({ name: f.get('name'), code: f.get('code'), description: f.get('description'), color: this.state.color, requirements: f.get('requirements') });
        this.setState({ course });
        if (!this.state.uploadQueue.length) { this.props.onFinish(course); return; }
        await this.uploadFiles(course, this.state.uploadQueue);
    }
    catch (e) {
        this.setState({ error: e.message, busy: false });
    } }
    render() {
        const { busy, course, uploadQueue } = this.state;
        const failed = uploadQueue.some(item => item.status === 'failed');
        const createLabel = uploadQueue.length
            ? this.t('courseForm.createWithFiles', { count: uploadQueue.length })
            : this.t('courses.create');
        return <form className="course-create-form" onSubmit={e => this.submit(e)}>
            <fieldset disabled={busy || !!course}>
                <div className="field"><label htmlFor="course-name">{this.t('courses.courseName')}</label>
                    <input id="course-name" name="name" required maxLength="100" placeholder={this.t('courseForm.nameExample')}/></div>
                <div className="field"><label htmlFor="course-code">{this.t('courseForm.code')}</label>
                    <input id="course-code" name="code" maxLength="30" placeholder={this.t('courseForm.codeExample')}/></div>
                <div className="field"><label htmlFor="course-description">{this.t('courseForm.description')}</label>
                    <textarea id="course-description" name="description" maxLength="500"/></div>
                <div className="field"><label htmlFor="course-requirements">{this.t('courseForm.requirements')}</label>
                    <textarea id="course-requirements" name="requirements" placeholder={this.t('courseForm.requirementsExample')} maxLength="10000"/></div>
                <div className="swatches">{COLORS.map(color => <button type="button" className={'swatch ' + (this.state.color === color ? 'selected' : '')} key={color}
                    style={{ background: color }} onClick={() => this.setState({ color })} aria-label={this.t('courseForm.color', { color })}/>)}</div>
            </fieldset>
            <div className="field course-file-picker"><label htmlFor="course-files">{this.t('courseForm.materials')}</label>
                <input id="course-files" type="file" multiple disabled={busy || !!course} accept=".pdf,.txt,.md,.csv,.ipynb,.docx,.pptx,.png,.jpg,.jpeg,.webp" onChange={e => this.selectFiles(e)}/>
                <small className="helper-note">{this.t('courseForm.multiSelectHelp')}</small></div>
            <FileUploadQueue items={uploadQueue} busy={busy} onRetry={id => this.retryFile(id)} onRemove={id => this.removeFile(id)}/>
            <p className="helper-note" style={{ margin: '18px 0' }}><Icon name="lock"/> {this.t('courseForm.privateNote')}</p>
            {this.state.error && <p className="error-text">{this.state.error}</p>}
            {!course ? <button className="btn primary" disabled={busy}>{busy ? this.t('courseForm.creating') : createLabel}</button>
                : <div className="upload-complete-actions"><span className="helper-note">{this.t('courseForm.onceOnly')}</span>
                    {failed && <button type="button" className="btn" disabled={busy} onClick={() => this.retryFailed()}>{this.t('courseForm.retryAll')}</button>}
                    <button type="button" className="btn primary" disabled={busy} onClick={() => this.props.onFinish(course)}>{this.t('courseForm.openFiles')}</button></div>}
        </form>;
    }
}
