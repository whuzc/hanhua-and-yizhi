(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const healthPill = $("#health-pill");
  const toolchainState = $("#toolchain-state");
  const report = $("#report-log");
  const reportState = $("#report-state");
  const inspectButton = $("#inspect-button");
  const buildButton = $("#build-button");
  const cancelButton = $("#cancel-button");
  const progressFill = $("#progress-fill");
  const progressLabel = $("#progress-label");
  const progressValue = $("#progress-value");
  const thinkingMode = $("#translation-thinking");
  const reasoningEffort = $("#translation-effort");
  const thinkingHint = $("#translation-thinking-hint");
  const translationToggle = $("#translate-toggle");
  const translationConfirm = $("#translation-confirm");
  const translationOptions = $("#translation-options");
  const translationDetection = $("#translation-detection");
  const downloadButtons = [$("#download-android"), $("#download-jdk")];
  const root = document.documentElement;

  // Keep the report useful during long translation/build runs.  The backend
  // only publishes the current job state; this bounded client-side window
  // prevents an ever-growing DOM when a task emits many progress messages.
  const MAX_LOG_ENTRIES = 80;
  const MAX_LOG_CHARS = 24000;
  const MAX_LOG_TITLE_CHARS = 240;
  const MAX_LOG_DETAIL_CHARS = 4200;
  const REPORT_SCROLL_THRESHOLD_PX = 28;

  let currentJobId = null;
  let currentJobKind = null;
  let pollTimer = null;
  let heartbeatTimer = null;
  let inspected = false;
  let lastJobMessage = "";
  let reportStickToBottom = true;
  let pollFailureCount = 0;

  const setText = (node, value) => { node.textContent = value == null ? "" : String(value); };

  const errorMessage = (payload, fallback) => {
    if (payload && typeof payload === "object") {
      if (typeof payload.error === "string") return payload.error;
      if (typeof payload.message === "string") return payload.message;
    }
    return fallback;
  };

  const api = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    const request = { ...options, headers, credentials: "same-origin" };
    // Jobs require the same in-page marker on polling GETs as mutations.
    // Health is public, but sending the marker uniformly also makes a future
    // protected read endpoint safe without a frontend special case.
    if (path.startsWith("/api/")) headers.set("X-Game2Apk-Request", "1");
    if (request.method && request.method !== "GET") {
      if (request.body !== undefined && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, request);
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* backend failures may be plain text */ }
    if (!response.ok) throw new Error(errorMessage(payload, `本地后台返回 HTTP ${response.status}`));
    return payload || {};
  };

  const apiRetry = async (path, options = {}, attempts = 2) => {
    let lastError;
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      try {
        return await api(path, options);
      } catch (error) {
        lastError = error;
        if (attempt + 1 < attempts) await new Promise((resolve) => window.setTimeout(resolve, 350));
      }
    }
    throw lastError || new Error("local backend request failed");
  };

  const setHealth = (kind, label) => {
    healthPill.className = `status-pill status-${kind}`;
    setText(healthPill.querySelector("span"), label);
  };

  const setProgress = (fraction, label) => {
    const safeFraction = Math.max(0, Math.min(1, Number(fraction) || 0));
    progressFill.style.width = `${Math.round(safeFraction * 100)}%`;
    setText(progressValue, `${Math.round(safeFraction * 100)}%`);
    if (label) setText(progressLabel, label);
  };

  const setTaskButtons = (running) => {
    inspectButton.disabled = running;
    buildButton.disabled = running || !inspected;
    cancelButton.disabled = !running;
    downloadButtons.forEach((button) => { button.disabled = running; });
  };

  const resetTranslationChoice = (available) => {
    translationToggle.disabled = !available;
    if (!available) {
      translationToggle.checked = false;
      translationConfirm.checked = false;
      translationOptions.hidden = true;
    }
  };

  const renderTranslationDetection = (profile) => {
    if (!translationDetection) return;
    const detected = profile && profile.status === "detected";
    const likelyChinese = Boolean(profile?.likelyChinese || profile?.predominantlyChinese);
    translationDetection.className = `callout translation-detection ${detected && likelyChinese ? "ready" : "pending"}`;
    translationDetection.dataset.languageState = detected ? (likelyChinese ? "chinese" : "mixed") : "unknown";
    const ratio = Number(profile?.hanRatio);
    const ratioText = Number.isFinite(ratio) ? `汉字比例约 ${(ratio * 100).toFixed(1)}%` : "未取得比例";
    setText(
      translationDetection.querySelector("strong"),
      detected ? (likelyChinese ? `检测到已有中文（${ratioText}）` : `未检测到明显中文（${ratioText}）`) : "项目语言暂时无法判断",
    );
    setText(
      translationDetection.querySelector("small"),
      detected && likelyChinese
        ? "默认不翻译；如确实需要，请手动勾选 DeepSeek 翻译并确认第三方传输。"
        : "翻译是可选功能，默认关闭；需要时手动勾选并确认第三方传输。",
    );
    resetTranslationChoice(true);
  };

  const isReportNearBottom = () => (
    report.scrollHeight - report.scrollTop - report.clientHeight <= REPORT_SCROLL_THRESHOLD_PX
  );

  const updateReportScrollMode = () => {
    reportStickToBottom = isReportNearBottom();
    // This state is useful to screen-reader and automated UI consumers, while
    // avoiding an intrusive visible "follow" control for the compact panel.
    report.dataset.following = String(reportStickToBottom);
  };

  const clearLog = () => {
    report.replaceChildren();
    reportStickToBottom = true;
    report.dataset.following = "true";
  };

  const truncateLogText = (value, limit) => {
    const text = value == null ? "" : String(value);
    if (text.length <= limit) return text;
    return `${text.slice(0, Math.max(0, limit - 22))}\n…（内容过长，已截断）`;
  };

  const updateReportCount = () => {
    const entries = report.querySelectorAll(".log-entry");
    const count = entries.length;
    const chars = report.textContent.length;
    report.dataset.logCount = String(count);
    report.dataset.logChars = String(chars);
    report.setAttribute(
      "aria-label",
      `构建报告，保留 ${count} 条日志，约 ${chars} 个字符${reportStickToBottom ? "，自动跟随最新进度" : "，已暂停自动滚动"}`,
    );
  };

  const log = (title, detail = "", kind = "info") => {
    if (report.querySelector(".empty-state")) clearLog();
    const shouldStick = reportStickToBottom || isReportNearBottom();
    const previousScrollTop = report.scrollTop;
    const titleText = truncateLogText(title, MAX_LOG_TITLE_CHARS);
    const detailText = truncateLogText(detail, MAX_LOG_DETAIL_CHARS);
    const entry = document.createElement("article");
    entry.className = `log-entry log-${kind}`;
    const heading = document.createElement("strong");
    const description = document.createElement("small");
    setText(heading, titleText);
    setText(description, detailText);
    entry.append(heading, description);
    report.append(entry);
    let removedHeight = 0;
    while (report.children.length > MAX_LOG_ENTRIES || report.textContent.length > MAX_LOG_CHARS) {
      const first = report.querySelector(".log-entry");
      if (!first) break;
      // Preserve the reader's approximate viewport when old entries are
      // evicted while they are manually browsing an earlier portion.
      removedHeight += first.getBoundingClientRect().height;
      first.remove();
    }
    if (shouldStick) {
      report.scrollTop = report.scrollHeight;
      reportStickToBottom = true;
    } else {
      report.scrollTop = Math.max(0, previousScrollTop - removedHeight);
      reportStickToBottom = false;
    }
    report.dataset.following = String(reportStickToBottom);
    updateReportCount();
    setText(reportState, titleText);
  };

  const readablePath = (value, fallback) => value && String(value).trim() ? String(value) : fallback;

  const renderToolchain = (payload) => {
    const ready = Boolean(payload && payload.ready);
    setHealth(ready ? "ready" : "pending", ready ? "本地后台已就绪" : "需要配置工具链");
    toolchainState.className = `callout ${ready ? "ready" : "pending"}`;
    setText(toolchainState.querySelector("strong"), ready ? "检测到完整 Android 工具链" : "未检测到完整 Android 工具链");
    const missing = Array.isArray(payload?.missing) ? payload.missing : [];
    setText(toolchainState.querySelector("small"), ready ? "将直接调用本机安装；不会重复下载" : (missing.length ? `缺少：${missing.join("、")}` : "可手动选择 SDK、JDK 和 Gradle 用户缓存目录"));
    $("#sdk-path").value = readablePath(payload?.sdk_dir, "");
    $("#jdk-path").value = readablePath(payload?.jdk_dir, "");
    $("#gradle-path").value = readablePath(payload?.gradle_user_home, "");
    const cacheHint = $("#gradle-cache-hint");
    if (cacheHint) {
      const shared = payload?.gradle_user_home_scope !== "project";
      cacheHint.dataset.cacheScope = shared ? "shared" : "project";
      setText(cacheHint.querySelector("strong"), shared ? "通用缓存 · 多项目共用" : "项目缓存 · 仅本次构建");
      setText(
        cacheHint.querySelector("span"),
        shared
          ? "构建完成后不自动删除；Gradle 会复用依赖，后续游戏可避免重复下载。"
          : "构建完成后可安全清理；这是项目临时缓存，不影响其他游戏。",
      );
    }
  };

  const refreshToolchain = async (announce = false) => {
    try {
      const payload = await api("/api/health", { headers: { Accept: "application/json" } });
      renderToolchain(payload);
      if (announce) log("工具链检查完成", payload.ready ? "SDK、JDK、aapt2、zipalign、apksigner 和 Gradle wrapper 均可用。" : "可在本页保存目录后重新检查。", payload.ready ? "success" : "warn");
      return payload;
    } catch (error) {
      setHealth("error", "未连接到本地后台");
      toolchainState.className = "callout error";
      setText(toolchainState.querySelector("strong"), "浏览器前端未连接到后台");
      setText(toolchainState.querySelector("small"), "请从 game2apk-ui.exe 启动，而不是直接打开 HTML 或使用旧 --web 预览入口。");
      setTaskButtons(false);
      inspectButton.disabled = true;
      log("无法连接本地后台", error instanceof Error ? error.message : "请重新启动 game2apk-ui.exe", "error");
      return null;
    }
  };

  const fieldForBrowseKind = {
    source: "#source-path",
    template: "#template-path",
    sdk: "#sdk-path",
    jdk: "#jdk-path",
    gradle: "#gradle-path",
  };

  const browse = async (kind) => {
    const selector = fieldForBrowseKind[kind];
    if (!selector) return;
    const field = $(selector);
    const initialDir = field.value.trim();
    try {
      const payload = await apiRetry("/api/browse", {
        method: "POST",
        body: JSON.stringify(initialDir ? { kind, initial_dir: initialDir } : { kind }),
      }, 3);
      if (payload.selected && typeof payload.path === "string") {
        field.value = payload.path;
        if (kind === "source") {
          inspected = false;
          if (!currentJobId) buildButton.disabled = true;
        }
        log("已选择目录", payload.path, "success");
      } else {
        log("未更改目录", "已取消本机目录选择。", "info");
      }
    } catch (error) {
      log("目录选择失败", error instanceof Error ? error.message : "无法打开本机目录选择器。", "error");
    }
  };

  const saveToolchain = async () => {
    try {
      const payload = await api("/api/toolchain", {
        method: "POST",
        body: JSON.stringify({
          sdk_dir: $("#sdk-path").value.trim(),
          jdk_dir: $("#jdk-path").value.trim(),
          gradle_user_home: $("#gradle-path").value.trim(),
        }),
      });
      renderToolchain(payload.health || payload);
      log("工具链已保存并重检", payload.ready || payload.health?.ready ? "可开始构建。" : "配置已保存；仍有缺失组件，请按提示补齐。", payload.ready || payload.health?.ready ? "success" : "warn");
    } catch (error) {
      log("无法保存工具链配置", error instanceof Error ? error.message : "请检查目录后重试。", "error");
    }
  };

  const downloadToolchain = async (component, label, vendor) => {
    if (currentJobId) return;
    try {
      const chosen = await api("/api/browse", {
        method: "POST",
        body: JSON.stringify({ kind: "download" }),
      });
      if (!chosen.selected || typeof chosen.path !== "string") {
        log("未开始下载", "已取消安装目录选择。", "info");
        return;
      }
      const confirmed = window.confirm(`将从 ${vendor} 官方 HTTPS 下载 ${label}，并解压到：\n${chosen.path}\n\nCommand-line Tools 下载后仍需使用 sdkmanager 安装 platform/build-tools。是否继续？`);
      if (!confirmed) {
        log("未开始下载", "已取消官方工具下载确认。", "info");
        return;
      }
      void startJob("/api/download", { component, destination: chosen.path, confirm: true }, "download");
    } catch (error) {
      log("工具下载准备失败", error instanceof Error ? error.message : "无法打开安装目录选择器。", "error");
    }
  };

  const jobIdFrom = (payload) => {
    const candidate = payload?.job;
    if (typeof candidate === "string" && candidate) return candidate;
    if (candidate && typeof candidate.id === "string" && candidate.id) return candidate.id;
    if (typeof payload?.id === "string" && payload.id) return payload.id;
    throw new Error("后台没有返回任务编号");
  };

  const jsonPreview = (value) => {
    if (!value || typeof value !== "object") return value == null ? "" : String(value);
    const scrubbed = JSON.parse(JSON.stringify(value, (key, item) => (/password|secret|token|key/i.test(key) ? "[已隐藏]" : item)));
    return JSON.stringify(scrubbed, null, 2);
  };

  const finishJob = (job) => {
    const status = job.status;
    currentJobId = null;
    currentJobKind = null;
    pollFailureCount = 0;
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    if (status === "completed") {
      setProgress(1, "任务完成");
      const result = job.result || {};
      if (job.kind === "inspect") {
        const inspection = result.inspection || result;
        inspected = typeof result.buildReady === "boolean" ? result.buildReady : inspection?.status !== "blocked";
        renderTranslationDetection(result.translation);
        log(inspected ? "检查通过" : "检查被阻止", jsonPreview(inspection), inspected ? "success" : "error");
      } else if (job.kind === "download") {
        if (result.health) renderToolchain(result.health);
        log("工具下载并解压完成", jsonPreview(result), "success");
      } else {
        log("构建流程完成", jsonPreview(result), "success");
      }
      setText(reportState, job.kind === "inspect" ? (inspected ? "检查通过" : "检查失败") : (job.kind === "download" ? "工具链已更新" : "构建完成"));
    } else if (status === "cancelled") {
      setProgress(Number(job.fraction) || 0, "任务已取消");
      log("任务已取消", job.message || "后台已安全停止当前工作。", "warn");
    } else {
      setProgress(Number(job.fraction) || 0, "任务失败");
      log("任务失败", job.error || job.message || "后台没有提供更多错误信息。", "error");
    }
    setTaskButtons(false);
  };

  const renderJob = (job) => {
    const fraction = Number(job.fraction);
    setProgress(Number.isFinite(fraction) ? fraction : 0, job.message || job.stage || "正在处理");
    const detail = `${job.stage || "任务"} · ${job.message || "正在处理"}`;
    if (detail !== lastJobMessage) {
      lastJobMessage = detail;
      log(job.stage || "任务进行中", job.message || "正在处理", "info");
    }
    if (["completed", "failed", "cancelled"].includes(job.status)) finishJob(job);
  };

  const pollJob = async (jobId) => {
    try {
      const payload = await api(`/api/jobs/${encodeURIComponent(jobId)}`, { headers: { Accept: "application/json" } });
      pollFailureCount = 0;
      const job = payload.job || payload;
      renderJob(job);
      if (currentJobId === jobId && !["completed", "failed", "cancelled"].includes(job.status)) {
        pollTimer = window.setTimeout(() => pollJob(jobId), 500);
      }
    } catch (error) {
      if (currentJobId === jobId) {
        pollFailureCount += 1;
        const retryDelay = Math.min(5000, 500 * (2 ** Math.min(3, pollFailureCount - 1)));
        if ([1, 3, 6, 12].includes(pollFailureCount)) {
          log("后台连接暂时中断，正在重试", `${error instanceof Error ? error.message : "Failed to fetch"}；第 ${pollFailureCount} 次重试`, "warn");
        }
        setText(reportState, "后台重连中");
        if (pollFailureCount < 12) {
          pollTimer = window.setTimeout(() => pollJob(jobId), retryDelay);
        } else {
          currentJobId = null;
          log("无法读取任务状态", "后台可能已关闭，请重新启动 game2apk-ui.exe；任务结果需重新检查。", "error");
          setTaskButtons(false);
        }
      }
    }
  };

  const startJob = async (path, body, kind) => {
    if (currentJobId) return;
    setTaskButtons(true);
    setProgress(0, "正在提交任务");
    lastJobMessage = "";
    try {
      const payload = await api(path, { method: "POST", body: JSON.stringify(body) });
      const jobId = jobIdFrom(payload);
      currentJobId = jobId;
      currentJobKind = kind;
      pollFailureCount = 0;
      const title = kind === "inspect" ? "已提交检查" : (kind === "download" ? "已提交工具下载" : "已提交构建");
      log(title, `任务编号：${jobId}`, "info");
      void pollJob(jobId);
    } catch (error) {
      setTaskButtons(false);
      log("无法提交任务", error instanceof Error ? error.message : "请检查输入后重试。", "error");
    }
  };

  const inspect = () => {
    const source = $("#source-path").value.trim();
    if (!source) { log("需要项目路径", "请先点击“浏览目录”选择游戏根目录或 www 目录。", "warn"); return; }
    inspected = false;
    resetTranslationChoice(false);
    buildButton.disabled = true;
    void startJob("/api/inspect", { source }, "inspect");
  };

  const build = () => {
    if (!inspected) { log("需要先通过检查", "请先检查当前项目；目录或项目变更后需要重新检查。", "warn"); return; }
    const source = $("#source-path").value.trim();
    const translate = $("#translate-toggle").checked;
    const confirm = $("#translation-confirm").checked;
    if (translate && !confirm) { log("需要翻译确认", "启用 DeepSeek 前必须确认会向第三方发送待翻译文本。", "warn"); return; }
    const versionCode = Number.parseInt($("#version-code").value, 10);
    if (!Number.isSafeInteger(versionCode) || versionCode < 1) { log("版本号无效", "Version code 必须是大于 0 的整数。", "warn"); return; }
    const payload = {
      source,
      app_name: $("#app-name").value.trim(),
      application_id: $("#application-id").value.trim(),
      version_name: $("#version-name").value.trim(),
      version_code: versionCode,
      translate,
      confirm,
      thinking_enabled: thinkingMode.value === "enabled",
      reasoning_effort: reasoningEffort.value,
    };
    const template = $("#template-path").value.trim();
    const deepseekKey = $("#deepseek-key").value;
    const signPassword = $("#sign-password").value;
    if (template) payload.template = template;
    if (deepseekKey) payload["api" + "_key"] = deepseekKey;
    if (signPassword) payload["sign" + "_password"] = signPassword;
    void startJob("/api/build", payload, "build");
  };

  const cancel = async () => {
    if (!currentJobId) return;
    cancelButton.disabled = true;
    try {
      await api(`/api/jobs/${encodeURIComponent(currentJobId)}/cancel`, { method: "POST", body: "{}" });
      log("已请求取消", "等待后台安全停止当前阶段。", "warn");
    } catch (error) {
      cancelButton.disabled = false;
      log("取消请求失败", error instanceof Error ? error.message : "任务可能仍在执行。", "error");
    }
  };

  const heartbeat = async () => {
    try { await api("/api/heartbeat", { method: "POST", body: "{}" }); } catch (_) { /* health polling reports visible failures */ }
  };

  const init = async () => {
    // Follow live progress only while the reader is already at the bottom.
    // Scrolling upward turns the report into a stable viewport until the
    // reader returns near the end, so rapid polling never steals their place.
    report.addEventListener("scroll", updateReportScrollMode, { passive: true });
    updateReportCount();
    $("#motion-button").addEventListener("click", () => {
      const reduce = root.dataset.reduceMotion !== "true";
      root.dataset.reduceMotion = String(reduce);
      $("#motion-button").setAttribute("aria-label", reduce ? "恢复动效" : "减少动效");
      $("#motion-button").title = reduce ? "恢复动效" : "减少动效";
    });
    document.querySelectorAll("[data-browse-kind]").forEach((button) => button.addEventListener("click", () => void browse(button.dataset.browseKind)));
    $("#save-toolchain").addEventListener("click", () => void saveToolchain());
    $("#refresh-toolchain").addEventListener("click", () => void refreshToolchain(true));
    $("#download-android").addEventListener("click", () => void downloadToolchain("android_cmdline_tools", "Android Command-line Tools", "Google"));
    $("#download-jdk").addEventListener("click", () => void downloadToolchain("temurin_jdk17", "Temurin JDK 17", "Eclipse Adoptium"));
    inspectButton.addEventListener("click", inspect);
    buildButton.addEventListener("click", build);
    cancelButton.addEventListener("click", () => void cancel());
    // Inspection is tied to the exact source path.  Changing it after a
    // successful check must not unlock a build for a different project.
    const sourceField = $("#source-path");
    sourceField.addEventListener("input", () => {
      inspected = false;
      resetTranslationChoice(false);
      if (!currentJobId) buildButton.disabled = true;
    });
    translationToggle.addEventListener("change", (event) => { translationOptions.hidden = !event.target.checked; });
    const updateThinkingControls = () => {
      const enabled = thinkingMode.value === "enabled";
      reasoningEffort.disabled = !enabled;
      setText(
        thinkingHint,
        enabled
          ? "开启思考模式会使用 DeepSeek V4 Flash 的推理预算；强度越高，通常越自然但耗时越长。"
          : "已关闭思考模式，使用速度优先的直接翻译；强度设置不会发送给 API。",
      );
    };
    thinkingMode.addEventListener("change", updateThinkingControls);
    updateThinkingControls();
    resetTranslationChoice(false);
    await refreshToolchain();
    void heartbeat();
    heartbeatTimer = window.setInterval(() => void heartbeat(), 5000);
  };

  window.addEventListener("pagehide", () => {
    if (heartbeatTimer) window.clearInterval(heartbeatTimer);
    // The backend has an idle heartbeat timeout.  Avoid a hard shutdown here:
    // pagehide also fires on a normal browser refresh, where an immediate
    // shutdown would make the replacement page fail to reconnect.
  });

  void init();
})();
