import { RichText } from './richtext.jsx';
import React from 'react';
import { request, send, remove, download, key, streamEvents } from './api.js';
import { dateKey, zonedParts, wallTimeToISO, formatBytes, formatTime, goto } from './utils.js';
import { Icon, IconButton, Avatar } from './icons.jsx';
export class CourseFiles extends React.Component {
    state = { files: [], q: '', folder: '', error: '', loading: true, menu: null };
    componentDidMount() { this.load(); }
    async load() { try {
        const files = await request(`/courses/${this.props.course.id}/files`);
        this.setState({ files, loading: false, error: '' });
    }
    catch (e) {
        this.setState({ error: e.message, loading: false });
    } }
    async upload(e) { const input = e.currentTarget; const file = input.files[0]; if (!file)
        return; const body = new FormData(); body.append('file', file); body.append('folder', this.state.folder); this.setState({ loading: true }); try {
        const result = await request(`/courses/${this.props.course.id}/files`, { method: 'POST', body });
        await this.load();
        this.props.toast(result.duplicate ? '这份文件已经存在' : result.status === 'indexed' ? '文件已保存并完成文字索引' : '文件已保存，请查看解析提示');
    }
    catch (e) {
        this.props.toast(e.message);
        this.setState({ loading: false });
    } input.value = ''; }
    preview(file) { this.props.modal(file.name, <Preview course={this.props.course} file={file} toast={this.props.toast}/>); }
    async save(file) { try {
        const url = await download(this.props.course.id, file);
        const a = document.createElement('a');
        a.href = url;
        a.download = file.name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        this.setState({ menu: null });
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    render() {
        const { files, q, folder, menu } = this.state;
        const prefix = folder ? folder + '/' : '';
        const folders = q ? [] : [...new Set(files.map(f => f.folder).filter(f => f.startsWith(prefix) && f !== folder).map(f => f.slice(prefix.length).split('/')[0]))];
        const rows = files.filter(f => q ? f.name.toLowerCase().includes(q.toLowerCase()) : f.folder === folder);
        return <div className="course-scroll"><div className="section-heading"><h1>文件</h1><label className="btn"><Icon name="plus"/>添加我的资料<input type="file" style={{ display: 'none' }} onChange={e => this.upload(e)} accept=".pdf,.txt,.md,.csv,.ipynb,.docx,.pptx,.png,.jpg,.jpeg,.webp"/></label></div><form className="file-search" onSubmit={e => e.preventDefault()}><div className="search-field"><Icon name="search"/><input aria-label="搜索文件" placeholder="搜索文件…" value={q} onChange={e => this.setState({ q: e.target.value })}/></div><button className="btn">搜索</button></form><div className="file-path"><button onClick={() => this.setState({ folder: '', q: '' })}>{this.props.course.code} {this.props.course.name}</button>{folder && <><Icon name="arrow"/><span>{folder}</span></>}</div>{this.state.error && <p className="error-text">{this.state.error}</p>}<table className="file-table"><thead><tr><th>名称</th><th>大小</th><th>动作</th></tr></thead><tbody>{folders.map(f => <tr key={f}><td><button className="file-name-btn" onClick={() => this.setState({ folder: prefix + f })}><Icon name="folder"/><span>{f}</span></button></td><td className="file-size">—</td><td /></tr>)}{rows.map(f => <tr key={f.id}><td><button className={'file-name-btn ' + (f.mime === 'application/pdf' ? 'pdf' : '')} onClick={() => this.preview(f)}><Icon name="file"/><span>{f.name}{f.scope === 'private' && <small className="private-note">仅自己</small>}</span></button>{f.error && <p className="helper-note file-note">{f.error}</p>}</td><td className="file-size">{formatBytes(f.size)}</td><td className="file-action"><IconButton name="more" title={'文件操作 ' + f.name} onClick={() => this.setState({ menu: menu === f.id ? null : f.id })}/>{menu === f.id && <div className="dropdown"><button onClick={() => this.save(f)}><Icon name="download"/>下载</button>{f.scope === 'private' && <button onClick={async () => { if (!window.confirm('删除自己的这份文件及其本地索引？'))
            return; try {
            await remove(`/courses/${this.props.course.id}/files/${f.id}`);
            await this.load();
        }
        catch (e) {
            this.props.toast(e.message);
        } }}><Icon name="trash"/>删除我的文件</button>}</div>}</td></tr>)}</tbody></table>{!rows.length && !folders.length && <div className="empty-state"><Icon name="folder"/><h3>{this.state.loading ? '正在读取文件…' : q ? '没有找到匹配文件' : '还没有资料'}</h3><p>添加讲义、笔记或题目，开始你的课程。</p></div>}<p className="file-foot">名称 → 预览 · 右侧菜单 → 下载。新增资料保存在服务器，官方课程里的个人补充仅本人可见。</p></div>;
    }
}
class Preview extends React.Component {
    state = { url: '', text: '', error: '', zoom: 100 };
    componentDidMount() { this.load(); }
    componentWillUnmount() { if (this.state.url)
        URL.revokeObjectURL(this.state.url); this.unmounted = true; }
    async load() {
        try {
            const f = this.props.file;
            if (['application/pdf', 'image/png', 'image/jpeg', 'image/webp'].includes(f.mime)) {
                const url = await download(this.props.course.id, f, true);
                if (this.unmounted) {
                    URL.revokeObjectURL(url);
                    return;
                }
                this.setState({ url });
            }
            else {
                const p = await request(`/courses/${this.props.course.id}/files/${f.id}/text`);
                if (!this.unmounted)
                    this.setState({ text: p.pages.map(x => x.text).join('\n\n') || '此格式暂无文本预览，原文件仍可下载。' });
            }
        }
        catch (e) {
            if (!this.unmounted)
                this.setState({ error: e.message });
        }
    }
    async save() { try {
        const url = await download(this.props.course.id, this.props.file);
        const a = document.createElement('a');
        a.href = url;
        a.download = this.props.file.name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    render() { const f = this.props.file; return <div className="real-preview"><div className="row between"><span className="muted">{formatBytes(f.size)} · 课程资料预览</span><button className="btn small" onClick={() => this.save()}><Icon name="download"/>下载</button></div>{this.state.error ? <div className="error-text">{this.state.error}</div> : this.state.url ? f.mime === 'application/pdf' ? <iframe title={f.name} src={this.state.url + '#toolbar=1'} className="pdf-frame"/> : <div className="image-preview"><img alt={f.name} src={this.state.url}/></div> : this.state.text ? <pre className="text-preview">{this.state.text}</pre> : <div className="empty-state">正在加载预览…</div>}</div>; }
}
export class Discussion extends React.Component {
    state = { rows: [], text: '', replyTo: null, reply: '', busy: false, error: '' };
    componentDidMount() { this.load(); this.timer = setInterval(() => { if (!document.hidden)
        this.load(); }, 15000); }
    componentWillUnmount() { clearInterval(this.timer); this.unmounted = true; }
    async load() { try {
        const rows = await request(`/courses/${this.props.course.id}/comments`);
        if (!this.unmounted)
            this.setState({ rows, error: '' });
    }
    catch (e) {
        if (!this.unmounted)
            this.setState({ error: e.message });
    } }
    async post(parent = null) { const text = parent ? this.state.reply : this.state.text; if (!text.trim())
        return; this.setState({ busy: true }); try {
        await send(`/courses/${this.props.course.id}/comments`, { text, parent, request_id: key() });
        this.setState({ text: parent ? this.state.text : '', reply: '', replyTo: null });
        await this.load();
        this.props.refresh();
    }
    catch (e) {
        this.props.toast(e.message);
    }
    finally {
        this.setState({ busy: false });
    } }
    async like(row) { try {
        if (row.liked)
            await remove(`/courses/${this.props.course.id}/comments/${row.id}/like`);
        else
            await send(`/courses/${this.props.course.id}/comments/${row.id}/like`, {}, 'PUT');
        await this.load();
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    render() { const { rows } = this.state; return <div className="course-scroll"><div className="section-heading"><div><h1>评论</h1><p className="helper-note" style={{ marginTop: 7 }}>交流思路，也把你的问题留在这里。</p></div><span className="chip neutral">{this.props.course.visibility === 'private' ? '私人课程讨论' : '课程公共讨论'}</span></div><form className="discussion-compose" onSubmit={e => { e.preventDefault(); this.post(); }}><div className="compose-main"><Avatar name={this.props.user.name}/><div><textarea aria-label="课程评论" placeholder="对这门课有什么想法？一起交流吧…" maxLength="6000" value={this.state.text} onChange={e => this.setState({ text: e.target.value })}/><div className="row between"><small className="muted">对所有有权访问本课程的用户可见</small><button className="btn primary small" disabled={this.state.busy || !this.state.text.trim()}>发表评论</button></div></div></div></form>{this.state.error && <p className="error-text">{this.state.error}</p>}<div className="discussion-feed">{rows.filter(x => !x.parent).map(row => <article className="discussion" key={row.id} id={'comment-' + row.id}><Avatar name={row.name}/><div className="discussion-content"><div className="discussion-title"><strong>{row.name}</strong><time>{formatTime(row.created_at)}</time></div><p className="discussion-text">{row.text}</p><div className="discussion-actions"><button onClick={() => this.setState({ replyTo: row.id, reply: '' })}><Icon name="comment"/>回复</button><button onClick={() => this.like(row)}><Icon name="heart"/>{row.likes || '赞'}</button>{row.author === this.props.user.id && !row.deleted && <button onClick={async () => { if (window.confirm('删除这条评论？')) {
        await remove(`/courses/${this.props.course.id}/comments/${row.id}`);
        this.load();
    } }}>删除</button>}</div>{rows.filter(x => x.parent === row.id).map(reply => <div className="reply" key={reply.id}><Avatar name={reply.name}/><div><div className="discussion-title"><strong>{reply.name}</strong><time>{formatTime(reply.created_at)}</time></div><p className="discussion-text">{reply.text}</p><button className="link small" onClick={() => this.setState({ replyTo: reply.id, reply: '' })}>回复</button></div></div>)}{(this.state.replyTo === row.id || rows.some(x => x.id === this.state.replyTo && x.parent === row.id)) && <form className="reply-box" onSubmit={e => { e.preventDefault(); this.post(this.state.replyTo); }}><input autoFocus aria-label="回复评论" placeholder="写下你的回复…" value={this.state.reply} maxLength="6000" onChange={e => this.setState({ reply: e.target.value })}/><button className="btn small primary" disabled={this.state.busy}>发送回复</button></form>}</div></article>)}{!rows.length && <div className="empty-state"><Icon name="comment"/><h3>开始这门课的第一段讨论</h3><p>别人回复后，你会在收件箱收到通知。</p></div>}</div></div>; }
}
export class Inbox extends React.Component {
    state = { notifications: [], threads: [], tab: 'all', selected: null, messages: [], reply: '', error: '' };
    componentDidMount() { this.load(); this.timer = setInterval(() => { if (!document.hidden)
        this.load(); }, 10000); }
    componentWillUnmount() { clearInterval(this.timer); this.unmounted = true; }
    async load() { try {
        const [notifications, threads] = await Promise.all([request('/notifications'), request('/threads')]);
        if (!this.unmounted)
            this.setState({ notifications, threads, error: '' });
        if (this.state.selected?.kind === 'thread') {
            const messages = await request(`/threads/${this.state.selected.id}/messages`);
            if (!this.unmounted)
                this.setState({ messages });
        }
    }
    catch (e) {
        if (!this.unmounted)
            this.setState({ error: e.message });
    } }
    async select(item) { try {
        this.setState({ selected: item, reply: '', messages: [] });
        if (item.kind === 'thread') {
            const messages = await request(`/threads/${item.id}/messages`);
            await send(`/threads/${item.id}/read`, {}, 'PUT');
            this.setState({ messages });
        }
        else
            await send(`/notifications/${item.id}/read`, {}, 'PUT');
        await this.load();
        this.props.onRead();
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    compose = () => this.props.modal('发送信息', <ComposeMessage onSubmit={async (payload) => { const m = await send('/messages', payload); this.props.closeModal(); await this.load(); const t = this.state.threads.find(t => t.id === m.thread); if (t)
        this.select({ ...t, kind: 'thread' }); this.props.toast('信息已发送到对方收件箱'); }}/>);
    async reply(e) { e.preventDefault(); const s = this.state.selected; try {
        await send('/messages', { recipient: s.peer.id, text: this.state.reply, request_id: key() });
        this.setState({ reply: '' });
        await this.load();
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    render() { const { notifications, threads, selected: s, tab, messages } = this.state; const all = [...notifications.map(n => ({ ...n, kind: 'notice', title: '回复了你的课程评论', name: n.actor_name, preview: n.text, time: n.created_at, unread: !n.read_at })), ...threads.map(t => ({ ...t, kind: 'thread', title: t.peer.name, name: t.peer.name, preview: t.last?.text || '', time: t.last?.created_at || t.created_at }))].filter(x => tab === 'all' || (tab === 'reply' ? x.kind === 'notice' : x.kind === 'thread')).sort((a, b) => b.time.localeCompare(a.time)); return <div className="page"><header className="page-heading row between"><div><h1>收件箱</h1><p>课程里的回应，以及与你有关的交流。</p></div><button className="btn primary" onClick={this.compose}><Icon name="edit"/>写信息</button></header>{this.state.error && <p className="error-text">{this.state.error}</p>}<div className="inbox-layout"><div className="mail-list"><div className="mail-tabs">{[['all', '全部'], ['reply', '评论回复'], ['dm', '私信']].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => this.setState({ tab })}>{label}</button>)}</div>{all.map(x => <button className={'mail-item ' + (s?.id === x.id ? 'selected' : '')} key={x.id} onClick={() => this.select(x)}><Avatar name={x.name}/><div className="mail-info"><div className="from">{x.name}<span>{formatTime(x.time)}</span></div><strong>{x.title}</strong><p>{x.preview}</p></div>{x.unread > 0 && <i className="unread-dot"/>}</button>)}{!all.length && <div className="empty-state">还没有信息</div>}</div><div className="mail-detail">{!s ? <div className="empty-state"><Icon name="mail"/><h3>选择一条信息，开始交流</h3><p>你的私信不会出现在公开课程评论中。</p></div> : s.kind === 'notice' ? <><div className="mail-detail-head"><h2>{s.actor_name} 回复了你</h2><Icon name="comment"/></div><p className="helper-note">{formatTime(s.created_at)}</p><div className="mail-message">{s.text}</div><button className="btn primary" onClick={() => goto(`course/${s.course}/comments`)}>查看课程讨论 <Icon name="arrow"/></button></> : <><div className="mail-detail-head"><div><h2>{s.peer.name}</h2><span className="helper-note">@{s.peer.handle}</span></div><IconButton name="more" title="屏蔽此联系人" onClick={async () => { if (window.confirm('屏蔽后双方无法继续发私信。确认？')) {
        await send(`/people/${s.peer.id}/block`, {}, 'PUT');
        this.props.toast('已屏蔽此联系人');
    } }}/></div><div className="direct-message-log">{messages.map(m => <div className={'dm-bubble ' + (m.sender === this.props.user.id ? 'mine' : '')} key={m.id}><div className="helper-note">{m.name} · {formatTime(m.created_at)}</div><p>{m.text}</p></div>)}</div><form onSubmit={e => this.reply(e)}><textarea aria-label="私信回复" placeholder="写下回复…" value={this.state.reply} maxLength="6000" onChange={e => this.setState({ reply: e.target.value })}/><button className="btn primary" disabled={!this.state.reply.trim()}>发送回复</button></form></>}</div></div></div>; }
}
class ComposeMessage extends React.Component {
    state = { q: '', people: [], person: null, text: '', error: '', busy: false };
    componentWillUnmount() { clearTimeout(this.timer); }
    search(q) { this.setState({ q }); clearTimeout(this.timer); this.timer = setTimeout(async () => { try {
        const people = await request('/people?q=' + encodeURIComponent(q));
        this.setState({ people });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }, 250); }
    async submit(e) { e.preventDefault(); if (!this.state.person)
        return; try {
        this.setState({ busy: true });
        await this.props.onSubmit({ recipient: this.state.person.id, text: this.state.text, request_id: key() });
    }
    catch (e) {
        this.setState({ error: e.message, busy: false });
    } }
    render() { return <form onSubmit={e => this.submit(e)}><div className="field"><label>收件人</label><input autoFocus aria-label="查找收件人" value={this.state.q} placeholder="输入至少两个字或用户名" onChange={e => this.search(e.target.value)}/><div className="people-results">{this.state.people.map(p => <button type="button" key={p.id} className={'person-option ' + (this.state.person?.id === p.id ? 'selected' : '')} onClick={() => this.setState({ person: p })}><Avatar name={p.name}/><span>{p.name}<small>@{p.handle}</small></span>{this.state.person?.id === p.id && <Icon name="check"/>}</button>)}</div>{this.state.person && <p className="helper-note">收件人：{this.state.person.name}</p>}</div><div className="field"><label>信息内容</label><textarea required maxLength="6000" style={{ minHeight: 130 }} value={this.state.text} onChange={e => this.setState({ text: e.target.value })}/></div><p className="helper-note">只展示已允许搜索的用户，不公开邮箱或手机号。</p>{this.state.error && <p className="error-text">{this.state.error}</p>}<button className="btn primary" style={{ marginTop: 20 }} disabled={!this.state.person || this.state.busy}>发送信息</button></form>; }
}
export class Calendar extends React.Component {
    state = { month: new Date(new Date().getFullYear(), new Date().getMonth(), 1), tasks: [], plan: '', answer: '', busy: false, error: '' };
    componentDidMount() { this.load(); }
    async load() { try {
        this.setState({ tasks: await request('/tasks'), error: '' });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    task = (date, id = null) => { const task = this.state.tasks.find(x => x.id === id); this.props.modal(task ? '修改学习安排' : '新建学习安排', <TaskForm task={task} date={date} courses={this.props.courses} user={this.props.user} onSubmit={async (value) => { if (task)
        await send('/tasks/' + task.id, { title: value.title, due_at: value.due_at, version: task.version }, 'PATCH');
    else
        await send('/tasks', value); this.props.closeModal(); await this.load(); this.props.toast('学习安排已保存'); }}/>); };
    async done(t) { try {
        await send('/tasks/' + t.id, { version: t.version, status: t.status === 'done' ? 'todo' : 'done' }, 'PATCH');
        await this.load();
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async plan(e) { e.preventDefault(); this.setState({ busy: true, answer: '' }); try {
        const result = await send('/tasks/plan', { text: this.state.plan, request_id: key() });
        this.setState({ answer: result.text || result.answer || result.message || '已执行，请检查安排。', plan: '' });
        await this.load();
    }
    catch (e) {
        this.setState({ answer: e.message });
    }
    finally {
        this.setState({ busy: false });
    } }
    render() { const { month, tasks } = this.state; const start = new Date(month); start.setDate(1 - ((start.getDay() + 6) % 7)); const days = Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d; }); const zone = this.props.user.timezone; const today = zonedParts(new Date(),zone).date; return <div className="page"><header className="page-heading"><h1>日历</h1><p>把学习放进生活的节奏里。<span className="small">　{zone}</span></p></header>{this.state.error && <p className="error-text">{this.state.error}</p>}<section className="calendar"><div className="calendar-toolbar"><h2>{month.getFullYear()} 年 {month.getMonth() + 1} 月</h2><div className="row"><button className="btn small" onClick={() => this.setState({ month: new Date(new Date().getFullYear(), new Date().getMonth(), 1) })}>今天</button><IconButton name="back" title="上个月" onClick={() => this.setState({ month: new Date(month.getFullYear(), month.getMonth() - 1, 1) })}/><IconButton name="arrow" title="下个月" onClick={() => this.setState({ month: new Date(month.getFullYear(), month.getMonth() + 1, 1) })}/></div></div><div className="calendar-week">{['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map(x => <div key={x}>{x}</div>)}</div><div className="calendar-grid">{days.map(d => <div key={dateKey(d)} className={'calendar-cell ' + (d.getMonth() !== month.getMonth() ? 'out' : '')} onClick={() => this.task(dateKey(d))} role="button" tabIndex="0" onKeyDown={e => { if (e.key === 'Enter')
        this.task(dateKey(d)); }} aria-label={dateKey(d) + ' 添加安排'}><div className={'calendar-day ' + (dateKey(d) === today ? 'today' : '')}>{d.getDate()}</div>{tasks.filter(t => zonedParts(t.due_at, zone).date === dateKey(d)).map(t => <button key={t.id} className={'calendar-event ' + (t.status === 'done' ? 'done-event' : '')} onClick={e => { e.stopPropagation(); this.task(dateKey(d), t.id); }}>{zonedParts(t.due_at, zone).time} {t.title}</button>)}</div>)}</div></section><section className="plan-section"><div className="row between"><h2>制定学习计划</h2><button className="btn" onClick={() => this.task(today)}><Icon name="plus"/>新建安排</button></div><p>一句话告诉学习计划 Agent，或手动安排下一次复习。</p><div className="plan-layout"><form className="plan-chat" onSubmit={e => this.plan(e)}><div className="row"><span className="mini-logo"><Icon name="book"/></span><h3>学习计划助手</h3></div><p>例如：“明天下午两点复习 DBSCAN”。任务创建、修改和完成会同步到上方日历。</p><textarea aria-label="自然语言学习安排" required maxLength="2000" placeholder="你想怎样安排接下来的学习？" value={this.state.plan} onChange={e => this.setState({ plan: e.target.value })}/><button className="btn primary" disabled={this.state.busy}>{this.state.busy ? '正在处理…' : '安排学习'}</button>{this.state.answer && <p className="plan-response">{this.state.answer}</p>}</form><div className="task-list">{tasks.map(t => <article className="task-card" key={t.id}><button className={'task-check ' + (t.status === 'done' ? 'done' : '')} aria-label={'完成 ' + t.title} onClick={() => this.done(t)}>{t.status === 'done' && <Icon name="check"/>}</button><div style={{ flex: 1 }}><h3 className={t.status === 'done' ? 'completed-title' : ''}>{t.title}</h3><p className="helper-note">{zonedParts(t.due_at, zone).date}　{zonedParts(t.due_at, zone).time}{t.course ? ' · ' + (this.props.courses.find(c => c.id === t.course)?.code || '课程') : ''}</p></div><IconButton name="edit" title={'修改 ' + t.title} onClick={() => this.task('', t.id)}/><IconButton name="trash" title={'删除 ' + t.title} onClick={async () => { if (window.confirm('删除这项学习安排？')) {
        await remove('/tasks/' + t.id+'?version='+t.version);
        this.load();
    } }}/></article>)}{!tasks.length && <div className="empty-state"><Icon name="calendar"/><h3>给下一次学习留一点时间</h3><p>创建安排后会在这里和日历中同步显示。</p></div>}</div></div></section></div>; }
}
class TaskForm extends React.Component {
    state = { error: '', busy: false };
    async submit(e) { e.preventDefault(); const f = new FormData(e.currentTarget); this.setState({ busy: true }); try {
        await this.props.onSubmit({ title: f.get('title'), due_at: wallTimeToISO(f.get('date'), f.get('time'), this.props.user.timezone), timezone: this.props.user.timezone, course: f.get('course') || null, request_id: key() });
    }
    catch (e) {
        this.setState({ error: e.message, busy: false });
    } }
    render() { const { task, user, courses } = this.props; const dt = task ? zonedParts(task.due_at, user.timezone) : { date: this.props.date || dateKey(new Date()), time: '14:00' }; return <form onSubmit={e => this.submit(e)}><div className="field"><label>学习内容</label><input name="title" required maxLength="150" defaultValue={task?.title || ''} placeholder="例如：复习 DBSCAN"/></div><div className="row"><div className="field" style={{ flex: 1 }}><label>日期</label><input name="date" type="date" required defaultValue={dt.date}/></div><div className="field"><label>时间</label><input name="time" type="time" required defaultValue={dt.time}/></div></div><div className="field"><label>所属课程</label><select name="course" defaultValue={task?.course || ''} disabled={!!task}><option value="">个人学习</option>{courses.map(c => <option key={c.id} value={c.id}>{c.code} {c.name}</option>)}</select></div><p className="helper-note">时区：{user.timezone}</p>{this.state.error && <p className="error-text">{this.state.error}</p>}<button className="btn primary" disabled={this.state.busy} style={{ marginTop: 18 }}>保存安排</button></form>; }
}
function inline(text) { return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((x, i) => x.startsWith('**') ? <strong key={i}>{x.slice(2, -2)}</strong> : x.startsWith('`') ? <code key={i}>{x.slice(1, -1)}</code> : x); }
export class Learn extends React.Component {
    state = { attachments:{teach:[],problem:[]}, uploading:{teach:false,problem:false}, nodes: [], expanded: false, hover: null, ratio: .5, fullscreen: false, mobile: 'teach', conv: { teach: null, problem: null }, messages: { teach: [], problem: [] }, inputs: { teach: '', problem: '' }, run: { teach: null, problem: null }, partial: { teach: '', problem: '' }, status: { teach: '', problem: '' }, activeNode: null, bridge: null, error: '', busy: { teach: false, problem: false } };
    controllers = {};
    follow = {teach:true,problem:true};
    componentDidUpdate(prevProps,prevState){
        for(const lane of ['teach','problem'])if(this.follow[lane]&&(prevState.messages[lane]!==this.state.messages[lane]||prevState.partial[lane]!==this.state.partial[lane])){
            const el=document.getElementById('messages-'+lane);if(el)el.scrollTop=el.scrollHeight;
        }
    }
    componentDidMount() { this.load(); this.keyHandler = e => { if (e.key === 'Escape')
        this.setState({ fullscreen: false, expanded: false }); }; window.addEventListener('keydown', this.keyHandler); }
    componentWillUnmount() { this.unmounted = true; window.removeEventListener('keydown', this.keyHandler); Object.values(this.controllers).forEach(c => c.abort()); if(this.onMove){window.removeEventListener('mousemove',this.onMove);window.removeEventListener('touchmove',this.onMove);}if(this.onUp){window.removeEventListener('mouseup',this.onUp);window.removeEventListener('touchend',this.onUp);window.removeEventListener('touchcancel',this.onUp);} }
    async load() { try {
        const cid = this.props.course.id;
        const [nodes, layout] = await Promise.all([request(`/courses/${cid}/knowledge`), request(`/courses/${cid}/layout`)]);
        this.setState({ nodes, ratio: layout.ratio || .5, activeNode: layout.active_node, bridge: layout.bridge || null });
        for (const lane of ['teach', 'problem'])
            if (layout[lane + '_conversation']) {
                try {
                    await this.restore(lane, layout[lane + '_conversation'], false);
                }
                catch { }
            }
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    setLane(field, lane, value, callback) { if (this.unmounted)
        return; this.setState(s => ({ [field]: { ...s[field], [lane]: value } }), callback); }
    async saveLayout() { try {
        await send(`/courses/${this.props.course.id}/layout`, { ratio: this.state.ratio, teach_conversation: this.state.conv.teach, problem_conversation: this.state.conv.problem, active_node: this.state.activeNode }, 'PUT');
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async newChat(lane) { this.controllers[lane]?.abort(); this.setLane('conv', lane, null, () => this.saveLayout()); this.setLane('messages', lane, []); this.setLane('partial', lane, ''); this.setLane('status', lane, ''); this.setLane('run', lane, null); this.setLane('busy', lane, false); }
    async restore(lane, id, save = true) { this.follow[lane]=true;this.controllers[lane]?.abort(); const data = await request('/conversations/' + id); if (this.unmounted)
        return; this.setLane('conv', lane, id, () => { if (save)
        this.saveLayout(); }); this.setLane('messages', lane, data.messages); this.setLane('partial', lane, ''); this.setLane('status', lane, ''); this.setLane('run', lane, null); this.setLane('busy', lane, false); const active = data.active_run; if (active && !['completed', 'cancelled', 'failed'].includes(active.status)) {
        this.setLane('run', lane, active.id);
        this.setLane('partial', lane, active.partial_text);
        this.setLane('busy', lane, true);
        this.watch(lane, active.id, id, true);
    }
    else if (active && active.status === 'failed') {
        this.setLane('status', lane, `上次生成未完成：${active.error}`);
        this.setLane('partial', lane, active.partial_text);
    } }
    history(lane) { this.props.modal(lane === 'teach' ? '知识学习 · 历史对话' : '题目应对 · 历史对话', <History course={this.props.course.id} lane={lane} onSelect={id => { this.props.closeModal(); this.restore(lane, id); }} onDelete={id => { if (this.state.conv[lane] === id)
        this.newChat(lane); }}/>); }
    async ask(lane, text = null, bridge = null) {
        const value = text || this.state.inputs[lane];
        if (!value.trim() || this.state.busy[lane])
            return;
        this.follow[lane]=true;
        this.setLane('busy', lane, true);
        this.setLane('partial', lane, '');
        this.setLane('status', lane, '正在保存问题…');
        try {
            let id = this.state.conv[lane];
            if (!id) {
                const c = await send('/conversations', { course: this.props.course.id, lane });
                id = c.id;
                this.setLane('conv', lane, id, () => this.saveLayout());
            }
            const result = await send(`/conversations/${id}/runs`, { text: value, request_id: key(), bridge_id: bridge?.id || null, node_id: lane === 'teach' ? this.state.activeNode : null, attachment_ids:this.state.attachments[lane].map(f=>f.id) });
            const saved = await request('/conversations/' + id);
            this.setLane('messages', lane, saved.messages);
            this.setLane('inputs', lane, '');
            this.setLane('attachments',lane,[]);
            this.setLane('run', lane, result.id);
            await this.watch(lane, result.id, id, false);
        }
        catch (e) {
            this.setLane('status', lane, e.message);
            this.setLane('busy', lane, false);
            this.props.toast(e.message);
        }
    }
    async watch(lane, rid, cid, recover) {
        const controller = new AbortController();
        this.controllers[lane] = controller;
        try {
            if (recover)
                this.setLane('partial', lane, '');
            await streamEvents(rid, (type, data) => { if (this.state.conv[lane] !== cid)
                return; if (type === 'delta')
                this.setState(s => ({ partial: { ...s.partial, [lane]: s.partial[lane] + data.text } })); if (type === 'status')
                this.setLane('status', lane, data.label || '准备生成…'); if (type === 'error')
                this.setLane('status', lane, data.code + ' · ' + data.message); }, controller.signal);
            if (this.state.conv[lane] === cid && !this.unmounted) {
                const [saved, run] = await Promise.all([request('/conversations/' + cid), request('/runs/' + rid)]);
                this.setLane('messages', lane, saved.messages);
                this.setLane('partial', lane, run.status === 'completed' ? '' : run.partial_text);
                this.setLane('status', lane, run.status === 'completed' ? (this.props.config.provider_mode === 'test' ? '已保存 · 本地合同测试' : '已保存 · 千问双阶段教学') : `${run.status} · ${run.error || ''}`);
                this.setLane('busy', lane, false);
                this.setLane('run', lane, null);
            }
        }
        catch (e) {
            if (e.name !== 'AbortError') {
                this.setLane('status', lane, '连接中断。历史仍在服务器，可打开历史恢复，不会自动再次调用模型。');
                this.setLane('busy', lane, false);
            }
        }
    }
    async attach(lane,e){
        const input=e.currentTarget, file=input.files[0];if(!file)return;
        this.setLane('uploading',lane,true);
        try{
            if(this.state.attachments[lane].length>=4)throw Error('每次最多选择 4 个附件');
            const data=new FormData();data.append('file',file);data.append('folder','我的题目');
            const saved=await request(`/courses/${this.props.course.id}/files`,{method:'POST',body:data});
            if(!this.state.attachments[lane].some(x=>x.id===saved.id))this.setLane('attachments',lane,[...this.state.attachments[lane],saved]);
            if(!this.state.inputs[lane].trim())this.setLane('inputs',lane,'请阅读这个附件，'+(lane==='problem'?'逐步讲解题目；看不清的条件请先指出。':'用中文帮我学习其中的知识，保留英文术语。'));
        }catch(error){this.props.toast(error.message);}finally{input.value='';this.setLane('uploading',lane,false);}
    }
    async inspectPrompt(message){
        try{const run=await request('/runs/'+message.run);this.props.modal('本次千问生成的教学 Prompt',<div><p className="helper-note">这是第一阶段实际生成并保存的 Prompt 正文，第二阶段用它生成讲解。不是模型的私有思维链。</p><pre className="prompt-inspector">{run.generated_prompt||'本次没有保存生成的 Prompt'}</pre><p className="helper-note">状态：{run.status} · 请求：{run.id}</p></div>);}catch(e){this.props.toast(e.message);}
    }
    async stop(lane) { const rid = this.state.run[lane]; if (rid)
        await send('/runs/' + rid + '/cancel', {}); }
    drag(e) {
        e.preventDefault();
        const rect=this.workspace.getBoundingClientRect();
        this.setState({resizing:true});window.getSelection()?.removeAllRanges();
        this.onMove=x=>{if(x.cancelable)x.preventDefault();const cx=x.touches?.[0]?.clientX??x.clientX;this.setState({ratio:Math.max(.25,Math.min(.75,(cx-rect.left)/rect.width))});};
        this.onUp=()=>{window.removeEventListener('mousemove',this.onMove);window.removeEventListener('mouseup',this.onUp);window.removeEventListener('touchmove',this.onMove);window.removeEventListener('touchend',this.onUp);window.removeEventListener('touchcancel',this.onUp);this.setState({resizing:false},()=>this.saveLayout());};
        window.addEventListener('mousemove',this.onMove);window.addEventListener('mouseup',this.onUp);window.addEventListener('touchmove',this.onMove,{passive:false});window.addEventListener('touchend',this.onUp);window.addEventListener('touchcancel',this.onUp);
    }
    async bridge(message, step, title) { try {
        const question = `请讲解原题第 ${step} 步所用的知识：${title.replace(/^#+\s*/, '')}`;
        const bridge = await send(`/courses/${this.props.course.id}/bridges`, { problem_message: message.id, step, question, node: null });
        this.setState({ bridge, mobile: 'teach' });
        await this.ask('teach', question, bridge);
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async backToProblem() { const b = this.state.bridge; if (!b)
        return; await send(`/bridges/${b.id}/return`, {}, 'PATCH'); this.setState({ mobile: 'problem' }, () => document.getElementById(`step-${b.problem_message}-${b.step}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })); }
    learnNode(node) { this.setState({ activeNode: node.id, expanded: false, hover: null, mobile: 'teach' }, () => { this.saveLayout(); this.ask('teach', `请用中文从零教我理解 ${node.title}，保留英文术语，结合课程资料和例题。`); }); }
    async assess(node) { try {
        const result = await request(`/courses/${this.props.course.id}/knowledge/${node.id}/assessment`);
        this.props.modal(node.title + ' · 测评', <div><p>测评服务已连接。</p><pre>{JSON.stringify(result, null, 2)}</pre></div>);
    }
    catch (e) {
        this.props.modal(node.title + ' · 测评', <div><p>{e.message}</p><p className="helper-note" style={{ marginTop: 12 }}>学习进度和测评结果是两个独立状态。没有真实测评时不显示虚构分数。</p></div>);
    } }
    async source(c) { try {
        const rows = await request(`/courses/${this.props.course.id}/files`);
        const f = rows.find(x => x.id === c.document_id);
        if (!f)
            throw new Error('原文件不存在或不可访问');
        this.props.modal(f.name, <Preview course={this.props.course} file={f} toast={this.props.toast}/>);
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    renderTree() { const groups = this.state.nodes.filter(n => !n.parent); return <div className="tree-expanded"><div className="row between"><div><h2>课程知识点树</h2><p className="helper-note" style={{ marginTop: 5 }}>选择节点，分别查看学习进度与测评结果。</p></div><IconButton name="close" title="收起知识树" onClick={() => this.setState({ expanded: false })}/></div><div className="tree-columns">{groups.map(root => <div className="tree-group" key={root.id}><div className="tree-group-title">{root.title}</div>{this.renderNodes(root.id, 0)}</div>)}</div>{!groups.length && <div className="empty-state"><Icon name="tree"/><h3>还没有课程知识树</h3><p>上传资料后，需由现有 V3 知识引擎生成。此更新包不会伪造节点和学习状态。</p></div>}</div>; }
    renderNodes(parent, depth) { return this.state.nodes.filter(n => n.parent === parent).map(n => <div key={n.id} style={{ marginLeft: depth * 14 }}><div className={'tree-node-new ' + (this.state.activeNode === n.id ? 'selected' : '')} tabIndex="0" onMouseEnter={() => this.setState({ hover: n.id })} onFocus={() => this.setState({ hover: n.id })} onMouseLeave={() => this.setState({ hover: null })} onClick={() => this.setState({ hover: n.id })}><Icon name="book"/><span>{n.title}</span><Icon name="arrow"/>{this.state.hover === n.id && <div className="node-popover" onClick={e => e.stopPropagation()}><strong>{n.title}</strong><button onClick={() => this.learnNode(n)}><span>学习进度</span><b>{n.progress === 'LEARNED' ? '教学已完成' : n.progress === 'LEARNING' ? '学习中' : '未开始'}</b><Icon name="arrow"/></button><button onClick={() => this.assess(n)}><span>测评结果</span><b>{n.grade || '未测评'}</b><Icon name="arrow"/></button></div>}</div>{this.renderNodes(n.id, depth + 1)}</div>); }
    renderPane(lane) { const isTeach = lane === 'teach', messages = this.state.messages[lane]; return <section className={'learning-pane pane-' + lane + ' ' + (this.state.mobile === lane ? 'mobile-active' : '')}><header className="pane-header"><div className="row"><span className="pane-symbol"><Icon name={isTeach ? 'book' : 'edit'}/></span><div><h3>{isTeach ? '知识学习' : '题目应对'}</h3><small>{isTeach ? '理解原理，连接知识' : '拆解题目，逐步解决'}</small></div></div><div className="row" style={{ gap: 1 }}><IconButton name="history" title={(isTeach ? '知识' : '题目') + '历史'} onClick={() => this.history(lane)}/><IconButton name="plus" title={(isTeach ? '知识' : '题目') + '新对话'} onClick={() => this.newChat(lane)}/></div></header>{isTeach && this.state.bridge && <button className="bridge-banner" onClick={() => this.backToProblem()}><Icon name="back"/>返回原题 · 第 {this.state.bridge.step} 步 <small>已携带题目上下文</small></button>}<div className="pane-messages" id={'messages-' + lane} onScroll={e=>{const el=e.currentTarget;this.follow[lane]=el.scrollHeight-el.scrollTop-el.clientHeight<100;}}>{messages.length === 0 && !this.state.partial[lane] ? <div className="pane-welcome"><div className="welcome-symbol"><Icon name={isTeach ? 'book' : 'edit'}/></div><h2>{isTeach ? '从一个问题，真正学会' : '把难题，拆成能理解的小步'}</h2><p>{isTeach ? '选一个知识点，或者直接问我。\n从为什么开始，把概念和例题连起来。' : '输入题目或指定文件、题号。\n完整参考解法之后，每个步骤都能继续学。'}</p><div className="suggestion-stack">{(isTeach ? [(this.props.course.id === 'cs3481' ? '请用中文解释 DBSCAN 的核心点' : '请用中文介绍这门课的核心知识'), '我想先看看这门课的知识地图'] : [(this.props.course.id === 'cs3481' ? '讲解 Tutorial_02_Clustering.pdf 的 Question 2' : '请结合我上传的题目说明解题步骤'), '解题时怎样判断应该用哪种方法？']).map(text => <button key={text} onClick={() => this.ask(lane, text)}>{text}<Icon name="arrow"/></button>)}</div></div> : messages.map(m => <article className={'chat-message-new ' + m.role} key={m.id}><div className="message-byline">{m.role === 'user' ? this.props.user.name : 'CourseMate'}{m.role === 'assistant' && <span>{this.props.config.provider_mode === 'test' ? '本地测试 Provider' : this.props.config.model}</span>}</div>{m.attachments?.length>0&&<div className="attachment-chips">{m.attachments.map(f=><span key={f.id}><Icon name="file"/>{f.name}</span>)}</div>}<RichText text={m.text} message={m} lane={lane} onBridge={(...a) => this.bridge(...a)}/>{m.role==='assistant'&&m.run&&<button className="prompt-inspect-button" onClick={()=>this.inspectPrompt(m)}>查看本次教学 Prompt</button>}{m.citations?.length > 0 && <div className="citation-row">{m.citations.map(c => <button key={c.id} onClick={() => this.source(c)}><Icon name="file"/>{c.name} · p.{c.page}</button>)}</div>}</article>)}{this.state.partial[lane] && <article className="chat-message-new assistant"><div className="message-byline">CourseMate <span>生成中 / 未完成内容</span></div><RichText text={this.state.partial[lane]}/></article>}</div><footer className="pane-footer"><div className="generation-status" role="status">{this.state.status[lane] || 'CS3481 模板 → 千问撰写 Prompt → 千问教学'}</div>{this.state.attachments[lane].length>0&&<div className="attachment-chips">{this.state.attachments[lane].map(f=><span key={f.id}><Icon name="file"/>{f.name}<button title="移除本次附件" onClick={()=>this.setLane('attachments',lane,this.state.attachments[lane].filter(x=>x.id!==f.id))}>×</button></span>)}</div>}<form className="chat-composer" onSubmit={e => { e.preventDefault(); this.ask(lane); }}><textarea aria-label={isTeach ? '知识学习输入' : '题目应对输入'} placeholder={isTeach ? '问一个问题，或者告诉我你想学什么…' : '输入题目，或写下文件名与题号…'} value={this.state.inputs[lane]} maxLength="6000" onChange={e => this.setLane('inputs', lane, e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
        e.preventDefault();
        this.ask(lane);
    } }}/><div className="composer-bottom"><div className="row"><label className="attach-button" title="添加题目图片或课程文件"><Icon name="file"/><input type="file" hidden aria-label={isTeach?"知识学习附件":"题目附件"} accept=".pdf,.txt,.md,.csv,.ipynb,.png,.jpg,.jpeg,.webp,.docx,.pptx" disabled={this.state.busy[lane]||this.state.uploading[lane]} onChange={e=>this.attach(lane,e)}/></label><span className="helper-note">{this.state.uploading[lane]?"正在上传…":"Shift + Enter 换行"}</span></div>{this.state.busy[lane] ? <IconButton name="stop" title="停止生成" onClick={() => this.stop(lane)}/> : <button className="send-button" aria-label={isTeach ? '发送知识问题' : '发送题目'} disabled={!this.state.inputs[lane].trim()||this.state.uploading[lane]}><Icon name="send"/></button>}</div></form></footer></section>; }
    render() { return <div className={'learn-new ' + (this.state.fullscreen ? 'focus-mode' : '')}><button className="knowledge-strip" onClick={() => this.setState({ expanded: !this.state.expanded })}><span className="row"><Icon name="tree"/><strong>课程知识点树</strong><small>{this.state.nodes.length} 个节点 · 点击展开</small></span><Icon name={this.state.expanded ? 'up' : 'down'}/></button><div className="workspace-new"><header className="workspace-toolbar"><IconButton name={this.state.fullscreen ? 'collapse' : 'expand'} title={this.state.fullscreen ? '退出全屏学习' : '全屏学习'} onClick={() => this.setState({ fullscreen: !this.state.fullscreen })}/><span className="muted small">{this.props.course.code} · 学习工作台</span><span className="model-label">{this.props.config.provider_mode === 'disabled' ? '模型未连接' : this.props.config.provider_mode === 'test' ? '测试 Provider · 非真实千问' : this.props.config.model}</span></header><div className="mobile-pane-tabs"><button className={this.state.mobile === 'teach' ? 'active' : ''} onClick={() => this.setState({ mobile: 'teach' })}>知识学习</button><button className={this.state.mobile === 'problem' ? 'active' : ''} onClick={() => this.setState({ mobile: 'problem' })}>题目应对</button></div>{this.state.error && <p className="error-text">{this.state.error}</p>}<div className={'workspace-columns '+(this.state.resizing?'is-resizing':'')} ref={el => this.workspace = el} style={{ gridTemplateColumns: `minmax(0,${this.state.ratio}fr) 9px minmax(0,${1 - this.state.ratio}fr)` }}>{this.renderPane('teach')}<div className="pane-divider" role="separator" aria-label="调整学习双栏比例" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow={Math.round(this.state.ratio * 100)} tabIndex="0" onMouseDown={e => this.drag(e)} onTouchStart={e=>this.drag(e)} onKeyDown={e => { if (['ArrowLeft', 'ArrowRight'].includes(e.key)) {
        e.preventDefault();
        this.setState({ ratio: Math.max(.25, Math.min(.75, this.state.ratio + (e.key === 'ArrowLeft' ? -.025 : .025))) }, () => this.saveLayout());
    } }}><span /></div>{this.renderPane('problem')}</div></div>{this.state.expanded && this.renderTree()}</div>; }
}
class History extends React.Component {
    state = { rows: [], error: '' };
    componentDidMount() { this.load(); }
    async load() { try {
        this.setState({ rows: await request(`/conversations?course_id=${this.props.course}&lane=${this.props.lane}`) });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    render() { return <div>{this.state.error && <p className="error-text">{this.state.error}</p>}{this.state.rows.map(c => <div key={c.id} className="history-line"><button className="history-item" onClick={() => this.props.onSelect(c.id)}><Icon name="history"/><span>{c.title}</span><small>{formatTime(c.updated_at)}</small></button><IconButton name="edit" title={'重命名 ' + c.title} onClick={async () => { const title = window.prompt('对话名称', c.title); if (title) {
        await send('/conversations/' + c.id, { title }, 'PATCH');
        this.load();
    } }}/><IconButton name="trash" title={'删除对话 ' + c.title} onClick={async () => { if (window.confirm('删除这段对话？')) {
        try {
            await remove('/conversations/' + c.id);
            this.props.onDelete(c.id);
            this.load();
        }
        catch (e) {
            this.setState({ error: e.message });
        }
    } }}/></div>)}{!this.state.rows.length && <p className="helper-note">还没有历史对话。发送第一个问题后，会保存在这里。</p>}</div>; }
}
