export type Major = "CS" | "SMART_MANUFACTURING" | "MATERIALS" | "ENERGY";
export type Mode = "AUTO" | "TEACHING" | "PROBLEM";
export interface LearningNode { id: string; title: string; status: string; progress: string; major: Major }
export interface KnowledgeLink { node_id: string; question_text: string; reason: string }
export interface SolutionStep { id: string; ordinal: number; operation: string; result: string; explanation: string; knowledge_links: KnowledgeLink[] }
export interface Solution { id: string; status?: string; question: string; exam_answer: string; steps: SolutionStep[]; answer_origin: string; assumptions: string[] }
export interface Bridge { id: string; status: string; node_id: string; return_anchor: string; problem_snapshot: { question: string; conditions: string[]; step: SolutionStep } }
export interface Unit { id: string; status?: string; sections: { section_id: string; title: string; content: string }[]; uncertainties: string[] }
export interface LayoutPreference { orientation: "columns" | "rows"; swapped: boolean; ratio: number }
export interface LearningState {
  id: string; course_id: string; revision: number; mode: Mode; layout: Partial<LayoutPreference>;
  cursor: { node_id?: string; step_id?: string; solution_id?: string; unit_id?: string; bridge_id?: string; pane?: string };
  nodes: LearningNode[]; solutions: Solution[]; bridges: Bridge[]; units: Unit[];
  operations: { id: string; kind: string; status: string }[];
}
