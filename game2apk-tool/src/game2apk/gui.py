"""Non-blocking Tkinter/ttk wizard over :class:`PipelineService`."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import build_config, default_control_config
from .errors import Game2ApkError
from .models import BuildConfig
from .pipeline import PipelineService


class WizardApp:
    def __init__(self, root: tk.Tk, tool_root: str | Path):
        self.root = root
        self.tool_root = Path(tool_root).resolve()
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="game2apk")
        self.cancel_event = threading.Event()
        self.service = PipelineService(self.tool_root, progress=lambda stage, fraction, message: self.queue.put(("progress", (stage, fraction, message))), cancel_event=self.cancel_event)
        self.inspection = None
        self.stage = None
        self.build_result = None
        self._build_vars()
        self._build_ui()
        self.root.after(100, self._poll)

    def _build_vars(self) -> None:
        self.source_var = tk.StringVar()
        self.template_var = tk.StringVar(value=str(self.tool_root / "templates" / "android-rpgmv"))
        self.app_name_var = tk.StringVar(value="仙肴圣餐超魔改 Ver22")
        self.application_id_var = tk.StringVar(value="com.game2apk.xianyaoshengcanver22")
        self.version_code_var = tk.IntVar(value=2)
        self.version_name_var = tk.StringVar(value="1.0.1")
        self.translate_var = tk.BooleanVar(value=False)
        self.confirm_var = tk.BooleanVar(value=False)
        self.api_key_var = tk.StringVar()
        self.sign_password_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请选择已解包的 RPG Maker MV 游戏目录")
        self.progress_var = tk.DoubleVar(value=0)

    def _build_ui(self) -> None:
        self.root.title("RPG Maker MV → Android APK")
        self.root.geometry("820x620")
        self.root.minsize(720, 520)
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        title = ttk.Label(outer, text="RPG Maker MV Android 工具", font=("Segoe UI", 16, "bold"))
        title.pack(anchor="w")
        ttk.Label(outer, text="选择游戏 → 检查 → 可选翻译 → 应用/控件/签名设置 → 构建 → 验证").pack(anchor="w", pady=(2, 10))

        source_frame = ttk.LabelFrame(outer, text="1. 选择游戏")
        source_frame.pack(fill="x", pady=4)
        ttk.Entry(source_frame, textvariable=self.source_var).pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(source_frame, text="浏览…", command=self._browse_source).pack(side="left", padx=6)
        self.inspect_button = ttk.Button(source_frame, text="检查", command=self._inspect)
        self.inspect_button.pack(side="left", padx=(0, 6))

        self.report_text = tk.Text(outer, height=11, wrap="word", state="disabled")
        self.report_text.pack(fill="both", expand=True, pady=4)

        settings = ttk.LabelFrame(outer, text="2. 应用 / 控件 / 签名设置")
        settings.pack(fill="x", pady=4)
        self._row(settings, 0, "应用名", self.app_name_var)
        self._row(settings, 1, "包名", self.application_id_var)
        self._row(settings, 2, "版本", self.version_name_var)
        ttk.Label(settings, text="版本号 versionCode").grid(row=3, column=0, sticky="w", padx=6, pady=2)
        ttk.Spinbox(settings, from_=1, to=2_147_483_647, textvariable=self.version_code_var, increment=1).grid(row=3, column=1, columnspan=2, sticky="ew", padx=6, pady=2)
        self._row(settings, 4, "模板", self.template_var)
        ttk.Checkbutton(settings, text="强制翻译未汉化文本（本游戏默认建议关闭）", variable=self.translate_var).grid(row=5, column=0, columnspan=3, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(settings, text="确认将选中文本发送给第三方 DeepSeek 服务", variable=self.confirm_var).grid(row=6, column=0, columnspan=3, sticky="w", padx=6, pady=2)
        ttk.Label(settings, text="DeepSeek Key（仅当前进程）").grid(row=7, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(settings, textvariable=self.api_key_var, show="*").grid(row=7, column=1, columnspan=2, sticky="ew", padx=6, pady=2)
        ttk.Label(settings, text="签名密码（DPAPI 保护，可留空自动生成）").grid(row=8, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(settings, textvariable=self.sign_password_var, show="*").grid(row=8, column=1, columnspan=2, sticky="ew", padx=6, pady=2)
        settings.columnconfigure(1, weight=1)

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(6, 0))
        self.build_button = ttk.Button(controls, text="构建并验证", command=self._run_pipeline, state="disabled")
        self.build_button.pack(side="left")
        self.cancel_button = ttk.Button(controls, text="取消", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        ttk.Label(controls, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        ttk.Progressbar(controls, variable=self.progress_var, maximum=100, length=180).pack(side="right")
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    @staticmethod
    def _row(parent, row: int, label: str, variable: tk.Variable) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=2)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, columnspan=2, sticky="ew", padx=6, pady=2)

    def _browse_source(self) -> None:
        value = filedialog.askdirectory(title="选择游戏根目录或 www 目录")
        if value:
            self.source_var.set(value)

    def _show_report(self, text: str) -> None:
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.insert("1.0", text)
        self.report_text.configure(state="disabled")

    def _inspect(self) -> None:
        source = self.source_var.get().strip()
        if not source:
            messagebox.showwarning("需要选择游戏", "请选择游戏根目录或 www 目录。")
            return
        self.inspect_button.configure(state="disabled")
        self.status_var.set("正在检查…")
        self.executor.submit(self._inspect_worker, source)

    def _inspect_worker(self, source: str) -> None:
        try:
            report = self.service.inspect(source)
            self.queue.put(("inspection", report))
        except Exception as exc:  # surfaced on UI thread with diagnostic text
            self.queue.put(("error", exc))

    def _run_pipeline(self) -> None:
        if self.inspection is None or self.inspection.blocked:
            messagebox.showerror("检查未通过", "必须先通过 RPG Maker MV 检查。")
            return
        self.build_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.cancel_event.clear()
        self.status_var.set("准备构建…")
        settings = {
            "app_name": self.app_name_var.get(),
            "application_id": self.application_id_var.get(),
            "version_code": int(self.version_code_var.get()),
            "version_name": self.version_name_var.get(),
            "template": self.template_var.get(),
            "translate": bool(self.translate_var.get()),
            "confirm": bool(self.confirm_var.get()),
            "api_key": self.api_key_var.get() or None,
            "sign_password": self.sign_password_var.get() or None,
        }
        self.executor.submit(self._pipeline_worker, settings)

    def _pipeline_worker(self, settings: dict[str, object]) -> None:
        try:
            data = build_config(
                app_name=str(settings["app_name"]),
                application_id=str(settings["application_id"]),
                version_code=int(settings["version_code"]),
                version_name=str(settings["version_name"]),
                control=default_control_config(),
            )
            config = BuildConfig(data["appName"], data["applicationId"], data["versionCode"], data["versionName"], control_config=data["control"])
            stage = self.service.stage(self.inspection)
            self.service.patch(stage, config)
            if bool(settings["translate"]):
                if not bool(settings["confirm"]):
                    raise Game2ApkError("翻译前必须勾选第三方 DeepSeek 发送确认")
                self.service.translate(stage, api_key=settings["api_key"], confirmed_third_party=True, force=True)
            result = self.service.build(str(settings["template"]), stage, config, api_key=settings["api_key"])
            if result.return_code != 0 or not result.apk_path:
                raise Game2ApkError(f"Gradle 构建失败，退出码 {result.return_code}；日志：{result.log_path}")
            self.service.sign(result, config, password=settings["sign_password"])
            verification = self.service.verify(result, config, install=False)
            promoted = self.service.promote(verification, config) if verification.signature_candidate else None
            self.queue.put(("complete", (result, verification, promoted)))
        except Exception as exc:
            self.queue.put(("error", exc))

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.status_var.set("正在请求取消…")

    def _poll(self) -> None:
        try:
            while True:
                event, value = self.queue.get_nowait()
                if event == "progress":
                    stage, fraction, message = value
                    self.progress_var.set(float(fraction) * 100)
                    self.status_var.set(f"{stage}: {message}")
                elif event == "inspection":
                    self.inspection = value
                    keys = ", ".join(f"{item.get('key')}→公共事件 {item.get('common_event_id')}" for item in value.custom_keys)
                    self._show_report(
                        f"状态：{value.status}\n引擎：{value.engine} {value.engine_version or '未知'}\n标题：{value.title or '未知'}\n"
                        f"最终有效分辨率：{value.effective_width}×{value.effective_height}\n"
                        f"MV 默认：{value.mv_default_width}×{value.mv_default_height}；外层窗口：{value.outer_window_width}×{value.outer_window_height}\n"
                        f"文件：{value.file_count}，字节：{value.total_bytes}\n启用插件：{len(value.enabled_plugins)}；自定义键：{keys or '未识别'}\n"
                        + "\n".join(f"[{risk.level}] {risk.message}" for risk in value.risks[:12])
                    )
                    self.build_button.configure(state="normal" if not value.blocked else "disabled")
                    self.inspect_button.configure(state="normal")
                    self.status_var.set("检查完成；本游戏默认建议跳过翻译")
                elif event == "complete":
                    result, verification, promoted = value
                    self.cancel_button.configure(state="disabled")
                    promoted_text = f"\n交付 APK：{promoted}" if promoted else ""
                    self._show_report(self.report_text.get("1.0", "end") + f"\n\nAPK：{result.apk_path}\n静态签名候选：{verification.signature_candidate}\nSHA-256：{verification.sha256}{promoted_text}")
                    self.status_var.set("完成" if verification.passed else "已生成但静态验收未通过")
                    messagebox.showinfo("构建结果", self.status_var.get())
                    self.build_button.configure(state="normal")
                elif event == "error":
                    self.cancel_button.configure(state="disabled")
                    self.build_button.configure(state="normal" if self.inspection and not self.inspection.blocked else "disabled")
                    self.status_var.set("失败")
                    messagebox.showerror("任务失败", str(value))
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _close(self) -> None:
        self.cancel_event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main(tool_root: str | Path | None = None) -> None:
    root = Path(tool_root or Path(__file__).resolve().parents[2])
    window = tk.Tk()
    WizardApp(window, root)
    window.mainloop()
