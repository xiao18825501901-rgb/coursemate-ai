let tokenGetter = async () => null;
let uiErrorTranslator = null;
const LOCALIZED_ERROR_CODES = new Set([
    'WORKSPACE_BUSY', 'OPERATION_IN_PROGRESS', 'QUESTION_ENGINE_FAILED',
    'ASSESSMENT_POINTS_NOT_READY', 'CATALOG_SCOPE_OR_VERSION_MISMATCH',
    'QUESTION_FORM_NOT_ALLOWED', 'SECOND_ITEM_PURPOSE_REQUIRED',
    'INTENT_PAYLOAD_CONFLICT', 'PAPER_INCOMPLETE', 'ASSESSMENT_ALREADY_ACTIVE',
    'NEEDS_REVIEW', 'UNKNOWN_REQUEST', 'SOURCE_NOT_READY', 'PERMISSION_DENIED',
    'SESSION_EXPIRED', 'NETWORK_UNAVAILABLE', 'STREAM_LIMIT', 'STREAM_UNAVAILABLE',
]);
export function setTokenGetter(fn) { tokenGetter = fn; }
export function setUiErrorTranslator(fn) {
    uiErrorTranslator = typeof fn === 'function' ? fn : null;
    const installed = uiErrorTranslator;
    return () => { if (uiErrorTranslator === installed) uiErrorTranslator = null; };
}
function translatedErrorMessage(code, status, params = {}, diagnosticId = null) {
    const displayCode = code === 'STREAM_INTERRUPTED' ? 'NETWORK_UNAVAILABLE' : (LOCALIZED_ERROR_CODES.has(code) ? code : 'HTTP_STATUS');
    const fallback = displayCode === 'NETWORK_UNAVAILABLE' ? 'Connection unavailable; current progress is retained'
        : displayCode === 'STREAM_LIMIT' ? 'The response stream exceeded the safe size limit'
        : displayCode === 'STREAM_UNAVAILABLE' ? 'The browser could not read the response stream'
        : `Request failed (${status || 'unknown'})`;
    let message = uiErrorTranslator ? uiErrorTranslator(`errors.${displayCode}`, { ...params, status: status || 'unknown' }) : fallback;
    if (!message || message === `errors.${displayCode}`) message = fallback;
    if (diagnosticId) {
        const diagnostic = uiErrorTranslator ? uiErrorTranslator('errors.diagnostic', { id: diagnosticId }) : `Diagnostic ID: ${diagnosticId}`;
        message += ` · ${diagnostic}`;
    }
    return message;
}
function safeParams(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, item]) => ['string', 'number', 'boolean'].includes(typeof item)));
}
function uiError(code, { status = null, rawMessage = '', detail = null, body = null, cause = null } = {}) {
    const objectDetail = detail && typeof detail === 'object' ? detail : null;
    const params = safeParams(objectDetail?.params);
    const diagnosticId = objectDetail?.diagnostic_id || body?.diagnostic_id || null;
    const error = new Error(translatedErrorMessage(code, status, params, diagnosticId));
    error.status = status;
    error.code = code;
    error.detail = detail;
    error.body = body;
    error.rawMessage = rawMessage || '';
    if (cause) error.cause = cause;
    return error;
}
export function base() { return (window.COURSEMATE_CONFIG?.apiBase || '/api/ui/v1').replace(/\/$/, ''); }
export async function request(path, options = {}) {
    const token = await tokenGetter();
    const headers = { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(token ? { 'Authorization': `Bearer ${token}` } : {}) };
    let response;
    try {
        response = await fetch(base() + path, { ...options, headers: { ...headers, ...options.headers }, credentials: 'include', cache: 'no-store' });
    } catch (cause) {
        if (cause?.name === 'AbortError') throw cause;
        throw uiError('NETWORK_UNAVAILABLE', { rawMessage: cause?.message || String(cause), cause });
    }
    if (!response.ok) {
        let error;
        try {
            error = await response.json();
        }
        catch {
            error = { detail: null };
        }
        const detail = error.detail;
        const rawMessage = typeof detail === 'string' ? detail : (detail && typeof detail === 'object' && typeof detail.message === 'string' ? detail.message : '');
        const code = detail && typeof detail === 'object' ? detail.code || 'HTTP_STATUS' : (error.code || 'HTTP_STATUS');
        throw uiError(code, { status: response.status, rawMessage, detail, body: error });
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
        if(field==='data'){chars+=value.length;if(chars>1000000)throw uiError('STREAM_LIMIT');data.push(value);}
        else if(field==='event')event=value;
        else if(field==='id'&&!value.includes('\0'))id=Number(value)||0;
    }
    return (chunk,final=false)=>{
        buffer+=chunk;
        if(buffer.length>1000000)throw uiError('STREAM_LIMIT');
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
    if(!response.body)throw uiError('STREAM_UNAVAILABLE');
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
export const createExercise = (courseId, node = null, pairId = null, cycleId = null, purpose = null) => send(`/courses/${courseId}/exercises`, { request_id: key(), node, pair_id: pairId, cycle_id: cycleId, purpose });
export const getExercise = (id) => request('/exercises/' + id);
export const revealExercise = (id) => send(`/exercises/${id}/reveal`, { request_id: key() });
export const requestExerciseHint = (id) => send(`/exercises/${id}/hints`, { request_id: key() });
export const submitPracticeAttempt = (id, answer) => send(`/exercises/${id}/attempts`, { answer, request_id: key() });
export const scheduleLearningFollowup = (courseId, cycleId, timezone) => send(`/courses/${courseId}/learning-loops/${cycleId}/followups`, { request_id: key(), explicit_opt_in: true, timezone });
export const configureLearningDiagnostic = (courseId, cycleId) => send(`/courses/${courseId}/learning-loops/${cycleId}/diagnostic`, { request_id: key() });
export const skipLearningDiagnostic = (courseId, cycleId) => send(`/courses/${courseId}/learning-loops/${cycleId}/diagnostic/skip`, { request_id: key() });
export const markLearningDiagnosticUnsure = (courseId, cycleId, assignmentId) => send(`/courses/${courseId}/learning-loops/${cycleId}/diagnostic/${assignmentId}/unsure`, { request_id: key() });
// Step explanations (详解) and follow-ups.
export const createExplanation = (exerciseId, stepId) => send(`/exercises/${exerciseId}/steps/${stepId}/explanation`, { request_id: key() });
export const getExplanation = (id) => request('/explanations/' + id);
export const postExplanationMessage = (id, text) => send(`/explanations/${id}/messages`, { text, request_id: key() });
export const cancelExplanation = (id) => send(`/explanations/${id}/cancel`, {});
// Visual Learning Engine. Status reads are GET-only and can never enqueue work.
export const listMessageVisuals = (courseId, messageId) => request(`/courses/${encodeURIComponent(courseId)}/messages/${encodeURIComponent(messageId)}/visuals`);
export const listPairVisuals = (courseId, pairId) => request(`/courses/${encodeURIComponent(courseId)}/pairs/${encodeURIComponent(pairId)}/visuals`);
export const createVisual = (courseId, messageId, pairId, action, requestId = null) => send(`/courses/${encodeURIComponent(courseId)}/messages/${encodeURIComponent(messageId)}/visuals`, { request_id: requestId || key(), pair_id: pairId, action });
export const getVisualAssistance = (courseId) => request(`/courses/${encodeURIComponent(courseId)}/visual-assistance`);
export const setVisualAssistance = (courseId, enabled) => send(`/courses/${encodeURIComponent(courseId)}/visual-assistance`, { request_id: key(), enabled, consent_version: 'visual-assistance-v1' }, 'PUT');
export const getVisualJob = (jobId) => request(`/visual-jobs/${encodeURIComponent(jobId)}`);
export const cancelVisualJob = (jobId) => send(`/visual-jobs/${encodeURIComponent(jobId)}/cancel`, {});
export const retryVisualJob = (jobId) => send(`/visual-jobs/${encodeURIComponent(jobId)}/retry`, { request_id: key() });
export const fallbackVisualJob = (jobId) => send(`/visual-jobs/${encodeURIComponent(jobId)}/fallback`, { request_id: key() });
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
// Configurable assessment unified flow (fullscreen workspace).
export const getAssessment = (courseId, nodeId) => request(`/courses/${courseId}/knowledge/${nodeId}/assessment`);
export const getAssessmentSetup = (courseId, nodeId, contentLanguage = 'zh-CN') => request(`/courses/${courseId}/knowledge/${nodeId}/assessment/setup?content_language=${encodeURIComponent(contentLanguage)}`);
export const getAssessmentPreparation = (courseId, nodeId, configurationId) => request(`/courses/${courseId}/knowledge/${nodeId}/assessment/prepare/status?configuration_id=${encodeURIComponent(configurationId)}`);
export const startAssessment = (courseId, nodeId, configuration = {}) => send(`/courses/${courseId}/knowledge/${nodeId}/assessment/session`, { ...configuration, request_id: key() });
export const getAssessmentSession = (courseId, sessionId) => request(`/courses/${courseId}/knowledge/assessment/${sessionId}`);
export const submitAssessment = (courseId, sessionId, payload) => send(`/courses/${courseId}/knowledge/assessment/${sessionId}/submit`, { ...payload, request_id: key() });
export const abandonAssessment = (courseId, sessionId) => send(`/courses/${courseId}/knowledge/assessment/${sessionId}/abandon`, { request_id: key() });
export const saveAssessmentDraft = (courseId, sessionId, payload) => send(`/courses/${courseId}/knowledge/assessment/${sessionId}/draft`, { ...payload, request_id: key() });
export const loadAssessmentDraft = (courseId, sessionId) => request(`/courses/${courseId}/knowledge/assessment/${sessionId}/draft`);
export const cancelPreparation = (courseId, nodeId, jobId) => send(`/courses/${courseId}/knowledge/${nodeId}/assessment/prepare/cancel`, { job: jobId, request_id: key() });
export const resumePreparation = (courseId, nodeId) => send(`/courses/${courseId}/knowledge/${nodeId}/assessment/prepare/resume`, { request_id: key() });
export const createAssessmentExplanation = (courseId, sessionId, blueprintItemId, stepId) => send(`/courses/${courseId}/knowledge/assessment/${sessionId}/explain`, { blueprint_item: blueprintItemId, step: stepId, request_id: key() });
// User-initiated feedback reports go to the RAG API host at /api/feedback, a
// sibling of the ui-extension base the rest of this client uses.
export async function submitFeedback(payload) {
    const token = await tokenGetter();
    const headers = { 'Content-Type': 'application/json', ...(token ? { 'Authorization': `Bearer ${token}` } : {}) };
    const response = await fetch('/api/feedback', { method: 'POST', headers, credentials: 'include', cache: 'no-store', body: JSON.stringify(payload) });
    if (!response.ok) {
        let body = null;
        try { body = await response.json(); } catch { /* keep body null */ }
        const nested = body && (body.error || body.detail);
        const rawMessage = typeof nested === 'string' ? nested : (nested && typeof nested === 'object' && nested.message) || '';
        const err = new Error(translatedErrorMessage('HTTP_STATUS', response.status));
        err.status = response.status;
        err.body = body;
        err.rawMessage = rawMessage;
        throw err;
    }
    return response.json();
}
