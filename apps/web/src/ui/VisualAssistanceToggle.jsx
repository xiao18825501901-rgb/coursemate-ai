import React, { useContext } from 'react';
import { Icon } from './icons.jsx';
import { UiLocaleContext, defaultUiTranslate } from './UiLocale';

export function VisualAssistanceToggle({ enabled, busy, onEnableRequest, onDisable }) {
    const { t } = useContext(UiLocaleContext);
    const label = t(enabled ? 'visual.toggleOn' : 'visual.toggleOff');
    return <button
        type="button"
        className={'visual-assistance-toggle' + (enabled ? ' enabled' : '')}
        aria-pressed={!!enabled}
        aria-label={label}
        title={label}
        disabled={busy}
        onClick={() => enabled ? onDisable() : onEnableRequest()}
    ><Icon name="image"/><span className="visual-assistance-full">{label}</span><span className="visual-assistance-short">{t('visual.shortLabel')}</span></button>;
}

export class VisualAssistanceConsent extends React.Component {
    static contextType = UiLocaleContext;
    translate(name) { return (this.context?.t || defaultUiTranslate)('visual.' + name); }
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
            <p>{this.translate('consentBody')}</p>
            {this.state.error && <p className="error-text" role="alert">{this.state.error}</p>}
            <div className="modal-actions">
                <button type="button" className="btn" disabled={busy} onClick={this.props.onCancel}>{this.translate('notNow')}</button>
                <button type="button" className="btn primary" disabled={busy} onClick={this.confirm}>{this.translate(busy ? 'enabling' : 'confirmEnable')}</button>
            </div>
        </div>;
    }
}
