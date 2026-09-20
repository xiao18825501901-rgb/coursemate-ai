import { RichText } from './richtext.jsx';
import { DirectoryPicker } from './DirectoryPicker.jsx';
import React from 'react';
import { request, send, remove, download, key, streamEvents, listPairs, getPair, createPair, renamePair, deletePair, bindPair, createExercise, revealExercise, createExplanation, getExplanation, postExplanationMessage, cancelExplanation, searchPeople, listShares, getShare, createShare, joinShare } from './api.js';
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
        return <div className="course-scroll"><div className="section-heading"><h1>文件</h1><label className="btn" role="button" tabIndex={0} aria-label="添加我的资料" onKeyDown={e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();e.currentTarget.querySelector("input")?.click();}}}><Icon name="plus"/>添加我的资料<input type="file" style={{ display: 'none' }} onChange={e => this.upload(e)} accept=".pdf,.txt,.md,.csv,.ipynb,.docx,.pptx,.png,.jpg,.jpeg,.webp"/></label></div><form className="file-search" onSubmit={e => e.preventDefault()}><div className="search-field"><Icon name="search"/><input aria-label="搜索文件" placeholder="搜索文件…" value={q} onChange={e => this.setState({ q: e.target.value })}/></div><button className="btn">搜索</button></form><div className="file-path"><button onClick={() => this.setState({ folder: '', q: '' })}>{this.props.course.code} {this.props.course.name}</button>{folder && <><Icon name="arrow"/><span>{folder}</span></>}</div>{this.state.error && <p className="error-text">{this.state.error}</p>}<table className="file-table"><thead><tr><th>名称</th><th>大小</th><th>动作</th></tr></thead><tbody>{folders.map(f => <tr key={f}><td><button className="file-name-btn" onClick={() => this.setState({ folder: prefix + f })}><Icon name="folder"/><span>{f}</span></button></td><td className="file-size">—</td><td /></tr>)}{rows.map(f => <tr key={f.id}><td><button className={'file-name-btn ' + (f.mime === 'application/pdf' ? 'pdf' : '')} onClick={() => this.preview(f)}><Icon name="file"/><span>{f.name}{f.scope === 'private' && <small className="private-note">仅自己</small>}</span></button>{f.error && <p className="helper-note file-note">{f.error}</p>}</td><td className="file-size">{formatBytes(f.size)}</td><td className="file-action"><IconButton name="more" title={'文件操作 ' + f.name} onClick={() => this.setState({ menu: menu === f.id ? null : f.id })}/>{menu === f.id && <div className="dropdown"><button onClick={() => this.save(f)}><Icon name="download"/>下载</button>{f.scope === 'private' && <button onClick={async () => { if (!window.confirm('删除自己的这份文件及其本地索引？'))
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
    state = { notifications: [], threads: [], shares: { received: [], sent: [] }, sharesQ: 'received', tab: 'all', selected: null, messages: [], reply: '', error: '', inboxPage:0 };
    componentDidMount() { this.load(); this.timer = setInterval(() => { if (!document.hidden)
        this.load(); }, 10000); }
    componentWillUnmount() { clearInterval(this.timer); this.unmounted = true; }
    async load() { try {
        const offset=this.state.inboxPage*100;
        const [notifications, threads, received, sent] = await Promise.all([request(`/notifications?limit=100&offset=${offset}`), request('/threads'), listShares('received',offset), listShares('sent',offset)]);
        if (!this.unmounted)
            this.setState({ notifications, threads, shares: { received, sent }, error: '' });
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
    shareCourse = () => this.props.modal('共享课程', <ShareCourseModal toast={this.props.toast} closeModal={this.props.closeModal} onDone={() => this.load()}/>);
    async viewShare(share) { try {
        const d = await getShare(share.id);
        const files = d.files || [];
        this.props.modal('共享内容 · ' + d.course_name, <div className="share-review"><p><strong>{d.sender_name}</strong> · {formatTime(d.snapshot_at)}</p><p className="muted">{files.length} 个文件 · {d.history_scope === 'none' ? '不含历史' : '含历史'}{d.pair_count ? ' · ' + d.pair_count + ' 个知识点对话' : ''}{d.requires_student_verification ? ' · 需学生认证' : ''}</p><div className="divider"/>{files.map(f => <div key={f.id || f.name} className="share-pair-row"><Icon name="file"/><span>{f.name}</span></div>)}{!files.length && <p className="helper-note">没有文件</p>}</div>);
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async joinShare(share) { try {
        await joinShare(share.id);
        await this.props.onJoined?.();
        this.props.toast('已加入课程');
        await this.load();
        this.props.onRead?.();
    }
    catch (e) {
        if (e.status === 403)
            this.props.toast('请先完成学生认证（账户 → 学生认证）');
        else
            this.props.toast(e.message);
    } }
    renderShares() { const { shares, sharesQ } = this.state; const rows = shares[sharesQ] || []; return <div className="inbox-share-list"><div className="mail-tabs"><button className={sharesQ === 'received' ? 'active' : ''} onClick={() => this.setState({ sharesQ: 'received' })}>收到</button><button className={sharesQ === 'sent' ? 'active' : ''} onClick={() => this.setState({ sharesQ: 'sent' })}>发出</button></div>{rows.map(sh => <div key={sh.id} className="inbox-share-item"><div className="inbox-share-head"><strong>{sh.course_name}</strong><span>{formatTime(sh.snapshot_at)}</span></div><div className="share-meta">{sharesQ === 'received' && sh.sender_name ? sh.sender_name + ' · ' : ''}{sh.file_count} 个文件 · {sh.history_scope === 'none' ? '不含历史' : '含历史'}{sh.requires_student_verification ? ' · 需学生认证' : ''}</div><div className="share-actions"><button className="btn" onClick={() => this.viewShare(sh)}>查看共享内容</button>{sharesQ === 'received' && (sh.joined_course_id ? <span className="helper-note">已加入</span> : <button className="btn primary" onClick={() => this.joinShare(sh)}>加入所有课程</button>)}</div></div>)}{!rows.length && <div className="empty-state">还没有共享课程</div>}</div>; }
    async reply(e) { e.preventDefault(); const s = this.state.selected; try {
        await send('/messages', { recipient: s.peer.id, text: this.state.reply, request_id: key() });
        this.setState({ reply: '' });
        await this.load();
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    render() { const { notifications, threads, selected: s, tab, messages } = this.state; const all = [...notifications.map(n => ({ ...n, kind: 'notice', title: '回复了你的课程评论', name: n.actor_name, preview: n.text, time: n.created_at, unread: !n.read_at })), ...threads.map(t => ({ ...t, kind: 'thread', title: t.peer.name, name: t.peer.name, preview: t.last?.text || '', time: t.last?.created_at || t.created_at }))].filter(x => tab === 'all' || (tab === 'reply' ? x.kind === 'notice' : x.kind === 'thread')).sort((a, b) => b.time.localeCompare(a.time)); return <div className="page"><header className="page-heading row between"><div><h1>收件箱</h1><p>课程里的回应，以及与你有关的交流。</p></div><div className="row" style={{ gap: 8 }}><button className="btn" onClick={this.shareCourse}><Icon name="shareCourse"/>共享课程</button><button className="btn primary" onClick={this.compose}><Icon name="edit"/>写信息</button></div></header><nav aria-label="收件箱分页" className="row"><button className="btn small" disabled={this.state.inboxPage===0} onClick={()=>this.setState(s=>({inboxPage:s.inboxPage-1}),()=>this.load())}>上一页通知与共享</button><span>第 {this.state.inboxPage+1} 页</span><button className="btn small" onClick={()=>this.setState(s=>({inboxPage:s.inboxPage+1}),()=>this.load())}>下一页通知与共享</button></nav>{this.state.error && <p className="error-text">{this.state.error}</p>}<div className="inbox-layout"><div className="mail-list"><div className="mail-tabs">{[['all', '全部'], ['reply', '评论回复'], ['dm', '私信'], ['shares', '共享']].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => this.setState({ tab: id })}>{label}</button>)}</div>{tab === 'shares' ? this.renderShares() : <>{all.map(x => <button className={'mail-item ' + (s?.id === x.id ? 'selected' : '')} key={x.id} onClick={() => this.select(x)}><Avatar name={x.name}/><div className="mail-info"><div className="from">{x.name}<span>{formatTime(x.time)}</span></div><strong>{x.title}</strong><p>{x.preview}</p></div>{x.unread > 0 && <i className="unread-dot"/>}</button>)}{!all.length && <div className="empty-state">还没有信息</div>}</>}</div><div className="mail-detail">{!s ? <div className="empty-state"><Icon name="mail"/><h3>选择一条信息，开始交流</h3><p>你的私信不会出现在公开课程评论中。</p></div> : s.kind === 'notice' ? <><div className="mail-detail-head"><h2>{s.actor_name} 回复了你</h2><Icon name="comment"/></div><p className="helper-note">{formatTime(s.created_at)}</p><div className="mail-message">{s.text}</div><button className="btn primary" onClick={() => goto(`course/${s.course}/comments`)}>查看课程讨论 <Icon name="arrow"/></button></> : <><div className="mail-detail-head"><div><h2>{s.peer.name}</h2><span className="helper-note">@{s.peer.handle}</span></div><IconButton name="more" title="屏蔽此联系人" onClick={async () => { if (window.confirm('屏蔽后双方无法继续发私信。确认？')) {
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
    render() { return <form onSubmit={e => this.submit(e)}><div className="field"><label>收件人</label><DirectoryPicker selected={this.state.person?[this.state.person.id]:[]} onSelect={person=>this.setState({person})}/>{this.state.person && <p className="helper-note">收件人：{this.state.person.name}</p>}</div><div className="field"><label>信息内容</label><textarea required maxLength="6000" style={{ minHeight: 130 }} value={this.state.text} onChange={e => this.setState({ text: e.target.value })}/></div><p className="helper-note">只展示已允许搜索的用户，不公开邮箱或手机号。</p>{this.state.error && <p className="error-text">{this.state.error}</p>}<button className="btn primary" style={{ marginTop: 20 }} disabled={!this.state.person || this.state.busy}>发送信息</button></form>; }
}
class ShareCourseModal extends React.Component {
    state = { step: 1, courses: [], course: null, q: '', people: [], recipients: [], scope: 'none', pairs: [], selectedPairs: [], fileCount: 0, busy: false, error: '', requestId: null };
    componentDidMount() { this.loadCourses(); }
    componentWillUnmount() { clearTimeout(this.timer); }
    async loadCourses() { try {
        const courses = await request('/courses');
        this.setState({ courses });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    search(q) { this.setState({ q }); clearTimeout(this.timer); this.timer = setTimeout(async () => { try {
        const people = await searchPeople(q);
        this.setState({ people });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }, 250); }
    pickCourse(c) { this.setState({ course: c, step: 2, scope: 'none', selectedPairs: [], recipients: [], q: '' }); }
    toggleRecipient(p) { this.setState(s => ({ recipients: s.recipients.some(r => r.id === p.id) ? s.recipients.filter(r => r.id !== p.id) : [...s.recipients, p] })); }
    async pickScope(scope) { this.setState({ scope, selectedPairs: [] }); if (scope === 'selected') { try {
        const pairs = await listPairs(this.state.course.id);
        this.setState({ pairs });
    }
    catch (e) {
        this.setState({ error: e.message });
    } } }
    togglePair(id) { this.setState(s => ({ selectedPairs: s.selectedPairs.includes(id) ? s.selectedPairs.filter(x => x !== id) : [...s.selectedPairs, id] })); }
    async review() { try {
        const files = await request(`/courses/${this.state.course.id}/files`);
        this.setState({ fileCount: files.length, step: 4 });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async send() { const payload = { course: this.state.course.id, recipients: this.state.recipients.map(r => r.id), history_scope: this.state.scope, selected_pair_ids: this.state.scope === 'selected' ? this.state.selectedPairs : [] }; const requestId = this.state.requestId || key(); this.setState({ requestId, busy: true }); try {
        const result = await createShare(payload, requestId);
        this.props.closeModal();
        this.props.toast('共享已发送' + (result.reused ? '（已复用之前的请求）' : ''));
        this.props.onDone?.();
    }
    catch (e) {
        this.setState({ error: e.message, busy: false });
    } }
    scopeLabel() { return this.state.scope === 'all' ? '全部发送' : this.state.scope === 'none' ? '全部不发送' : '选择特定知识点对话'; }
    render() { const { step, courses, course, q, people, recipients, scope, pairs, selectedPairs, fileCount, busy, error } = this.state; return <div className="share-wizard">{error && <p className="error-text">{error}</p>}{step === 1 && <div className="share-step"><h4>1. 选择要共享的课程</h4><div className="node-picker-list">{courses.map(c => <button type="button" key={c.id} className="node-picker-row" onClick={() => this.pickCourse(c)}><Icon name="book"/><span>{c.name}</span><small className="muted">{c.code}</small></button>)}{!courses.length && <p className="helper-note" style={{ padding: 12 }}>没有可共享的课程</p>}</div></div>}{step === 2 && <div className="share-step"><h4>2. 选择接收者</h4><DirectoryPicker selected={recipients.map(r=>r.id)} onSelect={p=>this.toggleRecipient(p)}/><div className="recipient-chips">{recipients.map(r => <span className="recipient-chip" key={r.id}>{r.name}<button type="button" onClick={() => this.toggleRecipient(r)}>×</button></span>)}</div><div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => this.setState({ step: 1 })}>上一步</button><button className="btn primary" disabled={!recipients.length} onClick={() => this.setState({ step: 3 })}>下一步</button></div></div>}{step === 3 && <div className="share-step"><h4>3. 历史范围</h4><div className="share-radio"><label><input type="radio" name="scope" checked={scope === 'all'} onChange={() => this.pickScope('all')}/>全部发送</label><label><input type="radio" name="scope" checked={scope === 'none'} onChange={() => this.pickScope('none')}/>全部不发送</label><label><input type="radio" name="scope" checked={scope === 'selected'} onChange={() => this.pickScope('selected')}/>选择特定知识点对话</label></div>{scope === 'selected' && <div className="share-pair-list">{pairs.map(p => <label key={p.id} className="share-pair-row"><input type="checkbox" checked={selectedPairs.includes(p.id)} onChange={() => this.togglePair(p.id)}/><span>{p.title}</span><small className="muted">{formatTime(p.updated_at)}</small></label>)}{!pairs.length && <p className="helper-note" style={{ padding: 12 }}>没有知识点对话</p>}</div>}<div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => this.setState({ step: 2 })}>上一步</button><button className="btn primary" disabled={scope === 'selected' && !selectedPairs.length} onClick={() => this.review()}>下一步</button></div></div>}{step === 4 && <div className="share-step"><h4>4. 确认发送</h4><div className="share-review"><p>课程：{course?.name}</p><p>接收者：{recipients.map(r => r.name).join('、')}</p><p>文件：{fileCount} 个</p><p>历史：{this.scopeLabel()}{scope === 'selected' ? '（' + selectedPairs.length + ' 个对话）' : ''}</p></div><div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => this.setState({ step: 3 })}>上一步</button><button className="btn primary" disabled={busy} onClick={() => this.send()}>{busy ? '发送中…' : '确认发送'}</button></div></div>}</div>; }
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
class ReasoningStrengthPicker extends React.Component {
    state = { open: false };
    componentDidUpdate(_, previous) { if (!previous.open && this.state.open)
        document.addEventListener('mousedown', this.dismiss, true); else if (previous.open && !this.state.open)
        document.removeEventListener('mousedown', this.dismiss, true); }
    componentWillUnmount() { document.removeEventListener('mousedown', this.dismiss, true); }
    dismiss = event => { if (!this.root?.contains(event.target)) this.close(); };
    close = () => this.setState({ open: false }, () => this.button?.focus());
    choose = value => { this.props.onChange(value); this.close(); };
    render() { const values = ['medium', 'high', 'max'], labels = { medium: '中', high: '高', max: '最高' }, index = values.indexOf(this.props.value); return <span className="reasoning-strength" ref={el => this.root = el}><button ref={el => this.button = el} type="button" className="reasoning-trigger" aria-label={`${this.props.lane === 'teach' ? '知识学习' : '题目应对'}推理强度：${labels[this.props.value]}`} aria-haspopup="dialog" aria-expanded={this.state.open} disabled={this.props.disabled} onClick={() => this.setState(s => ({ open: !s.open }))}><Icon name="gauge"/><span>{labels[this.props.value]}</span></button>{this.state.open && <div className="reasoning-popover" role="dialog" aria-label="推理强度" onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); this.close(); } }}><strong>推理强度</strong><input aria-label="推理强度" type="range" min="0" max="2" step="1" value={index} onChange={event => this.props.onChange(values[Number(event.target.value)])}/><div className="reasoning-ticks">{values.map((value, tick) => <button type="button" key={value} className={this.props.value === value ? 'selected' : ''} aria-pressed={this.props.value === value} onClick={() => this.choose(value)}><i>{tick + 1}</i>{labels[value]}</button>)}</div></div>}</span>; }
}
export class Learn extends React.Component {
    state = { attachments:{teach:[],problem:[]}, uploading:{teach:false,problem:false}, nodes: [], expanded: false, hover: null, ratio: .5, fullscreen: false, mobile: 'teach', conv: { teach: null, problem: null }, messages: { teach: [], problem: [] }, inputs: { teach: '', problem: '' }, run: { teach: null, problem: null }, partial: { teach: '', problem: '' }, status: { teach: '', problem: '' }, activeNode: null, error: '', busy: { teach: false, problem: false }, thinking: { teach: false }, strength: { teach: 'medium', problem: 'medium' }, exercises: {}, explanations: {}, windows: {}, pair: null };
    controllers = {};
    explanationControllers = {};
    follow = {teach:true,problem:true};
    winZ = 0;
    winCount = 0;
    componentDidUpdate(prevProps,prevState){
        for(const lane of ['teach','problem'])if(this.follow[lane]&&(prevState.messages[lane]!==this.state.messages[lane]||prevState.partial[lane]!==this.state.partial[lane])){
            const el=document.getElementById('messages-'+lane);if(el)el.scrollTop=el.scrollHeight;
        }
    }
    componentDidMount() { this.load(); this.keyHandler = e => { if (e.key === 'Escape')
        this.setState({ fullscreen: false, expanded: false }); }; window.addEventListener('keydown', this.keyHandler); }
    componentWillUnmount() { this.unmounted = true; window.removeEventListener('keydown', this.keyHandler); Object.values(this.controllers).forEach(c => c.abort()); Object.values(this.explanationControllers).forEach(c => c.abort()); if(this.onMove){window.removeEventListener('mousemove',this.onMove);window.removeEventListener('touchmove',this.onMove);}if(this.onUp){window.removeEventListener('mouseup',this.onUp);window.removeEventListener('touchend',this.onUp);window.removeEventListener('touchcancel',this.onUp);} }
    async load() { const revision=this.pairRevision || 0; try {
        const cid = this.props.course.id;
        const [nodes, layout] = await Promise.all([request(`/courses/${cid}/knowledge`), request(`/courses/${cid}/layout`)]);
        if (this.unmounted || revision !== (this.pairRevision || 0)) return;
        this.setState({ nodes, ratio: layout.ratio || .5, activeNode: layout.active_node, strength: { teach: layout.teach_strength || 'medium', problem: layout.problem_strength || 'medium' } });
        const pairs = await listPairs(cid);
        if (this.unmounted || revision !== (this.pairRevision || 0)) return;
        const current = pairs.find(p =>
            (layout.teach_conversation && p.teach_conversation === layout.teach_conversation) ||
            (layout.problem_conversation && p.problem_conversation === layout.problem_conversation));
        if (current) { await this.restorePair(current.id); return; }
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
    setStrength(lane, strength) {
        this.setLane('strength', lane, strength, () => this.saveLayout());
    }
    async saveLayout() { try {
        await send(`/courses/${this.props.course.id}/layout`, { ratio: this.state.ratio, teach_conversation: this.state.conv.teach, problem_conversation: this.state.conv.problem, active_node: this.state.activeNode, teach_strength: this.state.strength.teach, problem_strength: this.state.strength.problem }, 'PUT');
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async newPair() { const revision=this.pairRevision=(this.pairRevision || 0)+1; for (const lane of ['teach', 'problem'])
        this.controllers[lane]?.abort(); try {
        const pair = await createPair(this.props.course.id);
        if (this.unmounted || this.pairRevision!==revision) return;
        this.setState({ pair: pair.id, conv: { teach: null, problem: null }, messages: { teach: [], problem: [] }, inputs: { teach: '', problem: '' }, attachments: { teach: [], problem: [] }, partial: { teach: '', problem: '' }, status: { teach: '', problem: '' }, run: { teach: null, problem: null }, busy: { teach: false, problem: false } }, () => this.saveLayout());
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async restorePair(id) { const revision = this.pairRevision = (this.pairRevision || 0) + 1; for (const lane of ['teach', 'problem'])
        this.controllers[lane]?.abort(); try {
        const pair = await getPair(id);
        if (this.unmounted || revision !== this.pairRevision) return;
        for (const lane of ['teach', 'problem']) {
            const data = pair[lane];
            this.follow[lane] = true;
            if (data) {
                this.setLane('conv', lane, data.conversation.id);
                this.setLane('messages', lane, data.messages);
                this.setLane('partial', lane, '');
                this.setLane('status', lane, '');
                this.setLane('run', lane, null);
                this.setLane('busy', lane, false);
                const active = data.active_run;
                if (active && !['completed', 'cancelled', 'failed'].includes(active.status)) {
                    this.setLane('run', lane, active.id);
                    this.setLane('partial', lane, active.partial_text);
                    this.setLane('busy', lane, true);
                    this.watch(lane, active.id, data.conversation.id, true);
                }
                else if (active && active.status === 'failed') {
                    this.setLane('status', lane, `上次生成未完成：${active.error}`);
                    this.setLane('partial', lane, active.partial_text);
                }
            }
            else {
                this.setLane('conv', lane, null);
                this.setLane('messages', lane, []);
                this.setLane('partial', lane, '');
                this.setLane('status', lane, '');
                this.setLane('run', lane, null);
                this.setLane('busy', lane, false);
            }
        }
        this.setState({ pair: id, activeNode: pair.bound_node || null }, () => this.saveLayout());
    }
    catch (e) {
        this.props.toast(e.message);
    } }
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
    history() { this.props.modal('历史对话', <PairHistory course={this.props.course.id} toast={this.props.toast} closeModal={this.props.closeModal} onSelect={id => { this.props.closeModal(); this.restorePair(id); }} onDeleted={(id, teachConv, problemConv) => { if (teachConv === this.state.conv.teach || problemConv === this.state.conv.problem) {
        this.setState({ pair: null, conv: { teach: null, problem: null }, messages: { teach: [], problem: [] }, partial: { teach: '', problem: '' }, status: { teach: '', problem: '' }, run: { teach: null, problem: null }, busy: { teach: false, problem: false } });
    } }}/>); }
    async ensurePair() {
        if (this.state.pair) return this.state.pair;
        if (!this.pendingPair) this.pendingPair = createPair(this.props.course.id).then(pair => {
            this.setState({pair: pair.id}); return pair.id;
        }).finally(() => { this.pendingPair = null; });
        return this.pendingPair;
    }
    async ask(lane, text = null) {
        const value = text || this.state.inputs[lane];
        const revision=this.pairRevision || 0;
        const frozen={node_id:lane==='teach'?this.state.activeNode:null,
            attachment_ids:this.state.attachments[lane].map(f=>f.id),
            teaching_mode:lane==='teach'&&this.state.thinking.teach?'thinking':'normal',
            reasoning_strength:this.state.strength[lane]};
        if (!value.trim() || this.state.busy[lane])
            return;
        this.follow[lane]=true;
        this.setLane('busy', lane, true);
        this.setLane('partial', lane, '');
        this.setLane('status', lane, '正在思考中');
        try {
            let id = this.state.conv[lane];
            if (!id) {
                const pairId = await this.ensurePair();
                const c = await send('/conversations', { course: this.props.course.id, lane, pair_id: pairId });
                id = c.id;
                this.setLane('conv', lane, id, () => this.saveLayout());
            }
            const result = await send(`/conversations/${id}/runs`, { text: value, request_id: key(), ...frozen });
            const saved = await request('/conversations/' + id);
            if(this.unmounted || revision!==(this.pairRevision || 0)) return;
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
            let seenDelta = false;
            await streamEvents(rid, (type, data) => { if (this.state.conv[lane] !== cid)
                return; if (type === 'delta') {
                seenDelta = true;
                this.setState(s => ({ partial: { ...s.partial, [lane]: s.partial[lane] + data.text } }));
                this.setLane('status', lane, '正在输出中');
            }
            if (type === 'status')
                this.setLane('status', lane, seenDelta ? '正在输出中' : (data.label || '正在思考中')); if (type === 'error')
                this.setLane('status', lane, data.message || (data.code + ' · ' + data.message)); }, controller.signal);
            if (this.state.conv[lane] === cid && !this.unmounted) {
                const [saved, run] = await Promise.all([request('/conversations/' + cid), request('/runs/' + rid)]);
                this.setLane('messages', lane, saved.messages);
                this.setLane('partial', lane, run.status === 'completed' ? '' : run.partial_text);
                if (run.status === 'completed') {
                    const coverage = run.coverage;
                    const coverageLabel = coverage && coverage.status === 'submitted' ? (coverage.covered_items && JSON.parse(coverage.covered_items).length > 0 ? ' · 已计入覆盖' : ' · 覆盖待确认') : '';
                    // The completed run is the authoritative receipt. Keep its
                    // result visible instead of clearing the user-facing proof
                    // before the next render; it does not alter the coverage
                    // ledger or conflate LEARNED with an assessment result.
                    this.setLane('status', lane, coverageLabel.trim());
                }
                else if (!this.state.status[lane]) {
                    this.setLane('status', lane, `${run.status} · ${run.error || ''}`);
                }
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
    async stop(lane) { const rid = this.state.run[lane]; if (rid)
        await send('/runs/' + rid + '/cancel', {}); }
    async doExercise() { const lane = 'problem'; if (this.state.busy.problem)
        return; this.follow.problem = true; this.setLane('busy', lane, true); this.setLane('partial', lane, ''); this.setLane('status', lane, '正在出题…'); try {
        const run = await createExercise(this.props.course.id, null, this.state.pair?.id || this.state.pair);
        this.setLane('run', lane, run.id);
        await this.watchExercise(run.id);
    }
    catch (e) {
        this.setLane('status', lane, e.message);
        this.setLane('busy', lane, false);
        this.props.toast(e.message);
    } }
    async watchExercise(rid) {
        const controller = new AbortController();
        this.controllers['problem'] = controller;
        let seenDelta = false;
        try {
            await streamEvents(rid, (type, data) => { if (type === 'delta') {
                seenDelta = true;
                this.setState(s => ({ partial: { ...s.partial, problem: s.partial.problem + data.text } }));
                this.setLane('status', 'problem', '正在输出中');
            }
            if (type === 'status')
                this.setLane('status', 'problem', seenDelta ? '正在输出中' : (data.label || '正在思考中')); if (type === 'error')
                this.setLane('status', 'problem', data.message || (data.code + ' · ' + data.message)); }, controller.signal);
            if (!this.unmounted) {
                const run = await request('/runs/' + rid);
                if (run.conversation) {
                    this.setLane('conv', 'problem', run.conversation, () => this.saveLayout());
                    const saved = await request('/conversations/' + run.conversation);
                    this.setLane('messages', 'problem', saved.messages);
                }
                this.setLane('partial', 'problem', run.status === 'completed' ? '' : run.partial_text);
                if (run.status === 'completed')
                    this.setLane('status', 'problem', '');
                else if (!this.state.status.problem)
                    this.setLane('status', 'problem', `${run.status} · ${run.error || ''}`);
                this.setLane('busy', 'problem', false);
                this.setLane('run', 'problem', null);
            }
        }
        catch (e) {
            if (e.name !== 'AbortError') {
                this.setLane('status', 'problem', '连接中断。题目可能仍在生成，可稍后刷新查看。');
                this.setLane('busy', 'problem', false);
            }
        }
    }
    async revealSteps(exerciseId) { try {
        const revealed = await revealExercise(exerciseId);
        this.setState(s => ({ exercises: { ...s.exercises, [exerciseId]: { ...(s.exercises[exerciseId] || {}), revealed: true, steps: revealed.steps } } }));
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    renderExercise(m) { const ex = this.state.exercises[m.exercise] || m.exercise_state; const revealed = !!ex?.revealed; return <div className="exercise-actions">{!revealed ? <button className="show-answer-link" onClick={() => this.revealSteps(m.exercise)}>显示答案</button> : <div className="exercise-steps">{(ex.steps || []).map(s => <div className="exercise-step" key={s.step_id}><div className="step-title">{s.ordinal}. {s.title}</div><div className="step-text">{s.text}</div><button className="step-explain-link" onClick={() => this.openExplanation(m.exercise, s, s.ordinal)}>详解</button></div>)}</div>}</div>; }
    openExplanation(exerciseId, step, ordinal) {
        const key = exerciseId + ':' + step.step_id;
        if (this.state.windows[key]) {
            this.closeWindow(key);
            return;
        }
        const n = this.winCount++, z = ++this.winZ, w = 520, h = 420;
        const x = Math.max(12, Math.round((window.innerWidth - w) / 2) - 60 + n * 24);
        const y = Math.max(12, Math.round((window.innerHeight - h) / 2) - 40 + n * 24);
        this.setState(s => ({ windows: { ...s.windows, [key]: { exerciseId, stepId: step.step_id, ordinal, title: step.title, x, y, w, h, z } } }));
        this.ensureExplanation(key, exerciseId, step.step_id);
    }
    closeWindow(key) { this.explanationControllers[key]?.abort(); this.setState(s => { const w = { ...s.windows };
        delete w[key];
        return { windows: w }; }); }
    raiseWindow(key) { const z = ++this.winZ; this.setState(s => ({ windows: { ...s.windows, [key]: { ...(s.windows[key] || {}), z } } })); }
    async ensureExplanation(key, exerciseId, stepId) { try {
        let exp = this.state.explanations[key];
        if (!exp?.id) {
            const created = await createExplanation(exerciseId, stepId);
            if (created.status === 'completed' || !created.run) {
                const detail = await getExplanation(created.id);
                this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...detail } } }));
                return;
            }
            this.setState(s => ({ explanations: { ...s.explanations, [key]: { id: created.id, status: 'generating', text: '', messages: [], run: created.run, partial: '' } } }));
            this.watchExplanation(key, created.id, created.run);
            return;
        }
        const detail = await getExplanation(exp.id);
        this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...detail } } }));
        if (detail.status === 'generating' && detail.run)
            this.watchExplanation(key, detail.id, detail.run);
    }
    catch (e) {
        this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...(s.explanations[key] || {}), status: 'error', error: e.message } } }));
    } }
    refreshExplanation(key) { const exp = this.state.explanations[key]; if (!exp?.id)
        return; getExplanation(exp.id).then(detail => { if (!this.unmounted)
        this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...detail } } })); }).catch(() => { }); }
    watchExplanation(key, expId, runId) {
        const controller = new AbortController();
        this.explanationControllers[key] = controller;
        streamEvents(runId, (type, data) => { if (this.unmounted)
            return; if (type === 'delta')
            this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...(s.explanations[key] || {}), status: 'generating', partial: ((s.explanations[key] || {}).partial || '') + data.text } } })); if (type === 'error')
            this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...(s.explanations[key] || {}), status: 'error', error: data.message || data.code } } })); }, controller.signal).then(() => { if (!this.unmounted)
            this.refreshExplanation(key); }).catch(e => { if (e.name !== 'AbortError' && !this.unmounted)
            this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...(s.explanations[key] || {}), status: 'error', error: '连接中断' } } })); });
    }
    sendExplanationFollowUp(key, text) { const exp = this.state.explanations[key]; if (!exp || !text || !text.trim())
        return; const t = text.trim(); this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...(s.explanations[key] || {}), status: 'generating', partial: '', error: '' } } })); (async () => { try {
        const result = await postExplanationMessage(exp.id, t);
        if (result.run)
            this.watchExplanation(key, exp.id, result.run);
        else
            this.refreshExplanation(key);
    }
    catch (e) {
        this.props.toast(e.message);
    } })(); }
    cancelExplanationWindow(key) { const exp = this.state.explanations[key]; if (!exp)
        return; this.explanationControllers[key]?.abort(); (async () => { try {
        await cancelExplanation(exp.id);
        this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...(s.explanations[key] || {}), status: 'cancelled' } } }));
    }
    catch (e) {
        this.props.toast(e.message);
    } })(); }
    renderWindows() { const keys = Object.keys(this.state.windows); if (!keys.length)
        return null; return keys.map(key => <ExplanationWindow key={key} win={this.state.windows[key]} exp={this.state.explanations[key]} onClose={() => this.closeWindow(key)} onRaise={() => this.raiseWindow(key)} onFollowUp={text => this.sendExplanationFollowUp(key, text)} onCancel={() => this.cancelExplanationWindow(key)}/>); }
    drag(e) {
        e.preventDefault();
        const rect=this.workspace.getBoundingClientRect();
        this.setState({resizing:true});window.getSelection()?.removeAllRanges();
        this.onMove=x=>{if(x.cancelable)x.preventDefault();const cx=x.touches?.[0]?.clientX??x.clientX;this.setState({ratio:Math.max(.25,Math.min(.75,(cx-rect.left)/rect.width))});};
        this.onUp=()=>{window.removeEventListener('mousemove',this.onMove);window.removeEventListener('mouseup',this.onUp);window.removeEventListener('touchmove',this.onMove);window.removeEventListener('touchend',this.onUp);window.removeEventListener('touchcancel',this.onUp);this.setState({resizing:false},()=>this.saveLayout());};
        window.addEventListener('mousemove',this.onMove);window.addEventListener('mouseup',this.onUp);window.addEventListener('touchmove',this.onMove,{passive:false});window.addEventListener('touchend',this.onUp);window.addEventListener('touchcancel',this.onUp);
    }
    async learnNode(node) {
        try {
        const opened = await send(`/courses/${this.props.course.id}/nodes/${node.id}/open`, {});
            this.setState({ activeNode: node.id, expanded: false, hover: null, mobile: 'teach' });
            await this.restorePair(opened.pair_id);
        } catch (error) { this.props.toast(error.message); }
    }
    async assess(node) { try {
        const result = await request(`/courses/${this.props.course.id}/knowledge/${node.id}/assessment`);
        this.props.modal(node.title + ' · 测评', <Assessment course={this.props.course} node={node} result={result} onDone={() => this.load()}/>);
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
    renderTree() { const groups = this.state.nodes.filter(n => !n.parent); return <div className="tree-expanded"><div className="row between"><div><h2>课程知识点树</h2><p className="helper-note" style={{ marginTop: 5 }}>选择节点，分别查看学习进度与测评结果。</p></div><IconButton name="close" title="收起知识树" onClick={() => this.setState({ expanded: false })}/></div><div className="tree-columns">{groups.map(root => { const children = this.state.nodes.filter(n => n.parent === root.id); return <div className="tree-group" key={root.id}>{children.length ? <div className="tree-group-title">{root.title}</div> : null}{children.length ? this.renderNodes(root.id, 0) : this.renderNodeRow(root, 0)}</div>; })}</div>{!groups.length && <div className="empty-state"><Icon name="tree"/><h3>还没有课程知识树</h3><p>上传资料后，需由现有 V3 知识引擎生成。此更新包不会伪造节点和学习状态。</p></div>}</div>; }
    renderNodeRow(n, depth) { return <div key={n.id} style={{ marginLeft: depth * 14 }}><div className={'tree-node-new ' + (this.state.activeNode === n.id ? 'selected' : '')} tabIndex="0" onMouseEnter={() => this.setState({ hover: n.id })} onFocus={() => this.setState({ hover: n.id })} onMouseLeave={() => this.setState({ hover: null })} onClick={() => this.setState({ hover: n.id })}><Icon name="book"/><span>{n.title}</span><Icon name="arrow"/>{this.state.hover === n.id && <div className="node-popover" onClick={e => e.stopPropagation()}><strong>{n.title}</strong><button onClick={() => this.learnNode(n)}><span>学习进度</span><b>{n.progress === 'LEARNED' ? '教学已完成' : n.progress === 'LEARNING' ? '学习中' : '未开始'}</b><Icon name="arrow"/></button><button onClick={() => this.assess(n)}><span>测评结果</span><b>{n.grade || '未测评'}</b><Icon name="arrow"/></button></div>}</div>{this.renderNodes(n.id, depth + 1)}</div>; }
    renderNodes(parent, depth) { return this.state.nodes.filter(n => n.parent === parent).map(n => this.renderNodeRow(n, depth)); }
    renderPane(lane) {
        const isTeach = lane === 'teach', messages = this.state.messages[lane];
        const title = isTeach ? '知识学习' : '题目应对';
        return <section className={'learning-pane pane-' + lane + ' ' + (this.state.mobile === lane ? 'mobile-active' : '')}>
            <header className="pane-header"><div className="row"><span className="pane-symbol"><Icon name={isTeach ? 'book' : 'edit'}/></span><div><h3>{title}</h3><small>{isTeach ? '理解原理，连接知识' : '拆解题目，逐步解决'}</small></div></div><div className="row" style={{ gap: 1 }}><IconButton name="history" title={isTeach ? '知识历史' : '题目历史'} onClick={() => this.history()}/><IconButton name="plus" title="新对话" onClick={() => this.newPair()}/></div></header>
            <div className="pane-messages" id={'messages-' + lane} onScroll={e => { const el = e.currentTarget; this.follow[lane] = el.scrollHeight - el.scrollTop - el.clientHeight < 100; }}>
                {messages.length === 0 && !this.state.partial[lane] ? <div className="pane-welcome"><div className="welcome-symbol"><Icon name={isTeach ? 'book' : 'edit'}/></div><h2>{isTeach ? '从一个问题，真正学会' : '把难题，拆成能理解的小步'}</h2><p>{isTeach ? '选一个知识点，或者直接问我。\n从为什么开始，把概念和例题连起来。' : '输入题目或指定文件、题号。\n完整参考解法之后，可在独立的详解窗口深入某一步。'}</p><div className="suggestion-stack">{(isTeach ? [(this.props.course.id === 'cs3481' ? '请用中文解释 DBSCAN 的核心点' : '请用中文介绍这门课的核心知识'), '我想先看看这门课的知识地图'] : [(this.props.course.id === 'cs3481' ? '讲解 Tutorial_02_Clustering.pdf 的 Question 2' : '请结合我上传的题目说明解题步骤'), '解题时怎样判断应该用哪种方法？']).map(text => <button key={text} onClick={() => this.ask(lane, text)}>{text}<Icon name="arrow"/></button>)}</div></div> : messages.map(m => {
                    const exercise = this.state.exercises[m.exercise] || m.exercise_state;
                    const visibleMessage = m.exercise && !exercise?.revealed ? {...m, steps: []} : m;
                    return <article className={'chat-message-new ' + m.role} key={m.id}><div className="message-byline">{m.role === 'user' ? this.props.user.name : 'CourseMate'}{m.role === 'assistant' && <span>{this.props.config.provider_mode === 'test' ? '本地测试 Provider' : this.props.config.model}</span>}</div>{m.attachments?.length > 0 && <div className="attachment-chips">{m.attachments.map(f => <span key={f.id}><Icon name="file"/>{f.name}</span>)}</div>}<RichText text={m.text} message={visibleMessage}/>{m.role === 'assistant' && m.exercise && this.renderExercise(m)}{m.citations?.length > 0 && <div className="citation-row">{m.citations.map(c => <button key={c.id} onClick={() => this.source(c)}><Icon name="file"/>{c.name} · p.{c.page}</button>)}</div>}</article>;
                })}{this.state.partial[lane] && <article className="chat-message-new assistant"><div className="message-byline">CourseMate <span>生成中 / 未完成内容</span></div><RichText text={this.state.partial[lane]}/></article>}
            </div>
            <footer className="pane-footer"><div className="generation-status" role="status">{this.state.status[lane] || ''}</div>{this.state.attachments[lane].length > 0 && <div className="attachment-chips">{this.state.attachments[lane].map(f => <span key={f.id}><Icon name="file"/>{f.name}<button title="移除本次附件" onClick={() => this.setLane('attachments', lane, this.state.attachments[lane].filter(x => x.id !== f.id))}>×</button></span>)}</div>}<form className="chat-composer" onSubmit={e => { e.preventDefault(); this.ask(lane); }}><textarea aria-label={isTeach ? '知识学习输入' : '题目应对输入'} placeholder={isTeach ? '问一个问题，或者告诉我你想学什么…' : '输入题目，或写下文件名与题号…'} value={this.state.inputs[lane]} maxLength="6000" onChange={e => this.setLane('inputs', lane, e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); this.ask(lane); } }}/><div className="composer-bottom"><div className="row"><label className="attach-button" role="button" tabIndex={this.state.busy[lane] || this.state.uploading[lane] ? -1 : 0} aria-label={isTeach ? '添加知识学习附件' : '添加题目附件'} title="添加题目图片或课程文件" onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.querySelector('input')?.click(); } }}><Icon name="file"/><input type="file" hidden aria-label={isTeach ? '知识学习附件' : '题目附件'} accept=".pdf,.txt,.md,.csv,.ipynb,.png,.jpg,.jpeg,.webp,.docx,.pptx" disabled={this.state.busy[lane] || this.state.uploading[lane]} onChange={e => this.attach(lane, e)}/></label>{this.state.uploading[lane] && <span className="helper-note">正在上传…</span>}<ReasoningStrengthPicker lane={lane} value={this.state.strength[lane]} disabled={this.state.busy[lane] || this.state.uploading[lane]} onChange={strength => this.setStrength(lane, strength)}/>{isTeach && <span className="thinking-control"><span className="thinking-label">Thinking</span><button type="button" className={'thinking-circle' + (this.state.thinking.teach ? ' on' : '')} aria-pressed={this.state.thinking.teach} aria-label="思考模式" onClick={() => this.setState(s => ({thinking: {...s.thinking, teach: !s.thinking.teach}}))}><span className="thinking-dot"/></button></span>}</div><div className="row" style={{gap: 8}}>{!isTeach && <button type="button" className="do-exercise-btn" onClick={() => this.doExercise()} disabled={this.state.busy.problem || this.state.uploading.problem}>做一题</button>}{this.state.busy[lane] ? <IconButton name="stop" title="停止生成" onClick={() => this.stop(lane)}/> : <button className="send-button" aria-label={isTeach ? '发送知识问题' : '发送题目'} disabled={!this.state.inputs[lane].trim() || this.state.uploading[lane]}><Icon name="send"/></button>}</div></div></form></footer>
        </section>;
    }
    render() { return <div className={'learn-new ' + (this.state.fullscreen ? 'focus-mode' : '')}><button className="knowledge-strip" onClick={() => this.setState({ expanded: !this.state.expanded })}><span className="row"><Icon name="tree"/><strong>课程知识点树</strong><small>{this.state.nodes.length} 个节点 · 点击展开</small></span><Icon name={this.state.expanded ? 'up' : 'down'}/></button><div className="workspace-new"><header className="workspace-toolbar"><IconButton name={this.state.fullscreen ? 'collapse' : 'expand'} title={this.state.fullscreen ? '退出全屏学习' : '全屏学习'} onClick={() => this.setState({ fullscreen: !this.state.fullscreen })}/><span className="muted small">{this.props.course.code} · 学习工作台</span><span className="model-label">{this.props.config.provider_mode === 'disabled' ? '模型未连接' : this.props.config.provider_mode === 'test' ? '测试 Provider · 非真实千问' : this.props.config.model}</span></header><div className="mobile-pane-tabs"><button className={this.state.mobile === 'teach' ? 'active' : ''} onClick={() => this.setState({ mobile: 'teach' })}>知识学习</button><button className={this.state.mobile === 'problem' ? 'active' : ''} onClick={() => this.setState({ mobile: 'problem' })}>题目应对</button></div>{this.state.error && <p className="error-text">{this.state.error}</p>}<div className={'workspace-columns '+(this.state.resizing?'is-resizing':'')} ref={el => this.workspace = el} style={{ gridTemplateColumns: `minmax(0,${this.state.ratio}fr) 9px minmax(0,${1 - this.state.ratio}fr)` }}>{this.renderPane('teach')}<div className="pane-divider" role="separator" aria-label="调整学习双栏比例" aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow={Math.round(this.state.ratio * 100)} tabIndex="0" onMouseDown={e => this.drag(e)} onTouchStart={e=>this.drag(e)} onKeyDown={e => { if (['ArrowLeft', 'ArrowRight'].includes(e.key)) {
        e.preventDefault();
        this.setState({ ratio: Math.max(.25, Math.min(.75, this.state.ratio + (e.key === 'ArrowLeft' ? -.025 : .025))) }, () => this.saveLayout());
    } }}><span /></div>{this.renderPane('problem')}</div></div>{this.state.expanded && this.renderTree()}{this.renderWindows()}</div>; }
}
class Assessment extends React.Component {
    state = { view: null, answers: {}, busy: false, error: '', finished: false };
    componentDidMount() { const s = this.props.result || {}; if (s.status === 'IN_PROGRESS' && s.session)
        this.open(s.session); }
    base = () => `/courses/${this.props.course.id}/knowledge`;
    async open(session) { this.setState({ busy: true, error: '' }); try {
        this.setState({ view: await request(this.base() + '/assessment/' + session) });
    }
    catch (e) {
        this.setState({ error: e.message });
    }
    finally {
        this.setState({ busy: false });
    } }
    async start() { this.setState({ busy: true, error: '' }); try {
        const started = await send(this.base() + '/' + this.props.node.id + '/assessment/session', { request_id: key() });
        this.setState({ view: await request(this.base() + '/assessment/' + started.id), finished: false });
    }
    catch (e) {
        this.setState({ error: e.message });
    }
    finally {
        this.setState({ busy: false });
    } }
    async submit() { const view = this.state.view; if (!view || view.status !== 'IN_PROGRESS')
        return; const answers = view.questions.map(q => ({ blueprint_item_id: q.id, answer: String(this.state.answers[q.id] ?? '').trim() })); if (answers.some(a => !a.answer))
        return this.setState({ error: '请回答全部题目后再提交。' }); this.setState({ busy: true, error: '' }); try {
        await send(this.base() + '/assessment/' + view.id + '/submit', { request_id: key(), answers });
        const graded = await request(this.base() + '/assessment/' + view.id);
        this.setState({ view: graded, finished: true });
        this.props.onDone?.();
    }
    catch (e) {
        this.setState({ error: e.message });
    }
    finally {
        this.setState({ busy: false });
    } }
    async abandon() { const view = this.state.view; if (!view)
        return; this.setState({ busy: true }); try {
        await send(this.base() + '/assessment/' + view.id + '/abandon', { request_id: key() });
        this.setState({ view: null, finished: true });
        this.props.onDone?.();
    }
    catch (e) {
        this.setState({ error: e.message });
    }
    finally {
        this.setState({ busy: false });
    } }
    renderSummary() { const view = this.state.view; const r = view ? { status: view.status, grade: view.grade?.label || null, score: view.raw_score, session: view.id, mode: view.mode, assistance: view.assistance_status, source: 'V3 assessment engine' } : (this.props.result || {}); const status = r.status || 'NOT_ASSESSED'; const scored = status === 'GRADED' || typeof r.score === 'number'; return <div><dl className="assessment-grid"><dt>状态</dt><dd>{status === 'GRADED' ? '已评阅' : status === 'IN_PROGRESS' ? '进行中' : status === 'SUBMITTED' ? '已提交' : status === 'NOT_ASSESSED' ? '未测评' : status}</dd><dt>成绩</dt><dd>{r.grade || '未出具'}</dd><dt>原始分</dt><dd>{typeof r.score === 'number' ? r.score : '—'}</dd>{r.session && <><dt>测评场次</dt><dd className="mono">{r.session}</dd></>}{r.mode && <><dt>模式</dt><dd>{r.mode === 'INDEPENDENT' ? '独立完成' : r.mode === 'PRACTICE' ? '练习' : r.mode}</dd></>}{r.assistance && <><dt>协助状态</dt><dd>{r.assistance === 'UNASSISTED' ? '无协助' : r.assistance === 'ASSISTED' ? '有提示' : r.assistance === 'ANSWER_EXPOSED' ? '已看过答案' : r.assistance}</dd></>}</dl>{r.source && <p className="helper-note" style={{ marginTop: 12 }}>来源：{r.source}</p>}{!scored && status !== 'IN_PROGRESS' && <p className="helper-note" style={{ marginTop: 12 }}>还没有真实测评成绩。学习进度和测评结果是两个独立状态，这里不显示虚构分数。</p>}</div>; }
    renderQuestion(q, i) { const value = this.state.answers[q.id] ?? ''; const locked = this.state.view?.status !== 'IN_PROGRESS'; return <article className="assessment-question" key={q.id}><header><strong>第 {i + 1} 题</strong><small>{q.question_type}{q.marks ? ' · ' + q.marks + ' 分' : ''}</small></header><p className="assessment-prompt">{q.prompt}</p>{q.options && q.options.length ? <div className="assessment-options">{q.options.map((option, j) => <label key={j} className={'assessment-option' + (value === String(option) ? ' selected' : '')}><input type="radio" name={q.id} disabled={locked} checked={value === String(option)} onChange={() => this.setState({ answers: { ...this.state.answers, [q.id]: option } })}/><span>{option}</span></label>)}</div> : <textarea aria-label={'第 ' + (i + 1) + ' 题答案'} disabled={locked} rows={3} maxLength="12000" placeholder="在这里作答…" value={value} onChange={e => this.setState({ answers: { ...this.state.answers, [q.id]: e.target.value } })}/>}{q.review && <div className="assessment-review"><p className="helper-note">你的答案：{q.review.submitted_answer ?? '（未作答）'}</p><p className="helper-note">参考答案：{JSON.stringify(q.review.answer)}</p><p className="helper-note">得分：{q.review.awarded_marks} / {q.marks}{q.review.feedback ? ' · ' + q.review.feedback : ''}</p></div>}</article>; }
    render() { const { view, busy, error, finished } = this.state; const active = view && view.status === 'IN_PROGRESS'; return <div className="assessment-flow">{this.state.error && <p className="error-text">{this.state.error}</p>}{this.renderSummary()}{!view && !finished && <div className="row" style={{ marginTop: 16 }}><button className="btn primary" disabled={busy} onClick={() => this.start()}>{busy ? '正在准备…' : '开始测评（5 题）'}</button>{this.props.result?.status === 'GRADED' && <p className="helper-note">已有评分记录；再次测评会开启新的场次。</p>}</div>}{active && <><div className="assessment-questions">{view.questions.map((q, i) => this.renderQuestion(q, i))}</div><div className="row" style={{ marginTop: 16 }}><button className="btn primary" disabled={busy} onClick={() => this.submit()}>{busy ? '正在提交…' : '提交答案'}</button><button className="btn" disabled={busy} onClick={() => this.abandon()}>放弃本次测评</button></div></>}{view && view.status === 'GRADED' && <><p className="helper-note" style={{ marginTop: 12 }}>评阅完成。查看每题反馈后关闭即可。</p><div className="assessment-questions">{view.questions.map((q, i) => this.renderQuestion(q, i))}</div><div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => this.setState({ view: null, finished: true })}>返回概览</button><button className="btn" onClick={() => this.start()}>再测一次</button></div></>}</div>; }
}
export class ExplanationWindow extends React.Component {
    state = { x: 0, y: 0, w: 520, h: 420, followUp: '' };
    componentDidMount() { const w = this.props.win || {}; this.setState({ x: w.x ?? 60, y: w.y ?? 60, w: w.w ?? 520, h: w.h ?? 420 }); }
    startDrag(e) { if (e.target.closest('button') || e.target.closest('input'))
        return; e.preventDefault(); const startX = e.touches?.[0]?.clientX ?? e.clientX, startY = e.touches?.[0]?.clientY ?? e.clientY; const { x, y } = this.state; const onMove = ev => { if (ev.cancelable)
        ev.preventDefault(); const cx = ev.touches?.[0]?.clientX ?? ev.clientX, cy = ev.touches?.[0]?.clientY ?? ev.clientY; this.setState({ x: x + (cx - startX), y: y + (cy - startY) }); }; const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); window.removeEventListener('touchmove', onMove); window.removeEventListener('touchend', onUp); window.removeEventListener('touchcancel', onUp); }; window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp); window.addEventListener('touchmove', onMove, { passive: false }); window.addEventListener('touchend', onUp); window.addEventListener('touchcancel', onUp); }
    startResize(e) { e.preventDefault(); e.stopPropagation(); const startX = e.touches?.[0]?.clientX ?? e.clientX, startY = e.touches?.[0]?.clientY ?? e.clientY; const { w, h } = this.state; const onMove = ev => { if (ev.cancelable)
        ev.preventDefault(); const cx = ev.touches?.[0]?.clientX ?? ev.clientX, cy = ev.touches?.[0]?.clientY ?? ev.clientY; this.setState({ w: Math.max(280, w + (cx - startX)), h: Math.max(220, h + (cy - startY)) }); }; const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); window.removeEventListener('touchmove', onMove); window.removeEventListener('touchend', onUp); window.removeEventListener('touchcancel', onUp); }; window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp); window.addEventListener('touchmove', onMove, { passive: false }); window.addEventListener('touchend', onUp); window.addEventListener('touchcancel', onUp); }
    keyboardAdjust(e, resize = false) {
        const delta = {ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]}[e.key];
        if (!delta) return;
        e.preventDefault(); e.stopPropagation(); this.props.onRaise();
        this.setState(s => resize ? {w:Math.max(280,s.w+delta[0]),h:Math.max(220,s.h+delta[1])} :
            {x:Math.max(0,Math.min(window.innerWidth-80,s.x+delta[0])),y:Math.max(0,Math.min(window.innerHeight-60,s.y+delta[1]))});
    }
    submit(e) { e.preventDefault(); this.props.onFollowUp(this.state.followUp); this.setState({ followUp: '' }); }
    render() { const { win, exp } = this.props; const { x, y, w, h, followUp } = this.state; const status = exp?.status; const generating = status === 'generating'; const messages = exp?.messages || []; const partial = exp?.partial || ''; return <div className="explain-window" style={{ left: x, top: y, width: w, height: h, zIndex: win.z }} role="dialog" aria-label={'详解 · 第 ' + win.ordinal + ' 步'} onMouseDown={() => this.props.onRaise()} onTouchStart={() => this.props.onRaise()}><div className="explain-head" role="button" tabIndex={0} aria-label="移动详解窗口（方向键）" onKeyDown={e => { if(e.target===e.currentTarget) this.keyboardAdjust(e); }} onMouseDown={e => this.startDrag(e)} onTouchStart={e => this.startDrag(e)}><strong>详解 · 第 {win.ordinal} 步</strong><button type="button" className="explain-close" aria-label="关闭详解" onClick={() => this.props.onClose()}>×</button></div><div className="explain-body">{messages.map(m => <div className={'explain-bubble ' + m.role} key={m.id || m.role + m.text.slice(0, 8)}><RichText text={m.text}/></div>)}{generating && <div className="explain-bubble assistant"><RichText text={partial || '正在思考中…'}/></div>}{status === 'completed' && messages.length === 0 && <div className="explain-bubble assistant"><RichText text={exp.text}/></div>}{status === 'error' && <div className="explain-status"><span className="error-text">{exp.error || '生成失败'}</span></div>}{status === 'cancelled' && <div className="explain-status">已停止，窗口可关闭。</div>}{!status && <div className="explain-status">正在加载…</div>}</div><form className="explain-foot" onSubmit={e => this.submit(e)}><input type="text" aria-label="追问" placeholder="追问这个步骤…" value={followUp} disabled={generating} onChange={e => this.setState({ followUp: e.target.value })}/>{generating ? <button type="button" className="btn" onClick={() => this.props.onCancel()}>停止</button> : <button type="submit" className="btn primary" disabled={!followUp.trim() || status === 'error'}>追问</button>}</form><div className="explain-resize" role="button" tabIndex={0} aria-label="调整窗口大小" onKeyDown={e => this.keyboardAdjust(e,true)} onMouseDown={e => this.startResize(e)} onTouchStart={e => this.startResize(e)}/></div>; }
}
class PairHistory extends React.Component {
    state = { rows: [], nodes: [], legacy: [], legacyOpen: null, error: '', menu: null, picker: null, conflict: null };
    componentDidMount() { this.load(); }
    async load() { try {
        // The V3 records deliberately remain in their original store. Pair
        // history and the old Q&A history are adjacent views, never copies.
        const [rows, nodes, legacy] = await Promise.all([
            listPairs(this.props.course),
            request(`/courses/${this.props.course}/knowledge`),
            request(`/courses/${this.props.course}/legacy-conversations`).catch(() => []),
        ]);
        this.setState({ rows, nodes, legacy, error: '' });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async openLegacy(id) { try {
        const legacyOpen = await request(`/courses/${this.props.course}/legacy-conversations/${id}`);
        this.setState({ legacyOpen, error: '' });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async rename(p) { const title = window.prompt('对话名称', p.title); if (!title || title === p.title)
        return; try {
        await renamePair(p.id, title);
        this.load();
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async remove(p) { if (!window.confirm('删除这段对话？'))
        return; try {
        await deletePair(p.id);
        this.props.onDeleted(p.id, p.teach_conversation, p.problem_conversation);
        this.load();
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async bindNode(nodeId) { const p = this.state.picker; if (!p)
        return; try {
        await bindPair(p.pairId, nodeId);
        this.setState({ picker: null, conflict: null });
        this.load();
    }
    catch (e) {
        if (e.code === 'NODE_ALREADY_BOUND')
            this.setState({ conflict: { node: nodeId, pair: e.detail?.pair || null } });
        else
            this.setState({ error: e.message });
    } }
    async unbind(p) { try {
        await bindPair(p.id, null);
        this.load();
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    renderPicker() { const p = this.state.picker; const term = (p.q || '').toLowerCase(); const filtered = term ? this.state.nodes.filter(n => (n.title || '').toLowerCase().includes(term)) : this.state.nodes; return <div className="node-picker"><div className="row between"><h3>{p.mode === 'rebind' ? '更换绑定知识点' : '绑定知识点'}</h3><IconButton name="close" title="返回" onClick={() => this.setState({ picker: null, conflict: null })}/></div>{this.state.conflict && <div className="error-text" style={{ padding: '8px 0' }}>该知识点已绑定到另一会话「{this.state.conflict.pair?.title || '未知会话'}」<button className="link" style={{ marginLeft: 8 }} onClick={() => { const id = this.state.conflict.pair?.id; if (id) {
        this.props.onSelect(id);
    } }}>打开</button></div>}<input className="node-picker-search" autoFocus aria-label="搜索知识点" placeholder="搜索知识点…" value={p.q || ''} onChange={e => this.setState(s => ({ picker: { ...s.picker, q: e.target.value } }))}/><div className="node-picker-list">{filtered.map(n => <button type="button" key={n.id} className="node-picker-row" onClick={() => this.bindNode(n.id)}><Icon name="book"/><span>{n.title}</span></button>)}{!filtered.length && <p className="helper-note" style={{ padding: 12 }}>没有匹配的知识点</p>}</div></div>; }
    renderLegacy() { const { legacy, legacyOpen } = this.state; if (!legacy.length && !legacyOpen)
        return null; return <section className="legacy-history"><div className="divider"/><h3>旧版问答记录</h3><p className="helper-note" style={{ marginTop: 6 }}>这些是原问答页面的历史对话，保存在原记录里，只读，不会被复制到本页历史。</p>{legacy.map(c => <div key={c.id} className="history-line"><button className="history-item" onClick={() => this.openLegacy(c.id)}><Icon name="history"/><span className="pair-title-time"><strong>{c.title}</strong><small>{formatTime(c.updated_at)} · {c.message_count} 条</small></span></button></div>)}{legacyOpen && <div className="legacy-reader"><div className="row between"><strong>{legacyOpen.title}</strong><IconButton name="close" title="关闭旧版对话" onClick={() => this.setState({ legacyOpen: null })}/></div><div className="legacy-messages">{legacyOpen.messages.map((m, i) => <article key={i} className={m.role === 'user' ? 'legacy-message mine' : 'legacy-message'}><small>{m.role === 'user' ? '你' : 'CourseMate'}</small><RichText text={m.text}/>{m.citations?.length > 0 && <ul className="legacy-citations">{m.citations.map((c, j) => <li key={j}>{c.filename || c.document_id || '课程资料'}</li>)}</ul>}</article>)}</div></div>}</section>; }
    render() { const { rows, error, menu, picker } = this.state; if (picker)
        return this.renderPicker(); return <div className="pair-history">{error && <p className="error-text">{error}</p>}{rows.map(p => <div key={p.id} className="history-line"><button className="history-item" onClick={() => this.props.onSelect(p.id)}><Icon name="history"/><span className="pair-title-time"><strong>{p.title}</strong><small>{formatTime(p.updated_at)}</small></span>{p.bound_node && <span className="pair-bound-tag">已绑定知识点</span>}</button><IconButton name="trash" title={'删除对话 ' + p.title} onClick={() => this.remove(p)}/><div style={{ position: 'relative' }}><IconButton name="more" title={'对话操作 ' + p.title} onClick={() => this.setState({ menu: menu === p.id ? null : p.id })}/>{menu === p.id && <div className="dropdown"><button onClick={() => this.rename(p)}>重命名</button><button onClick={() => this.setState({ picker: { pairId: p.id, mode: 'bind', q: '' }, menu: null, conflict: null })}>绑定知识点</button>{p.bound_node && <button onClick={() => this.setState({ picker: { pairId: p.id, mode: 'rebind', q: '' }, menu: null, conflict: null })}>更换绑定</button>}{p.bound_node && <button onClick={() => this.unbind(p)}>解除绑定</button>}</div>}</div></div>)}{!rows.length && <p className="helper-note">还没有历史对话。发送第一个问题后，会保存在这里。</p>}{this.renderLegacy()}</div>; }
}
