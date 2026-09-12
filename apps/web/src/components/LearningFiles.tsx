import { useEffect, useState } from "react";
import { useCourseMateAuth } from "../auth/AuthProvider";
import { authenticatedFetch, requestJson, requireOk } from "../services/http";
import { learningBase } from "../services/learningApi";

type PreviewKind =
  | "INLINE_ORIGINAL"
  | "DERIVED_PDF"
  | "SAFE_TEXT"
  | "TABLE_PREVIEW"
  | "NOTEBOOK_PREVIEW"
  | "DOWNLOAD_ONLY";

interface PreviewCapability {
  kind: PreviewKind;
  available: boolean;
  reason: string | null;
  artifact_id?: string;
}

interface FileItem {
  id: string;
  filename: string;
  extension: string;
  byte_size?: number;
  status: string;
  source_scope?: "OFFICIAL" | "OWNER_COURSE" | "WORKSPACE_PRIVATE";
  access_scope?: "COURSE_SHARED" | "REVIEWED_SHARED" | "OWNER_PRIVATE";
  version_id?: string;
  version_number?: number;
  preview?: PreviewCapability;
}

interface SafeTextPreview {
  kind: "SAFE_TEXT";
  text: string;
  truncated: boolean;
}

interface TablePreview {
  kind: "TABLE_PREVIEW";
  columns: string[];
  rows: string[][];
  truncated: boolean;
}

interface NotebookCell {
  cell_type: string;
  source: string;
  outputs: string[];
}

interface NotebookPreview {
  kind: "NOTEBOOK_PREVIEW";
  cells: NotebookCell[];
  executed: false;
  truncated: boolean;
}

type StructuredPreview = SafeTextPreview | TablePreview | NotebookPreview;
type ActivePreview =
  | { name: string; type: "pdf" | "image"; url: string }
  | { name: string; type: "structured"; data: StructuredPreview };

function fallbackCapability(file: FileItem): PreviewCapability {
  if ([".pdf", ".png", ".jpg", ".jpeg", ".gif"].includes(file.extension)) {
    return { kind: "INLINE_ORIGINAL", available: true, reason: null };
  }
  if ([".txt", ".md", ".markdown"].includes(file.extension)) {
    return { kind: "SAFE_TEXT", available: true, reason: null };
  }
  return { kind: "DOWNLOAD_ONLY", available: false, reason: "FORMAT_NOT_PREVIEWABLE" };
}

function previewReason(reason: string | null): string | null {
  if (reason === "CONTROLLED_CONVERTER_NOT_CONFIGURED") {
    return "需要安全转换器，当前仅可下载";
  }
  if (reason === "ORIGINAL_UNAVAILABLE") return "原文件不可用";
  if (reason) return "当前格式仅可下载";
  return null;
}

function scopeLabel(scope: FileItem["source_scope"]): string {
  if (scope === "OFFICIAL") return "课程资料";
  if (scope === "WORKSPACE_PRIVATE") return "我的文件";
  if (scope === "OWNER_COURSE") return "用户课程资料";
  return "来源待确认";
}

function permissionLabel(access: FileItem["access_scope"]): string {
  if (access === "COURSE_SHARED") return "课程共享";
  if (access === "REVIEWED_SHARED") return "审核后共享";
  return "仅本人";
}

function fileSize(byteSize: number | undefined): string {
  if (byteSize === undefined) return "大小未知";
  if (byteSize < 1024) return `${byteSize} B`;
  if (byteSize < 1024 * 1024) return `${(byteSize / 1024).toFixed(1).replace(".0", "")} KB`;
  return `${(byteSize / (1024 * 1024)).toFixed(1).replace(".0", "")} MB`;
}

function TablePreviewView({ name, data }: { name: string; data: TablePreview }) {
  return (
    <div className="learning-table-wrap">
      {data.truncated && <p>表格预览已按行、列或字符上限截断。</p>}
      <table aria-label={`${name} 表格预览`}>
        <thead>
          <tr>
            {data.columns.map((column, index) => (
              <th scope="col" key={`${index}-${column}`}>
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {data.columns.map((_column, columnIndex) => (
                <td key={columnIndex}>{row[columnIndex] ?? ""}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LearningFiles({
  workspace,
  onDocumentsChanged,
}: {
  workspace: string;
  onDocumentsChanged?: () => void | Promise<void>;
}) {
  const { getToken } = useCourseMateAuth();
  const [files, setFiles] = useState<FileItem[]>([]);
  const [scope, setScope] = useState("union");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<ActivePreview | null>(null);

  async function load() {
    const result = await requestJson<{ data: FileItem[] }>(
      getToken,
      `${learningBase}/workspaces/${workspace}/documents?scope=${scope}`,
    );
    setFiles(result.data);
  }

  useEffect(() => {
    let active = true;
    void requestJson<{ data: FileItem[] }>(
      getToken,
      `${learningBase}/workspaces/${workspace}/documents?scope=${scope}`,
    )
      .then((result) => {
        if (active) setFiles(result.data);
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "文件列表加载失败");
      });
    return () => {
      active = false;
    };
  }, [workspace, scope, getToken]);

  useEffect(
    () => () => {
      if (preview?.type === "pdf" || preview?.type === "image") {
        URL.revokeObjectURL(preview.url);
      }
    },
    [preview],
  );

  async function download(file: FileItem) {
    setBusy(true);
    setError("");
    try {
      const source = file.version_id
        ? `${learningBase}/document-versions/${file.version_id}`
        : `${learningBase}/documents/${file.id}`;
      const response = await requireOk(
        await authenticatedFetch(getToken, `${source}/content?download=true`),
      );
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "下载失败");
    } finally {
      setBusy(false);
    }
  }

  async function openPreview(file: FileItem) {
    const descriptor = file.preview ?? fallbackCapability(file);
    if (!descriptor.available) return;
    setBusy(true);
    setError("");
    try {
      const source = file.version_id
        ? `${learningBase}/document-versions/${file.version_id}`
        : `${learningBase}/documents/${file.id}`;
      if (descriptor.kind === "INLINE_ORIGINAL" || descriptor.kind === "DERIVED_PDF") {
        const target =
          descriptor.kind === "DERIVED_PDF" && descriptor.artifact_id
            ? `${learningBase}/artifacts/${descriptor.artifact_id}/content`
            : `${source}/content`;
        const response = await requireOk(await authenticatedFetch(getToken, target));
        const url = URL.createObjectURL(await response.blob());
        setPreview({
          name: file.filename,
          type: file.extension === ".pdf" || descriptor.kind === "DERIVED_PDF" ? "pdf" : "image",
          url,
        });
      } else {
        const response = await requireOk(
          await authenticatedFetch(
            getToken,
            `${source}/preview`,
          ),
        );
        setPreview({
          name: file.filename,
          type: "structured",
          data: (await response.json()) as StructuredPreview,
        });
      }
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "文件预览不可用");
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setBusy(true);
    setError("");
    try {
      const data = new FormData();
      data.set("file", file);
      await requireOk(
        await authenticatedFetch(
          getToken,
          `${learningBase}/workspaces/${workspace}/documents`,
          { method: "POST", body: data },
        ),
      );
      await load();
      await onDocumentsChanged?.();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="learning-files">
      <summary>课程文件与我的私人资料</summary>
      <p>私人文件及其预览只对本人可见，不会修改官方资料；Notebook 仅静态展示，绝不执行。</p>
      <label>
        文件范围{" "}
        <select value={scope} onChange={(event) => setScope(event.target.value)}>
          <option value="union">官方 + 我的</option>
          <option value="official">仅课程共享资料</option>
          <option value="mine">仅我的资料</option>
        </select>
      </label>
      <label>
        添加私人资料{" "}
        <input
          type="file"
          disabled={busy}
          accept=".pdf,.txt,.md,.markdown,.csv,.ipynb,.png,.jpg,.jpeg,.gif,.doc,.docx,.xls,.xlsx,.ppt,.pptx"
          onChange={(event) => {
            const selected = event.target.files?.[0];
            if (selected) void upload(selected);
            event.target.value = "";
          }}
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <ul className="learning-file-list">
        {files.map((file) => {
          const descriptor = file.preview ?? fallbackCapability(file);
          const reason = previewReason(descriptor.reason);
          return (
            <li key={file.id}>
              <span>
                <strong>{file.filename}</strong>{" "}
                <small>
                  {scopeLabel(file.source_scope)} · {permissionLabel(file.access_scope)} · v
                  {file.version_number ?? 1} · 解析 {file.status} · {fileSize(file.byte_size)}
                </small>
                {reason && <small>{reason}</small>}
              </span>
              <span className="learning-file-actions">
                <button
                  type="button"
                  disabled={busy || !descriptor.available}
                  aria-label={`预览 ${file.filename}`}
                  onClick={() => void openPreview(file)}
                >
                  预览
                </button>
                <button
                  type="button"
                  disabled={busy}
                  aria-label={`下载 ${file.filename}`}
                  onClick={() => void download(file)}
                >
                  下载
                </button>
              </span>
            </li>
          );
        })}
      </ul>
      {!files.length && <p>当前范围暂无文件。</p>}
      {preview && (
        <section className="learning-file-preview" aria-label={`文件预览 ${preview.name}`}>
          <header>
            <h3>{preview.name}</h3>
            <button type="button" onClick={() => setPreview(null)}>
              关闭预览
            </button>
          </header>
          {preview.type === "pdf" && (
            <iframe title={preview.name} src={preview.url} sandbox="allow-same-origin" />
          )}
          {preview.type === "image" && <img src={preview.url} alt={`${preview.name} 预览`} />}
          {preview.type === "structured" && preview.data.kind === "SAFE_TEXT" && (
            <>
              {preview.data.truncated && <p>预览已按安全上限截断。</p>}
              <pre>{preview.data.text}</pre>
            </>
          )}
          {preview.type === "structured" && preview.data.kind === "TABLE_PREVIEW" && (
            <TablePreviewView name={preview.name} data={preview.data} />
          )}
          {preview.type === "structured" && preview.data.kind === "NOTEBOOK_PREVIEW" && (
            <div className="notebook-preview">
              <p>静态预览：未执行任何 Cell。</p>
              {preview.data.truncated && <p>Notebook 预览已按 Cell 上限截断。</p>}
              {preview.data.cells.map((cell, index) => (
                <article key={index}>
                  <h4>
                    Cell {index + 1} · {cell.cell_type}
                  </h4>
                  <pre>{cell.source}</pre>
                  {cell.outputs.map((output, outputIndex) => (
                    <pre className="notebook-output" key={outputIndex}>
                      {output}
                    </pre>
                  ))}
                </article>
              ))}
            </div>
          )}
        </section>
      )}
    </details>
  );
}
