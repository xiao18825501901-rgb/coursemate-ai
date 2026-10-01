import React from 'react';
import { request } from './api.js';

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
        const link = document.createElement('a');
        link.href = this.state.url;
        link.download = `coursejesus-visual-${this.props.asset.id}`;
        link.click();
    };
    render() {
        const { asset } = this.props;
        return <figure className="visual-asset-card">
            {this.state.error && <p className="visual-error">{this.state.error}</p>}
            {!this.state.url && !this.state.error && <div className="visual-placeholder" aria-busy="true">正在读取视觉资源…</div>}
            {this.state.url && asset.mime_type.startsWith('image/') && <img src={this.state.url} alt={asset.alt_text}/>}
            <figcaption><span>{asset.alt_text}</span><button type="button" onClick={this.download} disabled={!this.state.url}>下载</button></figcaption>
            {asset.semantic_validation === 'LIMITED' && <small>生成图像为教学示意；文字与结构由系统单独校验。</small>}
        </figure>;
    }
}
