(() => {
  const $ = (selector) => document.querySelector(selector);
  const healthPill = $("#health-pill");
  const state = $("#toolchain-state");
  const report = $("#report-log");
  const reportState = $("#report-state");
  const buildButton = document.querySelector('[data-action="build"]');
  const root = document.documentElement;

  const setHealth = (kind, label) => {
    healthPill.className = `status-pill status-${kind}`;
    healthPill.innerHTML = `<i></i>${label}`;
  };

  const renderToolchain = (payload) => {
    const ready = Boolean(payload && payload.ready);
    setHealth(ready ? "ready" : "pending", ready ? "工具链已就绪" : "需要配置工具链");
    state.className = `callout ${ready ? "ready" : "pending"}`;
    state.querySelector("strong").textContent = ready ? "检测到本机 Android 工具" : "未发现完整工具链";
    state.querySelector("small").textContent = ready ? "将直接调用，不会重复下载" : "可手动选择目录，或确认下载官方工具";
    $("#sdk-path").textContent = payload?.sdk_dir || "未发现";
    $("#jdk-path").textContent = payload?.jdk_dir || "未发现";
    $("#gradle-path").textContent = payload?.gradle_user_home || "用户目录缓存";
  };

  const log = (title, detail) => {
    // Keep user-entered paths as text nodes.  The shell is loopback-only, but
    // a project folder name must never become HTML in the report panel.
    report.replaceChildren();
    const entry = document.createElement("div");
    entry.className = "log-entry";
    const heading = document.createElement("strong");
    heading.textContent = title;
    const description = document.createElement("small");
    description.textContent = detail;
    entry.append(heading, description);
    report.append(entry);
    reportState.textContent = title;
  };

  const requestHealth = async () => {
    try {
      const response = await fetch("/api/health", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      renderToolchain(await response.json());
    } catch (_) {
      // Opening index.html directly is still a useful visual preview.  The
      // canonical build path remains the Tk GUI when no local bridge exists.
      setHealth("pending", "浏览器预览模式");
      state.className = "callout pending";
      state.querySelector("strong").textContent = "等待桌面桥接";
      state.querySelector("small").textContent = "使用 game2apk-tool.exe 打开完整构建向导";
    }
  };

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => {
      const action = button.dataset.action;
      if (action === "toggle-motion") {
        const reduced = root.dataset.reduceMotion === "true";
        root.dataset.reduceMotion = String(!reduced);
        button.setAttribute("aria-label", reduced ? "减少动效" : "恢复动效");
      } else if (action === "inspect") {
        const source = $("#source-path").value.trim();
        if (!source) { log("需要项目路径", "请先在桌面版选择 RPG Maker MV 项目目录"); return; }
        log("检查请求已发送", source);
        fetch("/api/inspect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source }) }).catch(() => {});
        buildButton.disabled = false;
      } else if (action === "download") {
        log("需要确认下载", "桌面版会弹出官方 HTTPS 下载确认框");
      } else if (action === "configure") {
        log("手动配置", "请使用桌面版工具链卡片选择 SDK、JDK 和 Gradle 目录");
      } else if (action === "choose-source") {
        log("浏览器限制", "浏览器预览不能读取本地路径；请使用桌面版选择目录");
      } else if (action === "build") {
        log("构建仍由桌面桥接执行", "前端不会在浏览器内执行 Gradle 或读取游戏资源");
      }
    });
  });
  requestHealth();
})();
