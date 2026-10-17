import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { CanvasImport } from "./CanvasImport.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

beforeEach(() => localStorage.clear());

function mount(step: string) {
  vi.spyOn(CanvasImport.prototype, "componentDidMount").mockImplementation(async function (this: any) {
    this.setState({ step, institutions: [{ key: "school", label: "用户学校 Qwen", origin: "https://canvas.example.edu", connectable: true }],
      connection: { connectionId: "TEST_ONLY-connection", canvasName: "原账号 DeepSeek" },
      courses: [{ id: "TEST_ONLY-course", name: "原始课程 Qwen", readable: true }],
      selected: ["TEST_ONLY-course"], picked: "other", otherSchool: "https://canvas.example.edu/user/source?keep=1",
      job: { jobId: "TEST_ONLY-original-job", status: "QUEUED" } });
  });
  let instance: any;
  const view = render(<UiLocaleProvider><LanguageControl /><CanvasImport ref={value => { instance = value; }} /></UiLocaleProvider>);
  return { ...view, instance };
}

test("Canvas selection translates controls but preserves connection, course IDs, selection and job", () => {
  const { instance } = mount("select");
  const before = instance.state;
  const checkbox = screen.getByRole("checkbox", { name: "原始课程 Qwen" });
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByText("Choose courses to import")).toBeVisible();
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "Save this connection to sync new materials later" })).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "原始课程 Qwen" })).toBe(checkbox);
  expect(checkbox).toBeChecked();
  expect(instance.state.connection).toBe(before.connection);
  expect(instance.state.connection.connectionId).toBe("TEST_ONLY-connection");
  expect(instance.state.selected).toBe(before.selected);
  expect(instance.state.job).toBe(before.job);
  expect(screen.getByText(/原账号 DeepSeek/)).toBeVisible();
  expect(fetchSpy).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(screen.getByText("选择要导入的课程")).toBeVisible();
  expect(checkbox).toBeChecked();
});

test("Canvas school picker translates address labels without clearing the address or school", () => {
  const { instance } = mount("connect");
  const address = screen.getByRole("textbox", { name: "学校 Canvas 地址" });
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("group", { name: "Choose your school" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "School Canvas URL" })).toBe(address);
  expect(address).toHaveValue("https://canvas.example.edu/user/source?keep=1");
  expect(screen.getByText("用户学校 Qwen")).toBeVisible();
  expect(instance.state.picked).toBe("other");
  expect(fetchSpy).not.toHaveBeenCalled();
  act(() => instance.setState({ busy: true }));
  expect(screen.getByRole("button", { name: "Connect Canvas" })).toBeDisabled();
});

test("Canvas owner task credential paste step translates without clearing sensitive draft state", () => {
  const { instance } = mount("taskToken");
  act(() => instance.setState({
    taskStage: "paste",
    taskToken: "TEST_ONLY-pasted-token",
    canvasAddress: "https://canvas.example.edu/courses/42",
    resumeJobId: "",
  }));
  const address = screen.getByRole("textbox", { name: "学校 Canvas 地址" });
  const token = screen.getByLabelText("本次 Access Token");
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByText("Import courses from Canvas")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "School Canvas URL" })).toBe(address);
  expect(screen.getByLabelText("One-time access token")).toBe(token);
  expect(address).toHaveValue("https://canvas.example.edu/courses/42");
  expect(token).toHaveValue("TEST_ONLY-pasted-token");
  expect(screen.getByRole("button", { name: "Confirm and choose courses" })).toBeVisible();
  expect(instance.state.taskToken).toBe("TEST_ONLY-pasted-token");
});

test("Canvas local bridge and job status translate while retaining operation identity", () => {
  const { instance } = mount("bridge");
  act(() => instance.setState({
    bridge: {
      sessionId: "TEST_ONLY-bridge-session",
      status: "OPEN",
      expiresAt: new Date(Date.now() + 600_000).toISOString(),
    },
    bridgeTicket: "TEST_ONLY-bridge-ticket",
    bridgeRelease: { publicPath: "/bridge.zip", version: "1.2.3" },
  }));
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByText("Connect Canvas with the local import assistant")).toBeVisible();
  expect(screen.getByText("Current connection details")).toBeVisible();
  expect(screen.getByRole("button", { name: "Copy connection details" })).toBeVisible();
  expect(instance.state.bridge.sessionId).toBe("TEST_ONLY-bridge-session");
  expect(instance.state.bridgeTicket).toBe("TEST_ONLY-bridge-ticket");

  act(() => instance.setState({
    step: "job",
    job: { jobId: "TEST_ONLY-original-job", status: "QUEUED", files: 1, courses: 1, byStatus: {} },
  }));
  expect(screen.getByText("Queued")).toBeVisible();
  expect(screen.getByText("1 file · 1 course")).toBeVisible();
  expect(screen.getByRole("button", { name: "Cancel import" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Done" })).toBeVisible();
  expect(instance.state.job.jobId).toBe("TEST_ONLY-original-job");
});

