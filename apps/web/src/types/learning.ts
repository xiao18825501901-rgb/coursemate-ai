export type Major = "CS" | "SMART_MANUFACTURING" | "MATERIALS" | "ENERGY";
export type Mode = "AUTO" | "TEACHING" | "PROBLEM";
export type KnowledgeNodeKind = "ATOMIC" | "COMPOSITE";
export type KnowledgeSource = "CANONICAL" | "PRIVATE";
export type LearningProgressStatus = "NOT_STARTED" | "LEARNING" | "LEARNED" | "SPEC_UNAVAILABLE";
export interface LearningProgress {
  status: LearningProgressStatus;
  spec_version: number | null;
  required_total: number;
  covered_required: number;
  atomic_descendant_count?: number;
  historical_learned_spec_versions: number[];
}
export interface AssessmentState {
  status: "NOT_ASSESSED" | "IN_PROGRESS" | "GRADED" | "UNCONFIGURED";
  raw_score: number | null;
  grade_label: string | null;
}
export interface KnowledgeNodeState { learning: LearningProgress; assessment: AssessmentState }
export interface LearningNode {
  id: string;
  title: string;
  description: string;
  status: string;
  progress: LearningProgressStatus;
  major: Major;
  kind: KnowledgeNodeKind;
  source: KnowledgeSource;
  learning: LearningProgress;
  assessment: AssessmentState;
}
export interface KnowledgeLink { node_id: string; question_text: string; reason: string }
export interface SolutionStep { id: string; ordinal: number; operation: string; result: string; explanation: string; knowledge_links: KnowledgeLink[] }
export interface Solution { id: string; status?: string; question: string; exam_answer: string; steps: SolutionStep[]; answer_origin: string; assumptions: string[] }
export interface Bridge { id: string; status: string; node_id: string; return_anchor: string; problem_snapshot: { question: string; conditions: string[]; step: SolutionStep } }
export interface ComprehensionCheck {
  check_id: string;
  kind: "DEFINITION" | "DISTINCTION" | "ENGLISH" | "APPLICATION" | "SYNTHESIS";
  prompt: string;
}
export interface Unit {
  id: string;
  status?: string;
  sections: { section_id: string; title: string; content: string }[];
  uncertainties: string[];
  comprehension_checks?: ComprehensionCheck[];
  display?: { question_prefix: string | null };
  plan_version?: number;
  plan_unit_key?: string;
  plan_reused?: boolean;
}
export interface LayoutPreference { orientation: "columns" | "rows"; swapped: boolean; ratio: number }
export interface KnowledgeRegistryNode {
  id: string;
  title: string;
  description: string;
  major: Major;
  kind: KnowledgeNodeKind;
  status: string;
  source: KnowledgeSource;
  aliases: string[];
  state: KnowledgeNodeState;
}
export interface KnowledgeTreeMember {
  node_id: string;
  parent_node_id: string | null;
  ordinal: number;
  spec_version: number | null;
  title: string;
  description: string;
  major: Major;
  kind: KnowledgeNodeKind;
  source: KnowledgeSource;
  state: KnowledgeNodeState;
}
export interface KnowledgeTree {
  id?: string;
  kind?: "OFFICIAL" | "PERSONALIZED";
  status: "NO_REVIEWED_TREE" | "NOT_CREATED" | "PUBLISHED" | "ACTIVE";
  version?: number;
  title?: string;
  change_reason?: string;
  base_tree_version_id?: string | null;
  members: KnowledgeTreeMember[];
  prerequisites: { node_id: string; prerequisite_node_id: string }[];
}
export interface KnowledgeSnapshot {
  workspace_id: string;
  course_id: string;
  revision: number;
  selected_tree: "NONE" | "OFFICIAL" | "PERSONALIZED";
  official_tree: KnowledgeTree;
  personalized_tree: KnowledgeTree;
  registry: KnowledgeRegistryNode[];
}
export interface PersonalPlanDraft {
  title: string;
  change_reason: string;
  memberships: {
    node_id: string;
    parent_node_id: string | null;
    ordinal: number;
    spec_version?: number;
  }[];
  prerequisites: { node_id: string; prerequisite_node_id: string }[];
}
export interface LearningState {
  id: string; course_id: string; revision: number; mode: Mode; layout: Partial<LayoutPreference>;
  cursor: { node_id?: string; step_id?: string; solution_id?: string; unit_id?: string; bridge_id?: string; pane?: string };
  nodes: LearningNode[]; solutions: Solution[]; bridges: Bridge[]; units: Unit[];
  operations: { id: string; kind: string; status: string }[];
}
