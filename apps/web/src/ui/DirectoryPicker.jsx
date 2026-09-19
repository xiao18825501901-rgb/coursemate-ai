import React from 'react';
import { request } from './api.js';
import { Avatar } from './icons.jsx';

export class DirectoryPicker extends React.Component {
    state = { q: '', offset: 0, rows: [], busy: true, error: '' };
    revision = 0;
    componentDidMount() { this.load('', 0); }
    componentWillUnmount() { this.revision++; }
    async load(q, offset) {
        const revision = ++this.revision;
        this.setState({ q, offset, busy: true, error: '' });
        try {
            const rows = await request(`/people?q=${encodeURIComponent(q)}&limit=20&offset=${offset}`);
            if (revision === this.revision) this.setState({ rows, busy: false });
        } catch (error) {
            if (revision === this.revision) this.setState({ error: error.message, busy: false });
        }
    }
    render() {
        const { q, offset, rows, busy, error } = this.state;
        return <div>
            <input aria-label="查找收件人" value={q} placeholder="浏览用户，或输入姓名/用户名搜索" onChange={e => this.load(e.target.value, 0)}/>
            {error && <p role="alert" className="error-text">{error}</p>}
            <div className="people-results" aria-busy={busy}>
                {rows.map(person => <button type="button" key={person.id} className={'person-option ' + ((this.props.selected || []).includes(person.id) ? 'selected' : '')} aria-pressed={(this.props.selected || []).includes(person.id)} onClick={() => this.props.onSelect(person)}>
                    <Avatar name={person.name}/><span>{person.name}<small>@{person.handle}</small></span>
                </button>)}
            </div>
            {!busy && !rows.length && <p role="status">没有可显示的用户</p>}
            <div className="row">
                <button className="btn" type="button" disabled={busy || offset === 0} onClick={() => this.load(q, Math.max(0, offset - 20))}>上一页用户</button>
                <button className="btn" type="button" disabled={busy || rows.length < 20} onClick={() => this.load(q, offset + 20)}>下一页用户</button>
            </div>
        </div>;
    }
}
