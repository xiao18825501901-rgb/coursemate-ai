let tokenGetter = async () => null;
export function setTokenGetter(fn) { tokenGetter = fn; }
export function base() { return (window.COURSEMATE_CONFIG?.apiBase || '/api/ui/v1').replace(/\/$/, ''); }
export async function request(path, options = {}) {
    const token = await tokenGetter();
    const headers = { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(token ? { 'Authorization': `Bearer ${token}` } : {}) };
    const response = await fetch(base() + path, { ...options, headers: { ...headers, ...options.headers }, credentials: 'include', cache: 'no-store' });
    if (!response.ok) {
        let error;
        try {
            error = await response.json();
        }
        catch {
            error = { detail: `请求失败 (${response.status})` };
        }
        const detail = error.detail;
        const message = typeof detail === 'string' ? detail : (detail && typeof detail === 'object' && typeof detail.message === 'string' ? detail.message : (detail && typeof detail === 'object' ? JSON.stringify(detail) : `请求失败 (${response.status})`));
        const err = new Error(message || `请求失败 (${response.status})`);
        err.status = response.status;
        err.code = detail && typeof detail === 'object' ? detail.code || null : null;
        err.detail = detail;
        err.body = error;
        throw err;
    }
    if (options.raw)
        return response;
    return response.status === 204 ? null : response.json();
}
export const send = (path, body, method = 'POST') => request(path, { method, body: JSON.stringify(body) });
export const remove = (path) => request(path, { method: 'DELETE' });
export const key = () => { if (crypto.randomUUID)
    return crypto.randomUUID(); const b = crypto.getRandomValues(new Uint8Array(16)); return Array.from(b, x => x.toString(16).padStart(2, '0')).join(''); };
export async function download(course, file, inline = false) {
    const response = await request(`/courses/${encodeURIComponent(course)}/files/${encodeURIComponent(file.id)}/content?download=${!inline}`, { raw: true });
    return URL.createObjectURL(await response.blob());
}
// Incremental SSE parser: CRLF can split across network chunks; multi-line data is legal.
export function createSSEParser(handle) {
    let buffer='', event='message', data=[], id=0, chars=0, first=true;
    function line(s) {
        if(first){s=s.replace(/^\uFEFF/,'');first=false;}
        if(s==='') {
            if(data.length)handle(event,data.join('\n'),id);
            event='message';data=[];chars=0;return;
        }
        if(s.startsWith(':'))return;
        const i=s.indexOf(':'), field=i<0?s:s.slice(0,i);
        let value=i<0?'':s.slice(i+1);if(value.startsWith(' '))value=value.slice(1);
        if(field==='data'){chars+=value.length;if(chars>1000000)throw Error('SSE 数据超限');data.push(value);}
        else if(field==='event')event=value;
        else if(field==='id'&&!value.includes('\0'))id=Number(value)||0;
    }
    return (chunk,final=false)=>{
        buffer+=chunk;
        if(buffer.length>1000000)throw Error('SSE 数据超限');
        while(true){
            const index=buffer.search(/[\r\n]/);if(index<0)break;
            if(buffer[index]==='\r'&&index===buffer.length-1&&!final)break;
            const length=buffer[index]==='\r'&&buffer[index+1]==='\n'?2:1;
            const current=buffer.slice(0,index);buffer=buffer.slice(index+length);line(current);
        }
        // A frame without its terminal blank line is incomplete and intentionally not emitted.
    };
}
export async function streamEvents(run, handle, signal, after = 0) {
    const response=await request(`/runs/${run}/events?after=${after}`,{raw:true,signal});
    if(!response.body)throw Error('浏览器没有收到可读取的数据流');
    const reader=response.body.getReader(), decoder=new TextDecoder();let last=after;
    const parse=createSSEParser((event,payload,id)=>{
        if(id && id<=last)return;
        handle(event,JSON.parse(payload),id);if(id)last=id;
    });
    try { while(true){const {done,value}=await reader.read();if(done)break;parse(decoder.decode(value,{stream:true}));}parse(decoder.decode(),true); }
    finally {reader.releaseLock();}
}
// Unified dual-pane sessions (pairs).
export const listPairs = (courseId) => request(`/pairs?course_id=${encodeURIComponent(courseId)}`);
export const getPair = (id) => request('/pairs/' + id);
export const createPair = (course) => send('/pairs', { course });
export const renamePair = (id, title) => send('/pairs/' + id, { title }, 'PATCH');
export const deletePair = (id) => remove('/pairs/' + id);
export const bindPair = (id, node) => send(`/pairs/${id}/bind`, { node });
// Exercises (做一题) and reveals.
export const createExercise = (courseId, node = null, pairId = null) => send(`/courses/${courseId}/exercises`, { request_id: key(), node, pair_id: pairId });
export const getExercise = (id) => request('/exercises/' + id);
export const revealExercise = (id) => send(`/exercises/${id}/reveal`, { request_id: key() });
// Step explanations (详解) and follow-ups.
export const createExplanation = (exerciseId, stepId) => send(`/exercises/${exerciseId}/steps/${stepId}/explanation`, { request_id: key() });
export const getExplanation = (id) => request('/explanations/' + id);
export const postExplanationMessage = (id, text) => send(`/explanations/${id}/messages`, { text, request_id: key() });
export const cancelExplanation = (id) => send(`/explanations/${id}/cancel`, {});
// Student verification.
export const getVerification = () => request('/me/verification');
export const redeemVerification = (code) => send('/me/verification/redeem', { code, request_id: key() });
// Course shares.
export const listShares = (q,offset=0,limit=100) => request('/shares?q=' + encodeURIComponent(q)+`&offset=${offset}&limit=${limit}`);
export const getShare = (id) => request('/shares/' + id);
export const createShare = (payload, requestId) => send('/shares', { ...payload, request_id: requestId || key() });
export const joinShare = (id) => send(`/shares/${id}/join`, {});
// Course classification.
export const getClassification = (courseId) => request(`/courses/${courseId}/classification`);
export const setClassification = (courseId, templateId) => send(`/courses/${courseId}/classification`, { template_id: templateId });
// People directory search.
export const searchPeople = (q) => request('/people?q=' + encodeURIComponent(q));
