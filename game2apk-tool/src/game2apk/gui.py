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
from .toolchain import COMPONENTS, download_component, discover_configured, load_config, missing_components, save_config
from .translation import DEFAULT_TRANSLATION_REASONING_EFFORT, DEFAULT_TRANSLATION_THINKING_ENABLED
from .visuals import BACKGROUND, GLASS, INK, MINT, MINT_DARK, MUTED, GlassButton, GlassCard, LiquidBackdrop, apply_windows_backdrop


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
        self._refresh_toolchain()
        self.root.after(100, self._poll)

    def _build_vars(self) -> None:
        self.source_var = tk.StringVar()
        self.template_var = tk.StringVar(value=str(self.tool_root / "templates" / "android-rpgmv"))
        self.app_name_var = tk.StringVar(value="仙肴圣餐超魔改 Ver22")
        self.application_id_var = tk.StringVar(value="com.game2apk.xianyaoshengcanver22")
        self.version_code_var = tk.IntVar(value=8)
        self.version_name_var = tk.StringVar(value="1.3.0")
        self.translate_var = tk.BooleanVar(value=False)
        self.confirm_var = tk.BooleanVar(value=False)
        self.api_key_var = tk.StringVar()
        self.sign_password_var = tk.StringVar()
        self.status_var = tk.StringVar(value="请选择已解包的 RPG Maker MV 游戏目录")
        self.progress_var = tk.DoubleVar(value=0)
        self.toolchain_status_var = tk.StringVar(value="正在检查 Android 构建工具链…")
        self.sdk_dir_var = tk.StringVar()
        self.jdk_dir_var = tk.StringVar()
        self.gradle_home_var = tk.StringVar()

    def _build_ui(self) -> None:
        """Build the glass/liquid desktop surface while keeping widget handles stable."""
        self.root.title("RPG Maker MV → Android APK")
        self.root.geometry("1120x820")
        self.root.minsize(920, 680)
        self.root.configure(bg=BACKGROUND)
        # Keep the client area opaque so Chinese glyphs and thin strokes stay
        # crisp. The liquid backdrop supplies depth without window-wide alpha.
        apply_windows_backdrop(self.root)

        self._backdrop = LiquidBackdrop(self.root)
        self._backdrop.pack(fill="both", expand=True)

        tk.Label(self._backdrop, text="RPG Maker MV  →  Android", bg=BACKGROUND, fg=MINT_DARK, font=("Segoe UI", 23, "bold"), anchor="w").place(relx=0.035, rely=0.025, relwidth=0.7, relheight=0.05)
        tk.Label(self._backdrop, text="安全暂存 · 可选汉化 · 签名构建 · 静态验收", bg=BACKGROUND, fg=MUTED, font=("Segoe UI", 10), anchor="w").place(relx=0.037, rely=0.078, relwidth=0.65, relheight=0.035)
        tk.Label(self._backdrop, text="●  LOCAL · 未联网", bg=BACKGROUND, fg=MINT_DARK, font=("Segoe UI", 9, "bold"), anchor="e").place(relx=0.75, rely=0.04, relwidth=0.21, relheight=0.04)

        source = GlassCard(self._backdrop, "01  项目来源")
        source.place(relx=0.025, rely=0.125, relwidth=0.95, relheight=0.095)
        self.source_var_entry = tk.Entry(source.body, textvariable=self.source_var, bg="#ffffff", fg=INK, relief="flat", highlightthickness=1, highlightbackground="#c9eee2", highlightcolor=MINT, font=("Segoe UI", 10))
        self.source_var_entry.pack(side="left", fill="x", expand=True, padx=(12, 6), pady=8, ipady=6)
        self.inspect_button = GlassButton(source.body, text="检查项目", command=self._inspect)
        self.inspect_button.pack(side="left", padx=(0, 12), pady=8)
        GlassButton(source.body, text="浏览…", command=self._browse_source, bg="#dff6ed", fg=MINT_DARK, activebackground="#bdebdc", activeforeground=MINT_DARK).pack(side="left", padx=(0, 8), pady=8)

        toolchain = GlassCard(self._backdrop, "00  Android 工具链  ·  Release 不内置")
        toolchain.place(relx=0.025, rely=0.225, relwidth=0.95, relheight=0.25)
        tk.Label(toolchain.body, textvariable=self.toolchain_status_var, bg=GLASS, fg=INK, font=("Segoe UI", 9), anchor="w").grid(row=0, column=0, columnspan=4, sticky="ew", padx=12, pady=(2, 5))
        self._glass_path_row(toolchain.body, 1, "SDK", self.sdk_dir_var, "选择 SDK", "Choose Android SDK directory")
        self._glass_path_row(toolchain.body, 2, "JDK", self.jdk_dir_var, "选择 JDK", "Choose JDK directory")
        self._glass_path_row(toolchain.body, 3, "Gradle 缓存", self.gradle_home_var, "选择缓存", "Choose Gradle user directory")
        toolchain.body.columnconfigure(1, weight=1)
        GlassButton(toolchain.body, text="保存并重检", command=self._save_toolchain, bg="#dff6ed", fg=MINT_DARK, activebackground="#bdebdc", activeforeground=MINT_DARK).grid(row=1, column=3, rowspan=2, padx=8, pady=2)
        GlassButton(toolchain.body, text="下载 Android 工具", command=lambda: self._download_tool("android_cmdline_tools"), bg="#dff6ed", fg=MINT_DARK, activebackground="#bdebdc", activeforeground=MINT_DARK).grid(row=3, column=3, padx=8, pady=2)
        GlassButton(toolchain.body, text="下载 JDK 17", command=lambda: self._download_tool("temurin_jdk17"), bg="#dff6ed", fg=MINT_DARK, activebackground="#bdebdc", activeforeground=MINT_DARK).grid(row=4, column=3, padx=8, pady=(2, 4))

        settings = GlassCard(self._backdrop, "02  应用与签名")
        settings.place(relx=0.025, rely=0.50, relwidth=0.365, relheight=0.425)
        form = settings.body
        for row, label, variable in ((0, "应用名", self.app_name_var), (1, "包名", self.application_id_var), (2, "版本", self.version_name_var), (4, "模板", self.template_var)):
            self._glass_form_row(form, row, label, variable)
        tk.Label(form, text="版本号 versionCode", bg=GLASS, fg=INK, anchor="w", font=("Segoe UI", 9)).grid(row=3, column=0, sticky="w", padx=12, pady=3)
        tk.Spinbox(form, from_=1, to=2_147_483_647, textvariable=self.version_code_var, bg="#ffffff", fg=INK, relief="flat", highlightthickness=1, highlightbackground="#c9eee2", highlightcolor=MINT).grid(row=3, column=1, sticky="ew", padx=(4, 12), pady=3, ipady=3)
        tk.Checkbutton(form, text="强制翻译未汉化文本", variable=self.translate_var, bg=GLASS, activebackground=GLASS, fg=INK, selectcolor="#dff6ed", anchor="w", font=("Segoe UI", 9)).grid(row=5, column=0, columnspan=2, sticky="ew", padx=12, pady=3)
        tk.Checkbutton(form, text="确认发送文本给 DeepSeek", variable=self.confirm_var, bg=GLASS, activebackground=GLASS, fg=INK, selectcolor="#dff6ed", anchor="w", font=("Segoe UI", 9)).grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=3)
        self._glass_form_row(form, 7, "DeepSeek Key", self.api_key_var, secret=True)
        self._glass_form_row(form, 8, "签名密码", self.sign_password_var, secret=True)
        form.columnconfigure(1, weight=1)

        report_card = GlassCard(self._backdrop, "03  检查报告 / 构建日志")
        report_card.place(relx=0.41, rely=0.50, relwidth=0.565, relheight=0.425)
        self.report_text = tk.Text(report_card.body, height=18, wrap="word", state="disabled", bg="#ffffff", fg=INK, relief="flat", highlightthickness=1, highlightbackground="#c9eee2", padx=12, pady=10, font=("Cascadia Mono", 9))
        self.report_text.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        controls = tk.Frame(self._backdrop, bg=BACKGROUND)
        controls.place(relx=0.025, rely=0.925, relwidth=0.95, relheight=0.055)
        self.build_button = GlassButton(controls, text="构建并验证", command=self._run_pipeline, state="disabled")
        self.build_button.pack(side="left")
        self.cancel_button = GlassButton(controls, text="取消", command=self._cancel, state="disabled", bg="#dff6ed", fg=MINT_DARK, activebackground="#bdebdc", activeforeground=MINT_DARK)
        self.cancel_button.pack(side="left", padx=8)
        tk.Label(controls, textvariable=self.status_var, bg=BACKGROUND, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(side="left", fill="x", expand=True, padx=12)
        self.progress_bar = ttk.Progressbar(controls, variable=self.progress_var, maximum=100, length=220, mode="determinate")
        self.progress_bar.pack(side="right", padx=4)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    @staticmethod
    def _glass_form_row(parent: tk.Misc, row: int, label: str, variable: tk.Variable, secret: bool = False) -> None:
        tk.Label(parent, text=label, bg=GLASS, fg=INK, anchor="w", font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", padx=12, pady=3)
        entry = tk.Entry(parent, textvariable=variable, show="*" if secret else "", bg="#ffffff", fg=INK, relief="flat", highlightthickness=1, highlightbackground="#c9eee2", highlightcolor=MINT, font=("Segoe UI", 9))
        entry.grid(row=row, column=1, sticky="ew", padx=(4, 12), pady=3, ipady=3)

    def _glass_path_row(self, parent: tk.Misc, row: int, label: str, variable: tk.StringVar, button: str, dialog_title: str) -> None:
        tk.Label(parent, text=label, bg=GLASS, fg=INK, anchor="w", font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", padx=12, pady=2)
        tk.Entry(parent, textvariable=variable, bg="#ffffff", fg=INK, relief="flat", highlightthickness=1, highlightbackground="#c9eee2", highlightcolor=MINT, font=("Segoe UI", 9)).grid(row=row, column=1, sticky="ew", padx=4, pady=2, ipady=3)
        GlassButton(parent, text=button, command=lambda: self._choose_tool_path(variable, dialog_title), bg="#dff6ed", fg=MINT_DARK, activebackground="#bdebdc", activeforeground=MINT_DARK, padx=9, pady=4, font=("Segoe UI", 9)).grid(row=row, column=2, padx=4, pady=2)

    def _build_ui_legacy(self) -> None:
        self.root.title("RPG Maker MV → Android APK")
        self.root.geometry("1040x760")
        self.root.minsize(860, 640)
        self.root.configure(bg="#edf7f2")
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#edf7f2")
        style.configure("Card.TLabelframe", background="#ffffff", bordercolor="#c3ecdf", relief="solid")
        style.configure("Card.TLabelframe.Label", background="#ffffff", foreground="#1d7463", font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background="#edf7f2", foreground="#263e3a")
        style.configure("Title.TLabel", background="#edf7f2", foreground="#1b5d51", font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background="#edf7f2", foreground="#728b85")
        style.configure("Accent.TButton", background="#2eb595", foreground="#ffffff", padding=(14, 8), font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#209278"), ("disabled", "#a9cfc2")])
        style.configure("TButton", padding=(10, 6))
        style.configure("TEntry", fieldbackground="#ffffff")
        style.configure("Horizontal.TProgressbar", troughcolor="#dff6ed", background="#2eb595", bordercolor="#dff6ed", lightcolor="#58c9ad", darkcolor="#209278")
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        title = ttk.Label(outer, text="RPG Maker MV → Android", style="Title.TLabel")
        title.pack(anchor="w")
        ttk.Label(outer, text="安全暂存 · 可选汉化 · 签名构建 · 静态验收", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 14))

        source_frame = ttk.LabelFrame(outer, text="01  项目来源", style="Card.TLabelframe")
        source_frame.pack(fill="x", pady=4)

        toolchain = ttk.LabelFrame(outer, text="00  Android build toolchain (not bundled in Release)", style="Card.TLabelframe")
        toolchain.pack(fill="x", pady=4)
        ttk.Label(toolchain, textvariable=self.toolchain_status_var).grid(row=0, column=0, columnspan=4, sticky="w", padx=8, pady=(6, 3))
        ttk.Label(toolchain, text="SDK").grid(row=1, column=0, sticky="w", padx=8, pady=2)
        ttk.Entry(toolchain, textvariable=self.sdk_dir_var).grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(toolchain, text="Choose", command=lambda: self._choose_tool_path(self.sdk_dir_var, "Choose Android SDK directory")).grid(row=1, column=2, padx=4, pady=2)
        ttk.Label(toolchain, text="JDK").grid(row=2, column=0, sticky="w", padx=8, pady=2)
        ttk.Entry(toolchain, textvariable=self.jdk_dir_var).grid(row=2, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(toolchain, text="Choose", command=lambda: self._choose_tool_path(self.jdk_dir_var, "Choose JDK directory")).grid(row=2, column=2, padx=4, pady=2)
        ttk.Label(toolchain, text="Gradle cache").grid(row=3, column=0, sticky="w", padx=8, pady=2)
        ttk.Entry(toolchain, textvariable=self.gradle_home_var).grid(row=3, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(toolchain, text="Choose", command=lambda: self._choose_tool_path(self.gradle_home_var, "Choose Gradle user directory")).grid(row=3, column=2, padx=4, pady=2)
        ttk.Button(toolchain, text="Save and recheck", command=self._save_toolchain).grid(row=1, column=3, rowspan=2, padx=8, pady=2)
        ttk.Button(toolchain, text="Download Android tools", command=lambda: self._download_tool("android_cmdline_tools")).grid(row=3, column=3, padx=8, pady=2)
        ttk.Button(toolchain, text="Download JDK 17", command=lambda: self._download_tool("temurin_jdk17")).grid(row=4, column=3, padx=8, pady=(2, 6))
        toolchain.columnconfigure(1, weight=1)
        ttk.Entry(source_frame, textvariable=self.source_var).pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(source_frame, text="浏览…", command=self._browse_source).pack(side="left", padx=6)
        self.inspect_button = ttk.Button(source_frame, text="检查", command=self._inspect)
        self.inspect_button.pack(side="left", padx=(0, 6))

        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True, pady=8)
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.rowconfigure(0, weight=1)
        report_card = ttk.LabelFrame(content, text="检查报告 / 构建日志", style="Card.TLabelframe")
        report_card.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        self.report_text = tk.Text(report_card, height=16, wrap="word", state="disabled", bg="#ffffff", fg="#263e3a", relief="flat", padx=10, pady=8, font=("Consolas", 10))
        self.report_text.pack(fill="both", expand=True, padx=6, pady=6)

        settings = ttk.LabelFrame(content, text="02  应用与签名", style="Card.TLabelframe")
        settings.grid(row=0, column=0, sticky="new")
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
        self.build_button = ttk.Button(controls, text="构建并验证", style="Accent.TButton", command=self._run_pipeline, state="disabled")
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

    def _choose_tool_path(self, variable: tk.StringVar, title: str) -> None:
        value = filedialog.askdirectory(title=title)
        if value:
            variable.set(value)

    def _refresh_toolchain(self) -> None:
        saved = load_config()
        self.sdk_dir_var.set(saved.get("sdk_dir", ""))
        self.jdk_dir_var.set(saved.get("jdk_dir", ""))
        self.gradle_home_var.set(saved.get("gradle_user_home", ""))
        try:
            info = discover_configured(self.template_var.get())
            if not self.sdk_dir_var.get() and info.sdk_dir:
                self.sdk_dir_var.set(info.sdk_dir)
            if not self.jdk_dir_var.get() and info.jdk_dir:
                self.jdk_dir_var.set(info.jdk_dir)
            if not self.gradle_home_var.get() and info.gradle_user_home:
                self.gradle_home_var.set(info.gradle_user_home)
            missing = missing_components(info)
            if missing:
                self.toolchain_status_var.set("Missing: " + ", ".join(missing) + ". Choose folders or explicitly download.")
            else:
                self.toolchain_status_var.set("Toolchain ready: SDK, JDK, aapt2, zipalign, apksigner and Gradle wrapper (adb optional)")
        except Exception as exc:
            self.toolchain_status_var.set(f"Toolchain check failed: {exc}")

    def _save_toolchain(self) -> None:
        save_config({"sdk_dir": self.sdk_dir_var.get(), "jdk_dir": self.jdk_dir_var.get(), "gradle_user_home": self.gradle_home_var.get()})
        self._refresh_toolchain()

    def _download_tool(self, component_name: str) -> None:
        component = COMPONENTS[component_name]
        target = filedialog.askdirectory(title=f"Choose install directory for {component['label']}")
        if not target:
            return
        if not messagebox.askyesno("Confirm download", f"Download {component['label']} from official host {component['host']}?\nNo API keys or credentials are sent."):
            return
        self.status_var.set(f"Downloading {component['label']}…")
        self.cancel_button.configure(state="normal")
        self.cancel_event.clear()

        def worker() -> None:
            try:
                result = download_component(component_name, target, confirm=lambda _message: True, progress=lambda done, total: self.queue.put(("download", (done, total))))
                self.queue.put(("download_complete", (component_name, result)))
            except Exception as exc:
                self.queue.put(("error", exc))

        self.executor.submit(worker)

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
            translate_requested = bool(settings["translate"])
            resume_key = self.service.build_resume_key(
                self.inspection,
                str(settings["template"]),
                config,
                translate=translate_requested,
                thinking_enabled=DEFAULT_TRANSLATION_THINKING_ENABLED,
                reasoning_effort=DEFAULT_TRANSLATION_REASONING_EFFORT,
            )
            stage = self.service.stage(self.inspection, resume=True, resume_key=resume_key)
            resumed = bool(stage.resumed_from_existing)
            if not resumed:
                self.service.patch(stage, config)
            if translate_requested and not resumed:
                if not bool(settings["confirm"]):
                    raise Game2ApkError("翻译前必须勾选第三方 DeepSeek 发送确认")
                self.service.translate(stage, api_key=settings["api_key"], confirmed_third_party=True, force=True)
            if not resumed:
                self.service.mark_prepared(stage)
            configured_tools = discover_configured(str(settings["template"]))
            # adb is useful for optional device install/diagnostics but is not
            # required to assemble or sign a release APK.
            missing = [item for item in missing_components(configured_tools) if item != "adb"]
            if missing:
                raise Game2ApkError("Android 构建工具链未就绪：" + ", ".join(missing) + "。请先在顶部选择/安装并保存路径。")
            result = self.service.build(str(settings["template"]), stage, config, toolchain=configured_tools, api_key=settings["api_key"])
            if result.return_code != 0 or not result.apk_path:
                raise Game2ApkError(f"Gradle 构建失败，退出码 {result.return_code}；日志：{result.log_path}")
            self.service.sign(result, config, password=settings["sign_password"])
            verification = self.service.verify(result, config, install=False)
            promoted = self.service.promote(verification, config) if verification.signature_candidate and verification.passed else None
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
                elif event == "download":
                    done, total = value
                    self.progress_var.set((float(done) / float(total) * 100) if total else 0)
                    self.status_var.set(f"Downloading toolchain: {done // (1024 * 1024)} MiB")
                elif event == "download_complete":
                    component_name, result = value
                    self.cancel_button.configure(state="disabled")
                    if component_name == "android_cmdline_tools":
                        self.sdk_dir_var.set(str(result.extracted_to))
                        self._save_toolchain()
                    elif component_name == "temurin_jdk17":
                        self.jdk_dir_var.set(str(result.extracted_to))
                        self._save_toolchain()
                    self.status_var.set(f"Downloaded {COMPONENTS[component_name]['label']} to {result.extracted_to}")
                    messagebox.showinfo("Toolchain download", "Download and extraction complete. Android command-line tools only provide sdkmanager; install an Android platform and build-tools package with sdkmanager before building. The app does not silently install packages.")
                    self._refresh_toolchain()
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
                    self._show_report(self.report_text.get("1.0", "end") + f"\n\n签名 APK：{result.apk_path}\n静态签名候选：{verification.signature_candidate}\nSHA-256：{verification.sha256}{promoted_text}")
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
