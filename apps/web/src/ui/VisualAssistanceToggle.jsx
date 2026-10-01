import React from 'react';
import { Icon } from './icons.jsx';

export function VisualAssistanceToggle({ enabled, busy, onEnableRequest, onDisable }) {
    const label = enabled ? '图片/视频辅助 · 已启用' : '图片/视频辅助 · 关闭';
    return <button
        type="button"
        className={'visual-assistance-toggle' + (enabled ? ' enabled' : '')}
        aria-pressed={!!enabled}
        aria-label={label}
        title={label}
        disabled={busy}
        onClick={() => enabled ? onDisable() : onEnableRequest()}
    ><Icon name="image"/><span className="visual-assistance-full">{label}</span><span className="visual-assistance-short">视觉辅助</span></button>;
}

export class VisualAssistanceConsent extends React.Component {
    state = { busy: false, error: '' };
    confirm = async () => {
        if (this.state.busy) return;
        this.setState({ busy: true, error: '' });
        try { await this.props.onConfirm(); }
        catch (error) { this.setState({ busy: false, error: error.message || String(error) }); }
    };
    render() {
        const busy = this.props.busy || this.state.busy;
        return <div className="visual-assistance-consent">
            <p>启用后，CourseJesus 会在课程学习中按需生成<br/>图片、图解或动画内容。<br/>文字回答仍会优先显示，<br/>视觉内容将在后台异步生成。<br/>你可以随时关闭。</p>
            {this.state.error && <p className="error-text" role="alert">{this.state.error}</p>}
            <div className="modal-actions">
                <button type="button" className="btn" disabled={busy} onClick={this.props.onCancel}>暂不启用</button>
                <button type="button" className="btn primary" disabled={busy} onClick={this.confirm}>{busy ? '正在启用…' : '确认启用'}</button>
            </div>
        </div>;
    }
}
