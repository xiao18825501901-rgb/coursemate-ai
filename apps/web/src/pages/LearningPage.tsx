import { type CSSProperties, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useCourseMateAuth } from "../auth/AuthProvider";
import { LearningFiles } from "../components/LearningFiles";
import { getLearningState, joinLearning, learningAction } from "../services/learningApi";
import type { LearningState, LayoutPreference, Major, Mode } from "../types/learning";
import "./learning.css";

export function LearningPage() {
  const { courseId = "" } = useParams();
  const { getToken } = useCourseMateAuth();
  const [state, setState] = useState<LearningState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [nodeId, setNodeId] = useState("");
  const [title, setTitle] = useState("");
  const [major, setMajor] = useState<Major>("CS");
  const [question, setQuestion] = useState("");
  const [preference, setPreference] = useState("");
  const [layout, setLayout] = useState<LayoutPreference>({ orientation: "columns", swapped: false, ratio: 50 });
  const [mode, setMode] = useState<Mode>("AUTO");
  useEffect(() => {
    let active = true; setState(null); setError(""); setNodeId(""); setQuestion("");
    void joinLearning(getToken, courseId).then(w => getLearningState(getToken, w.id)).then(s => {
      if (!active) return;
      setState(s); setNodeId(s.cursor.node_id ?? s.nodes[0]?.id ?? "");
      setQuestion(s.solutions.find(p => !p.status)?.question ?? ""); setMode(s.mode);
      setLayout({ orientation: "columns", swapped: false, ratio: 50, ...s.layout });
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "工作区无法加载"); });
    return () => { active = false; };
  }, [courseId, getToken]);
  useEffect(() => {
    if (state?.cursor.pane === "PROBLEM" && state.cursor.step_id) {
      document.getElementById(`step-${state.cursor.step_id}`)?.focus({ preventScroll: false });
    }
  }, [state]);
  async function refresh() {
    if (state) { const next = await getLearningState(getToken, state.id); setState(next); return next; }
  }
  async function action(path: string, payload: object = {}, method = "POST") {
    if (!state || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    try {
      await learningAction(getToken, state.id, path,
        path === "nodes" ? payload : { operation_id: crypto.randomUUID(), revision: state.revision, ...payload }, method);
      const next = await refresh();
      if (path === "nodes") setNodeId(next?.nodes.at(-1)?.id ?? "");
      if (path === "bridges") setNodeId(next?.cursor.node_id ?? nodeId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作未完成；请读取已保存状态，不要重复生成。");
      await refresh().catch(() => undefined);
    } finally { lock.current = false; setBusy(false); }
  }
  const node = state?.nodes.find(n => n.id === nodeId);
  const solution = state?.solutions.find(s => s.id === state.cursor.solution_id) ?? state?.solutions[0];
  const bridge = state?.bridges.find(b => b.id === state.cursor.bridge_id);
  const unit = state?.units.find(u => u.id === state.cursor.unit_id) ?? state?.units[0];
  const createNode = () => action("nodes", { title, description: title, major, kind: "ATOMIC", items: [
    { item_id: "principle", requirement: "REQUIRED", objective: `解释 ${title} 的原理并应用到当前题`,
      acceptance: "保存完整原理解释、具体例子与当前题 Step 应用；仅标题不能计覆盖", evidence_ids: [] },
  ] });
  return <div className="page learning-page">
    <header className="page-intro"><span className="eyebrow">CourseMate V3 · 内测</span><h1>协同学习工作区</h1>
      <p>教学与题目共享学习进度。完成必需教学即可 LEARNED；成绩独立记录。</p>
      <Link to={`/qa/${courseId}`}>旧版问答与历史</Link> · <Link to={`/courses/${courseId}/settings`}>课程教学偏好</Link>
    </header>
    {error && <p className="alert alert-error" role="alert">{error} <button onClick={() => void refresh().catch(e => setError(String(e)))}>读取保存状态</button></p>}
    {!state ? <p aria-busy={!error}>{error ? "请检查登录和 V3 后端开关。" : "正在恢复课程学习状态…"}</p> : <>
      <div className="learning-toolbar">
        <label>当前知识节点 <select value={nodeId} onChange={e => setNodeId(e.target.value)}><option value="">选择知识节点</option>{state.nodes.map(n => <option key={n.id} value={n.id}>{n.title} {n.status === "PRIVATE" ? "[My Files / 私人]" : ""}</option>)}</select></label>
        <span>Learning Progress：<strong>{node?.progress ?? "NOT_STARTED"}</strong></span><span>Assessment Grade：NOT_ASSESSED</span>
        <label>模式偏好 <select value={mode} onChange={e => setMode(e.target.value as Mode)}><option>AUTO</option><option>TEACHING</option><option>PROBLEM</option></select></label>
        <label>窗格布局 <select value={layout.orientation} onChange={e => setLayout({ ...layout, orientation: e.target.value as "columns" | "rows" })}><option value="columns">左右</option><option value="rows">上下</option></select></label>
        <label>教学窗格比例 <input type="range" min={30} max={70} value={layout.ratio} onChange={e => setLayout({ ...layout, ratio: Number(e.target.value) })} /></label>
        <button onClick={() => setLayout({ ...layout, swapped: !layout.swapped })}>交换窗格</button>
        <button onClick={() => setLayout({ orientation: "columns", swapped: false, ratio: 50 })}>恢复默认布局</button>
        <button disabled={busy} onClick={() => void action("preferences", { mode, layout }, "PATCH")}>保存布局和偏好</button>
      </div>
      <details><summary>建立私人知识教学范围（不发布官方树）</summary>
        <p>当前内测支持手动建立一个原子教学范围；这不是已审核的官方 Teaching Spec。</p>
        <label>新私人知识节点 <input value={title} onChange={e => setTitle(e.target.value)} maxLength={150} /></label>
        <label>专业策略 <select value={major} onChange={e => setMajor(e.target.value as Major)}><option value="CS">计算机科学</option><option value="SMART_MANUFACTURING">智能制造</option><option value="MATERIALS">材料科学</option><option value="ENERGY">能源</option></select></label>
        <button disabled={busy || !title.trim()} onClick={() => void createNode()}>建立私人教学范围</button>
      </details>
      <LearningFiles workspace={state.id} />
      <p role="status">{busy ? "正在执行一个有界操作。刷新后请读取保存状态，不会自动重新调用模型。" : `已恢复 · 状态版本 ${state.revision}`}</p>
      <div className={`learning-panes ${layout.orientation} ${layout.swapped ? "swapped" : ""}`} style={{ "--teaching-ratio": `${layout.ratio}%` } as CSSProperties}>
        <section className="teaching-pane learning-pane" aria-label="知识教学"><h2>知识教学</h2>
          {bridge?.problem_snapshot && <aside><h3>原题条件</h3><p>{bridge.problem_snapshot.question}</p><p>{bridge.problem_snapshot.conditions.join("；")}</p><p>Step {bridge.problem_snapshot.step.ordinal}：{bridge.problem_snapshot.step.operation}</p></aside>}
          <label>本单元学习方式（可选） <textarea value={preference} onChange={e => setPreference(e.target.value)} maxLength={2000} placeholder="例如：先直觉，后公式，用中文逐步讲解" /></label>
          <button disabled={busy || !nodeId} onClick={() => void action("units", { node_id: nodeId, bridge_id: bridge?.node_id === nodeId ? bridge.id : null, preference })}>继续一个教学单元</button>
          {unit?.sections?.map(s => <article key={s.section_id}><h3>{s.title}</h3><p className="learning-prose">{s.content}</p></article>)}
          {unit?.status === "SOURCE_UNAVAILABLE" && <p>原教学来源已不可用。</p>}
          {!unit && <p>选择知识节点开始，或点击题目 Step 下的知识问题。</p>}
          {bridge?.return_anchor && <button disabled={busy} onClick={() => void action(`bridges/${bridge.id}/return`)}>返回原题原 Step</button>}
        </section>
        <section className="problem-pane learning-pane" aria-label="题目应对"><h2>题目应对</h2>
          <label>题目内容 <textarea rows={5} value={question} onChange={e => setQuestion(e.target.value)} maxLength={6000} /></label>
          <button disabled={busy || !nodeId || !question.trim()} onClick={() => void action("solutions", { question, node_ids: [nodeId] })}>获取完整解答</button>
          <p>默认直接给完整答案；会记录 ANSWER_EXPOSED，不当作独立测评成绩。</p>
          {solution?.exam_answer && <><h3>完整答题版本</h3><p className="learning-prose">{solution.exam_answer}</p><small>{solution.answer_origin} · 尚未独立验证</small></>}
          {solution?.steps?.map(step => <article className="solution-step" id={`step-${step.id}`} key={step.id} tabIndex={-1}>
            <h3>Step {step.ordinal} · {step.operation}</h3><p>{step.explanation}</p><p>结果：{step.result}</p>
            {step.knowledge_links.map(k => <button key={k.node_id} disabled={busy} onClick={() => void action("bridges", { step_id: step.id, node_id: k.node_id })}>{k.question_text}</button>)}
          </article>)}
          {solution?.status === "SOURCE_UNAVAILABLE" && <p>题目来源已不可用；不能恢复失效内容。</p>}
        </section>
      </div>
      <details><summary>操作记录（重连不重复执行）</summary><ul>{state.operations.map(o => <li key={o.id}>{o.kind} · {o.status} · {o.id}</li>)}</ul></details>
    </>}
  </div>;
}
