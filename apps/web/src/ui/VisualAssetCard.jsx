import React from 'react';
import { request } from './api.js';
import { defaultUiTranslate } from './UiLocale';

export class VisualAssetCard extends React.Component {
    state = { url: '', error: '' };
    componentDidMount() { this.load(); }
    componentDidUpdate(previous) { if (previous.asset.id !== this.props.asset.id) this.load(); }
    componentWillUnmount() { this.unmounted = true; this.release(); }
    release() { if (this.state.url) URL.revokeObjectURL(this.state.url); }
    async load() {
        this.release();
        try {
            const response = await request(this.props.asset.content_url, { raw: true });
            const url = URL.createObjectURL(await response.blob());
            if (this.unmounted) { URL.revokeObjectURL(url); return; }
            this.setState({ url, error: '' });
        } catch (error) {
            if (!this.unmounted) this.setState({ error: error.message, url: '' });
        }
    }
    download = () => {
        if (!this.state.url) return;
        const extension = {
            'image/png': 'png',
            'image/jpeg': 'jpg',
            'image/svg+xml': 'svg',
            'video/mp4': 'mp4',
        }[this.props.asset.mime_type];
        const link = document.createElement('a');
        link.href = this.state.url;
        link.download = `coursejesus-visual-${this.props.asset.id}${extension ? `.${extension}` : ''}`;
        link.hidden = true;
        document.body.appendChild(link);
        link.click();
        link.remove();
    };
    render() {
        const { asset } = this.props;
        const t = this.props.t || defaultUiTranslate;
        return <figure className="visual-asset-card">
            {this.state.error && <p className="visual-error">{this.state.error}</p>}
            {!this.state.url && !this.state.error && <div className="visual-placeholder" aria-busy="true">{t('visual.loadingAsset')}</div>}
            {this.state.url && asset.mime_type.startsWith('image/') && <img className={asset.mime_type === 'image/svg+xml' ? 'visual-diagram' : undefined} src={this.state.url} alt={asset.alt_text}/>}
            {this.state.url && asset.mime_type === 'video/mp4' && <video src={this.state.url} aria-label={asset.alt_text} controls playsInline preload="metadata"/>}
            <figcaption><span>{asset.alt_text}</span><button type="button" onClick={this.download} disabled={!this.state.url}>{t('visual.download')}</button></figcaption>
            {asset.semantic_validation === 'LIMITED' && <small>{t('visual.limitedNotice')}</small>}
        </figure>;
    }
}
