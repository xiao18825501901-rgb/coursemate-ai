import { useEffect, useMemo, useState } from "react";

import { useCourseMateAuth } from "../auth/AuthProvider";
import { getKnowledgeState } from "../services/learningApi";
import type {
  KnowledgeNodeState,
  KnowledgeSnapshot,
  KnowledgeTree,
  KnowledgeTreeMember,
  PersonalPlanDraft,
} from "../types/learning";

interface KnowledgeTreesProps {
  workspace: string;
  revision: number;
  busy: boolean;
  onCreatePlan: (draft: PersonalPlanDraft) => Promise<void> | void;
  onAssessNode: (nodeId: string) => void;
  onSelectNode: (nodeId: string) => void;
}

function AxisState({
  nodeId,
  onAssessNode,
  onSelectNode,
  state,
  title,
}: {
  nodeId: string;
  onAssessNode: (nodeId: string) => void;
  onSelectNode: (nodeId: string) => void;
  state: KnowledgeNodeState;
  title: string;
}) {
  const assessment = state.assessment.grade_label ?? state.assessment.status;
  return (
    <dl className="knowledge-axes">
      <div><dt>Learning Progress</dt><dd><button aria-label={`Learning Progress ${state.learning.status} for ${title}`} onClick={() => onSelectNode(nodeId)} type="button">{state.learning.status}</button></dd></div>
      <div><dt>Assessment Grade</dt><dd><button aria-label={`Assessment Grade ${assessment} for ${title}`} onClick={() => onAssessNode(nodeId)} type="button">{assessment}</button></dd></div>
    </dl>
  );
}

function TreePanel({
  empty,
  heading,
  tree,
  onAssessNode,
  onSelectNode,
}: {
  empty: string;
  heading: string;
  tree: KnowledgeTree;
  onAssessNode: (nodeId: string) => void;
  onSelectNode: (nodeId: string) => void;
}) {
  const membersById = new Map(tree.members.map((member) => [member.node_id, member]));
  const depthOf = (member: KnowledgeTreeMember) => {
    let depth = 0;
    let parent = member.parent_node_id;
    const seen = new Set([member.node_id]);
    while (parent && membersById.has(parent) && !seen.has(parent) && depth < 12) {
      seen.add(parent);
      parent = membersById.get(parent)?.parent_node_id ?? null;
      depth += 1;
    }
    return depth;
  };
  return (
    <section className="knowledge-tree-card" aria-label={heading}>
      <header>
        <div><h3>{heading}</h3>{tree.title && <p>{tree.title}</p>}</div>
        <span className="knowledge-status">{tree.status}</span>
      </header>
      {tree.members.length === 0 ? <p>{empty}</p> : (
        <ol className="knowledge-tree-list">
          {tree.members.map((member) => (
            <li key={member.node_id} style={{ "--tree-depth": depthOf(member) } as React.CSSProperties}>
              <div>
                <strong>{member.title}</strong>
                <small>{member.kind === "COMPOSITE" ? "知识分组" : `Teaching Spec v${member.spec_version ?? "—"}`} · {member.source === "PRIVATE" ? "仅本人" : "官方规范节点"}</small>
              </div>
              <AxisState
                nodeId={member.node_id}
                onAssessNode={onAssessNode}
                onSelectNode={onSelectNode}
                state={member.state}
                title={member.title}
              />
              <button type="button" onClick={() => onSelectNode(member.node_id)}>在工作区选择 {member.title}</button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function KnowledgeTrees({
  workspace,
  revision,
  busy,
  onCreatePlan,
  onAssessNode,
  onSelectNode,
}: KnowledgeTreesProps) {
  const { getToken } = useCourseMateAuth();
  const [snapshot, setSnapshot] = useState<KnowledgeSnapshot | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const currentSnapshot = snapshot?.workspace_id === workspace ? snapshot : null;

  useEffect(() => {
    setSelected(new Set());
  }, [workspace]);

  useEffect(() => {
    let active = true;
    setError("");
    void getKnowledgeState(getToken, workspace)
      .then((result) => {
        if (result.workspace_id !== workspace) {
          throw new Error("知识树响应与当前工作区不匹配");
        }
        if (active) setSnapshot(result);
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "知识树无法加载");
      });
    return () => { active = false; };
  }, [getToken, revision, workspace]);

  const atomicNodes = useMemo(
    () => currentSnapshot?.registry.filter((node) => node.kind === "ATOMIC") ?? [],
    [currentSnapshot],
  );
  const createPlan = async () => {
    const memberships = atomicNodes
      .filter((node) => selected.has(node.id))
      .map((node, ordinal) => ({ node_id: node.id, parent_node_id: null, ordinal }));
    if (memberships.length === 0) return;
    await onCreatePlan({
      title: "我的学习路径",
      change_reason: "Learner selected an ordered atomic-node plan in the CourseMate UI",
      memberships,
      prerequisites: [],
    });
  };
  const toggle = (nodeId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  };

  return (
    <section className="knowledge-map" aria-labelledby="knowledge-map-title">
      <header className="knowledge-map-heading">
        <div><span className="eyebrow">Shared learning state</span><h2 id="knowledge-map-title">课程知识树</h2></div>
        <p>官方树只显示已审核发布版本；个人树引用相同知识节点，不复制进度或成绩。</p>
      </header>
      {error && <p className="alert alert-error" role="alert">{error}</p>}
      {!currentSnapshot ? <p aria-busy={!error}>{error ? "请稍后重试。" : "正在读取知识树…"}</p> : <>
        <div className="knowledge-tree-grid">
          <TreePanel
            empty="尚无已审核发布的官方树"
            heading="官方课程树"
            onAssessNode={onAssessNode}
            onSelectNode={onSelectNode}
            tree={currentSnapshot.official_tree}
          />
          <TreePanel
            empty="尚未建立个人学习树"
            heading="我的个性化树"
            onAssessNode={onAssessNode}
            onSelectNode={onSelectNode}
            tree={currentSnapshot.personalized_tree}
          />
        </div>
        <details className="personal-plan-builder">
          <summary>建立或更新个人学习树</summary>
          <p>当前界面按所选原子节点建立平铺顺序；不会发布或改写官方树。</p>
          <fieldset>
            <legend>选择知识节点</legend>
            {atomicNodes.map((node) => (
              <div key={node.id} className="knowledge-plan-option">
                <label>
                  <input
                    aria-label={`选择 ${node.title}`}
                    checked={selected.has(node.id)}
                    disabled={busy}
                    onChange={() => toggle(node.id)}
                    type="checkbox"
                  />
                  <span><strong>{node.title}</strong><small>{node.source === "PRIVATE" ? "仅本人" : "官方规范节点"}</small></span>
                </label>
                <AxisState
                  nodeId={node.id}
                  onAssessNode={onAssessNode}
                  onSelectNode={onSelectNode}
                  state={node.state}
                  title={node.title}
                />
                <button type="button" onClick={() => onSelectNode(node.id)}>在工作区选择 {node.title}</button>
              </div>
            ))}
          </fieldset>
          <button disabled={busy || selected.size === 0} onClick={() => void createPlan()} type="button">建立个人学习树</button>
        </details>
      </>}
    </section>
  );
}
