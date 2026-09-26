from __future__ import annotations

import argparse
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from bridge_core import (
    BridgeError,
    TRUSTED_API_ORIGINS,
    TRUSTED_CANVAS_ORIGINS,
    decode_connection,
    run_bridge,
)


VERSION = "1.0.0"
API_ORIGINS = tuple(sorted(TRUSTED_API_ORIGINS))
CANVAS_LABELS = {
    f"{key} — {origin}": key for key, origin in TRUSTED_CANVAS_ORIGINS.items()
}


class BridgeWindow:
    def __init__(self, root: tk.Tk, ticket: str = "") -> None:
        self.root = root
        self.root.title("CourseJesus Canvas 本地导入")
        self.root.geometry("760x720")
        self.root.minsize(660, 620)
        self.cancel_event = threading.Event()
        self.events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="CourseJesus Canvas 本地导入", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Token 只在本机内存中使用；网页只接收课程信息、文件和导入回执。", wraplength=670).pack(anchor="w", pady=(4, 14))

        ttk.Label(frame, text="1. 网页生成的连接信息").pack(anchor="w")
        self.ticket = tk.Text(frame, height=5, wrap="word")
        self.ticket.pack(fill="x", pady=(5, 12))
        if ticket:
            self.ticket.insert("1.0", ticket)
        self.ticket.bind("<KeyRelease>", self.inspect_connection)

        legacy = ttk.LabelFrame(frame, text="仅旧版单个连接码需要明确选择", padding=8)
        legacy.pack(fill="x", pady=(0, 12))
        self.api_choice = tk.StringVar(value="")
        self.canvas_choice = tk.StringVar(value="")
        ttk.Label(legacy, text="CourseJesus 服务").grid(row=0, column=0, sticky="w")
        api_box = ttk.Combobox(legacy, state="readonly", values=API_ORIGINS, textvariable=self.api_choice)
        api_box.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(legacy, text="学校 Canvas").grid(row=1, column=0, sticky="w", pady=(6, 0))
        canvas_box = ttk.Combobox(
            legacy, state="readonly", values=tuple(CANVAS_LABELS), textvariable=self.canvas_choice
        )
        canvas_box.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        legacy.columnconfigure(1, weight=1)
        api_box.bind("<<ComboboxSelected>>", self.inspect_connection)
        canvas_box.bind("<<ComboboxSelected>>", self.inspect_connection)

        target = ttk.LabelFrame(frame, text="只读连接目标", padding=8)
        target.pack(fill="x", pady=(0, 12))
        self.api_target = tk.StringVar(value="—")
        self.canvas_target = tk.StringVar(value="—")
        ttk.Label(target, text="将连接的网站").grid(row=0, column=0, sticky="w")
        ttk.Label(target, textvariable=self.api_target).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(target, text="学校 Canvas").grid(row=1, column=0, sticky="w", pady=(5, 0))
        ttk.Label(target, textvariable=self.canvas_target).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(5, 0))

        ttk.Label(frame, text="2. Canvas Token（输入后立即从窗口清除，不写入磁盘）").pack(anchor="w")
        self.token = ttk.Entry(frame, show="●")
        self.token.pack(fill="x", pady=(5, 12))

        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="连接并读取课程", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="停止", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        ttk.Label(actions, text=f"v{VERSION} · Windows x64 · 未签名", foreground="#6b7280").pack(side="right")

        ttk.Label(frame, text="状态").pack(anchor="w", pady=(16, 5))
        self.log = tk.Text(frame, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        self.write("请先在 CourseJesus 网页生成连接信息。")
        self.inspect_connection()
        self.root.after(100, self.drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def write(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def legacy_targets(self) -> tuple[str, str]:
        return self.api_choice.get(), CANVAS_LABELS.get(self.canvas_choice.get(), "")

    def inspect_connection(self, _event: object | None = None) -> None:
        value = self.ticket.get("1.0", "end").strip()
        if not value:
            self.api_target.set("—")
            self.canvas_target.set("—")
            return
        api_origin, institution_key = self.legacy_targets()
        try:
            ticket = decode_connection(
                value,
                legacy_api_origin=api_origin,
                legacy_institution_key=institution_key,
            )
        except BridgeError:
            self.api_target.set(api_origin or "等待有效连接信息")
            self.canvas_target.set(TRUSTED_CANVAS_ORIGINS.get(institution_key, "等待有效连接信息"))
            return
        self.api_target.set(ticket.api_origin)
        self.canvas_target.set(ticket.institution_origin)

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        ticket = self.ticket.get("1.0", "end").strip()
        token = self.token.get().strip()
        legacy_api_origin, legacy_institution_key = self.legacy_targets()
        self.token.delete(0, "end")
        if not ticket or not token:
            messagebox.showerror("缺少信息", "请填写网页连接信息和 Canvas Token。")
            return
        self.cancel_event.clear()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        def work() -> None:
            nonlocal token
            try:
                run_bridge(
                    ticket,
                    token,
                    on_status=lambda text: self.events.put(("status", text)),
                    cancel=self.cancel_event,
                    legacy_api_origin=legacy_api_origin,
                    legacy_institution_key=legacy_institution_key,
                )
                self.events.put(("done", "导入流程已结束。可以回到网页查看课程。"))
            except Exception as error:
                self.events.put(("error", str(error) or type(error).__name__))
            finally:
                token = ""

        self.worker = threading.Thread(target=work, name="canvas-bridge", daemon=True)
        self.worker.start()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.write("正在停止；当前网络请求结束后不会开始下一个文件。")

    def drain_events(self) -> None:
        try:
            while True:
                kind, text = self.events.get_nowait()
                self.write(text)
                if kind in {"done", "error"}:
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    if kind == "error":
                        messagebox.showerror("导入未完成", text)
        except queue.Empty:
            pass
        self.root.after(100, self.drain_events)

    def close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("停止导入", "工具仍在工作。确定停止并关闭吗？"):
                return
            self.cancel_event.set()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--ticket", default="")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print(VERSION)
        return
    root = tk.Tk()
    BridgeWindow(root, ticket=args.ticket)
    root.mainloop()


if __name__ == "__main__":
    main()
