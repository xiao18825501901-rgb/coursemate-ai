import React from 'react';
import { request, send, remove, setTokenGetter, key, getVerification, redeemVerification } from './api.js';
import { route, goto } from './utils.js';
import { Icon, IconButton, Avatar } from './icons.jsx';
import { CourseFiles, Discussion, Inbox, Calendar, Learn } from './pages.jsx';
const COLORS = ['#38585b', '#756480', '#95657b', '#5b7793', '#a18b58', '#558b7a'];
const HELPS = [['开始学习', '在“课程 → 所有课程”点加号，选择显示在控制面板的课程。首次控制面板只有创建框。'], ['创建自己的课程', '点击虚线框或所有课程顶部的“创建课程”。新课程默认私人，创建后自动加入控制面板。'], ['文件与课程资料', '点击文件名预览；行末三点菜单下载。在官方课程添加的个人文件仅自己可见。'], ['知识和题目，一起学', '左边学知识，右边解题。拖动中间分隔条调比例，左上角按钮进入页面全屏，Esc 退出。'], ['题目到知识，再返回', '在右侧答案步骤下面点击知识问题，左侧携带原题上下文讲解；“返回题目”回到原步骤。'], ['学习历史', '每个模式有独立历史入口。对话和完成的生成记录由服务器保存，刷新、退出重登后可以恢复。'], ['日历与学习计划', '日历下方有计划入口，安排保存在账户下。已完成任务会同步显示在日历和列表。'], ['评论和信息', '课程评论对能访问该课程的用户可见。别人回复你的评论会通知你。私信只有参与双方可以读取。']];
export class App extends React.Component {
    state = { loading: true, error: '', config: null, user: null, verification: null, courses: [], route: route(), drawer: null, modal: null, unread: 0, toast: '' };
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
                        throw new Error('DSH 需要接入当前项目已验证的认证桥');
                    if (!window.Clerk) {
                        if (!config.clerk_publishable_key || !config.clerk_issuer)
                            throw new Error('Clerk 前端配置未完成');
                        await new Promise((resolve, reject) => { const s = document.createElement('script'); s.src = config.clerk_issuer.replace(/\/$/, '') + '/npm/@clerk/clerk-js@5/dist/clerk.browser.js'; s.crossOrigin = 'anonymous'; s.dataset.clerkPublishableKey = config.clerk_publishable_key; s.onload = resolve; s.onerror = () => reject(new Error('Clerk 加载失败')); document.head.appendChild(s); });
                    }
                    await window.Clerk.load();
                    setTokenGetter(() => window.Clerk.session?.getToken() || null);
                    if (!this.authUnsubscribe)
                        this.authUnsubscribe = window.Clerk.addListener(() => this.authChanged());
                }
            }
            const user = await request('/me');
            let verification = null;
            try { verification = await getVerification(); } catch { }
            this.setState({ user, verification, loading: false });
            await this.refresh();
        }
        catch (e) {
            this.setState({ loading: false, error: e.message });
        }
    }
    async authChanged() { try {
        const user = await request('/me');
        if (user.id !== this.state.user?.id) {
            this.setState({ user, verification: null, courses: [], drawer: null, modal: null, error: '', loading: false });
            await this.refresh();
            await this.loadVerification();
        }
    }
    catch {
        if (this.state.user)
            this.setState({ user: null, courses: [], drawer: null, modal: null, unread: 0 });
    } }
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
    modal = (title, body) => this.setState({ modal: { title, body } });
    close = () => this.setState({ modal: null });
    courseTypeLabel = (c) => c.display_type === 'campus' ? '校园课程' : c.display_type === 'shared' ? '共享课程' : '自建课程';
    courseTypeClass = (c) => c.display_type === 'campus' ? 'course-type-badge campus' : c.display_type === 'shared' ? 'course-type-badge shared' : 'course-type-badge private';
    isCampusUnverified = (c) => (c.display_type === 'campus' || c.requires_student_verification) && !this.state.verification?.verified;
    loadVerification = async () => { try { const verification = await getVerification(); this.setState({ verification }); } catch { } };
    redeemCode = async () => { const code = this.verifyCodeInput?.value || ''; if (!/^[0-9]{7}$/.test(code)) { this.toast('请输入 7 位数字认证码'); return; } try { await redeemVerification(code); await this.loadVerification(); this.toast('认证成功'); if (this.verifyCodeInput) this.verifyCodeInput.value = ''; } catch (e) { this.toast(e.message || '认证码无效'); } };
    renderVerification() { const v = this.state.verification; const verified = !!v?.verified; const methodLabel = v?.method === 'code' ? '兑换码' : v?.method === 'grandfathered' ? '历史用户' : (v?.method || ''); return <div className="verification-box"><div className="row between"><span className="verification-status">学生认证</span>{verified ? <span className="verification-status done">已认证{methodLabel ? '（' + methodLabel + '）' : ''}</span> : <span className="verification-status">未认证</span>}</div>{!verified && <div className="row" style={{ marginTop: 10 }}><input aria-label="7 位认证码" type="text" inputMode="numeric" pattern="[0-9]{7}" maxLength="7" placeholder="7 位认证码" ref={el => this.verifyCodeInput = el} onChange={e => { e.target.value = e.target.value.replace(/[^0-9]/g, '').slice(0, 7); }} onKeyDown={e => { if (e.key === 'Enter') this.redeemCode(); }}/><button className="btn primary" onClick={() => this.redeemCode()}>兑换认证码</button></div>}{!verified && <p className="helper-note campus-hint">校园课程需要完成学生认证后才能查看内容。</p>}</div>; }
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
        await window.Clerk.signOut(); location.hash = '#/dashboard'; this.setState({ user: null, drawer: null, courses: [] }); }
    async togglePin(c) { try {
        if (c.pinned)
            await remove(`/courses/${c.id}/pin`);
        else
            await send(`/courses/${c.id}/pin`, {}, 'PUT');
        await this.refresh();
        this.toast(c.pinned ? '已移出控制面板（未删除课程）' : '已添加到控制面板');
    }
    catch (e) {
        this.toast(e.message);
    } }
    createCourse = () => this.modal('创建你的课程', <CourseForm onSubmit={async (data) => { const result = await send('/courses', data); this.close(); await this.refresh(); goto(`course/${result.id}/files`); this.toast('课程已创建，可以添加你的资料'); }}/>);
    profile = () => this.modal('个人资料与偏好', <ProfileForm user={this.state.user} onSubmit={async (data) => { const user = await send('/me', data, 'PATCH'); this.setState({ user }); this.close(); this.toast('资料已保存到服务器'); }}/>);
    renderNav() { const { route: r, drawer, unread, user } = this.state; return <nav className="global-nav" aria-label="主导航"><button className="brand" onClick={() => goto('dashboard')} title="CourseMate 控制面板"><Icon name="book"/><span>CourseMate</span></button><div className="nav-items">{[['account', 'user', '账户'], ['dashboard', 'dashboard', '控制面板'], ['courses', 'courses', '课程'], ['calendar', 'calendar', '日历'], ['inbox', 'inbox', '收件箱'], ['help', 'help', '帮助']].map(([id, icon, label]) => <button key={id} className={'global-item ' + ((drawer === id || r.page === id || (id === 'courses' && r.page === 'course')) ? 'active' : '')} onClick={() => ['account', 'courses', 'help'].includes(id) ? this.setState({ drawer: drawer === id ? null : id }) : goto(id)}><Icon name={icon}/><span>{label}</span>{id === 'inbox' && unread > 0 && <span className="badge">{unread > 99 ? '99+' : unread}</span>}</button>)}</div><div className="nav-bottom"><span className="demo-mark">{this.state.config?.environment === 'production' ? 'LEARN' : '本地联调'}</span></div></nav>; }
    renderDrawer() { const { drawer, courses, user } = this.state; if (!drawer)
        return null; return <><div className="drawer-backdrop" onClick={() => this.setState({ drawer: null })}/><aside className="drawer" role="dialog" aria-label={drawer === 'account' ? '账户面板' : drawer === 'courses' ? '课程面板' : '帮助面板'}><IconButton name="close" title="关闭侧栏" className="icon-btn drawer-close" onClick={() => this.setState({ drawer: null })}/>{drawer === 'account' ? <><div className="account-hero"><Avatar name={user.name}/><h2>{user.name}</h2><p>@{user.handle}</p><button className="btn small" onClick={() => this.logout()}>退出登录</button></div><div className="divider"/>{[['bell', '通知', () => goto('inbox')], ['user', '个人资料', this.profile], ['folder', '文件', () => goto('courses')], ['settings', '设置', this.profile]].map(([icon, title, fn]) => <button className="drawer-link" key={title} onClick={() => { this.setState({ drawer: null }); fn(); }}><Icon name={icon}/>{title}</button>)}{this.renderVerification()}</> : drawer === 'courses' ? <><h2 className="drawer-title">课程</h2><div className="divider"/><button className="drawer-link" onClick={() => goto('courses')}>所有课程 <Icon name="arrow"/></button><div className="divider"/>{courses.filter(c => c.pinned).map(c => <button key={c.id} className="drawer-course" onClick={() => goto(`course/${c.id}/learn`)}><strong><i className="color-dot" style={{ background: c.color }}/>{c.code} {c.name}</strong><p>已加入控制面板</p></button>)}<p className="helper-note" style={{ marginTop: 24 }}>在“所有课程”中点击加号，把希望显示的课程加入控制面板。</p></> : <><h2 className="drawer-title">帮助</h2><div className="help-art"><Icon name="book"/></div><div className="help-intro"><h3>让每一步学习，都有方向</h3><p>CourseMate 使用指南</p></div>{HELPS.map(([title, text]) => <details key={title} className="help-link"><summary>{title}</summary><p className="helper-note" style={{ marginTop: 10 }}>{text}</p></details>)}</>}</aside></>; }
    renderDashboard() { const rows = this.state.courses.filter(c => c.pinned); return <div className="page"><header className="page-heading"><h1>控制面板</h1><p>你的课程，按你的节奏。</p></header><div className="dashboard-grid">{rows.map(c => <article className="course-card" key={c.id}><button className="course-card-menu icon-btn" title="从控制面板移除" aria-label={'移除 ' + c.code} onClick={() => this.togglePin(c)}><Icon name="more"/></button><div className="course-cover" style={{ background: c.color }} onClick={() => goto(`course/${c.id}/learn`)}><span className="cover-code">{c.code}</span></div><div className="course-card-body" onClick={() => goto(`course/${c.id}/learn`)}><h3 title={c.name}>{c.name}</h3><p><span className={this.courseTypeClass(c)}>{this.courseTypeLabel(c)}</span></p></div><div className="card-tools">{[['comment', 'comments', '评论'], ['folder', 'files', '文件'], ['book', 'learn', '学习']].map(([icon, tab, label]) => <button key={tab} className={tab === 'learn' ? 'learn-tool' : ''} title={label} aria-label={`${c.code} ${label}`} onClick={() => goto(`course/${c.id}/${tab}`)}><Icon name={icon}/>{tab === 'learn' && <span>学习</span>}</button>)}</div></article>)}<button className="add-course-card" onClick={this.createCourse}><span className="add-plus"><Icon name="plus"/></span><strong>创建自己的课程</strong><small>添加资料，开启一段新的学习旅程</small></button></div><p className="dashboard-guide">还想学习更多课程？ <button className="link" onClick={() => goto('courses')}>前往所有课程 <span>→</span></button></p></div>; }
    renderCourses() { return <div className="page"><header className="page-heading"><h1>所有课程</h1></header><div className="course-banner"><div className="row"><div className="banner-icon"><Icon name="plus"/></div><div><h3>让你的学习资料，成为一门课程</h3><p>创建私人课程，上传讲义和笔记，再用你喜欢的方式学习。</p></div></div><button className="btn primary" onClick={this.createCourse}><Icon name="plus"/>创建课程</button></div><div className="table-wrap"><table><thead><tr><th>课程</th><th>类型</th><th>可见性</th><th>控制面板</th></tr></thead><tbody>{this.state.courses.map(c => <tr key={c.id}><td><button className="course-name" onClick={() => goto(`course/${c.id}/learn`)}><i className="color-dot" style={{ background: c.color }}/><span><strong>{c.name}</strong><small>{c.code}{c.description ? ' · ' + c.description : ''}</small></span></button></td><td><span className={this.courseTypeClass(c)}>{this.courseTypeLabel(c)}</span></td><td><span className={'chip ' + (c.visibility === 'public' ? 'neutral' : '')}>{c.visibility === 'public' ? '公开' : '仅自己'}</span></td><td>{this.isCampusUnverified(c) && !c.pinned ? <span className="helper-note campus-hint" title="需先完成学生认证">先完成学生认证</span> : <button className={'add-toggle ' + (c.pinned ? 'added' : '')} aria-label={(c.pinned ? '移除 ' : '添加 ') + c.code} title={c.pinned ? '移出控制面板' : '添加到控制面板'} onClick={() => this.togglePin(c)}><Icon name={c.pinned ? 'check' : 'plus'}/></button>}</td></tr>)}</tbody></table></div><p className="helper-note" style={{ marginTop: 20 }}>点击加号即可把课程卡片放到控制面板。移除快捷入口不会删除课程或学习记录。</p></div>; }
    renderCourse() {
        const { cid, tab } = this.state.route;
        const c = this.state.courses.find(x => x.id === cid);
        if (!c)
            return <div className="page"><h2>课程不存在或暂无访问权限</h2><button className="btn" onClick={() => goto('courses')}>返回所有课程</button></div>;
        const common = { course: c, user: this.state.user, config: this.state.config, toast: this.toast, modal: this.modal, closeModal: this.close, refresh: () => this.refresh() };
        return <div className="course-shell"><aside className="course-side"><button className="course-back" onClick={() => goto('courses')}><Icon name="back"/>所有课程</button><div className="side-code">{c.code}</div><div className="side-name">{c.name}</div><div className="side-nav">{[['comment', 'comments', '评论'], ['folder', 'files', '文件'], ['book', 'learn', '学习']].map(([icon, id, label]) => <button className={'course-nav-link ' + (tab === id ? 'active' : '')} key={id} onClick={() => goto(`course/${cid}/${id}`)}><Icon name={icon}/>{label}</button>)}</div><div className="side-course-meta">{c.official ? '课程共享资料 · 个人学习记录' : c.visibility === 'private' ? '私人课程 · 仅自己可见' : '公开课程'}<br />CourseMate Learning Space</div></aside><main className="course-main"><header className="course-top"><Icon name="courses"/><span>{c.code}</span><Icon name="arrow"/><span className="crumb-weak">{tab === 'files' ? '文件' : tab === 'comments' ? '评论' : '学习'}</span></header>{tab === 'files' ? <CourseFiles key={cid} {...common}/> : tab === 'comments' ? <Discussion key={cid} {...common}/> : <Learn key={cid} {...common}/>}</main></div>;
    }
    render() {
        const { user, loading, config, route: r, modal, error, toast } = this.state;
        if (loading)
            return <div className="login-page"><Icon name="book"/><p>正在连接 CourseMate…</p></div>;
        if (!user)
            return <div className="login-page"><div className="login-card"><div className="login-brand"><Icon name="book"/>CourseMate</div><h1>欢迎回到学习空间</h1><p>整理课程，学习知识，一步一步解题。</p>{config?.auth_mode === 'development' ? <><div className="notice">本地联调模式 · 真实 SQLite 数据<br />{config.provider_mode === 'qwen' ? '已配置真实模型，调用受后台预算授权控制' : config.provider_mode === 'test' ? '测试 Provider，不是真实千问' : '模型未连接，不产生模型费用'}<br />测试账号只在本机启用，生产环境会拒绝此登录方式。</div>{[['alice', '以秋同学登录'], ['bob', '以林同学登录'], ['admin', '以课程管理员登录']].map(([a, label]) => <button key={a} className="btn primary" onClick={() => this.login(a)}>{label}</button>)}</> : <button className="btn primary" onClick={() => window.CourseMateAuth?.signIn?.() || window.Clerk?.openSignIn()}>登录 / 注册</button>}{error && !error.includes('请先选择') && <p className="error-text">{error}</p>}</div></div>;
        return <>{this.renderNav()}<div className="app" key={user.id}>{r.page === 'courses' ? this.renderCourses() : r.page === 'course' ? this.renderCourse() : r.page === 'calendar' ? <Calendar user={user} courses={this.state.courses} toast={this.toast} modal={this.modal} closeModal={this.close}/> : r.page === 'inbox' ? <Inbox onJoined={() => this.refresh()} user={user} toast={this.toast} modal={this.modal} closeModal={this.close} onRead={() => this.loadUnread()}/> : this.renderDashboard()}</div>{this.renderDrawer()}{modal && <div className="modal-layer" onClick={e => { if (e.target === e.currentTarget)
            this.close(); }}><section className="modal" role="dialog" aria-modal="true" aria-label={modal.title}><header className="modal-header"><h2>{modal.title}</h2><IconButton name="close" title="关闭窗口" onClick={this.close}/></header><div className="modal-body">{modal.body}</div></section></div>}{toast && <div className="toast" role="status">{toast}</div>}</>;
    }
}
class CourseForm extends React.Component {
    state = { color: COLORS[0], busy: false, error: '' };
    async submit(e) { e.preventDefault(); const f = new FormData(e.currentTarget); this.setState({ busy: true, error: '' }); try {
        await this.props.onSubmit({ name: f.get('name'), code: f.get('code'), description: f.get('description'), color: this.state.color, requirements: f.get('requirements') });
    }
    catch (e) {
        this.setState({ error: e.message, busy: false });
    } }
    render() { return <form onSubmit={e => this.submit(e)}><div className="field"><label>课程名称</label><input name="name" required maxLength="100" placeholder="例如：机器学习基础"/></div><div className="field"><label>课程编号（选填）</label><input name="code" maxLength="30" placeholder="例如：CS3501"/></div><div className="field"><label>课程说明</label><textarea name="description" maxLength="500"/></div><div className="field"><label>你希望怎样学？</label><textarea name="requirements" placeholder="例如：中文教学、保留英文术语，先讲直觉，再做例题。" maxLength="10000"/></div><div className="swatches">{COLORS.map(color => <button type="button" className={'swatch ' + (this.state.color === color ? 'selected' : '')} key={color} style={{ background: color }} onClick={() => this.setState({ color })} aria-label={'课程颜色 ' + color}/>)}</div><p className="helper-note" style={{ margin: '18px 0' }}><Icon name="lock"/> 新课程默认私人，创建后自动添加到你的控制面板。</p>{this.state.error && <p className="error-text">{this.state.error}</p>}<button className="btn primary" disabled={this.state.busy}>{this.state.busy ? '创建中…' : '创建课程'}</button></form>; }
}
class ProfileForm extends React.Component {
    state = { error: '', busy: false };
    async submit(e) { e.preventDefault(); const f = new FormData(e.currentTarget); try {
        this.setState({ busy: true });
        await this.props.onSubmit({ name: f.get('name'), handle: f.get('handle'), bio: f.get('bio'), language: f.get('language'), timezone: f.get('timezone'), reply_notify: f.has('reply_notify'), discoverable: f.has('discoverable') });
    }
    catch (e) {
        this.setState({ error: e.message, busy: false });
    } }
    render() { const u = this.props.user; return <form onSubmit={e => this.submit(e)}><div className="field"><label>显示名称</label><input name="name" defaultValue={u.name} required maxLength="50"/></div><div className="field"><label>用户名（用来查找联系人）</label><input name="handle" defaultValue={u.handle} required pattern="[a-z0-9][a-z0-9_-]{2,29}"/></div><div className="field"><label>个人简介</label><textarea name="bio" defaultValue={u.bio} maxLength="250"/></div><div className="field"><label>教学语言</label><select name="language" defaultValue={u.language}><option value="zh-CN">中文 · 保留英文术语</option><option value="en">English</option><option value="bilingual">中英双语</option><option value="auto">跟随提问语言</option></select></div><div className="field"><label>学习日历时区</label><select name="timezone" defaultValue={u.timezone}>{['Asia/Hong_Kong', 'Asia/Shanghai', 'Asia/Singapore', 'UTC', 'America/New_York', 'Europe/London'].map(z => <option key={z}>{z}</option>)}</select></div><label className="check-line"><input type="checkbox" name="discoverable" defaultChecked={!!u.discoverable}/>允许其他用户通过名字或用户名找到我</label><label className="check-line"><input type="checkbox" name="reply_notify" defaultChecked={!!u.reply_notify}/>接收课程评论回复通知</label>{this.state.error && <p className="error-text">{this.state.error}</p>}<button className="btn primary" style={{ marginTop: 18 }} disabled={this.state.busy}>保存资料</button></form>; }
}
