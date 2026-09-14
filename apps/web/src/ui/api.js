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
        throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail));
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
