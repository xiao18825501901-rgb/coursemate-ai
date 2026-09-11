import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TestAuthProvider } from "../auth/AuthProvider";
import { getKnowledgeState } from "../services/learningApi";
import type { KnowledgeSnapshot, PersonalPlanDraft } from "../types/learning";
import { KnowledgeTrees } from "./KnowledgeTrees";

vi.mock("../services/learningApi", () => ({
  getKnowledgeState: vi.fn(),
}));

const notAssessed = {
  status: "NOT_ASSESSED" as const,
  raw_score: null,
  grade_label: null,
};

const snapshot: KnowledgeSnapshot = {
  workspace_id: "workspace-1",
  course_id: "cs3481",
  revision: 3,
  selected_tree: "NONE",
  official_tree: {
    status: "NO_REVIEWED_TREE",
    members: [],
    prerequisites: [],
  },
  personalized_tree: {
    status: "NOT_CREATED",
    members: [],
    prerequisites: [],
  },
  registry: [
    {
      id: "canonical-node",
      title: "Rasterization",
      description: "Canonical rasterization node",
      major: "CS",
      kind: "ATOMIC",
      status: "PUBLISHED",
      source: "CANONICAL",
      aliases: [],
      state: {
        learning: {
          status: "LEARNED",
          spec_version: 2,
          required_total: 2,
          covered_required: 2,
          historical_learned_spec_versions: [1],
        },
        assessment: notAssessed,
      },
    },
    {
      id: "private-node",
      title: "My clipping notes",
      description: "Private scope",
      major: "CS",
      kind: "ATOMIC",
      status: "PRIVATE",
      source: "PRIVATE",
      aliases: [],
      state: {
        learning: {
          status: "NOT_STARTED",
          spec_version: 1,
          required_total: 1,
          covered_required: 0,
          historical_learned_spec_versions: [],
        },
        assessment: notAssessed,
      },
    },
  ],
};

describe("KnowledgeTrees", () => {
  beforeEach(() => {
    vi.mocked(getKnowledgeState).mockResolvedValue(snapshot);
  });

  it("keeps reviewed official and private personalized tree truth explicit", async () => {
    render(
      <TestAuthProvider token="token-a">
        <KnowledgeTrees
          busy={false}
          onCreatePlan={vi.fn()}
          onSelectNode={vi.fn()}
          revision={3}
          workspace="workspace-1"
        />
      </TestAuthProvider>,
    );

    expect(await screen.findByRole("heading", { name: "课程知识树" })).toBeVisible();
    expect(screen.getByText("尚无已审核发布的官方树")).toBeVisible();
    expect(screen.getByText("尚未建立个人学习树")).toBeVisible();
    fireEvent.click(screen.getByText("建立或更新个人学习树"));
    expect(screen.getByText("LEARNED")).toBeVisible();
    expect(screen.getAllByText("NOT_ASSESSED").length).toBeGreaterThan(0);
    expect(screen.getByText("官方规范节点")).toBeVisible();
    expect(screen.getByText("仅本人")).toBeVisible();
    expect(screen.queryByRole("button", { name: /发布官方树/ })).not.toBeInTheDocument();
  });

  it("builds an ordered personal plan from explicitly selected atomic nodes", async () => {
    const onCreatePlan = vi.fn<(draft: PersonalPlanDraft) => Promise<void>>()
      .mockResolvedValue(undefined);
    const onSelectNode = vi.fn();
    render(
      <TestAuthProvider token="token-a">
        <KnowledgeTrees
          busy={false}
          onCreatePlan={onCreatePlan}
          onSelectNode={onSelectNode}
          revision={3}
          workspace="workspace-1"
        />
      </TestAuthProvider>,
    );

    fireEvent.click(await screen.findByLabelText("选择 Rasterization"));
    fireEvent.click(screen.getByLabelText("选择 My clipping notes"));
    fireEvent.click(screen.getByRole("button", { name: "建立个人学习树" }));

    await waitFor(() => expect(onCreatePlan).toHaveBeenCalledWith({
      title: "我的学习路径",
      change_reason: "Learner selected an ordered atomic-node plan in the CourseMate UI",
      memberships: [
        { node_id: "canonical-node", parent_node_id: null, ordinal: 0 },
        { node_id: "private-node", parent_node_id: null, ordinal: 1 },
      ],
      prerequisites: [],
    }));
    fireEvent.click(screen.getByRole("button", { name: "在工作区选择 Rasterization" }));
    expect(onSelectNode).toHaveBeenCalledWith("canonical-node");
  });

  it("does not retain private registry content while switching workspaces", async () => {
    vi.mocked(getKnowledgeState).mockImplementation((_getToken, workspace) => (
      workspace === "workspace-1"
        ? Promise.resolve(snapshot)
        : new Promise<KnowledgeSnapshot>(() => undefined)
    ));
    const props = {
      busy: false,
      onCreatePlan: vi.fn(),
      onSelectNode: vi.fn(),
      revision: 3,
    };
    const view = render(
      <TestAuthProvider token="token-a">
        <KnowledgeTrees {...props} workspace="workspace-1" />
      </TestAuthProvider>,
    );
    expect(await screen.findByText("My clipping notes")).toBeInTheDocument();

    view.rerender(
      <TestAuthProvider token="token-a">
        <KnowledgeTrees {...props} workspace="workspace-2" />
      </TestAuthProvider>,
    );

    expect(screen.queryByText("My clipping notes")).not.toBeInTheDocument();
    expect(screen.getByText("正在读取知识树…")).toBeVisible();
  });
});
