import { type CSSProperties, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useCourseMateAuth } from "../auth/AuthProvider";
import { KnowledgeTrees } from "../components/KnowledgeTrees";
import { LearningFiles } from "../components/LearningFiles";
import {
  getLearningState,
  joinLearning,
  learningAction,
  listLearningDocuments,
  listProblemIndex,
} from "../services/learningApi";
import type {
  LearningDocumentSource,
  LearningState,
  LayoutPreference,
  Major,
  Mode,
  PersonalPlanDraft,
  ProblemSource,
} from "../types/learning";
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
  const [problemInput, setProblemInput] = useState<"TEXT" | "INDEXED" | "IMAGE">("TEXT");
  const [problemSearch, setProblemSearch] = useState("");
  const [problemIndex, setProblemIndex] = useState<ProblemSource[]>([]);
  const [selectedProblem, setSelectedProblem] = useState("");
  const [imageSources, setImageSources] = useState<LearningDocumentSource[]>([]);
  const [selectedImage, setSelectedImage] = useState("");
  const [transcriptionHint, setTranscriptionHint] = useState("");
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
    const workspace = state?.id;
    if (!workspace) return;
    let active = true;
    void Promise.all([
      listProblemIndex(getToken, workspace),
      listLearningDocuments(getToken, workspace),
    ]).then(([indexed, documents]) => {
      if (!active) return;
      setProblemIndex(indexed.items);
      setImageSources(
        documents.data.filter(file => [".png", ".jpg", ".jpeg"].includes(file.extension) && !!file.version_id),
      );
    }).catch(e => { if (active) setError(e instanceof Error ? e.message : "题目来源加载失败"); });
    return () => { active = false; };
  }, [state?.id, getToken]);
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
  async function searchProblems() {
    if (!state || busy) return;
    setBusy(true); setError("");
    try {
      const result = await listProblemIndex(getToken, state.id, problemSearch);
      setProblemIndex(result.items);
      if (selectedProblem && !result.items.some(item => item.id === selectedProblem)) {
        setSelectedProblem("");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "结构化题目索引查询失败");
    } finally { setBusy(false); }
  }
  async function refreshProblemSources() {
    if (!state) return;
    try {
      const [indexed, documents] = await Promise.all([
        listProblemIndex(getToken, state.id),
        listLearningDocuments(getToken, state.id),
      ]);
      setProblemIndex(indexed.items);
      setImageSources(
        documents.data.filter(file => [".png", ".jpg", ".jpeg"].includes(file.extension) && !!file.version_id),
      );
      setSelectedProblem(current => current && indexed.items.some(item => item.id === current) ? current : "");
      setSelectedImage(current => current && documents.data.some(file => file.version_id === current) ? current : "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "题目来源刷新失败");
    }
  }
  function solveProblem() {
    if (!nodeId) return;
    if (problemInput === "INDEXED") {
      if (selectedProblem) void action("solutions", { problem_index_entry_id: selectedProblem, node_ids: [nodeId] });
      return;
    }
    if (problemInput === "IMAGE") {
      if (selectedImage) void action("solutions", {
        question: question.trim() || "请转录并完整解答图片中的题目。",
        image_document_version_id: selectedImage,
        transcription_hint: transcriptionHint.trim() || undefined,
        node_ids: [nodeId],
      });
      return;
    }
    if (question.trim()) void action("solutions", { question, node_ids: [nodeId] });
  }
  const node = state?.nodes.find(n => n.id === nodeId);
  const solution = state?.solutions.find(s => s.id === state.cursor.solution_id) ?? state?.solutions[0];
  const bridge = state?.bridges.find(b => b.id === state.cursor.bridge_id);
  const unit = state?.units.find(u => u.id === state.cursor.unit_id) ?? state?.units[0];
  const indexedProblem = problemIndex.find(item => item.id === selectedProblem);
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
        <span>Learning Progress：<strong>{node?.progress ?? "NOT_STARTED"}</strong></span><span>Assessment Grade：{node?.assessment?.grade_label ?? node?.assessment?.status ?? "NOT_ASSESSED"}</span>
        <label>模式偏好 <select value={mode} onChange={e => setMode(e.target.value as Mode)}><option>AUTO</option><option>TEACHING</option><option>PROBLEM</option></select></label>
        <label>窗格布局 <select value={layout.orientation} onChange={e => setLayout({ ...layout, orientation: e.target.value as "columns" | "rows" })}><option value="columns">左右</option><option value="rows">上下</option></select></label>
        <label>教学窗格比例 <input type="range" min={30} max={70} value={layout.ratio} onChange={e => setLayout({ ...layout, ratio: Number(e.target.value) })} /></label>
        <button onClick={() => setLayout({ ...layout, swapped: !layout.swapped })}>交换窗格</button>
        <button onClick={() => setLayout({ orientation: "columns", swapped: false, ratio: 50 })}>恢复默认布局</button>
        <button disabled={busy} onClick={() => void action("preferences", { mode, layout }, "PATCH")}>保存布局和偏好</button>
      </div>
      <KnowledgeTrees
        busy={busy}
        onCreatePlan={(draft: PersonalPlanDraft) => action("plans", draft)}
        onSelectNode={setNodeId}
        revision={state.revision}
        workspace={state.id}
      />
      <details><summary>建立私人知识教学范围（不发布官方树）</summary>
        <p>当前内测支持手动建立一个原子教学范围；这不是已审核的官方 Teaching Spec。</p>
        <label>新私人知识节点 <input value={title} onChange={e => setTitle(e.target.value)} maxLength={150} /></label>
        <label>专业策略 <select value={major} onChange={e => setMajor(e.target.value as Major)}><option value="CS">计算机科学</option><option value="SMART_MANUFACTURING">智能制造</option><option value="MATERIALS">材料科学</option><option value="ENERGY">能源</option></select></label>
        <button disabled={busy || !title.trim()} onClick={() => void createNode()}>建立私人教学范围</button>
      </details>
      <LearningFiles workspace={state.id} onDocumentsChanged={refreshProblemSources} />
      <p role="status">{busy ? "正在执行一个有界操作。刷新后请读取保存状态，不会自动重新调用模型。" : `已恢复 · 状态版本 ${state.revision}`}</p>
      <div className={`learning-panes ${layout.orientation} ${layout.swapped ? "swapped" : ""}`} style={{ "--teaching-ratio": `${layout.ratio}%` } as CSSProperties}>
        <section className="teaching-pane learning-pane" aria-label="知识教学"><h2>知识教学</h2>
          {bridge?.problem_snapshot && <aside><h3>原题条件</h3><p>{bridge.problem_snapshot.question}</p><p>{bridge.problem_snapshot.conditions.join("；")}</p><p>Step {bridge.problem_snapshot.step.ordinal}：{bridge.problem_snapshot.step.operation}</p></aside>}
          <label>本单元学习方式（可选） <textarea value={preference} onChange={e => setPreference(e.target.value)} maxLength={2000} placeholder="例如：先直觉，后公式，用中文逐步讲解" /></label>
          <div className="teaching-actions">
            <button disabled={busy || !nodeId} onClick={() => void action("units", { node_id: nodeId, bridge_id: bridge?.node_id === nodeId ? bridge.id : null, preference })}>继续一个教学单元</button>
            <button disabled={busy || !nodeId} onClick={() => void action("units", { node_id: nodeId, bridge_id: bridge?.node_id === nodeId ? bridge.id : null, preference, replan: true })}>按当前偏好重新规划</button>
          </div>
          <small>普通继续会复用有效计划；明确重新规划会新增一次 Planner 模型调用。</small>
          {unit?.plan_version && <p className="plan-status">Teaching Plan v{unit.plan_version} · {unit.plan_reused ? "已复用" : "本次新建"} · {unit.plan_unit_key}</p>}
          {unit?.sections?.map(s => <article key={s.section_id}><h3>{s.title}</h3><p className="learning-prose">{s.content}</p></article>)}
          {!!unit?.comprehension_checks?.length && <section className="comprehension-checks" aria-label="理解检查">
            <h3>理解检查（不影响 LEARNED）</h3>
            <ol>{unit.comprehension_checks.map(check => <li key={check.check_id}>
              {unit.display?.question_prefix && <span className="question-prefix">{unit.display.question_prefix} </span>}{check.prompt}
            </li>)}</ol>
          </section>}
          {unit?.status === "SOURCE_UNAVAILABLE" && <p>原教学来源已不可用。</p>}
          {!unit && <p>选择知识节点开始，或点击题目 Step 下的知识问题。</p>}
          {bridge?.return_anchor && <button disabled={busy} onClick={() => void action(`bridges/${bridge.id}/return`)}>返回原题原 Step</button>}
        </section>
        <section className="problem-pane learning-pane" aria-label="题目应对"><h2>题目应对</h2>
          <fieldset className="problem-source-picker">
            <legend>题目来源</legend>
            <label><input type="radio" name="problem-input" checked={problemInput === "TEXT"} onChange={() => setProblemInput("TEXT")} /> 文字题</label>
            <label><input type="radio" name="problem-input" checked={problemInput === "INDEXED"} onChange={() => setProblemInput("INDEXED")} /> 文件题号</label>
            <label><input type="radio" name="problem-input" checked={problemInput === "IMAGE"} onChange={() => setProblemInput("IMAGE")} /> 私人题目图片</label>
          </fieldset>
          {problemInput === "TEXT" && <label>题目内容 <textarea rows={5} value={question} onChange={e => setQuestion(e.target.value)} maxLength={6000} /></label>}
          {problemInput === "INDEXED" && <div className="problem-index-picker">
            <label>搜索已导入题干 <input value={problemSearch} onChange={e => setProblemSearch(e.target.value)} maxLength={500} placeholder="文件名以外的题干关键词" /></label>
            <button type="button" disabled={busy} onClick={() => void searchProblems()}>查询题目索引</button>
            <label>精确题目版本 <select value={selectedProblem} onChange={e => setSelectedProblem(e.target.value)}>
              <option value="">选择文件与题号</option>
              {problemIndex.map(item => <option key={item.id} value={item.id}>{item.filename} · Q{item.question_number}{item.question_part ? `(${item.question_part})` : ""} · {item.locator_type} {item.locator_value}</option>)}
            </select></label>
            {indexedProblem && <blockquote><strong>{indexedProblem.heading_path ?? `Question ${indexedProblem.question_number}`}</strong><p>{indexedProblem.question_text}</p><small>固定来源版本 {indexedProblem.document_sha256.slice(0, 12)}…</small></blockquote>}
            {!problemIndex.length && <p>当前授权资料尚无可定位题号；请导入带明确 Question/Q/题号结构的文件。</p>}
          </div>}
          {problemInput === "IMAGE" && <div className="problem-image-picker">
            <label>已授权 PNG/JPEG <select value={selectedImage} onChange={e => setSelectedImage(e.target.value)}>
              <option value="">选择题目图片</option>
              {imageSources.map(file => <option key={file.version_id} value={file.version_id}>{file.filename} · v{file.version_number ?? 1} · {file.source_scope === "WORKSPACE_PRIVATE" ? "仅本人" : "课程资料"}</option>)}
            </select></label>
            <label>给转录的提示（可选，不视为已核验题干） <textarea rows={2} value={transcriptionHint} onChange={e => setTranscriptionHint(e.target.value)} maxLength={6000} /></label>
            <label>解题要求 <textarea rows={3} value={question} onChange={e => setQuestion(e.target.value)} maxLength={6000} placeholder="例如：解答这张图中的第 2 小问" /></label>
            {!imageSources.length && <p>先在上方“课程文件与我的私人资料”上传 PNG/JPEG；上传完成后此列表会自动刷新。</p>}
          </div>}
          <button disabled={busy || !nodeId || (problemInput === "TEXT" && !question.trim()) || (problemInput === "INDEXED" && !selectedProblem) || (problemInput === "IMAGE" && !selectedImage)} onClick={solveProblem}>获取完整参考解答</button>
          <p>默认直接给完整答案并记录 ANSWER_EXPOSED；它不是独立测评，也不会写入成绩。</p>
          {solution?.question_transcription && <section className="problem-transcription"><h3>图片题干转录</h3><p>{solution.question_transcription}</p><small>模型转录，需结合下方不确定标记核对原图。</small></section>}
          {!!solution?.visual_uncertainties?.length && <section className="problem-uncertainties" role="status"><h3>图像不确定性</h3><ul>{solution.visual_uncertainties.map(item => <li key={item}>{item}</li>)}</ul></section>}
          {solution?.exam_answer && <><h3>完整参考答题版本</h3><p className="learning-prose">{solution.exam_answer}</p><small>答案来源：{solution.answer_origin} · {solution.verification}</small></>}
          {!!solution?.conditions?.length && <details><summary>题意与已知条件</summary><ul>{solution.conditions.map(item => <li key={item}>{item}</li>)}</ul></details>}
          {solution?.steps?.map(step => <article className="solution-step" id={`step-${step.id}`} key={step.id} tabIndex={-1}>
            <h3>Step {step.ordinal} · {step.operation}</h3><p>{step.explanation}</p><p>结果：{step.result}</p>
            {!!step.formulae?.length && <p>公式 / 计算：{step.formulae.join("；")}</p>}
            {!!step.units?.length && <p>单位：{step.units.join("；")}</p>}
            {step.check && <p>检查：{step.check}</p>}
            <div className="step-knowledge-links">{step.knowledge_links.map(k => k.resolution_status !== "UNRESOLVED" && k.node_id
              ? <button key={k.id} disabled={busy} onClick={() => void action("bridges", { step_id: step.id, knowledge_link_id: k.id })}>{k.question_text}</button>
              : <span className="unresolved-link" key={k.id}>{k.question_text} · 待解析：{k.unresolved_reason}</span>)}</div>
          </article>)}
          {!!solution?.common_mistakes?.length && <details><summary>常见错点</summary><ul>{solution.common_mistakes.map(item => <li key={item}>{item}</li>)}</ul></details>}
          {!!solution?.sources?.length && <details><summary>资料引用</summary><ul>{solution.sources.map(source => <li key={source.id}>Source {source.id} · {source.locator_type} {source.locator_value} · Version {source.document_version_id}</li>)}</ul></details>}
          {solution?.status === "SOURCE_UNAVAILABLE" && <p>题目来源已不可用；不能恢复失效内容。</p>}
        </section>
      </div>
      <details><summary>操作记录（重连不重复执行）</summary><ul>{state.operations.map(o => <li key={o.id}>{o.kind} · {o.status} · {o.id}</li>)}</ul></details>
    </>}
  </div>;
}
