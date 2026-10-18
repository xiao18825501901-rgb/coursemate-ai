import { BRAND } from "../brand";
import { RichText } from './richtext.jsx';
import { DirectoryPicker } from './DirectoryPicker.jsx';
import React from 'react';
import { UiLocaleContext, defaultUiTranslate } from './UiLocale';
import { request, send, remove, download, key, streamEvents, listPairs, getPair, createPair, renamePair, deletePair, bindPair, createExercise, getExercise, revealExercise, requestExerciseHint, submitPracticeAttempt, scheduleLearningFollowup, configureLearningDiagnostic, skipLearningDiagnostic, markLearningDiagnosticUnsure, createExplanation, getExplanation, postExplanationMessage, cancelExplanation, searchPeople, listShares, getShare, createShare, joinShare, getAssessment, getAssessmentSetup, getAssessmentPreparation, startAssessment, getAssessmentSession, submitAssessment, abandonAssessment, saveAssessmentDraft, loadAssessmentDraft, cancelPreparation, resumePreparation, createAssessmentExplanation, submitFeedback, getVisualAssistance, setVisualAssistance } from './api.js';
import { dateKey, zonedParts, wallTimeToISO, formatBytes, formatTime, goto } from './utils.js';
import { citationVerdict } from './citationSupport.js';
import { referenceVerificationNote } from './referenceVerification.js';
import { Icon, IconButton, Avatar } from './icons.jsx';
import { FileUploadQueue, runUploadBatch, uploadItemsFrom } from './FileUploadQueue.jsx';
import { VisualControls } from './VisualControls.jsx';
import { VisualAssistanceConsent, VisualAssistanceToggle } from './VisualAssistanceToggle.jsx';
export class CourseFiles extends React.Component {
    static contextType = UiLocaleContext;
    state = { files: [], q: '', folder: '', error: '', loading: true, menu: null, uploadQueue: [], uploading: false };
    componentDidMount() { this.load(); }
    async load() { try {
        const files = await request(`/courses/${this.props.course.id}/files`);
        this.setState({ files, loading: false, error: '' });
    }
    catch (e) {
        this.setState({ error: e.message, loading: false });
    } }
    updateUpload = (clientItemId, patch) => this.setState(state => ({
        uploadQueue: state.uploadQueue.map(item => item.clientItemId === clientItemId ? { ...item, ...patch } : item),
    }));
    async selectUploads(e) {
        const input = e.currentTarget;
        const added = uploadItemsFrom(input.files);
        input.value = '';
        if (!added.length) return;
        this.setState(state => ({ uploadQueue: [...state.uploadQueue, ...added] }), () => this.runUploads(added));
    }
    async runUploads(items) {
        if (!items.length || this.state.uploading) return;
        this.setState({ uploading: true, error: '' });
        try {
            const outcome = await runUploadBatch(this.props.course.id, items, async (item, batchId) => {
                const body = new FormData();
                body.append('file', item.file);
                body.append('folder', this.state.folder);
                body.append('batch_id', batchId);
                body.append('batch_item_id', item.clientItemId.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 100));
                return request(`/courses/${this.props.course.id}/files`, { method: 'POST', body });
            }, this.updateUpload, 2);
            await this.load();
            this.props.toast(this.context.t(outcome.failed ? 'courses.uploadBatchFailed' : 'courses.uploadBatchComplete'));
        }
        catch (error) {
            this.setState({ error: error instanceof Error ? error.message : String(error) });
        }
        finally {
            this.setState({ uploading: false });
        }
    }
    retryUpload(clientItemId) {
        const item = this.state.uploadQueue.find(row => row.clientItemId === clientItemId && row.status === 'failed');
        if (item) this.runUploads([item]);
    }
    retryFailed() {
        this.runUploads(this.state.uploadQueue.filter(item => item.status === 'failed'));
    }
    removeUpload(clientItemId) {
        this.setState(state => ({ uploadQueue: state.uploadQueue.filter(item => item.clientItemId !== clientItemId) }));
    }
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
        const { files, q, folder, menu, uploadQueue, uploading } = this.state;
        const { t } = this.context;
        const prefix = folder ? folder + '/' : '';
        const folders = q ? [] : [...new Set(files.map(f => f.folder).filter(f => f.startsWith(prefix) && f !== folder).map(f => f.slice(prefix.length).split('/')[0]))];
        const rows = files.filter(f => q ? f.name.toLowerCase().includes(q.toLowerCase()) : f.folder === folder);
        return <div className="course-scroll"><div className="section-heading"><h1>{t('courses.files')}</h1><label className="btn" role="button" tabIndex={uploading ? -1 : 0} aria-label={t('courses.addMaterials')} onKeyDown={e=>{if(!uploading&&(e.key==="Enter"||e.key===" ")){e.preventDefault();e.currentTarget.querySelector("input")?.click();}}}><Icon name="plus"/>{uploading ? t('courses.uploading') : t('courses.addMaterials')}<input type="file" multiple disabled={uploading} style={{ display: 'none' }} onChange={e => this.selectUploads(e)} accept=".pdf,.txt,.md,.csv,.ipynb,.docx,.pptx,.png,.jpg,.jpeg,.webp"/></label></div><FileUploadQueue items={uploadQueue} busy={uploading} onRetry={id => this.retryUpload(id)} onRemove={id => this.removeUpload(id)}/>{uploadQueue.some(item => item.status === 'failed') && <button type="button" className="btn small upload-retry-all" disabled={uploading} onClick={() => this.retryFailed()}>{t('courses.retryFailed')}</button>}<form className="file-search" onSubmit={e => e.preventDefault()}><div className="search-field"><Icon name="search"/><input aria-label={t('courses.searchFiles')} placeholder={t('courses.searchFiles')} value={q} onChange={e => this.setState({ q: e.target.value })}/></div><button className="btn">{t('common.search')}</button></form><div className="file-path"><button onClick={() => this.setState({ folder: '', q: '' })}>{this.props.course.code} {this.props.course.name}</button>{folder && <><Icon name="arrow"/><span>{folder}</span></>}</div>{this.state.error && <p className="error-text">{this.state.error}</p>}<table className="file-table"><thead><tr><th>{t('courses.fileName')}</th><th>{t('courses.fileSize')}</th><th>{t('courses.fileActions')}</th></tr></thead><tbody>{folders.map(f => <tr key={f}><td><button className="file-name-btn" onClick={() => this.setState({ folder: prefix + f })}><Icon name="folder"/><span>{f}</span></button></td><td className="file-size">—</td><td /></tr>)}{rows.map(f => <tr key={f.id}><td><button className={'file-name-btn ' + (f.mime === 'application/pdf' ? 'pdf' : '')} onClick={() => this.preview(f)}><Icon name="file"/><span>{f.name}{f.scope === 'private' && <small className="private-note">{t('courses.onlyMe')}</small>}</span></button>{f.error && <p className="helper-note file-note">{f.error}</p>}</td><td className="file-size">{formatBytes(f.size)}</td><td className="file-action"><IconButton name="more" title={t('courses.fileActionsLabel', {name:f.name})} onClick={() => this.setState({ menu: menu === f.id ? null : f.id })}/>{menu === f.id && <div className="dropdown"><button onClick={() => this.save(f)}><Icon name="download"/>{t('common.download')}</button>{f.scope === 'private' && <button onClick={async () => { if (!window.confirm(t('courses.deleteFileConfirm')))
            return; try {
            await remove(`/courses/${this.props.course.id}/files/${f.id}`);
            await this.load();
        }
        catch (e) {
            this.props.toast(e.message);
        } }}><Icon name="trash"/>{t('courses.deleteMyFile')}</button>}</div>}</td></tr>)}</tbody></table>{!rows.length && !folders.length && <div className="empty-state"><Icon name="folder"/><h3>{this.state.loading ? t('common.loading') : q ? t('courses.noMatchingFiles') : t('courses.emptyFiles')}</h3><p>{t('courses.filesEmptyHint')}</p></div>}<p className="file-foot">{t('courses.filesHelp')}</p></div>;
    }
}
class Preview extends React.Component {
    static contextType = UiLocaleContext;
    state = { url: '', text: '', error: '', zoom: 100, previewReady: false };
    componentDidMount() {
        this.unmounted = false;
        this.previewEpoch = (this.previewEpoch || 0) + 1;
        this.load(this.previewEpoch);
    }
    componentWillUnmount() { if (this.state.url)
        URL.revokeObjectURL(this.state.url); this.unmounted = true; }
    async load(epoch) {
        try {
            const f = this.props.file;
            if (['application/pdf', 'image/png', 'image/jpeg', 'image/webp'].includes(f.mime)) {
                const url = await download(this.props.course.id, f, true);
                if (this.unmounted || epoch !== this.previewEpoch) {
                    URL.revokeObjectURL(url);
                    return;
                }
                this.setState({ url });
            }
            else {
                const p = await request(`/courses/${this.props.course.id}/files/${f.id}/text`);
                if (!this.unmounted && epoch === this.previewEpoch)
                    this.setState({ text: p.pages.map(x => x.text).join('\n\n'), previewReady: true });
            }
        }
        catch (e) {
            if (!this.unmounted && epoch === this.previewEpoch)
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
    render() { const f = this.props.file; const { t } = this.context; return <div className="real-preview"><div className="row between"><span className="muted">{formatBytes(f.size)} · {t('courses.previewHeading')}</span><button className="btn small" onClick={() => this.save()}><Icon name="download"/>{t('common.download')}</button></div>{this.state.error ? <div className="error-text">{this.state.error}</div> : this.state.url ? f.mime === 'application/pdf' ? <iframe title={f.name} src={this.state.url + '#toolbar=1'} className="pdf-frame"/> : <div className="image-preview"><img alt={f.name} src={this.state.url}/></div> : this.state.text ? <pre className="text-preview">{this.state.text}</pre> : <div className="empty-state">{t(this.state.previewReady ? 'courses.previewUnsupported' : 'courses.previewLoading')}</div>}</div>; }
}
export class Discussion extends React.Component {
    static contextType = UiLocaleContext;
    state = { rows: [], text: '', replyTo: null, reply: '', busy: false, error: '' };
    componentDidMount() { this.unmounted = false; this.mountEpoch = (this.mountEpoch || 0) + 1; this.load(); this.timer = setInterval(() => { if (!document.hidden)
        this.load(); }, 15000); }
    componentWillUnmount() { clearInterval(this.timer); this.unmounted = true; }
    async load() { const epoch = this.mountEpoch; try {
        const rows = await request(`/courses/${this.props.course.id}/comments`);
        if (!this.unmounted && epoch === this.mountEpoch)
            this.setState({ rows, error: '' });
    }
    catch (e) {
        if (!this.unmounted && epoch === this.mountEpoch)
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
    render() { const { rows } = this.state; const { t } = this.context; return <div className="course-scroll course-discussion"><div className="section-heading"><div><h1>{t('discussion.title')}</h1><p className="helper-note" style={{ marginTop: 7 }}>{t('discussion.subtitle')}</p></div><span className="chip neutral">{t(this.props.course.visibility === 'private' ? 'discussion.privateScope' : 'discussion.publicScope')}</span></div><form className="discussion-compose" onSubmit={e => { e.preventDefault(); this.post(); }}><div className="compose-main"><Avatar name={this.props.user.name}/><div><textarea aria-label={t('discussion.commentLabel')} placeholder={t('discussion.commentPlaceholder')} maxLength="6000" value={this.state.text} onChange={e => this.setState({ text: e.target.value })}/><div className="row between"><small className="muted">{t('discussion.visibilityNotice')}</small><button className="btn primary small" disabled={this.state.busy || !this.state.text.trim()}>{t('discussion.post')}</button></div></div></div></form>{this.state.error && <p className="error-text">{this.state.error}</p>}<div className="discussion-feed">{rows.filter(x => !x.parent).map(row => <article className="discussion" key={row.id} id={'comment-' + row.id}><Avatar name={row.name}/><div className="discussion-content"><div className="discussion-title"><strong>{row.name}</strong><time>{formatTime(row.created_at)}</time></div><p className="discussion-text">{row.text}</p><div className="discussion-actions"><button onClick={() => this.setState({ replyTo: row.id, reply: '' })}><Icon name="comment"/>{t('discussion.reply')}</button><button onClick={() => this.like(row)}><Icon name="heart"/>{row.likes || t('discussion.like')}</button>{row.author === this.props.user.id && !row.deleted && <button onClick={async () => { if (window.confirm(t('discussion.deleteConfirm'))) {
        await remove(`/courses/${this.props.course.id}/comments/${row.id}`);
        this.load();
    } }}>{t('discussion.delete')}</button>}</div>{rows.filter(x => x.parent === row.id).map(reply => <div className="reply" key={reply.id}><Avatar name={reply.name}/><div><div className="discussion-title"><strong>{reply.name}</strong><time>{formatTime(reply.created_at)}</time></div><p className="discussion-text">{reply.text}</p><button className="link small" onClick={() => this.setState({ replyTo: reply.id, reply: '' })}>{t('discussion.reply')}</button></div></div>)}{(this.state.replyTo === row.id || rows.some(x => x.id === this.state.replyTo && x.parent === row.id)) && <form className="reply-box" onSubmit={e => { e.preventDefault(); this.post(this.state.replyTo); }}><input autoFocus aria-label={t('discussion.replyLabel')} placeholder={t('discussion.replyPlaceholder')} value={this.state.reply} maxLength="6000" onChange={e => this.setState({ reply: e.target.value })}/><button className="btn small primary" disabled={this.state.busy}>{t('discussion.sendReply')}</button></form>}</div></article>)}{!rows.length && <div className="empty-state"><Icon name="comment"/><h3>{t('discussion.emptyTitle')}</h3><p>{t('discussion.emptyNotice')}</p></div>}</div></div>; }
}
export class Inbox extends React.Component {
    static contextType = UiLocaleContext;
    translate(name, params = {}) { return (this.context?.t || defaultUiTranslate)('inbox.' + name, params); }
    state = { notifications: [], threads: [], shares: { received: [], sent: [] }, sharesQ: 'received', tab: 'all', selected: null, messages: [], reply: '', error: '', inboxPage:0 };
    componentDidMount() { this.unmounted = false; this.load(); this.timer = setInterval(() => { if (!document.hidden)
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
    compose = () => this.props.modal(this.translate('compose'), <ComposeMessage onSubmit={async (payload) => { const m = await send('/messages', payload); this.props.closeModal(); await this.load(); const t = this.state.threads.find(t => t.id === m.thread); if (t)
        this.select({ ...t, kind: 'thread' }); this.props.toast(this.translate('messageSent')); }}/>);
    shareCourse = () => this.props.modal(this.translate('shareCourse'), <ShareCourseModal toast={this.props.toast} closeModal={this.props.closeModal} onDone={() => this.load()}/>);
    campusVerificationLabel = (requires) => requires && this.props.config?.student_verification_required_for_campus ? ` · ${this.translate('studentVerificationRequired')}` : '';
    async viewShare(share) { try {
        const d = await getShare(share.id);
        const files = d.files || [];
        this.props.modal(this.translate('sharedContentTitle', { course: d.course_name }), <div className="share-review"><p><strong>{d.sender_name}</strong> · {formatTime(d.snapshot_at)}</p><p className="muted">{this.translate('filesCount', { count: files.length })} · {this.translate(d.history_scope === 'none' ? 'noHistoryShort' : 'historyIncluded')}{d.pair_count ? ' · ' + this.translate('conversationsCount', { count: d.pair_count }) : ''}{this.campusVerificationLabel(d.requires_student_verification)}</p><div className="divider"/>{files.map(f => <div key={f.id || f.name} className="share-pair-row"><Icon name="file"/><span>{f.name}</span></div>)}{!files.length && <p className="helper-note">{this.translate('noFiles')}</p>}</div>);
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async joinShare(share) { try {
        await joinShare(share.id);
        await this.props.onJoined?.();
        this.props.toast(this.translate('joinedToast'));
        await this.load();
        this.props.onRead?.();
    }
    catch (e) {
        if (e.status === 403 && this.props.config?.student_verification_required_for_campus)
            this.props.toast(this.translate('verificationRequiredToast'));
        else
            this.props.toast(e.message);
    } }
    renderShares() { const { shares, sharesQ } = this.state; const rows = shares[sharesQ] || []; return <div className="inbox-share-list"><div className="mail-tabs"><button className={sharesQ === 'received' ? 'active' : ''} onClick={() => this.setState({ sharesQ: 'received' })}>{this.translate('received')}</button><button className={sharesQ === 'sent' ? 'active' : ''} onClick={() => this.setState({ sharesQ: 'sent' })}>{this.translate('sent')}</button></div>{rows.map(sh => <div key={sh.id} className="inbox-share-item"><div className="inbox-share-head"><strong>{sh.course_name}</strong><span>{formatTime(sh.snapshot_at)}</span></div><div className="share-meta">{sharesQ === 'received' && sh.sender_name ? sh.sender_name + ' · ' : ''}{this.translate('filesCount', { count: sh.file_count })} · {this.translate(sh.history_scope === 'none' ? 'noHistoryShort' : 'historyIncluded')}{this.campusVerificationLabel(sh.requires_student_verification)}</div><div className="share-actions"><button className="btn" onClick={() => this.viewShare(sh)}>{this.translate('viewShared')}</button>{sharesQ === 'received' && (sh.joined_course_id ? <span className="helper-note">{this.translate('joined')}</span> : <button className="btn primary" onClick={() => this.joinShare(sh)}>{this.translate('addSharedCourse')}</button>)}</div></div>)}{!rows.length && <div className="empty-state">{this.translate('emptyShares')}</div>}</div>; }
    async reply(e) { e.preventDefault(); const s = this.state.selected; try {
        await send('/messages', { recipient: s.peer.id, text: this.state.reply, request_id: key() });
        this.setState({ reply: '' });
        await this.load();
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    render() { const { notifications, threads, selected: s, tab, messages } = this.state; const all = [...notifications.map(n => ({ ...n, kind: 'notice', title: this.translate('noticeReplyTitle'), name: n.actor_name, preview: n.text, time: n.created_at, unread: !n.read_at })), ...threads.map(t => ({ ...t, kind: 'thread', title: t.peer.name, name: t.peer.name, preview: t.last?.text || '', time: t.last?.created_at || t.created_at }))].filter(x => tab === 'all' || (tab === 'reply' ? x.kind === 'notice' : x.kind === 'thread')).sort((a, b) => b.time.localeCompare(a.time)); return <div className="page"><header className="page-heading row between"><div><h1>{this.translate('title')}</h1><p>{this.translate('subtitle')}</p></div><div className="row" style={{ gap: 8 }}><button className="btn" onClick={this.shareCourse}><Icon name="shareCourse"/>{this.translate('shareCourse')}</button><button className="btn primary" onClick={this.compose}><Icon name="edit"/>{this.translate('compose')}</button></div></header><nav aria-label={this.translate('pagination')} className="row"><button className="btn small" disabled={this.state.inboxPage===0} onClick={()=>this.setState(s=>({inboxPage:s.inboxPage-1}),()=>this.load())}>{this.translate('previousPage')}</button><span>{this.translate('page', { page: this.state.inboxPage + 1 })}</span><button className="btn small" onClick={()=>this.setState(s=>({inboxPage:s.inboxPage+1}),()=>this.load())}>{this.translate('nextPage')}</button></nav>{this.state.error && <p className="error-text">{this.state.error}</p>}<div className="inbox-layout"><div className="mail-list"><div className="mail-tabs">{[['all', 'tabAll'], ['reply', 'tabReplies'], ['dm', 'tabDirect'], ['shares', 'tabShared']].map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => this.setState({ tab: id })}>{this.translate(label)}</button>)}</div>{tab === 'shares' ? this.renderShares() : <>{all.map(x => <button className={'mail-item ' + (s?.id === x.id ? 'selected' : '')} key={x.id} onClick={() => this.select(x)}><Avatar name={x.name}/><div className="mail-info"><div className="from">{x.name}<span>{formatTime(x.time)}</span></div><strong>{x.title}</strong><p>{x.preview}</p></div>{x.unread > 0 && <i className="unread-dot"/>}</button>)}{!all.length && <div className="empty-state">{this.translate('empty')}</div>}</>}</div><div className="mail-detail">{!s ? <div className="empty-state"><Icon name="mail"/><h3>{this.translate('emptySelectTitle')}</h3><p>{this.translate('emptySelectBody')}</p></div> : s.kind === 'notice' ? <><div className="mail-detail-head"><h2>{this.translate('repliedToYou', { name: s.actor_name })}</h2><Icon name="comment"/></div><p className="helper-note">{formatTime(s.created_at)}</p><div className="mail-message">{s.text}</div><button className="btn primary" onClick={() => goto(`course/${s.course}/comments`)}>{this.translate('viewDiscussion')} <Icon name="arrow"/></button></> : <><div className="mail-detail-head"><div><h2>{s.peer.name}</h2><span className="helper-note">@{s.peer.handle}</span></div><IconButton name="more" title={this.translate('blockContact')} onClick={async () => { if (window.confirm(this.translate('blockConfirm'))) {
        await send(`/people/${s.peer.id}/block`, {}, 'PUT');
        this.props.toast(this.translate('blocked'));
    } }}/></div><div className="direct-message-log">{messages.map(m => <div className={'dm-bubble ' + (m.sender === this.props.user.id ? 'mine' : '')} key={m.id}><div className="helper-note">{m.name} · {formatTime(m.created_at)}</div><p>{m.text}</p></div>)}</div><form onSubmit={e => this.reply(e)}><textarea aria-label={this.translate('replyLabel')} placeholder={this.translate('replyPlaceholder')} value={this.state.reply} maxLength="6000" onChange={e => this.setState({ reply: e.target.value })}/><button className="btn primary" disabled={!this.state.reply.trim()}>{this.translate('sendReply')}</button></form></>}</div></div></div>; }
}
class ComposeMessage extends React.Component {
    static contextType = UiLocaleContext;
    translate(name, params = {}) { return (this.context?.t || defaultUiTranslate)('inbox.' + name, params); }
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
    render() { return <form onSubmit={e => this.submit(e)}><div className="field"><label>{this.translate('recipient')}</label><DirectoryPicker selected={this.state.person?[this.state.person.id]:[]} onSelect={person=>this.setState({person})}/>{this.state.person && <p className="helper-note">{this.translate('selectedRecipient', { name: this.state.person.name })}</p>}</div><div className="field"><label>{this.translate('message')}</label><textarea required maxLength="6000" style={{ minHeight: 130 }} value={this.state.text} onChange={e => this.setState({ text: e.target.value })}/></div><p className="helper-note">{this.translate('privacyNotice')}</p>{this.state.error && <p className="error-text">{this.state.error}</p>}<button className="btn primary" style={{ marginTop: 20 }} disabled={!this.state.person || this.state.busy}>{this.translate('sendMessage')}</button></form>; }
}
class ShareCourseModal extends React.Component {
    static contextType = UiLocaleContext;
    translate(name, params = {}) { return (this.context?.t || defaultUiTranslate)('inbox.' + name, params); }
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
        this.props.toast(this.translate('shareSent') + (result.reused ? this.translate('reusedRequestSuffix') : ''));
        this.props.onDone?.();
    }
    catch (e) {
        this.setState({ error: e.message, busy: false });
    } }
    scopeLabel() { return this.translate(this.state.scope === 'all' ? 'allHistory' : this.state.scope === 'none' ? 'noHistory' : 'selectedHistory'); }
    render() { const { step, courses, course, recipients, scope, pairs, selectedPairs, fileCount, busy, error } = this.state; return <div className="share-wizard">{error && <p className="error-text">{error}</p>}{step === 1 && <div className="share-step"><h4>{this.translate('shareStepCourse')}</h4><div className="node-picker-list">{courses.map(c => <button type="button" key={c.id} className="node-picker-row" onClick={() => this.pickCourse(c)}><Icon name="book"/><span>{c.name}</span><small className="muted">{c.code}</small></button>)}{!courses.length && <p className="helper-note" style={{ padding: 12 }}>{this.translate('noShareableCourses')}</p>}</div></div>}{step === 2 && <div className="share-step"><h4>{this.translate('shareStepRecipients')}</h4><DirectoryPicker selected={recipients.map(r=>r.id)} onSelect={p=>this.toggleRecipient(p)}/><div className="recipient-chips">{recipients.map(r => <span className="recipient-chip" key={r.id}>{r.name}<button type="button" aria-label={this.translate('removeRecipient', { name: r.name })} onClick={() => this.toggleRecipient(r)}>×</button></span>)}</div><div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => this.setState({ step: 1 })}>{this.translate('previousStep')}</button><button className="btn primary" disabled={!recipients.length} onClick={() => this.setState({ step: 3 })}>{this.translate('nextStep')}</button></div></div>}{step === 3 && <div className="share-step"><h4>{this.translate('shareStepHistory')}</h4><div className="share-radio"><label><input type="radio" name="scope" checked={scope === 'all'} onChange={() => this.pickScope('all')}/>{this.translate('allHistory')}</label><label><input type="radio" name="scope" checked={scope === 'none'} onChange={() => this.pickScope('none')}/>{this.translate('noHistory')}</label><label><input type="radio" name="scope" checked={scope === 'selected'} onChange={() => this.pickScope('selected')}/>{this.translate('selectedHistory')}</label></div>{scope === 'selected' && <div className="share-pair-list">{pairs.map(p => <label key={p.id} className="share-pair-row"><input type="checkbox" checked={selectedPairs.includes(p.id)} onChange={() => this.togglePair(p.id)}/><span>{p.title}</span><small className="muted">{formatTime(p.updated_at)}</small></label>)}{!pairs.length && <p className="helper-note" style={{ padding: 12 }}>{this.translate('noConversations')}</p>}</div>}<div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => this.setState({ step: 2 })}>{this.translate('previousStep')}</button><button className="btn primary" disabled={scope === 'selected' && !selectedPairs.length} onClick={() => this.review()}>{this.translate('nextStep')}</button></div></div>}{step === 4 && <div className="share-step"><h4>{this.translate('shareStepConfirm')}</h4><div className="share-review"><p>{this.translate('courseReview', { course: course?.name || '' })}</p><p>{this.translate('recipientsReview', { recipients: recipients.map(r => r.name).join(this.translate('nameSeparator')) })}</p><p>{this.translate('filesReview', { count: fileCount })}</p><p>{this.translate('historyReview', { scope: this.scopeLabel() })}{scope === 'selected' ? this.translate('selectedConversationSuffix', { count: selectedPairs.length }) : ''}</p></div><div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => this.setState({ step: 3 })}>{this.translate('previousStep')}</button><button className="btn primary" disabled={busy} onClick={() => this.send()}>{this.translate(busy ? 'sending' : 'confirmSend')}</button></div></div>}</div>; }
}
export class Calendar extends React.Component {
    static contextType = UiLocaleContext;
    t = (name, params) => this.context.t('calendar.' + name, params);
    state = { month: new Date(new Date().getFullYear(), new Date().getMonth(), 1), tasks: [], plan: '', answer: '', answerFallback: false, busy: false, error: '' };
    componentDidMount() { this.load(); }
    async load() { try {
        this.setState({ tasks: await request('/tasks'), error: '' });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    task = (date, id = null) => { const task = this.state.tasks.find(x => x.id === id); this.props.modal({ titleKey: task ? 'calendar.editTask' : 'calendar.createTask' }, <TaskForm task={task} date={date} courses={this.props.courses} user={this.props.user} onSubmit={async (value) => { if (task)
        await send('/tasks/' + task.id, { title: value.title, due_at: value.due_at, version: task.version }, 'PATCH');
    else
        await send('/tasks', value); this.props.closeModal(); await this.load(); this.props.toast(this.t('saved')); }}/>); };
    async done(t) { try {
        await send('/tasks/' + t.id, { version: t.version, status: t.status === 'done' ? 'todo' : 'done' }, 'PATCH');
        await this.load();
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async plan(e) { e.preventDefault(); this.setState({ busy: true, answer: '', answerFallback: false }); try {
        const result = await send('/tasks/plan', { text: this.state.plan, request_id: key() });
        const answer = result.text || result.answer || result.message || '';
        this.setState({ answer, answerFallback: !answer, plan: '' });
        await this.load();
    }
    catch (e) {
        this.setState({ answer: e.message, answerFallback: false });
    }
    finally {
        this.setState({ busy: false });
    } }
    render() {
        const { month, tasks } = this.state;
        const start = new Date(month);
        start.setDate(1 - ((start.getDay() + 6) % 7));
        const days = Array.from({ length: 42 }, (_, i) => {
            const d = new Date(start); d.setDate(start.getDate() + i); return d;
        });
        const zone = this.props.user.timezone;
        const today = zonedParts(new Date(), zone).date;
        const monthLabel = new Intl.DateTimeFormat(this.context.locale, { year: 'numeric', month: 'long' }).format(month);
        return <div className="page course-calendar">
            <header className="page-heading"><h1>{this.t('title')}</h1><p>{this.t('intro')} <span className="small">{zone}</span></p></header>
            {this.state.error && <p className="error-text">{this.state.error}</p>}
            <section className="calendar">
                <div className="calendar-toolbar"><h2>{monthLabel}</h2><div className="row">
                    <button className="btn small" onClick={() => this.setState({ month: new Date(new Date().getFullYear(), new Date().getMonth(), 1) })}>{this.t('today')}</button>
                    <IconButton name="back" title={this.t('previousMonth')} onClick={() => this.setState({ month: new Date(month.getFullYear(), month.getMonth() - 1, 1) })}/>
                    <IconButton name="arrow" title={this.t('nextMonth')} onClick={() => this.setState({ month: new Date(month.getFullYear(), month.getMonth() + 1, 1) })}/>
                </div></div>
                <div className="calendar-week">{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(day => <div key={day}>{this.t('weekday' + day)}</div>)}</div>
                <div className="calendar-grid">{days.map(d => <div key={dateKey(d)}
                    className={'calendar-cell ' + (d.getMonth() !== month.getMonth() ? 'out' : '')}
                    onClick={() => this.task(dateKey(d))} role="button" tabIndex="0"
                    onKeyDown={e => { if (e.target === e.currentTarget && ['Enter', ' '].includes(e.key)) {
                        e.preventDefault(); this.task(dateKey(d));
                    } }} aria-label={this.t('addOnDate', { date: dateKey(d) })}>
                    <div className={'calendar-day ' + (dateKey(d) === today ? 'today' : '')}>{d.getDate()}</div>
                    {tasks.filter(t => zonedParts(t.due_at, zone).date === dateKey(d)).map(t =>
                        <button key={t.id} className={'calendar-event ' + (t.status === 'done' ? 'done-event' : '')}
                            onClick={e => { e.stopPropagation(); this.task(dateKey(d), t.id); }}>
                            {zonedParts(t.due_at, zone).time} {t.title}
                        </button>)}
                </div>)}</div>
            </section>
            <section className="plan-section">
                <div className="row between"><h2>{this.t('studyPlan')}</h2><button className="btn" onClick={() => this.task(today)}><Icon name="plus"/>{this.t('newArrangement')}</button></div>
                <p>{this.t('planIntro')}</p>
                <div className="plan-layout">
                    <form className="plan-chat" onSubmit={e => this.plan(e)}>
                        <div className="row"><span className="mini-logo"><Icon name="book"/></span><h3>{this.t('assistant')}</h3></div>
                        <p>{this.t('planExample')}</p>
                        <textarea aria-label={this.t('naturalPlan')} required maxLength="2000" placeholder={this.t('planPlaceholder')}
                            value={this.state.plan} onChange={e => this.setState({ plan: e.target.value })}/>
                        <button className="btn primary" disabled={this.state.busy}>{this.t(this.state.busy ? 'processing' : 'schedule')}</button>
                        {(this.state.answer || this.state.answerFallback) && <p className="plan-response">{this.state.answer || this.t('executed')}</p>}
                    </form>
                    <div className="task-list">{tasks.map(t => <article className="task-card" key={t.id}>
                        <button className={'task-check ' + (t.status === 'done' ? 'done' : '')}
                            aria-label={this.t(t.status === 'done' ? 'reopenNamed' : 'completeNamed', { title: t.title })}
                            onClick={() => this.done(t)}>{t.status === 'done' && <Icon name="check"/>}</button>
                        <div style={{ flex: 1 }}><h3 className={t.status === 'done' ? 'completed-title' : ''}>{t.title}</h3>
                            <p className="helper-note">{zonedParts(t.due_at, zone).date} {zonedParts(t.due_at, zone).time}
                                {t.course ? ' · ' + (this.props.courses.find(c => c.id === t.course)?.code || this.t('course')) : ''}</p></div>
                        <IconButton name="edit" title={this.t('editNamed', { title: t.title })} onClick={() => this.task('', t.id)}/>
                        <IconButton name="trash" title={this.t('deleteNamed', { title: t.title })} onClick={async () => {
                            if (window.confirm(this.t('deleteConfirm'))) {
                                await remove('/tasks/' + t.id + '?version=' + t.version); this.load();
                            }
                        }}/>
                    </article>)}
                    {!tasks.length && <div className="empty-state"><Icon name="calendar"/><h3>{this.t('emptyTitle')}</h3><p>{this.t('emptyNotice')}</p></div>}
                    </div>
                </div>
            </section>
        </div>;
    }
}
class TaskForm extends React.Component {
    static contextType = UiLocaleContext;
    t = (name, params) => this.context.t('calendar.' + name, params);
    fieldId = 'task-form-' + key();
    state = { error: '', busy: false };
    async submit(e) { e.preventDefault(); const f = new FormData(e.currentTarget); this.setState({ busy: true }); try {
        await this.props.onSubmit({ title: f.get('title'), due_at: wallTimeToISO(f.get('date'), f.get('time'), this.props.user.timezone), timezone: this.props.user.timezone, course: f.get('course') || null, request_id: key() });
    }
    catch (e) {
        this.setState({ error: e.message, busy: false });
    } }
    render() {
        const { task, user, courses } = this.props;
        const dt = task ? zonedParts(task.due_at, user.timezone) : { date: this.props.date || dateKey(new Date()), time: '14:00' };
        const field = name => this.fieldId + '-' + name;
        return <form onSubmit={e => this.submit(e)}>
            <div className="field"><label htmlFor={field('title')}>{this.t('content')}</label>
                <input id={field('title')} name="title" required maxLength="150" defaultValue={task?.title || ''} placeholder={this.t('contentExample')}/></div>
            <div className="row"><div className="field" style={{ flex: 1 }}><label htmlFor={field('date')}>{this.t('date')}</label>
                <input id={field('date')} name="date" type="date" required defaultValue={dt.date}/></div>
                <div className="field"><label htmlFor={field('time')}>{this.t('time')}</label>
                    <input id={field('time')} name="time" type="time" required defaultValue={dt.time}/></div></div>
            <div className="field"><label htmlFor={field('course')}>{this.t('taskCourse')}</label>
                <select id={field('course')} name="course" defaultValue={task?.course || ''} disabled={!!task}>
                    <option value="">{this.t('personal')}</option>{courses.map(c => <option key={c.id} value={c.id}>{c.code} {c.name}</option>)}</select></div>
            <p className="helper-note">{this.t('timezone', { zone: user.timezone })}</p>
            {this.state.error && <p className="error-text">{this.state.error}</p>}
            <button className="btn primary" disabled={this.state.busy} style={{ marginTop: 18 }}>{this.t('save')}</button>
        </form>;
    }
}
function inline(text) { return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((x, i) => x.startsWith('**') ? <strong key={i}>{x.slice(2, -2)}</strong> : x.startsWith('`') ? <code key={i}>{x.slice(1, -1)}</code> : x); }
const FEEDBACK_CATEGORIES = ['ANSWER_WRONG', 'CITATION_WRONG', 'QUESTION_INCOMPLETE', 'IMAGE_RECOGNITION', 'GRADING_DISPUTE', 'COURSE_CLASSIFICATION', 'SERVICE_FAULT', 'OTHER'];
export class FeedbackForm extends React.Component {
    static contextType = UiLocaleContext;
    translate(name, params = {}) { return (this.context?.t || defaultUiTranslate)('feedbackReport.' + name, params); }
    state = { category: '', text: '', includeBody: false, busy: false, error: '' };
    async submit(e) { e.preventDefault(); this.setState({ busy: true, error: '' }); const { course, config, lastMessage, lastAnswer, runId } = this.props; const attach = this.state.includeBody; const payload = { course_id: course.id, message_id: lastMessage?.id || null, run_id: runId || null, model: config?.model || null, category: this.state.category || null, report_text: attach ? (this.state.text.trim() || null) : null, question: attach ? (lastMessage?.text || null) : null, answer: attach ? (lastAnswer?.text || null) : null, attach_body: attach }; try {
        await submitFeedback(payload);
        this.props.onDone();
    }
    catch (err) {
        this.setState({ error: err.message, busy: false });
    } }
    render() { const { category, text, includeBody, busy, error } = this.state; return <form onSubmit={e => this.submit(e)}><p className="helper-note">{this.translate('intro')}</p><div className="field"><label>{this.translate('type')}</label><select value={category} onChange={e => this.setState({ category: e.target.value })}><option value="">{this.translate('automatic')}</option>{FEEDBACK_CATEGORIES.map(id => <option key={id} value={id}>{this.translate('categories.' + id)}</option>)}</select></div><label className="check-line"><input type="checkbox" checked={includeBody} onChange={e => this.setState({ includeBody: e.target.checked })}/>{this.translate('includeBody')}</label><div className="field"><label>{this.translate('details')}</label><textarea value={text} maxLength="2000" disabled={!includeBody} placeholder={this.translate(includeBody ? 'detailsPlaceholder' : 'detailsDisabledPlaceholder')} onChange={e => this.setState({ text: e.target.value })}/></div><p className="helper-note">{this.translate('privacy')}</p>{error && <p className="error-text">{error}</p>}<button className="btn primary" style={{ marginTop: 16 }} disabled={busy}>{this.translate(busy ? 'submitting' : 'submit')}</button></form>; }
}
export class Learn extends React.Component {
    static contextType = UiLocaleContext;
    state = { attachments:{teach:[],problem:[]}, uploading:{teach:false,problem:false}, nodes: [], knowledgeBuild: null, expanded: false, hover: null, ratio: .5, fullscreen: false, mobile: 'teach', conv: { teach: null, problem: null }, messages: { teach: [], problem: [] }, inputs: { teach: '', problem: '' }, run: { teach: null, problem: null }, partial: { teach: '', problem: '' }, status: { teach: '', problem: '' }, statusKeys: { teach: null, problem: null }, activeNode: null, error: '', busy: { teach: false, problem: false }, thinking: { teach: false }, exercises: {}, practiceAnswers: {}, practiceBusy: {}, explanations: {}, windows: {}, pair: null, assessment: null, assessPicker: null, visualAssistance: { enabled: false, loading: true }, visualPreferenceBusy: false, visualAutoEligible: {} };
    translate(name, params = {}) { return (this.context?.t || defaultUiTranslate)(name, params); }
    controllers = {};
    explanationControllers = {};
    follow = {teach:true,problem:true};
    // One bounded reconnect per run and lane, counted here so "retry until it works" cannot
    // become an unbounded loop during an outage. Reset when a run starts and when one is
    // reconciled as finished.
    streamRetries = {teach:0,problem:0};
    winZ = 0;
    winCount = 0;
    componentDidUpdate(prevProps,prevState){
        for(const lane of ['teach','problem'])if(this.follow[lane]&&(prevState.messages[lane]!==this.state.messages[lane]||prevState.partial[lane]!==this.state.partial[lane])){
            const el=document.getElementById('messages-'+lane);if(el)el.scrollTop=el.scrollHeight;
        }
    }
    componentDidMount() { this.unmounted = false; this.load(); this.keyHandler = e => { if (e.key === 'Escape')
        this.setState({ fullscreen: false, expanded: false }); }; window.addEventListener('keydown', this.keyHandler); }
    componentWillUnmount() { this.unmounted = true; clearTimeout(this.knowledgePoll); window.removeEventListener('keydown', this.keyHandler); Object.values(this.controllers).forEach(c => c.abort()); Object.values(this.explanationControllers).forEach(c => c.abort()); if(this.onMove){window.removeEventListener('mousemove',this.onMove);window.removeEventListener('touchmove',this.onMove);}if(this.onUp){window.removeEventListener('mouseup',this.onUp);window.removeEventListener('touchend',this.onUp);window.removeEventListener('touchcancel',this.onUp);} }
    async load() { const revision=this.pairRevision || 0; try {
        const cid = this.props.course.id;
        const [nodes, layout, knowledgeBuild, visualAssistance] = await Promise.all([request(`/courses/${cid}/knowledge`), request(`/courses/${cid}/layout`), request(`/courses/${cid}/knowledge-build-status`), this.props.config?.visual_engine_enabled ? getVisualAssistance(cid).catch(() => ({ enabled: false })) : Promise.resolve({ enabled: false })]);
        if (this.unmounted || revision !== (this.pairRevision || 0)) return;
        this.setState({ nodes, knowledgeBuild, ratio: layout.ratio || .5, activeNode: layout.active_node, visualAssistance: { ...visualAssistance, loading: false } });
        this.scheduleKnowledgePoll(knowledgeBuild);
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
    scheduleKnowledgePoll(status) {
        clearTimeout(this.knowledgePoll);
        if (!status || !['QUEUED','BUILDING','NOT_RECONCILED'].includes(status.status)) return;
        this.knowledgePoll = setTimeout(() => this.refreshKnowledge(), 5000);
    }
    async refreshKnowledge() { try {
        const cid = this.props.course.id;
        const [nodes, knowledgeBuild] = await Promise.all([request(`/courses/${cid}/knowledge`), request(`/courses/${cid}/knowledge-build-status`)]);
        if (this.unmounted) return;
        this.setState({ nodes, knowledgeBuild });
        this.scheduleKnowledgePoll(knowledgeBuild);
    } catch (e) { if (!this.unmounted) this.setState({ error: e.message }); } }
    knowledgeEmptyState() {
        const build = this.state.knowledgeBuild || {};
        const status = ['QUEUED', 'BUILDING', 'WAITING_SOURCE', 'BLOCKED', 'FAILED', 'UNKNOWN'].includes(build.status) ? build.status : 'EMPTY';
        const title = this.translate(`knowledge.empty.${status}.title`);
        const fallback = this.translate(`knowledge.empty.${status}.body`);
        const body = ['BLOCKED', 'FAILED'].includes(status) && build.message ? build.message : fallback;
        return <div className="empty-state"><Icon name="tree"/><h3>{title}</h3><p>{body}</p></div>;
    }
    displayStatus(status, lane) {
        if (!status) return '';
        const keyed = this.state.statusKeys?.[lane];
        if (keyed?.name) return this.uiStatus(keyed.name, keyed.params || {});
        if (typeof status === 'object' && status.i18nKey) return this.translate(status.i18nKey, status.params || {});
        const legacy = { '正在输出中': 'workspace.outputStatus', '正在思考中': 'workspace.thinkingStatus' }[status];
        return legacy ? this.translate(legacy) : status;
    }
    uiStatus(name, params = {}) { return this.translate('workspace.' + name, params); }
    setLaneUiStatus(lane, name, params = {}) {
        if (this.unmounted) return;
        this.setState(s => ({
            status: { ...s.status, [lane]: this.uiStatus(name, params) },
            statusKeys: { ...s.statusKeys, [lane]: { name, params } },
        }));
    }
    diag() { /* diagnostics removed after the round-93 investigation */ }
    async reconcile(lane, cid, rid, controller = null) {
        // Bounded, model-free reconciliation of one run against the server's canonical record.
        // This is the answer to "the server finished and the browser did not show it": a stream
        // can be skipped, aborted or cut, but the assistant message is already committed on the
        // server before the terminal event, so reading the conversation is enough to show it —
        // with **no second model call and no page reload** (a reload may find history; it is not
        // how the first answer is supposed to become visible).
        //
        // It is deliberately narrow, because the round-93 investigation measured what a loose
        // version does:
        //   * only the run's own conversation is read, and only while the pane still shows it,
        //     so a late answer cannot overwrite a conversation the learner has moved to;
        //   * it refuses when a newer run owns the lane (`this.state.run[lane]` is a different
        //     id), so an old watcher cannot clear a new run's state;
        //   * guarded on controller identity when one is supplied;
        //   * idempotent — the message list is replaced wholesale from the server, so running it
        //     twice renders exactly the same thing;
        //   * the composer input, the attachments and the Pair binding are never touched.
        // Returns true only when it actually reconciled the pane.
        if (this.unmounted)
            return false;
        if (controller && this.controllers[lane] !== controller)
            return false;
        if (this.state.conv[lane] !== cid)
            return false;
        const current = this.state.run[lane];
        if (current && rid && current !== rid)
            return false;
        let saved = null;
        try {
            saved = await request('/conversations/' + cid);
        }
        catch {
            return false;
        }
        // Re-check after the await: everything above is a claim about a moment that has passed.
        if (this.unmounted || this.state.conv[lane] !== cid)
            return false;
        if (controller && this.controllers[lane] !== controller)
            return false;
        const stillCurrent = this.state.run[lane];
        if (stillCurrent && rid && stillCurrent !== rid)
            return false;
        this.setLane('messages', lane, saved.messages);
        let run = null;
        if (rid) {
            try {
                run = await request('/runs/' + rid);
            }
            catch {
                run = null;
            }
        }
        const terminal = ['completed', 'cancelled', 'failed'];
        const finished = run ? terminal.includes(run.status) : !!saved.active_run && terminal.includes(saved.active_run.status);
        if (finished) {
            this.streamRetries[lane] = 0;
            this.setLane('partial', lane, '');
            this.setLane('busy', lane, false);
            this.setLane('run', lane, null);
            if (run && run.status === 'completed') {
                const coverage = run.coverage;
                const coverageLabel = coverage && coverage.status === 'submitted' ? (coverage.covered_items && JSON.parse(coverage.covered_items).length > 0 ? 'coverageCounted' : 'coveragePending') : null;
                if (coverageLabel) this.setLaneUiStatus(lane, coverageLabel); else this.setLane('status', lane, '');
                const latestAssistant = [...(saved.messages || [])].reverse().find(message => message.role === 'assistant');
                if (latestAssistant && this.state.visualAssistance.enabled && this.props.config.visual_auto_enabled)
                    this.setState(state => ({ visualAutoEligible: { ...state.visualAutoEligible, [latestAssistant.id]: true } }));
            }
            else if (run && !this.state.status[lane]) {
                this.setLane('status', lane, `${run.status} · ${run.error || ''}`);
            }
        }
        else {
            this.setLane('partial', lane, run ? run.partial_text : '');
            this.setLaneUiStatus(lane, 'outputStatus');
        }
        return true;
    }
    recoverOrphanedAnswer(lane, cid, controller) {
        // The pane moved to another conversation while this run was streaming (or while the run
        // was still being created), so the answer is in `cid`'s history rather than on screen.
        // This path used to do nothing at all: no status, no busy clear — the learner was left
        // with their question, no answer, and a send button disabled for good (measured in round
        // 93: `watch:skip conv=1ed8887b cid=50b7d9b1`, a node binding landing mid-run).
        // The run is not lost and the answer is not fabricated: say where it went — naming the
        // control the learner actually has, which is the history dialog — and release the
        // composer. Guarded on the controller identity so a superseded watcher cannot clear a
        // newer one's busy state.
        if (controller && this.controllers[lane] !== controller)
            return;
        this.setLane('busy', lane, false);
        this.setLane('run', lane, null);
        this.setLaneUiStatus(lane, 'orphanedAnswer');
    }
    setLane(field, lane, value, callback) { if (this.unmounted)
        return; this.setState(s => field === 'status'
            ? { status: { ...s.status, [lane]: value }, statusKeys: { ...s.statusKeys, [lane]: null } }
            : { [field]: { ...s[field], [lane]: value } }, callback); }
    async saveLayout() { try {
        await send(`/courses/${this.props.course.id}/layout`, { ratio: this.state.ratio, teach_conversation: this.state.conv.teach, problem_conversation: this.state.conv.problem, active_node: this.state.activeNode }, 'PUT');
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
    restorePair(id) {
        // A thin wrapper so `ask()` can wait for a binding that is still in flight: the
        // body below is unchanged, but its promise is published as `pendingRestore` for
        // as long as it is unsettled.
        const task = this._restorePair(id);
        this.pendingRestore = task;
        const clear = () => { if (this.pendingRestore === task) this.pendingRestore = null; };
        task.then(clear, clear);
        return task;
    }
    async _restorePair(id) { const revision = this.pairRevision = (this.pairRevision || 0) + 1; for (const lane of ['teach', 'problem'])
        this.controllers[lane]?.abort(); try {        const pair = await getPair(id);
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
                    this.setLaneUiStatus(lane, 'previousGenerationFailed', { error: active.error });
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
        this.setLaneUiStatus(lane, 'previousGenerationFailed', { error: active.error });
        this.setLane('partial', lane, active.partial_text);
    } }
    history() { this.props.modal(this.translate('workspace.history'), <PairHistory course={this.props.course.id} toast={this.props.toast} closeModal={this.props.closeModal} onSelect={id => { this.props.closeModal(); this.restorePair(id); }} onDeleted={(id, teachConv, problemConv) => { if (teachConv === this.state.conv.teach || problemConv === this.state.conv.problem) {
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
        // A node binding in flight (`learnNode` -> `restorePair`) moves this lane to the
        // pair's own conversation and bumps `pairRevision`. Starting a run before it lands
        // was measurable in round 93: the run went to the conversation the pane was
        // showing, the binding then switched the pane, and the answer belonged to a
        // conversation the learner was no longer looking at. Wait for the binding instead
        // of racing it — this is the same ordering the product intends, since the click
        // and the send are one user action apart. `pendingBinding` covers the whole node
        // click; `pendingRestore` covers a history selection.
        const binding = this.pendingBinding || this.pendingRestore;
        if (binding) {
            try { await binding; } catch (e) { /* a failed binding leaves the pane as it was */ }
            if (this.unmounted)
                return;
        }
        const revision=this.pairRevision || 0;
        const frozen={node_id:lane==='teach'?this.state.activeNode:null,
            attachment_ids:this.state.attachments[lane].map(f=>f.id),
            teaching_mode:lane==='teach'&&this.state.thinking.teach?'thinking':'normal'};
        if (!value.trim() || this.state.busy[lane])
            return;
        this.follow[lane]=true;
        this.streamRetries[lane]=0;
        this.setLane('busy', lane, true);
        this.setLane('partial', lane, '');
        this.setLaneUiStatus(lane, 'thinkingStatus');
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
            if (this.unmounted)
                return;
            // Two different moves invalidate this answer's place on screen, and they are checked
            // separately because they are raised by different code paths: a Pair binding or a
            // history selection bumps `pairRevision`, while `restore()` (a layout or history
            // restore) switches `conv` **without** bumping it. Testing only the revision is what
            // let a reply to one conversation be written over a pane that had already moved to
            // another.
            if (revision !== (this.pairRevision || 0) || this.state.conv[lane] !== id) {
                // This used to `return` silently: the run kept going on the server, nothing
                // watched it, and `busy` stayed true — the learner saw their question, no answer
                // and a dead composer until a reload. Reconcile the run's own conversation first;
                // if the pane is showing something else, say where the answer went.
                this.setLane('run', lane, result.id);
                const reconciled = await this.reconcile(lane, id, result.id);
                if (reconciled)
                    await this.watch(lane, result.id, id, false);
                else
                    this.recoverOrphanedAnswer(lane, id, null);
                return;
            }
            this.setLane('messages', lane, Array.isArray(saved.messages) ? saved.messages : this.state.messages[lane]);
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
                const firstVisible = !seenDelta;
                seenDelta = true;
                this.setState(s => ({ partial: { ...s.partial, [lane]: s.partial[lane] + data.text } }), () => {
                    if (!firstVisible || typeof globalThis.performance?.mark !== 'function') return;
                    try {
                        globalThis.performance.mark('coursejesus:first-visible-text', { detail: {
                            lane, run_id: rid, server_observed_at: data.server_observed_at || null,
                        } });
                    } catch { /* Performance marks are diagnostics and never block the answer. */ }
                });
                this.setLaneUiStatus(lane, 'outputStatus');
            }
            if (type === 'status')
                this.setLane('status', lane, seenDelta ? this.uiStatus('outputStatus') : (data.label || this.uiStatus('thinkingStatus'))); if (type === 'error')
                this.setLane('status', lane, data.message || (data.code + ' · ' + data.message)); }, controller.signal);
            if (this.state.conv[lane] === cid && !this.unmounted)
                await this.reconcile(lane, cid, rid, controller);
            else
                this.recoverOrphanedAnswer(lane, cid, controller);
        }
        catch (e) {
            if (e.name !== 'AbortError') {
                // The stream is gone; the run is not. The server commits the assistant message
                // before it emits the terminal event, so one bounded re-read can still show it —
                // with no second model call. One reconnect is attempted first, and the budget is
                // per run (`streamRetries`), because "retry until it works" is how an outage turns
                // into an unbounded loop.
                const attempts = this.streamRetries[lane] || 0;
                if (attempts < 1) {
                    this.streamRetries[lane] = attempts + 1;
                    this.setLaneUiStatus(lane, 'reconnecting');
                    await this.watch(lane, rid, cid, true);
                    return;
                }
                const reconciled = await this.reconcile(lane, cid, rid, controller);
                if (!reconciled) {
                    this.setLaneUiStatus(lane, 'disconnectedSaved');
                    this.setLane('busy', lane, false);
                }
            }
            else if (this.controllers[lane] === controller) {
                // A superseded watcher must not leave the composer disabled. `restore`
                // and `restorePair` abort the lane's stream before re-establishing
                // state; when the abort has no successor (nothing re-watched this lane)
                // the busy flag was never cleared, so the learner saw their question,
                // no answer, and a send button that stayed disabled for good. The run
                // itself completes on the server and its answer is in the history.
                // Guarded on the controller identity so an abort that WAS superseded
                // cannot clear the new watcher's busy state.
                const reconciled = await this.reconcile(lane, cid, rid, controller);
                if (!reconciled && this.controllers[lane] === controller) {
                    this.setLane('busy', lane, false);
                    this.setLane('run', lane, null);
                }
            }
        }
    }
    async attach(lane,e){
        const input=e.currentTarget, file=input.files[0];if(!file)return;
        this.setLane('uploading',lane,true);
        try{
            if(this.state.attachments[lane].length>=4)throw Error(this.translate('workspace.attachmentLimit', { count: 4 }));
            const data=new FormData();data.append('file',file);data.append('folder','我的题目');
            const saved=await request(`/courses/${this.props.course.id}/files`,{method:'POST',body:data});
            if(!this.state.attachments[lane].some(x=>x.id===saved.id))this.setLane('attachments',lane,[...this.state.attachments[lane],saved]);
            if(!this.state.inputs[lane].trim())this.setLane('inputs',lane,'请阅读这个附件，'+(lane==='problem'?'逐步讲解题目；看不清的条件请先指出。':'用中文帮我学习其中的知识，保留英文术语。'));
        }catch(error){this.props.toast(error.message);}finally{input.value='';this.setLane('uploading',lane,false);}
    }
    async stop(lane) { const rid = this.state.run[lane]; if (rid)
        await send('/runs/' + rid + '/cancel', {}); }
    currentPairId() { return typeof this.state.pair === 'object' ? this.state.pair?.id : this.state.pair; }
    isCurrentExerciseRun(rid, context) {
        return !this.unmounted && this.props.course.id === context.courseId &&
            this.currentPairId() === context.pairId && this.state.run.problem === rid;
    }
    async doExercise(explicitNode = null, cycleId = null, purpose = null) { const lane = 'problem'; if (this.state.busy.problem)
        return; this.follow.problem = true; this.setLane('busy', lane, true); this.setLane('partial', lane, ''); this.setLaneUiStatus(lane, 'questionGenerating'); try {
        const context = { courseId: this.props.course.id, pairId: this.currentPairId() };
        const run = await createExercise(context.courseId, explicitNode, context.pairId, cycleId, purpose);
        this.setLane('run', lane, run.id);
        await this.watchExercise(run.id, context);
    }
    catch (e) {
        this.setLane('status', lane, e.message);
        this.setLane('busy', lane, false);
        this.props.toast(e.message);
    } }
    async reconcileExercise(rid, context, controller) {
        const terminal = ['completed', 'cancelled', 'failed'];
        // The exercise run is durable. Polling this GET endpoint only observes that same run;
        // it never starts a replacement task or incurs another model call.
        for (let attempt = 0; attempt < 100; attempt += 1) {
            if (controller.signal.aborted || !this.isCurrentExerciseRun(rid, context)) return false;
            const run = await request('/runs/' + rid);
            if (!this.isCurrentExerciseRun(rid, context)) return false;
            if (!terminal.includes(run.status)) {
                this.setLane('partial', 'problem', run.partial_text || this.state.partial.problem);
                this.setLaneUiStatus('problem', run.status === 'running' ? 'questionRecovering' : 'questionPreparing');
                await new Promise(resolve => {
                    const timer = window.setTimeout(resolve, 1800);
                    controller.signal.addEventListener('abort', () => { window.clearTimeout(timer); resolve(); }, { once: true });
                });
                continue;
            }
            if (run.conversation) {
                const saved = await request('/conversations/' + run.conversation);
                if (!this.isCurrentExerciseRun(rid, context)) return false;
                this.setLane('conv', 'problem', run.conversation, () => this.saveLayout());
                this.setLane('messages', 'problem', Array.isArray(saved.messages) ? saved.messages : []);
            }
            this.setLane('partial', 'problem', run.status === 'completed' ? '' : (run.partial_text || ''));
            this.setLane('status', 'problem', run.status === 'completed' ? '' : (run.error || this.uiStatus(run.status === 'cancelled' ? 'generationStopped' : 'questionGenerationIncomplete')));
            this.setLane('busy', 'problem', false);
            this.setLane('run', 'problem', null);
            return true;
        }
        if (this.isCurrentExerciseRun(rid, context)) {
            this.setLaneUiStatus('problem', 'questionStillRunning');
            this.setLane('busy', 'problem', false);
        }
        return false;
    }
    async watchExercise(rid, context = { courseId: this.props.course.id, pairId: this.currentPairId() }) {
        const controller = new AbortController();
        this.controllers['problem'] = controller;
        let seenDelta = false;
        try {
            await streamEvents(rid, (type, data) => { if (!this.isCurrentExerciseRun(rid, context)) return; if (type === 'delta') {
                seenDelta = true;
                this.setState(s => ({ partial: { ...s.partial, problem: s.partial.problem + data.text } }));
                this.setLaneUiStatus('problem', 'outputStatus');
            }
            if (type === 'status')
                this.setLane('status', 'problem', seenDelta ? this.uiStatus('outputStatus') : (data.label || this.uiStatus('thinkingStatus'))); if (type === 'error')
                this.setLane('status', 'problem', data.message || (data.code + ' · ' + data.message)); }, controller.signal);
            await this.reconcileExercise(rid, context, controller);
        }
        catch (e) {
            if (e.name !== 'AbortError') {
                this.setLaneUiStatus('problem', 'questionReconnect');
                try { await this.reconcileExercise(rid, context, controller); }
                catch {
                    if (this.isCurrentExerciseRun(rid, context)) {
                        this.setLaneUiStatus('problem', 'questionStatusUnavailable');
                        this.setLane('busy', 'problem', false);
                    }
                }
            }
        }
    }
    mergeExercise(exerciseId, base, patch) {
        this.setState(s => ({ exercises: { ...s.exercises, [exerciseId]: { ...(base || {}), ...(s.exercises[exerciseId] || {}), ...patch } } }));
    }
    setPracticeBusy(exerciseId, value) {
        this.setState(s => ({ practiceBusy: { ...s.practiceBusy, [exerciseId]: value } }));
    }
    async requestPracticeHint(exerciseId, base) { if (this.state.practiceBusy[exerciseId]) return;
        this.setPracticeBusy(exerciseId, true); try {
            const hint = await requestExerciseHint(exerciseId);
            this.mergeExercise(exerciseId, base, { latest_hint: hint, hint_count: Number(base?.hint_count || 0) + 1 });
        } catch (e) { this.props.toast(e.message); } finally { this.setPracticeBusy(exerciseId, false); }
    }
    async submitPracticeAnswer(exerciseId, base) { if (this.state.practiceBusy[exerciseId]) return;
        const answer = (this.state.practiceAnswers[exerciseId] || '').trim();
        if (!answer) { this.props.toast(this.translate('workspace.practiceAnswerRequired')); return; }
        this.setPracticeBusy(exerciseId, true); try {
            const attempt = await submitPracticeAttempt(exerciseId, answer);
            this.mergeExercise(exerciseId, base, { latest_attempt: attempt });
            if (['PENDING','RUNNING'].includes(attempt.status)) this.pollPracticeEvaluation(exerciseId, base);
        } catch (e) { this.props.toast(e.message); } finally { this.setPracticeBusy(exerciseId, false); }
    }
    async pollPracticeEvaluation(exerciseId, base) {
        for (let n = 0; n < 120 && !this.unmounted; n += 1) {
            await new Promise(resolve => setTimeout(resolve, 1000));
            try {
                const current = await getExercise(exerciseId);
                this.mergeExercise(exerciseId, base, current);
                const status = current.latest_attempt?.status;
                if (!['PENDING','RUNNING'].includes(status)) return;
            } catch (error) {
                if (n === 119) this.props.toast(error.message);
            }
        }
    }
    async revealSteps(exerciseId, base = null) { try {
        const revealed = await revealExercise(exerciseId);
        this.mergeExercise(exerciseId, base, { revealed: true, steps: revealed.steps });
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    mergeDiagnostic(exerciseId, ex, update) {
        const current = ex.evidence_card?.diagnostic || {};
        const responses = update.responses || {};
        const items = (update.items || current.items || []).map(item => ({
            ...item,
            response: responses[item.question_revision_id] || item.response || null,
        }));
        this.mergeExercise(exerciseId, ex, {
            evidence_card: {
                ...(ex.evidence_card || {}),
                diagnostic: { ...current, ...update, items },
            },
        });
    }
    async startDiagnostic(exerciseId, ex) { if (this.state.practiceBusy[exerciseId]) return;
        this.setPracticeBusy(exerciseId, true); try {
            const diagnostic = await configureLearningDiagnostic(this.props.course.id, ex.learning_cycle_id);
            this.mergeDiagnostic(exerciseId, ex, diagnostic);
        } catch (e) { this.props.toast(e.message); } finally { this.setPracticeBusy(exerciseId, false); }
    }
    async skipDiagnostic(exerciseId, ex) { if (this.state.practiceBusy[exerciseId]) return;
        this.setPracticeBusy(exerciseId, true); try {
            const diagnostic = await skipLearningDiagnostic(this.props.course.id, ex.learning_cycle_id);
            this.mergeDiagnostic(exerciseId, ex, diagnostic);
        } catch (e) { this.props.toast(e.message); } finally { this.setPracticeBusy(exerciseId, false); }
    }
    async diagnosticUnsure(exerciseId, ex, assignmentId) { if (this.state.practiceBusy[exerciseId]) return;
        this.setPracticeBusy(exerciseId, true); try {
            const diagnostic = await markLearningDiagnosticUnsure(this.props.course.id, ex.learning_cycle_id, assignmentId);
            this.mergeDiagnostic(exerciseId, ex, diagnostic);
        } catch (e) { this.props.toast(e.message); } finally { this.setPracticeBusy(exerciseId, false); }
    }
    renderDiagnostic(exerciseId, ex, busy) {
        const diagnostic = ex.evidence_card?.diagnostic;
        if (!ex.learning_cycle_id || !diagnostic) return null;
        if (diagnostic.status === 'NOT_STARTED') return <section className="practice-feedback learning-loop-diagnostic" aria-label={this.translate('workspace.diagnosticOptionalLabel')}><div className="practice-feedback-title"><strong>{this.translate('workspace.diagnosticOptionalTitle')}</strong><span>{this.translate('workspace.diagnosticNotOfficial')}</span></div><p>{this.translate('workspace.diagnosticBody')}</p><div className="practice-controls"><button type="button" className="btn practice-submit" disabled={busy} onClick={() => this.startDiagnostic(exerciseId, ex)}>{this.translate('workspace.diagnosticStart')}</button><button type="button" className="btn" disabled={busy} onClick={() => this.skipDiagnostic(exerciseId, ex)}>{this.translate('workspace.diagnosticSkip')}</button></div></section>;
        if (diagnostic.status === 'SKIPPED') return <p className="helper-note" role="status">{this.translate('workspace.diagnosticSkipped')}</p>;
        const items = diagnostic.items || [];
        return <section className="practice-feedback learning-loop-diagnostic" aria-label={this.translate('workspace.diagnosticLabel')}><div className="practice-feedback-title"><strong>{this.translate('workspace.diagnosticTitle')}</strong><span>{this.translate(diagnostic.status === 'COMPLETED' ? 'workspace.diagnosticCompleted' : 'workspace.diagnosticSkippable')}</span></div><ol>{items.map(item => <li key={item.id}><p>{item.prompt}</p>{item.response ? <span className="helper-note">{this.translate('workspace.diagnosticUnsureRecorded')}</span> : <button type="button" className="btn" disabled={busy} onClick={() => this.diagnosticUnsure(exerciseId, ex, item.id)}>{this.translate('workspace.diagnosticUnsure')}</button>}</li>)}</ol>{diagnostic.status !== 'COMPLETED' && <button type="button" className="btn" disabled={busy} onClick={() => this.skipDiagnostic(exerciseId, ex)}>{this.translate('workspace.diagnosticSkipRemaining')}</button>}</section>;
    }
    async optInFollowup(exerciseId, ex) { if (this.state.practiceBusy[exerciseId]) return;
        this.setPracticeBusy(exerciseId, true); try {
            const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Hong_Kong';
            const followup = await scheduleLearningFollowup(this.props.course.id, ex.learning_cycle_id, timezone);
            this.mergeExercise(exerciseId, ex, { followup });
            this.props.toast(this.translate(followup.status === 'BOUND' ? 'workspace.followupScheduled' : 'workspace.followupPending'));
        } catch (e) { this.props.toast(e.message); } finally { this.setPracticeBusy(exerciseId, false); }
    }
    renderExercise(m) {
        const ex = this.state.exercises[m.exercise] || m.exercise_state || {};
        const revealed = !!ex.revealed, busy = !!this.state.practiceBusy[m.exercise];
        const hint = ex.latest_hint, attempt = ex.latest_attempt;
        const evaluationPending = attempt && ['PENDING','RUNNING'].includes(attempt.status);
        const evaluationFailed = attempt && ['FAILED','UNKNOWN'].includes(attempt.status);
        const listSeparator = this.translate('workspace.listSeparator');
        return <div className="exercise-actions">
            {this.renderDiagnostic(m.exercise, ex, busy)}
            {hint && <div className="practice-hint" role="status"><strong>{this.translate('workspace.hintTitle')}</strong><p>{hint.hint}</p><small>{hint.strategy}</small></div>}
            {evaluationPending && <div className="practice-feedback" role="status"><div className="practice-feedback-title"><strong>{this.translate('workspace.evaluationPending')}</strong><span>{this.translate(attempt.independent ? 'workspace.independentNoHelp' : 'workspace.helpSeen')}</span></div><p>{this.translate('workspace.evaluationPendingBody')}</p></div>}
            {evaluationFailed && <div className="practice-feedback verdict-needs_review" role="alert"><div className="practice-feedback-title"><strong>{this.translate(attempt.status === 'UNKNOWN' ? 'workspace.evaluationUnknown' : 'workspace.evaluationIncomplete')}</strong></div><p>{this.translate('workspace.evaluationFailedBody')}</p></div>}
            {attempt && !evaluationPending && !evaluationFailed && <div className={'practice-feedback verdict-' + String(attempt.verdict || '').toLowerCase()} role="status"><div className="practice-feedback-title"><strong>{this.translate(attempt.verdict === 'CORRECT' ? 'workspace.verdictCorrect' : attempt.verdict === 'PARTIAL' ? 'workspace.verdictPartial' : attempt.verdict === 'INCORRECT' ? 'workspace.verdictIncorrect' : 'workspace.verdictReview')}</strong><span>{this.translate(attempt.independent ? 'workspace.independentAnswer' : attempt.assistance === 'ANSWER_REVEALED' ? 'workspace.answerRevealed' : 'workspace.hintAssisted')}</span></div><p>{attempt.feedback}</p>{attempt.strengths?.length > 0 && <p><b>{this.translate('workspace.strengths')}</b>{attempt.strengths.join(listSeparator)}</p>}{attempt.gaps?.length > 0 && <p><b>{this.translate('workspace.gaps')}</b>{attempt.gaps.join(listSeparator)}</p>}<p><b>{this.translate('workspace.nextStep')}</b>{attempt.next_step}</p></div>}
            {ex.evidence_card && <div className="practice-feedback learning-loop-card" aria-label={this.translate('workspace.evidenceCardAria')}><div className="practice-feedback-title"><strong>{this.translate('workspace.evidenceCardTitle')}</strong><span>{this.translate(ex.evidence_card.currently_valid_closure ? 'workspace.closureValid' : ex.evidence_card.historical_closure_exists ? 'workspace.closureHistoryReview' : 'workspace.closureInProgress')}</span></div><p>{ex.evidence_card.label_zh}</p><small>{this.translate('workspace.validAttempts', { valid: ex.evidence_card.attempts?.filter(x => x.currently_eligible).length || 0, total: ex.evidence_card.attempts?.length || 0 })}</small></div>}
            {attempt?.feedback && ex.learning_cycle_id && !ex.evidence_card?.historical_closure_exists && <button type="button" className="btn" disabled={this.state.busy.problem} onClick={() => this.doExercise(ex.node || this.state.activeNode, ex.learning_cycle_id, 'TRANSFER')}>{this.translate('workspace.assignTransferQuestion')}</button>}
            {ex.evidence_card?.currently_valid_closure && !(ex.followup || ex.evidence_card.followups?.length) && <button type="button" className="btn" disabled={busy} onClick={() => this.optInFollowup(m.exercise, ex)}>{this.translate('workspace.scheduleFollowup')}</button>}
            {(ex.followup || ex.evidence_card?.followups?.at(-1)) && <small className="helper-note">{this.translate('workspace.followupTask', { status: (ex.followup || ex.evidence_card.followups.at(-1)).status })}</small>}
            {!revealed ? <div className="practice-response"><label htmlFor={'practice-answer-' + m.exercise}>{this.translate('workspace.answerLabel')}</label><textarea id={'practice-answer-' + m.exercise} aria-label={this.translate('workspace.answerAria')} maxLength="6000" value={this.state.practiceAnswers[m.exercise] || ''} onChange={e => this.setState(s => ({ practiceAnswers: { ...s.practiceAnswers, [m.exercise]: e.target.value } }))} placeholder={this.translate('workspace.answerPlaceholder')}/><div className="practice-controls"><button type="button" className="btn practice-submit" disabled={busy || !(this.state.practiceAnswers[m.exercise] || '').trim()} onClick={() => this.submitPracticeAnswer(m.exercise, ex)}>{this.translate('workspace.submitPractice')}</button><button type="button" className="btn" disabled={busy} onClick={() => this.requestPracticeHint(m.exercise, ex)}>{this.translate('workspace.requestHint')}</button><button type="button" className="show-answer-link" disabled={busy} onClick={() => this.revealSteps(m.exercise, ex)}>{this.translate('workspace.showAnswer')}</button></div></div> : <><div className="exercise-steps">{(ex.steps || []).map(s => <div className="exercise-step" key={s.step_id}><div className="step-title">{s.ordinal}. {s.title}</div><div className="step-text">{s.text}</div><button className="step-explain-link" onClick={() => this.openExplanation(m.exercise, s, s.ordinal)}>{this.translate('workspace.detailedExplanation')}</button></div>)}</div><button type="button" className="btn repractice-button" disabled={this.state.busy.problem} onClick={() => this.doExercise(ex.node || this.state.activeNode)}>{this.translate('workspace.practiceSameTarget')}</button></>}
        </div>;
    }
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
            this.setState(s => ({ explanations: { ...s.explanations, [key]: { ...(s.explanations[key] || {}), status: 'error', error: this.translate('workspace.connectionInterrupted') } } })); });
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
        // Published as `pendingBinding` for its whole duration, not just from
        // `restorePair` onwards: the first await below is the request that decides which
        // conversation this lane is about to be bound to, and a send that starts during
        // it lands in the conversation the pane happened to be showing (round 93).
        const task = this._learnNode(node);
        this.pendingBinding = task;
        const clear = () => { if (this.pendingBinding === task) this.pendingBinding = null; };
        task.then(clear, clear);
        return task;
    }
    async _learnNode(node) {
        try {
        const opened = await send(`/courses/${this.props.course.id}/nodes/${node.id}/open`, {});
            this.setState({ activeNode: node.id, expanded: false, hover: null, mobile: 'teach' });
            await this.restorePair(opened.pair_id);
        } catch (error) { this.props.toast(error.message); }
    }
    atomicDescendants(nodeId) { const result = [];
        const stack = [nodeId];
        while (stack.length) { const id = stack.pop(); for (const n of this.state.nodes.filter(x => x.parent === id)) { if (n.kind === 'ATOMIC')
            result.push(n);
        else
            stack.push(n.id); } }
        return result; }
    assess(node, mode = 'new') { if (node.kind === 'COMPOSITE') { const children = this.atomicDescendants(node.id); if (!children.length) {
            this.props.toast(this.translate('workspace.compositeNoAtomic'));
            return;
        }
        this.setState({ assessPicker: { parent: node, children, mode }, hover: null });
        return;
    }
        this.openAssessment(node, mode); }
    openAssessment(node, mode = 'new', sessionId = null) { this.setState({ assessment: { node, mode, sessionId, entryKey: key() }, expanded: false, hover: null, assessPicker: null }); }
    closeAssessment() { this.setState({ assessment: null, assessPicker: null }); this.load(); }
    renderAssessPicker() { const picker = this.state.assessPicker; if (!picker)
        return null; return <div className="assessment-overlay"><div className="assessment-workspace assess-picker"><header className="assessment-topbar"><div><h2>{this.translate('workspace.assessmentPickerTitle')}</h2><p className="muted">{picker.parent.title} · {this.translate('workspace.compositeNotDirect')}</p></div><button className="btn" onClick={() => this.setState({ assessPicker: null })}>{this.translate('workspace.cancel')}</button></header><div className="assessment-picker-list">{picker.children.map(child => <button key={child.id} className="node-picker-row" onClick={() => this.openAssessment(child, picker.mode)}><Icon name="book"/><span>{child.title}</span><small className="muted">{child.assessment_display || this.translate('knowledge.notAssessed')}</small></button>)}</div></div></div>; }
    async source(c) { try {
        const rows = await request(`/courses/${this.props.course.id}/files`);
        const f = rows.find(x => x.id === c.document_id);
        if (!f)
            throw new Error(this.translate('workspace.sourceUnavailable'));
        this.props.modal(f.name, <Preview course={this.props.course} file={f} toast={this.props.toast}/>);
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    reportProblem() { const all = [...this.state.messages.teach, ...this.state.messages.problem]; const lastUser = all.filter(m => m.role === 'user').pop(); const lastAnswer = all.filter(m => m.role === 'assistant').pop(); this.props.modal(this.translate('workspace.reportIssue'), <FeedbackForm course={this.props.course} config={this.props.config} lastMessage={lastUser} lastAnswer={lastAnswer} runId={this.state.run?.teach || this.state.run?.problem || null} onDone={() => { this.props.closeModal(); this.props.toast(this.translate('feedbackReport.received')); }}/>); }
    requestVisualAssistance = (afterEnable = null) => {
        if (this.state.visualAssistance.enabled) { afterEnable?.(); return; }
        this.props.modal(this.translate('visual.consentTitle'), <VisualAssistanceConsent
            onCancel={this.props.closeModal}
            onConfirm={async () => {
                const preference = await setVisualAssistance(this.props.course.id, true);
                if (this.unmounted) return;
                this.props.closeModal();
                this.props.toast(this.translate('workspace.visualAssistanceEnabled'));
                // Run the pending action only after the ON state has reached
                // VisualControls; otherwise it still sees stale OFF props.
                this.setState(
                    { visualAssistance: { ...preference, loading: false } },
                    () => afterEnable?.(),
                );
            }}/>)
    };
    disableVisualAssistance = async () => {
        if (this.state.visualPreferenceBusy) return;
        this.setState({ visualPreferenceBusy: true });
        try {
            const preference = await setVisualAssistance(this.props.course.id, false);
            if (!this.unmounted) this.setState({ visualAssistance: { ...preference, loading: false } });
            this.props.toast(this.translate('workspace.visualAssistanceDisabled'));
        } catch (error) { this.props.toast(error.message); }
        finally { if (!this.unmounted) this.setState({ visualPreferenceBusy: false }); }
    };
    renderTree() { const groups = this.state.nodes.filter(n => !n.parent), build = this.state.knowledgeBuild || {}; return <div className="tree-expanded"><div className="row between"><div><h2>{this.translate('knowledge.title')}</h2><p className="helper-note" style={{ marginTop: 5 }}>{this.translate('knowledge.selectHelp')}{build.machine_generated ? ` · ${this.translate('knowledge.machineGenerated')}` : ''}</p></div><IconButton name="close" title={this.translate('knowledge.collapse')} onClick={() => this.setState({ expanded: false })}/></div><div className="tree-columns">{groups.map(root => { const children = this.state.nodes.filter(n => n.parent === root.id); return <div className="tree-group" key={root.id}>{children.length ? <div className="tree-group-title">{root.title}</div> : null}{children.length ? this.renderNodes(root.id, 0) : this.renderNodeRow(root, 0)}</div>; })}</div>{!groups.length && this.knowledgeEmptyState()}</div>; }
    renderNodeRow(n, depth) { const progressLabel = n.progress === 'LEARNED' ? this.translate('knowledge.learned') : n.progress === 'LEARNING' ? this.translate('knowledge.learning') : n.progress === 'SPEC_UNAVAILABLE' ? this.translate('common.notAvailable') : this.translate('knowledge.notStarted'); return <div key={n.id} style={{ marginLeft: depth * 14 }}><div className={'tree-node-new ' + (this.state.activeNode === n.id ? 'selected' : '')} tabIndex="0" onMouseEnter={() => this.setState({ hover: n.id })} onFocus={() => this.setState({ hover: n.id })} onMouseLeave={() => this.setState({ hover: null })} onClick={() => this.setState({ hover: n.id })}><Icon name="book"/><span>{n.title}</span><Icon name="arrow"/>{this.state.hover === n.id && <div className="node-popover" onClick={e => e.stopPropagation()}><strong>{n.title}</strong><button onClick={() => this.learnNode(n)}><span>{this.translate('knowledge.progress')}</span><b>{progressLabel}</b><Icon name="arrow"/></button><div className="assessment-result-entry"><IconButton name="history" title={this.translate('knowledge.history')} onClick={event => { event.stopPropagation(); this.assess(n, 'history'); }}/><button onClick={() => this.assess(n, 'result')}><span>{this.translate('knowledge.result')}</span><b>{n.assessment_display || this.translate('knowledge.notAssessed')}</b><Icon name="arrow"/></button></div><button className="start-assessment" onClick={() => this.assess(n, 'new')}><span>{this.translate('knowledge.startAssessment')}</span><Icon name="arrow"/></button></div>}</div>{this.renderNodes(n.id, depth + 1)}</div>; }
    renderNodes(parent, depth) { return this.state.nodes.filter(n => n.parent === parent).map(n => this.renderNodeRow(n, depth)); }
    renderPane(lane) {
        const isTeach = lane === 'teach', messages = this.state.messages[lane];
        const title = this.translate(isTeach ? 'workspace.teaching' : 'workspace.problem');
        return <section className={'learning-pane pane-' + lane + ' ' + (this.state.mobile === lane ? 'mobile-active' : '')}>
            <header className="pane-header"><div className="row"><span className="pane-symbol"><Icon name={isTeach ? 'book' : 'edit'}/></span><div><h3>{title}</h3><small>{this.translate(isTeach ? 'workspace.teachingSubtitle' : 'workspace.problemSubtitle')}</small></div></div><div className="row" style={{ gap: 1 }}><IconButton name="history" title={this.translate(isTeach ? 'workspace.teachingHistory' : 'workspace.problemHistory')} onClick={() => this.history()}/><IconButton name="plus" title={this.translate('workspace.newPair')} onClick={() => this.newPair()}/></div></header>
            <div className="pane-messages" id={'messages-' + lane} onScroll={e => { const el = e.currentTarget; this.follow[lane] = el.scrollHeight - el.scrollTop - el.clientHeight < 100; }}>
                {messages.length === 0 && !this.state.partial[lane] ? <div className="pane-welcome"><div className="welcome-symbol"><Icon name={isTeach ? 'book' : 'edit'}/></div><h2>{this.translate(isTeach ? 'workspace.teachingWelcomeTitle' : 'workspace.problemWelcomeTitle')}</h2><p>{this.translate(isTeach ? 'workspace.teachingWelcomeBody' : 'workspace.problemWelcomeBody')}</p><div className="suggestion-stack">{(isTeach ? [(this.props.course.id === 'cs3481' ? '请用中文解释 DBSCAN 的核心点' : '请用中文介绍这门课的核心知识'), '我想先看看这门课的知识地图'] : [(this.props.course.id === 'cs3481' ? '讲解 Tutorial_02_Clustering.pdf 的 Question 2' : '请结合我上传的题目说明解题步骤'), '解题时怎样判断应该用哪种方法？']).map(text => <button key={text} onClick={() => this.ask(lane, text)}>{text}<Icon name="arrow"/></button>)}</div></div> : messages.map(m => {
                    const exercise = this.state.exercises[m.exercise] || m.exercise_state;
                    const visibleMessage = m.exercise && !exercise?.revealed ? {...m, steps: []} : m;
                    return <article className={'chat-message-new ' + m.role} key={m.id}><div className="message-byline">{m.role === 'user' ? this.props.user.name : BRAND.name}</div>{m.attachments?.length > 0 && <div className="attachment-chips">{m.attachments.map(f => <span key={f.id}><Icon name="file"/>{f.name}</span>)}</div>}<RichText text={m.text} message={visibleMessage}/>{m.role === 'assistant' && m.exercise && this.renderExercise(m)}{m.role === 'assistant' && <VisualControls locale={this.context.locale} t={this.context.t} videoEnabled={this.state.visualAssistance.video_enabled === true} enabled={!!this.props.config.visual_engine_enabled} autoEnabled={!!this.state.visualAutoEligible[m.id]} assistanceEnabled={!!this.state.visualAssistance.enabled} requestAssistance={this.requestVisualAssistance} courseId={this.props.course.id} pairId={this.state.pair} message={m} toast={this.props.toast}/>} {m.citations?.length > 0 && <div className="citation-row">{m.citations.map(c => { const verdict = citationVerdict(c, this.context.t); return <button key={c.id} title={verdict ? verdict.note : undefined} className={verdict ? 'citation-flagged citation-' + verdict.flag : ''} onClick={() => this.source(c)}><Icon name="file"/>{c.name} · p.{c.page}{verdict && <span className="citation-warning" role="img" aria-label={this.translate(verdict.flag === 'contradicted' ? 'workspace.citationContradicted' : 'workspace.citationUnverified')}><Icon name="help"/></span>}</button>; })}</div>}</article>;
                })}{this.state.partial[lane] && <article className="chat-message-new assistant"><div className="message-byline">{BRAND.name} <span>{this.translate('workspace.partialOutput')}</span></div><RichText text={this.state.partial[lane]}/></article>}
            </div>
            <footer className="pane-footer"><div className="generation-status" role="status">{this.displayStatus(this.state.status[lane], lane)}</div>{this.state.attachments[lane].length > 0 && <div className="attachment-chips">{this.state.attachments[lane].map(f => <span key={f.id}><Icon name="file"/>{f.name}<button title={this.translate('workspace.removeAttachment')} onClick={() => this.setLane('attachments', lane, this.state.attachments[lane].filter(x => x.id !== f.id))}>×</button></span>)}</div>}<form className="chat-composer" onSubmit={e => { e.preventDefault(); this.ask(lane); }}><textarea aria-label={this.translate(isTeach ? 'workspace.teachingInput' : 'workspace.problemInput')} placeholder={this.translate(isTeach ? 'workspace.teachingPlaceholder' : 'workspace.problemPlaceholder')} value={this.state.inputs[lane]} maxLength="6000" onChange={e => this.setLane('inputs', lane, e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); this.ask(lane); } }}/><div className="composer-bottom"><div className="row"><label className="attach-button" role="button" tabIndex={this.state.busy[lane] || this.state.uploading[lane] ? -1 : 0} aria-label={this.translate(isTeach ? 'workspace.teachingAttach' : 'workspace.problemAttach')} title={this.translate('workspace.attach')} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.querySelector('input')?.click(); } }}><Icon name="file"/><input type="file" hidden aria-label={this.translate(isTeach ? 'workspace.teachingAttachment' : 'workspace.problemAttachment')} accept=".pdf,.txt,.md,.csv,.ipynb,.png,.jpg,.jpeg,.webp,.docx,.pptx" disabled={this.state.busy[lane] || this.state.uploading[lane]} onChange={e => this.attach(lane, e)}/></label>{this.state.uploading[lane] && <span className="helper-note">{this.translate('workspace.uploading')}</span>}{isTeach && <span className="thinking-control"><span className="thinking-label">{this.translate('workspace.thinking')}</span><button type="button" className={'thinking-circle' + (this.state.thinking.teach ? ' on' : '')} aria-pressed={this.state.thinking.teach} aria-label={this.translate('workspace.thinkingToggle')} onClick={() => this.setState(s => ({thinking: {...s.thinking, teach: !s.thinking.teach}}))}><span className="thinking-dot"/></button></span>}</div><div className="row" style={{gap: 8}}>{!isTeach && <button type="button" className="do-exercise-btn" onClick={() => this.doExercise()} disabled={this.state.busy.problem || this.state.uploading.problem}>{this.translate('workspace.doOne')}</button>}{this.state.busy[lane] ? <IconButton name="stop" title={this.translate('workspace.stop')} onClick={() => this.stop(lane)}/> : <button className="send-button" aria-label={this.translate(isTeach ? 'workspace.sendTeaching' : 'workspace.sendProblem')} disabled={!this.state.inputs[lane].trim() || this.state.uploading[lane]}><Icon name="send"/></button>}</div></div></form></footer>
        </section>;
    }
    render() { return <div className={'learn-new ' + (this.state.fullscreen ? 'focus-mode' : '')}><button className="knowledge-strip" onClick={() => this.setState({ expanded: !this.state.expanded })}><span className="row"><Icon name="tree"/><strong>{this.translate('knowledge.title')}</strong><small>{this.translate('knowledge.nodeSummary', { count: this.state.nodes.length })}</small></span><Icon name={this.state.expanded ? 'up' : 'down'}/></button><div className="workspace-new"><header className="workspace-toolbar"><IconButton name={this.state.fullscreen ? 'collapse' : 'expand'} title={this.context.t(this.state.fullscreen ? 'workspace.exitFullscreen' : 'workspace.fullscreen')} onClick={() => this.setState({ fullscreen: !this.state.fullscreen })}/><span className="muted small">{this.props.course.code} · {this.context.t('workspace.title')}</span>{this.props.config.visual_engine_enabled && <VisualAssistanceToggle enabled={!!this.state.visualAssistance.enabled} busy={this.state.visualPreferenceBusy || this.state.visualAssistance.loading} onEnableRequest={() => this.requestVisualAssistance()} onDisable={this.disableVisualAssistance}/>}<button type="button" className="btn small" onClick={() => this.reportProblem()}><Icon name="help"/>{this.context.t('workspace.reportIssue')}</button><span className="model-label">{this.translate(this.props.config.provider_mode === 'disabled' ? 'workspace.serviceDisconnected' : 'workspace.serviceConnected')}</span></header><div className="mobile-pane-tabs"><button className={this.state.mobile === 'teach' ? 'active' : ''} onClick={() => this.setState({ mobile: 'teach' })}>{this.context.t('workspace.teaching')}</button><button className={this.state.mobile === 'problem' ? 'active' : ''} onClick={() => this.setState({ mobile: 'problem' })}>{this.context.t('workspace.problem')}</button></div>{this.state.error && <p className="error-text">{this.state.error}</p>}<div className={'workspace-columns '+(this.state.resizing?'is-resizing':'')} ref={el => this.workspace = el} style={{ gridTemplateColumns: `minmax(0,${this.state.ratio}fr) 9px minmax(0,${1 - this.state.ratio}fr)` }}>{this.renderPane('teach')}<div className="pane-divider" role="separator" aria-label={this.translate('workspace.resizePanes')} aria-orientation="vertical" aria-valuemin="25" aria-valuemax="75" aria-valuenow={Math.round(this.state.ratio * 100)} tabIndex="0" onMouseDown={e => this.drag(e)} onTouchStart={e=>this.drag(e)} onKeyDown={e => { if (['ArrowLeft', 'ArrowRight'].includes(e.key)) {
        e.preventDefault();
        this.setState({ ratio: Math.max(.25, Math.min(.75, this.state.ratio + (e.key === 'ArrowLeft' ? -.025 : .025))) }, () => this.saveLayout());
    } }}><span /></div>{this.renderPane('problem')}</div></div>{this.state.expanded && this.renderTree()}{this.renderAssessPicker()}{this.state.assessment && <AssessmentWorkspace key={this.state.assessment.entryKey} course={this.props.course} node={this.state.assessment.node} mode={this.state.assessment.mode} sessionId={this.state.assessment.sessionId} toast={this.props.toast} onExit={() => this.closeAssessment()}/>}{this.renderWindows()}</div>; }
}
function normalizedAssessmentOption(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}
export function assessmentPromptWithoutRepeatedOptions(prompt, options) {
    const text = String(prompt || '');
    if (!Array.isArray(options) || !options.length)
        return text;
    const lines = text.trimEnd().split(/\r?\n/);
    const nonEmpty = lines.map((line, index) => ({ line, index })).filter(item => item.line.trim());
    if (nonEmpty.length < options.length)
        return text;
    const tail = nonEmpty.slice(-options.length);
    const matches = tail.every((item, index) => {
        const labelled = item.line.match(/^\s*(?:[A-Za-z]|\d+)\s*[).、:：]\s*(.+?)\s*$/);
        return labelled && normalizedAssessmentOption(labelled[1]) === normalizedAssessmentOption(options[index]);
    });
    if (!matches)
        return text;
    return lines.slice(0, tail[0].index).join('\n').trimEnd();
}

function assessmentMarks(questionCount) {
    if (questionCount === 5)
        return [10, 15, 20, 25, 30];
    const base = Math.floor(10000 / questionCount), remainder = 10000 % questionCount;
    return Array.from({ length: questionCount }, (_, index) => (base + (index < remainder ? 1 : 0)) / 100);
}

function configuredAssessmentMarks(slots, policyVersion) {
    if (policyVersion !== 'cj.assessment.points.v1')
        return assessmentMarks(slots.length);
    const pointIds = [...new Set(slots.map(slot => slot.primary_point_id))];
    const pointBase = Math.floor(10000 / pointIds.length), pointRemainder = 10000 % pointIds.length;
    const shares = new Map(pointIds.map((pointId, index) => [pointId, pointBase + (index < pointRemainder ? 1 : 0)]));
    const seen = new Map();
    const counts = new Map(pointIds.map(pointId => [pointId, slots.filter(slot => slot.primary_point_id === pointId).length]));
    return slots.map(slot => {
        const count = counts.get(slot.primary_point_id), index = seen.get(slot.primary_point_id) || 0;
        seen.set(slot.primary_point_id, index + 1);
        const total = shares.get(slot.primary_point_id), base = Math.floor(total / count), remainder = total % count;
        return (base + (index < remainder ? 1 : 0)) / 100;
    });
}

function defaultTaskForm(questionType) {
    return { MCQ_SINGLE: 'concept', NUMERIC: 'calculation', SHORT_TEXT: 'definition', EXPLANATION: 'analysis', CODE: 'code' }[questionType] || 'analysis';
}


function validTaskForms(questionType, forms) {
    if (questionType === 'CODE')
        return forms.filter(form => form.id === 'code');
    if (questionType === 'EXPLANATION')
        return forms.filter(form => ['calculation', 'analysis', 'evaluation'].includes(form.id));
    return forms.filter(form => form.id === defaultTaskForm(questionType));
}
export function provisionalAssessmentScore(questions) {
    const awarded = (questions || []).map(question => question?.review?.awarded_marks);
    if (!awarded.length || awarded.some(value => typeof value !== 'number' || !Number.isFinite(value)))
        return null;
    return Math.round(awarded.reduce((total, value) => total + value, 0) * 10000) / 10000;
}
function assessmentAnswersFromDraft(text, questions) {
    const source = String(text || '');
    const pattern = /(?:^|\n)\s*(?:第\s*([1-9]\d*)\s*[题问]|([1-9]\d*)\s*[.)、:：]|[Qq]\s*([1-9]\d*)\s*[:：.])/g;
    const matches = [...source.matchAll(pattern)];
    const answers = {};
    matches.forEach((match, index) => {
        const ordinal = Number(match[1] || match[2] || match[3]);
        const question = questions.find(item => Number(item.ordinal) === ordinal) || questions[ordinal - 1];
        if (!question)
            return;
        const start = Number(match.index) + match[0].length;
        const end = index + 1 < matches.length ? Number(matches[index + 1].index) : source.length;
        answers[question.id] = source.slice(start, end).trim();
    });
    return answers;
}
function assessmentDraftFromAnswers(questions, answers) {
    return questions.map((question, index) => `${index + 1}. ${answers[question.id] || ''}`).join('\n');
}
export class AssessmentWorkspace extends React.Component {
    static contextType = UiLocaleContext;
    translate(name, params = {}) { return (this.context?.t || defaultUiTranslate)('assessment.' + name, params); }
    state = { view: null, summary: null, setup: null, slots: [], configurationId: null, busy: false, error: '', preparing: null, answers: {}, attachments: [], windows: {}, explanations: {} };
    assessmentIntentId = 'assessment-intent-' + key();
    winZ = 0;
    winCount = 0;
    componentDidMount() { this.loadSummary(); this.keyHandler = e => { if (e.key === 'Escape')
        this.props.onExit(); }; window.addEventListener('keydown', this.keyHandler); }
    componentWillUnmount() { window.removeEventListener('keydown', this.keyHandler); if (this.preparationTimer)
        window.clearTimeout(this.preparationTimer); }
    async loadSummary() { try {
        const summary = await getAssessment(this.props.course.id, this.props.node.id);
        this.setState({ summary });
        if (['IN_PROGRESS', 'SUBMITTED', 'NEEDS_REVIEW', 'GRADED'].includes(summary.status) && summary.session)
            await this.open(summary.session);
        else
            await this.loadSetup();
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async loadSetup() { try {
        const setup = await getAssessmentSetup(this.props.course.id, this.props.node.id);
        const active = setup.active_preparation;
        const slots = ((active?.slots?.length ? active.slots : setup.default_slots) || []).map(slot => ({ ...slot }));
        if (active?.client_intent_id)
            this.assessmentIntentId = active.client_intent_id;
        this.setState({ setup, slots, configurationId: active?.configuration_id || null, preparing: active || null, error: '' }, () => {
            if (active)
                this.handlePreparationState(active);
        });
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async open(session) { this.setState({ busy: true, error: '' }); try {
        const view = await getAssessmentSession(this.props.course.id, session);
        const emptyAnswers = Object.fromEntries((view.questions || []).map(question => [question.id, '']));
        this.setState({ view, preparing: null, answers: emptyAnswers });
        try {
            const draft = await loadAssessmentDraft(this.props.course.id, session);
            if (draft?.draft?.unified_answer)
                this.setState({ answers: { ...emptyAnswers, ...assessmentAnswersFromDraft(draft.draft.unified_answer, view.questions || []) } });
        }
        catch { }
    }
    catch (e) {
        this.setState({ error: e.message });
    }
    finally {
        this.setState({ busy: false });
    } }
    configurationPayload(intentAction = 'CONFIGURE', includeSlots = true) { const pointPolicy = this.state.setup?.policy_version === 'cj.assessment.points.v1'; const slots = includeSlots ? this.state.slots.map(slot => ({ slot_id: slot.slot_id, question_type: slot.question_type, task_form: slot.task_form, ...(pointPolicy ? { primary_point_id: slot.primary_point_id, variation_purpose: slot.variation_purpose ?? null, independently_scored_parts: 1 } : {}) })) : []; return {
        configuration_id: this.state.configurationId,
        slots,
        ...(pointPolicy ? { client_intent_id: this.assessmentIntentId, intent_action: intentAction, content_language: this.state.setup?.content_language || 'zh-CN' } : {}),
    }; }
    async start() { if (!this.state.setup || this.state.slots.length < this.state.setup.minimum_questions)
        return; this.setState({ busy: true, error: '', preparing: null }); try {
        const started = await startAssessment(this.props.course.id, this.props.node.id, this.configurationPayload());
        await this.handleStart(started);
    }
    catch (e) {
        this.setState({ error: e.message });
    }
    finally {
        this.setState({ busy: false });
    } }
    async handleStart(started) { if (started.preparation_job_id) {
        this.setState({ preparing: started, configurationId: started.configuration_id || this.state.configurationId });
        await this.handlePreparationState(started);
        return;
    }
        await this.open(started.id); }
    schedulePreparationPoll() { if (this.preparationTimer)
        window.clearTimeout(this.preparationTimer); this.preparationTimer = window.setTimeout(() => this.pollPreparation(), 1800); }
    async pollPreparation() { const configurationId = this.state.configurationId; if (!configurationId)
        return; try {
        const current = await getAssessmentPreparation(this.props.course.id, this.props.node.id, configurationId);
        this.setState({ preparing: current });
        await this.handlePreparationState(current);
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async handlePreparationState(preparation) { if (preparation.status === 'PREPARING')
        return this.schedulePreparationPoll(); if (preparation.status === 'READY' || (preparation.status === 'BLOCKED' && preparation.can_start_from_ready_pool)) {
        if (this.preparationTimer)
            window.clearTimeout(this.preparationTimer); const started = await startAssessment(this.props.course.id, this.props.node.id, { ...this.configurationPayload('OPEN', false), configuration_id: preparation.configuration_id }); if (started.preparation_job_id) {
            this.setState({ preparing: started });
            if (started.status === 'PREPARING')
                this.schedulePreparationPoll();
            return;
        }
        await this.open(started.id);
    } }
    async retryPreparation() { const retry = this.state.configurationId ? await startAssessment(this.props.course.id, this.props.node.id, this.configurationPayload()) : await resumePreparation(this.props.course.id, this.props.node.id); this.setState({ preparing: retry, configurationId: retry.configuration_id || this.state.configurationId }); await this.handlePreparationState(retry); }
    async cancelPreparation() { const job = this.state.preparing; if (!job?.preparation_job_id)
        return; await cancelPreparation(this.props.course.id, this.props.node.id, job.preparation_job_id); this.setState({ preparing: { ...job, status: 'CANCELLED' } }); }
    async attach(e) { const input = e.currentTarget; const file = input.files[0]; if (!file)
        return; try {
        const data = new FormData();
        data.append('file', file);
        data.append('folder', '我的题目');
        const saved = await request(`/courses/${this.props.course.id}/files`, { method: 'POST', body: data });
        this.setState(s => ({ attachments: [...s.attachments, saved] }));
    }
    catch (error) {
        this.props.toast(error.message);
    }
    finally {
        input.value = '';
    } }
    async saveDraft() { const view = this.state.view; if (!view)
        return; try {
        await saveAssessmentDraft(this.props.course.id, view.id, { unified_answer: assessmentDraftFromAnswers(view.questions || [], this.state.answers), attachments: this.state.attachments.map(a => ({ id: a.id, kind: 'image' })) });
        this.props.toast(this.translate('workspace.draftSaved'));
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    async submit() { const view = this.state.view; if (!view || view.status !== 'IN_PROGRESS')
        return; const mappedAnswers = (view.questions || []).map(question => ({ blueprint_item_id: question.id, answer: this.state.answers[question.id] || '' }));
        const unanswered = mappedAnswers.filter(answer => !answer.answer.trim());
        if (unanswered.length && !this.state.attachments.length && !window.confirm(this.translate('workspace.unansweredConfirm', { count: unanswered.length })))
            return; this.setState({ busy: true, error: '' }); try {
        const unified = assessmentDraftFromAnswers(view.questions || [], this.state.answers);
        await saveAssessmentDraft(this.props.course.id, view.id, { unified_answer: unified, attachments: this.state.attachments.map(a => ({ id: a.id, kind: 'image' })) });
        const attachmentOnly = this.state.attachments.length > 0 && mappedAnswers.every(answer => !answer.answer.trim());
        await submitAssessment(this.props.course.id, view.id, { answers: attachmentOnly ? [] : mappedAnswers, attachments: this.state.attachments.map(a => ({ id: a.id, kind: 'image' })), confirm_unanswered: attachmentOnly ? view.questions.map(q => q.id) : [] });
        const graded = await getAssessmentSession(this.props.course.id, view.id);
        this.setState({ view: graded, preparing: null });
    }
    catch (e) {
        this.setState({ error: e.message });
    }
    finally {
        this.setState({ busy: false });
    } }
    async abandon() { const view = this.state.view; if (!view)
        return; if (!window.confirm(this.translate('workspace.abandonConfirm')))
        return; await this.saveDraft(); try {
        await abandonAssessment(this.props.course.id, view.id);
        this.setState({ view: null, preparing: null });
        this.props.onExit();
    }
    catch (e) {
        this.props.toast(e.message);
    } }
    openStepExplanation(q, step) { const key = q.id + ':' + step.step_id; if (this.state.windows[key]) {
        this.closeExplanation(key);
        return;
    }
        const n = this.winCount++, z = ++this.winZ;
        this.setState(s => ({ windows: { ...s.windows, [key]: { ordinal: step.ordinal, title: step.operation, x: 90 + n * 24, y: 70 + n * 24, w: 520, h: 420, z } } }));
        this.ensureExplanation(key, q.id, step.step_id); }
    closeExplanation(key) { this.setState(s => { const w = { ...s.windows };
        delete w[key];
        return { windows: w }; }); }
    raiseExplanation(key) { const z = ++this.winZ; this.setState(s => ({ windows: { ...s.windows, [key]: { ...(s.windows[key] || {}), z } } })); }
    async ensureExplanation(key, blueprintItemId, stepId) { try {
        const created = await createAssessmentExplanation(this.props.course.id, this.state.view.id, blueprintItemId, stepId);
        this.setState(s => ({ explanations: { ...s.explanations, [key]: { status: 'completed', text: created.content?.text || this.translate('workspace.noExplanation'), messages: [] } } }));
    }
    catch (e) {
        this.setState(s => ({ explanations: { ...s.explanations, [key]: { status: 'error', error: e.message } } }));
    } }
    renderWindows() { const keys = Object.keys(this.state.windows); if (!keys.length)
        return null; return keys.map(key => <ExplanationWindow key={key} win={this.state.windows[key]} exp={this.state.explanations[key]} onClose={() => this.closeExplanation(key)} onRaise={() => this.raiseExplanation(key)} onFollowUp={() => this.props.toast(this.translate('workspace.noFollowUp'))} onCancel={() => { }}/>); }
    statusLabel() { const { view, preparing } = this.state; if (preparing)
        return this.translate(`workspace.${preparing.status === 'READY' ? 'ready' : preparing.status === 'BLOCKED' ? 'blocked' : preparing.status === 'CANCELLED' ? 'cancelled' : 'preparing'}`); if (!view)
            return this.translate('workspace.notStarted'); if (view.status === 'IN_PROGRESS')
            return this.translate('workspace.inProgress'); if (view.status === 'SUBMITTED')
            return this.translate('workspace.submitted'); if (view.status === 'GRADED')
            return this.translate('workspace.graded'); return view.status; }
    renderPreparing() { const p = this.state.preparing; const prepared = p.prepared_questions ?? p.eligible_families ?? 0; const total = p.question_count || this.state.slots.length; const number = p.current_ordinal || prepared + 1; const stage = p.current_stage === 'RESOLVING_EVIDENCE' ? this.translate('workspace.evidenceStage', { number }) : p.current_stage === 'AUTHORING_COMPLETE_QUESTION' ? this.translate('workspace.authorStage', { number }) : p.current_stage === 'AUTHOR_AND_BLIND_SOLVE' ? this.translate('workspace.solverStage', { number }) : this.translate('workspace.preparingSection'); return <div className="assessment-preparing"><p>{p.status === 'BLOCKED' ? (p.error_message || this.translate('workspace.blockedMessage')) : stage}</p><p>{this.translate('workspace.preparedProgress', { current: prepared, total })}</p>{p.status === 'BLOCKED' && <p className="error-text">{this.translate('workspace.retained')}{p.diagnostic_id ? ` ${this.translate('workspace.diagnostic', { id: p.diagnostic_id })}` : ''}</p>}<div className="row" style={{ marginTop: 12 }}>{p.status === 'BLOCKED' && <button className="btn" disabled={this.state.busy || p.error_code === 'MODEL_REQUEST_UNCERTAIN'} onClick={() => this.retryPreparation()}>{this.translate('workspace.continuePreparation')}</button>}{p.status === 'PREPARING' && <button className="btn" onClick={() => this.cancelPreparation()}>{this.translate('workspace.cancelPreparation')}</button>}</div></div>; }
    changeSlot(index, questionType) { this.setState(state => ({ slots: state.slots.map((slot, current) => current === index ? { ...slot, question_type: questionType, task_form: defaultTaskForm(questionType) } : slot), configurationId: null })); }
    changeTaskForm(index, taskForm) { this.setState(state => ({ slots: state.slots.map((slot, current) => current === index ? { ...slot, task_form: taskForm } : slot), configurationId: null })); }
    addSlot() { const setup = this.state.setup; if (!setup || this.state.slots.length >= setup.maximum_questions)
        return; if (setup.policy_version === 'cj.assessment.points.v1') { const point = (setup.points || []).find(item => this.state.slots.filter(slot => slot.primary_point_id === item.point_id).length < 2); if (!point)
            return; const first = this.state.slots.find(slot => slot.primary_point_id === point.point_id); const questionType = first?.question_type || point.allowed_forms?.[0]; this.setState(state => ({ slots: [...state.slots, { slot_id: 'point-item-' + key(), question_type: questionType, task_form: first?.task_form || defaultTaskForm(questionType), primary_point_id: point.point_id, variation_purpose: 'APPLICATION', independently_scored_parts: 1 }], configurationId: null })); return; }
        this.setState(state => ({ slots: [...state.slots, { slot_id: 'slot-' + key(), question_type: 'EXPLANATION', task_form: 'analysis' }], configurationId: null })); }
    canRemoveSlot(index) { const setup = this.state.setup, slots = this.state.slots; if (!setup || slots.length <= setup.minimum_questions)
        return false; if (setup.policy_version !== 'cj.assessment.points.v1')
        return true; const pointId = slots[index]?.primary_point_id; return slots.filter(slot => slot.primary_point_id === pointId).length > 1; }
    removeSlot(index) { if (!this.canRemoveSlot(index))
        return; this.setState(state => ({ slots: state.slots.filter((_, current) => current !== index), configurationId: null })); }
    renderSetup() { const { setup, slots } = this.state; if (!setup)
        return <div className="assessment-start"><p>{this.translate('workspace.setupLoading')}</p></div>; if (setup.policy_version === 'cj.assessment.points.v1' && setup.status !== 'READY')
        return <div className="assessment-start"><p>{this.translate('pointsNotReady')}</p></div>; const marks = configuredAssessmentMarks(slots, setup.policy_version); return <div className="assessment-setup"><div className="assessment-setup-intro"><h2>{this.translate('setupTitle')}</h2><p>{this.props.course.code} · {this.props.node.title}</p><p className="helper-note">{this.translate('workspace.legacySetupHint', { minimum: setup.minimum_questions })}</p></div><div className="assessment-slot-list">{slots.map((slot, index) => { const point = (setup.points || []).find(item => item.point_id === slot.primary_point_id); const types = point ? (setup.supported_types || []).filter(type => point.allowed_forms.includes(type.id)) : (setup.supported_types || []); const forms = validTaskForms(slot.question_type, setup.task_forms || []); return <div className="assessment-slot-row" key={slot.slot_id}><strong>{this.translate('questionOrdinal', { number: index + 1 })}</strong><label><span>{this.translate('form')}</span><select aria-label={this.translate('workspace.questionTypeAria', { number: index + 1 })} value={slot.question_type} onChange={event => this.changeSlot(index, event.target.value)}>{types.map(type => <option key={type.id} value={type.id}>{this.translate(`workspace.types.${type.id}`) || type.label}</option>)}</select></label><label><span>{this.translate('ability')}</span><select aria-label={this.translate('workspace.skillAria', { number: index + 1 })} value={slot.task_form} onChange={event => this.changeTaskForm(index, event.target.value)}>{forms.map(form => <option key={form.id} value={form.id}>{this.translate(`taskForm.${form.id}`) || form.label}</option>)}</select></label><span className="assessment-slot-marks">{this.translate('marks', { marks: marks[index].toFixed(2) })}</span><button type="button" className="icon-btn" aria-label={this.translate('deleteQuestion', { number: index + 1 })} disabled={!this.canRemoveSlot(index)} onClick={() => this.removeSlot(index)}>−</button></div>; })}</div><div className="assessment-setup-actions"><button type="button" className="btn" disabled={slots.length >= setup.maximum_questions} onClick={() => this.addSlot()}>{this.translate('workspace.addQuestion')}</button><span className="helper-note">{this.translate('workspace.totalQuestions', { count: slots.length })}</span><button type="button" className="btn primary" disabled={this.state.busy} onClick={() => this.start()}>{this.translate(this.state.busy ? 'workspace.freezing' : 'confirmStart')}</button></div></div>; }
    renderQuestion(q, i, editable = false) { const value = this.state.answers[q.id] || ''; const prompt = assessmentPromptWithoutRepeatedOptions(q.prompt, q.options); return <article className="assessment-question" key={q.id}><header><strong>{this.translate('questionOrdinal', { number: i + 1 })}</strong><small>{this.translate(`workspace.types.${q.question_type}`) || q.question_type}{q.marks ? ' · ' + this.translate('marks', { marks: q.marks }) : ''}{q.verification_method === 'AI_REVIEWED' ? ' · ' + this.translate('workspace.aiReference') : ''}</small></header><p className="assessment-prompt">{prompt}</p>{q.options && q.options.length ? <div className="assessment-options">{q.options.map((option, j) => editable ? <label key={j} className={'assessment-option ' + (value === String(j) ? 'selected' : '')}><input type="radio" name={'assessment-' + q.id} value={j} checked={value === String(j)} aria-label={this.translate('workspace.optionAria', { number: i + 1, optionNumber: j + 1, option })} onChange={e => this.setState(s => ({ answers: { ...s.answers, [q.id]: e.target.value } }))}/><span>{option}</span></label> : <span key={j} className="assessment-option-readonly">{option}</span>)}</div> : null}{editable && (!q.options || !q.options.length) ? <textarea aria-label={this.translate('workspace.answerAria', { number: i + 1 })} value={value} maxLength="12000" placeholder={this.translate('workspace.answerPlaceholder')} onChange={e => this.setState(s => ({ answers: { ...s.answers, [q.id]: e.target.value } }))}/> : null}</article>; }
    renderReview(q, i) { const review = q.review; if (!review)
        return null; const refNote = referenceVerificationNote(review.reference_verification, this.context?.t); return <div className="assessment-review"><p className="helper-note">{this.translate('workspace.yourAnswer', { answer: review.submitted_answer ?? this.translate('workspace.unanswered') })}</p><p className="helper-note">{this.translate('workspace.awarded', { awarded: review.awarded_marks ?? '—', total: q.marks })}</p>{review.rubric?.length ? <ul className="assessment-rubric">{review.rubric.map(c => <li key={c.criterion_id}>{c.dimension}：{c.description}</li>)}</ul> : null}{review.feedback ? <p className="helper-note">{review.feedback}</p> : null}{review.reference_solution ? <div className="reference-solution"><strong>{this.translate('workspace.referenceSteps')}</strong>{review.reference_solution.answer ? <p>{review.reference_solution.answer}</p> : null}{(review.reference_solution.steps || []).map(step => <div className="reference-step" key={step.step_id}><span>{step.ordinal}. {step.operation} → {step.result}</span><button className="step-explain-link" onClick={() => this.openStepExplanation(q, step)}>{this.translate('workspace.explain')}</button></div>)}{(review.reference_solution.source_refs || []).length ? <p className="muted">{this.translate('workspace.sources', { sources: review.reference_solution.source_refs.join(', ') })}</p> : null}{refNote ? <p className={`reference-verification ${refNote.kind}`} role="note">{refNote.note}</p> : null}</div> : null}</div>; }
    render() { const { view, busy, error } = this.state; const active = view && view.status === 'IN_PROGRESS'; const done = view && (view.status === 'GRADED' || view.status === 'SUBMITTED'); const provisionalScore = view?.status === 'SUBMITTED' ? provisionalAssessmentScore(view.questions) : null; return <div className="assessment-overlay" role="dialog" aria-label={this.translate('workspace.dialog')}><div className="assessment-workspace"><header className="assessment-topbar"><div><strong>{this.props.course.code}</strong> · {this.props.node.title}</div><span className="muted">{this.statusLabel()}</span><button className="btn" onClick={this.props.onExit}>{this.translate('workspace.exit')}</button></header><div className="assessment-body">{error && <p className="error-text" role="alert">{error}</p>}{this.state.preparing && this.renderPreparing()}{!view && !this.state.preparing && this.renderSetup()}{active && <div className="assessment-questions">{view.questions.map((q, i) => this.renderQuestion(q, i, true))}</div>}{done && <><div className="assessment-summary"><strong>{this.translate(view.status === 'GRADED' ? 'workspace.graded' : 'workspace.submitted')}</strong>{typeof view.raw_score === 'number' ? <span>{this.translate('workspace.rawScore', { score: view.raw_score })}</span> : provisionalScore !== null ? <span>{this.translate('workspace.provisional', { score: provisionalScore })}</span> : null}{view.grade?.label ? <span>{this.translate('workspace.gradeMapping', { grade: view.grade.label })}</span> : null}</div><div className="assessment-questions">{view.questions.map((q, i) => <div key={q.id}>{this.renderQuestion(q, i)}{this.renderReview(q, i)}</div>)}</div><div className="row" style={{ marginTop: 16 }}><button className="btn" onClick={() => this.setState({ view: null, preparing: null }, () => this.loadSetup())}>{this.translate('workspace.backHistory')}</button><button className="btn primary" onClick={() => this.setState({ view: null, preparing: null }, () => this.loadSetup())}>{this.translate('workspace.configureAnother')}</button></div></>}</div>{active && <footer className="assessment-composer"><div className="assessment-hint">{this.translate('workspace.answerHint')}</div><div className="row"><label className="attach-button" role="button" tabIndex={0} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault();
        e.currentTarget.querySelector('input')?.click(); } }}><Icon name="file"/><input type="file" hidden accept=".pdf,.txt,.md,.csv,.ipynb,.png,.jpg,.jpeg,.webp,.docx,.pptx" onChange={e => this.attach(e)}/></label>{this.state.attachments.length > 0 && <span className="muted">{this.translate('workspace.attachments', { count: this.state.attachments.length })}</span>}</div><div className="row" style={{ marginTop: 8 }}><button className="btn" disabled={busy} onClick={() => this.saveDraft()}>{this.translate('saveDraft')}</button><button className="btn" disabled={busy} onClick={() => this.abandon()}>{this.translate('workspace.abandon')}</button><button className="btn primary" disabled={busy} onClick={() => this.submit()}>{this.translate(busy ? 'workspace.submitBusy' : 'submit')}</button></div></footer>}{this.renderWindows()}</div></div>; }
}
export class ExplanationWindow extends React.Component {
    static contextType = UiLocaleContext;
    translate(name, params = {}) { return (this.context?.t || defaultUiTranslate)('explanationWindow.' + name, params); }
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
    render() { const { win, exp } = this.props; const { x, y, w, h, followUp } = this.state; const status = exp?.status; const generating = status === 'generating'; const messages = exp?.messages || []; const partial = exp?.partial || ''; const title = this.translate('title', { number: win.ordinal }); return <div className="explain-window" style={{ left: x, top: y, width: w, height: h, zIndex: win.z }} role="dialog" aria-label={title} onMouseDown={() => this.props.onRaise()} onTouchStart={() => this.props.onRaise()}><div className="explain-head" role="button" tabIndex={0} aria-label={this.translate('move')} onKeyDown={e => { if(e.target===e.currentTarget) this.keyboardAdjust(e); }} onMouseDown={e => this.startDrag(e)} onTouchStart={e => this.startDrag(e)}><strong>{title}</strong><button type="button" className="explain-close" aria-label={this.translate('close')} onClick={() => this.props.onClose()}>×</button></div><div className="explain-body">{messages.map(m => <div className={'explain-bubble ' + m.role} key={m.id || m.role + m.text.slice(0, 8)}><RichText text={m.text}/></div>)}{generating && <div className="explain-bubble assistant"><RichText text={partial || this.translate('preparing')}/></div>}{status === 'completed' && messages.length === 0 && <div className="explain-bubble assistant"><RichText text={exp.text}/></div>}{status === 'error' && <div className="explain-status"><span className="error-text">{exp.error || this.translate('failed')}</span></div>}{status === 'cancelled' && <div className="explain-status">{this.translate('stopped')}</div>}{!status && <div className="explain-status">{this.translate('loading')}</div>}</div><form className="explain-foot" onSubmit={e => this.submit(e)}><input type="text" aria-label={this.translate('followUp')} placeholder={this.translate('placeholder')} value={followUp} disabled={generating} onChange={e => this.setState({ followUp: e.target.value })}/>{generating ? <button type="button" className="btn" onClick={() => this.props.onCancel()}>{this.translate('stop')}</button> : <button type="submit" className="btn primary" disabled={!followUp.trim() || status === 'error'}>{this.translate('submit')}</button>}</form><div className="explain-resize" role="button" tabIndex={0} aria-label={this.translate('resize')} onKeyDown={e => this.keyboardAdjust(e,true)} onMouseDown={e => this.startResize(e)} onTouchStart={e => this.startResize(e)}/></div>; }
}
export class PairHistory extends React.Component {
    static contextType = UiLocaleContext;
    translate(name, params = {}) { return (this.context?.t || defaultUiTranslate)('workspace.' + name, params); }
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
    async rename(p) { const title = window.prompt(this.translate('conversationName'), p.title); if (!title || title === p.title)
        return; try {
        await renamePair(p.id, title);
        this.load();
    }
    catch (e) {
        this.setState({ error: e.message });
    } }
    async remove(p) { if (!window.confirm(this.translate('deleteConversationConfirm')))
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
    renderPicker() { const p = this.state.picker; const term = (p.q || '').toLowerCase(); const filtered = term ? this.state.nodes.filter(n => (n.title || '').toLowerCase().includes(term)) : this.state.nodes; return <div className="node-picker"><div className="row between"><h3>{this.translate(p.mode === 'rebind' ? 'changeBindingTitle' : 'bindNode')}</h3><IconButton name="close" title={this.translate('back')} onClick={() => this.setState({ picker: null, conflict: null })}/></div>{this.state.conflict && <div className="error-text" style={{ padding: '8px 0' }}>{this.translate('bindingConflict', { title: this.state.conflict.pair?.title || this.translate('unknownConversation') })}<button className="link" style={{ marginLeft: 8 }} onClick={() => { const id = this.state.conflict.pair?.id; if (id) {
        this.props.onSelect(id);
    } }}>{this.translate('open')}</button></div>}<input className="node-picker-search" autoFocus aria-label={this.translate('searchNodes')} placeholder={this.translate('searchNodesPlaceholder')} value={p.q || ''} onChange={e => this.setState(s => ({ picker: { ...s.picker, q: e.target.value } }))}/><div className="node-picker-list">{filtered.map(n => <button type="button" key={n.id} className="node-picker-row" onClick={() => this.bindNode(n.id)}><Icon name="book"/><span>{n.title}</span></button>)}{!filtered.length && <p className="helper-note" style={{ padding: 12 }}>{this.translate('noMatchingNodes')}</p>}</div></div>; }
    renderLegacy() { const { legacy, legacyOpen } = this.state; if (!legacy.length && !legacyOpen)
        return null; return <section className="legacy-history"><div className="divider"/><h3>{this.translate('legacyHistory')}</h3><p className="helper-note" style={{ marginTop: 6 }}>{this.translate('legacyHistoryNotice')}</p>{legacy.map(c => <div key={c.id} className="history-line"><button className="history-item" onClick={() => this.openLegacy(c.id)}><Icon name="history"/><span className="pair-title-time"><strong>{c.title}</strong><small>{formatTime(c.updated_at)} · {this.translate('messageCount', { count: c.message_count })}</small></span></button></div>)}{legacyOpen && <div className="legacy-reader"><div className="row between"><strong>{legacyOpen.title}</strong><IconButton name="close" title={this.translate('closeLegacy')} onClick={() => this.setState({ legacyOpen: null })}/></div><div className="legacy-messages">{legacyOpen.messages.map((m, i) => <article key={i} className={m.role === 'user' ? 'legacy-message mine' : 'legacy-message'}><small>{m.role === 'user' ? this.translate('you') : BRAND.name}</small><RichText text={m.text}/>{m.citations?.length > 0 && <ul className="legacy-citations">{m.citations.map((c, j) => <li key={j}>{c.filename || c.document_id || this.translate('courseMaterials')}</li>)}</ul>}</article>)}</div></div>}</section>; }
    render() { const { rows, error, menu, picker } = this.state; if (picker)
        return this.renderPicker(); return <div className="pair-history">{error && <p className="error-text">{error}</p>}{rows.map(p => <div key={p.id} className="history-line"><button className="history-item" onClick={() => this.props.onSelect(p.id)}><Icon name="history"/><span className="pair-title-time"><strong>{p.title}</strong><small>{formatTime(p.updated_at)}</small></span>{p.bound_node && <span className="pair-bound-tag">{this.translate('boundNode')}</span>}</button><IconButton name="trash" title={this.translate('deleteConversationNamed', { title: p.title })} onClick={() => this.remove(p)}/><div style={{ position: 'relative' }}><IconButton name="more" title={this.translate('conversationActionsNamed', { title: p.title })} onClick={() => this.setState({ menu: menu === p.id ? null : p.id })}/>{menu === p.id && <div className="dropdown"><button onClick={() => this.rename(p)}>{this.translate('rename')}</button><button onClick={() => this.setState({ picker: { pairId: p.id, mode: 'bind', q: '' }, menu: null, conflict: null })}>{this.translate('bindNode')}</button>{p.bound_node && <button onClick={() => this.setState({ picker: { pairId: p.id, mode: 'rebind', q: '' }, menu: null, conflict: null })}>{this.translate('changeBinding')}</button>}{p.bound_node && <button onClick={() => this.unbind(p)}>{this.translate('unbind')}</button>}</div>}</div></div>)}{!rows.length && <p className="helper-note">{this.translate('emptyHistory')}</p>}{this.renderLegacy()}</div>; }
}
