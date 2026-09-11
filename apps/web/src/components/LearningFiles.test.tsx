import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TestAuthProvider } from "../auth/AuthProvider";
import { authenticatedFetch, requestJson, requireOk } from "../services/http";
import { LearningFiles } from "./LearningFiles";

vi.mock("../services/http", () => ({
  authenticatedFetch: vi.fn(),
  requestJson: vi.fn(),
  requireOk: vi.fn(),
}));

const csvFile = {
  id: "doc-csv",
  filename: "scores.csv",
  extension: ".csv",
  byte_size: 1024,
  status: "ready",
  source_scope: "WORKSPACE_PRIVATE",
  access_scope: "OWNER_PRIVATE",
  version_id: "doc-csv-v1",
  version_number: 1,
  preview: { kind: "TABLE_PREVIEW", available: true, reason: null },
};

describe("LearningFiles", () => {
  beforeEach(() => {
    vi.mocked(requestJson).mockResolvedValue({
      data: [
        csvFile,
        {
          ...csvFile,
          id: "doc-office",
          filename: "legacy.doc",
          extension: ".doc",
          version_id: "doc-office-v1",
          preview: {
            kind: "DOWNLOAD_ONLY",
            available: false,
            reason: "CONTROLLED_CONVERTER_NOT_CONFIGURED",
          },
        },
      ],
    });
    vi.mocked(requireOk).mockImplementation(async (response) => response);
    vi.mocked(authenticatedFetch).mockImplementation(async (_getToken, url) => {
      if (url.endsWith("/document-versions/doc-csv-v1/preview")) {
        return new Response(
          JSON.stringify({
            kind: "TABLE_PREVIEW",
            columns: ["name", "value"],
            rows: [["alice", "=2+2"]],
            truncated: false,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
  });

  it("renders safe table data and an honest Office download fallback", async () => {
    render(
      <TestAuthProvider>
        <LearningFiles workspace="workspace-1" />
      </TestAuthProvider>,
    );

    fireEvent.click(screen.getByText("课程文件与我的私人资料"));
    fireEvent.click(await screen.findByRole("button", { name: "预览 scores.csv" }));
    expect(await screen.findByRole("table", { name: "scores.csv 表格预览" })).toBeVisible();
    expect(screen.getByText("alice")).toBeVisible();
    expect(screen.getByText("=2+2")).toBeVisible();
    expect(screen.queryByText(/alert\(/)).not.toBeInTheDocument();

    expect(screen.getByText("需要安全转换器，当前仅可下载")).toBeVisible();
    expect(screen.getAllByText(/1 KB/)).toHaveLength(2);
    expect(screen.getAllByText(/仅本人/)).toHaveLength(2);
    expect(screen.getByRole("button", { name: "预览 legacy.doc" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下载 legacy.doc" })).toBeEnabled();
  });
});
