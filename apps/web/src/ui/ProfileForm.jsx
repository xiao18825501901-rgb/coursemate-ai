import React from 'react';
import { UiLocaleContext, defaultUiTranslate } from './UiLocale';

// UI locale changes labels only. Uncontrolled fields retain in-flight drafts,
// including the separately chosen teaching language and original user content.
export class ProfileForm extends React.Component {
    static contextType = UiLocaleContext;
    t = (id) => (this.context?.t || defaultUiTranslate)(id);
    state = { failed: false, busy: false };
    async submit(event) {
        event.preventDefault();
        if (this.state.busy) return;
        const form = new FormData(event.currentTarget);
        this.setState({ busy: true, failed: false });
        try {
            await this.props.onSubmit({ name: form.get('name'), handle: form.get('handle'),
                bio: form.get('bio'), language: form.get('language'), timezone: form.get('timezone'),
                reply_notify: form.has('reply_notify'), discoverable: form.has('discoverable') });
        } catch {
            // Do not reflect raw internal/provider error text into system UI.
            this.setState({ failed: true, busy: false });
        }
    }
    render() {
        const user = this.props.user;
        return <form onSubmit={event => this.submit(event)} aria-busy={this.state.busy}>
            <div className="field"><label htmlFor="profile-name">{this.t('profile.name')}</label><input id="profile-name" name="name" defaultValue={user.name} required maxLength="50"/></div>
            <div className="field"><label htmlFor="profile-handle">{this.t('profile.handle')}</label><input id="profile-handle" name="handle" defaultValue={user.handle} required pattern={"[a-z0-9][a-z0-9_\\-]{2,29}"}/></div>
            <div className="field"><label htmlFor="profile-bio">{this.t('profile.bio')}</label><textarea id="profile-bio" name="bio" defaultValue={user.bio} maxLength="250"/></div>
            <div className="field"><label htmlFor="profile-language">{this.t('profile.teachingLanguage')}</label><select id="profile-language" name="language" defaultValue={user.language}>
                <option value="zh-CN">{this.t('profile.languages.zh-CN')}</option><option value="en">{this.t('profile.languages.en')}</option>
                <option value="bilingual">{this.t('profile.languages.bilingual')}</option><option value="auto">{this.t('profile.languages.auto')}</option>
            </select></div>
            <div className="field"><label htmlFor="profile-timezone">{this.t('profile.timezone')}</label><select id="profile-timezone" name="timezone" defaultValue={user.timezone}>
                {['Asia/Hong_Kong', 'Asia/Shanghai', 'Asia/Singapore', 'UTC', 'America/New_York', 'Europe/London'].map(zone => <option key={zone}>{zone}</option>)}
            </select></div>
            <label className="check-line"><input type="checkbox" name="discoverable" defaultChecked={!!user.discoverable}/>{this.t('profile.discoverable')}</label>
            <label className="check-line"><input type="checkbox" name="reply_notify" defaultChecked={!!user.reply_notify}/>{this.t('profile.replyNotify')}</label>
            {this.state.failed && <p className="error-text" role="alert">{this.t('profile.saveFailed')}</p>}
            <button className="btn primary" style={{ marginTop: 18 }} disabled={this.state.busy}>{this.t(this.state.busy ? 'common.saving' : 'profile.save')}</button>
        </form>;
    }
}

