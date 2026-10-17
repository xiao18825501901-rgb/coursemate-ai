import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { StrictMode, useState } from "react";
import type { ReactNode } from "react";

import { CourseFiles } from "./pages.jsx";
import { FileUploadQueue } from "./FileUploadQueue.jsx";
import { App } from "./App.jsx";
import { LanguageControl, UiLocaleProvider, dictionaryParity } from "./UiLocale";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

test("actual files UI translates without remounting, rewriting user names or resetting search", () => {
  vi.spyOn(CourseFiles.prototype, "load").mockImplementation(async function (this: any) {
    this.setState({ files: [{ id: "file-original", name: "我的 Qwen 资料.txt", folder: "",
      size: 12, scope: "private", mime: "text/plain" }], loading: false });
  });
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  let instance: any;
  render(<UiLocaleProvider><LanguageControl /><CourseFiles
    ref={value => { instance = value; }} course={{ id: "course-original", code: "CS1", name: "原课程" }}
    toast={vi.fn()} modal={vi.fn()} /></UiLocaleProvider>);
  const original = instance;
  fireEvent.change(screen.getByRole("textbox", { name: "搜索文件" }), { target: { value: "Qwen" } });
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("heading", { name: "Files" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Search files" })).toHaveValue("Qwen");
  expect(screen.getByRole("columnheader", { name: "Name" })).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "Size" })).toBeVisible();
  expect(screen.getByRole("columnheader", { name: "Actions" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Add my materials" })).toBeVisible();
  expect(screen.getByText("Only me")).toBeVisible();
  expect(screen.getByText("我的 Qwen 资料.txt")).toBeVisible();
  expect(instance).toBe(original);
  expect(instance.state.files[0].id).toBe("file-original");
  expect(fetchSpy).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "中文" }));
  expect(screen.getByRole("heading", { name: "文件" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "搜索文件" })).toHaveValue("Qwen");
});

test("queue UI translates statuses and accessible actions but keeps original item IDs and errors", () => {
  const retry = vi.fn(), remove = vi.fn();
  const items = [{ clientItemId: "original-item", name: "DeepSeek 用户笔记.txt", size: 11,
    status: "failed", error: "用户原始错误正文", result: null }];
  render(<UiLocaleProvider><LanguageControl /><FileUploadQueue
    items={items} onRetry={retry} onRemove={remove} /></UiLocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByLabelText("Upload queue")).toBeVisible();
  expect(screen.getByText(/Upload failed/)).toBeVisible();
  expect(screen.getByText("用户原始错误正文")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry this file" }));
  expect(retry).toHaveBeenCalledExactlyOnceWith("original-item");
  fireEvent.click(screen.getByRole("button", { name: "Remove DeepSeek 用户笔记.txt" }));
  expect(remove).toHaveBeenCalledExactlyOnceWith("original-item");
  expect(items[0]?.name).toBe("DeepSeek 用户笔记.txt");
});

test("file translations retain complete key and interpolation parity", () => {
  expect(dictionaryParity()).toEqual([]);
});

test("mounted course frame translates navigation without changing route or course identity", () => {
  vi.spyOn(CourseFiles.prototype,"load").mockResolvedValue(undefined);
  vi.spyOn(App.prototype,"boot").mockImplementation(async function(this:any) {
    this.setState({loading:false,user:{id:"original-owner",name:"原用户"},
      config:{environment:"production",auth_mode:"clerk"},
      courses:[{id:"original-course",code:"CS1",name:"用户 Qwen 课程",visibility:"private"}],
      route:{page:"course",cid:"original-course",tab:"files"}});
  });
  let instance:any;
  render(<UiLocaleProvider><LanguageControl /><App ref={value=>{instance=value;}} /></UiLocaleProvider>);
  const original=instance, route=instance.state.route;
  const fetchSpy=vi.spyOn(globalThis,"fetch");
  fireEvent.click(screen.getByRole("button",{name:"English"}));
  expect(screen.getByRole("button",{name:"All courses"})).toBeVisible();
  expect(screen.getByRole("button",{name:"Discussion"})).toBeVisible();
  expect(screen.getByRole("button",{name:"Learn"})).toBeVisible();
  expect(screen.getByText(/^Private course · Only you/)).toBeVisible();
  expect(screen.getByText("用户 Qwen 课程")).toBeVisible();
  expect(instance).toBe(original);
  expect(instance.state.route).toBe(route);
  expect(instance.state.user.id).toBe("original-owner");
  expect(fetchSpy).not.toHaveBeenCalled();
});

function FilesWithPreview() {
  const [preview, setPreview] = useState<ReactNode>(null);
  return <UiLocaleProvider><LanguageControl /><CourseFiles
    course={{id:"course-original",code:"CS1",name:"原课程"}} toast={vi.fn()}
    modal={(_title: string, body: ReactNode) => setPreview(body)} />{preview}</UiLocaleProvider>;
}

test("actual entry StrictMode replay still delivers original preview and ignores stale mount response", async () => {
  vi.spyOn(CourseFiles.prototype, "load").mockImplementation(async function (this: any) {
    this.setState({files:[{id:"file-original",name:"原文件.txt",folder:"",size:12,
      scope:"private",mime:"text/plain"}],loading:false});
  });
  let resolveStale!: (response: Response) => void;
  const response = (text: string) => new Response(JSON.stringify({pages:[{text}]}),
    {status:200,headers:{"Content-Type":"application/json"}});
  const fetchSpy = vi.spyOn(globalThis,"fetch")
    .mockImplementationOnce(() => new Promise<Response>(resolve => { resolveStale = resolve; }))
    .mockResolvedValueOnce(response("当前挂载原始正文 Qwen"));
  render(<StrictMode><FilesWithPreview /></StrictMode>);
  fireEvent.click(screen.getByRole("button",{name:/^原文件\.txt\s*仅自己$/}));
  expect(await screen.findByText("当前挂载原始正文 Qwen")).toBeVisible();
  resolveStale(response("已结束挂载的旧响应"));
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(screen.queryByText("已结束挂载的旧响应")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"English"}));
  expect(screen.getByText("当前挂载原始正文 Qwen")).toBeVisible();
  expect(screen.getByRole("button",{name:"Download"})).toBeVisible();
  expect(fetchSpy).toHaveBeenCalledTimes(2);
});

test.each(["用户原始 Qwen 正文，不得翻译。", ""])(
  "preview locale changes labels without changing original content or re-fetching: %s", async text => {
    vi.spyOn(CourseFiles.prototype, "load").mockImplementation(async function (this: any) {
      this.setState({files:[{id:"file-original",name:"原文件.txt",folder:"",size:12,
        scope:"private",mime:"text/plain"}],loading:false});
    });
    const fetchSpy = vi.spyOn(globalThis,"fetch").mockResolvedValue(new Response(
      JSON.stringify({pages:text ? [{text}] : []}), {status:200,headers:{"Content-Type":"application/json"}}
    ));
    render(<FilesWithPreview />);
    fireEvent.click(screen.getByRole("button",{name:/^原文件\.txt\s*仅自己$/}));
    if (text) expect(await screen.findByText(text)).toBeVisible();
    else expect(await screen.findByText("暂不支持预览此文件，可下载查看")).toBeVisible();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button",{name:"English"}));
    expect(screen.getByText(/Course material preview/)).toBeVisible();
    if (text) expect(screen.getByText(text)).toBeVisible();
    else expect(screen.getByText("Preview is unavailable for this file. Download it to view")).toBeVisible();
    expect(screen.getByRole("button",{name:"Download"})).toBeVisible();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  }
);

