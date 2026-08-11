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
  const cheatVariableState = $("#cheat-variable-state");
  const cheatVariableCallout = $("#cheat-variable-callout");
  const cheatVariableList = $("#cheat-variable-list");
  const cheatVariableSummary = $("#cheat-variable-summary");
  const cheatVariableSearch = $("#cheat-variable-search");
  const prepareCheatVariablesButton = $("#prepare-cheat-variables");
  const selectAllCheatVariablesButton = $("#select-all-cheat-variables");
  const clearCheatVariablesButton = $("#clear-cheat-variables");
  const layoutPreview = $("#layout-preview");
  const layoutState = $("#layout-state");
  const layoutSelect = $("#layout-button-select");
  const layoutLabel = $("#layout-button-label");
  const layoutKey = $("#layout-button-key");
  const layoutMode = $("#layout-button-mode");
  const layoutVisible = $("#layout-button-visible");
  const layoutAddButton = $("#layout-add-button");
  const layoutResetButton = $("#layout-reset-button");
  const layoutSaveButton = $("#layout-save-button");
  const layoutDeleteButton = $("#layout-delete-button");
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
  let cheatLabelsNeedTranslation = false;
  let cheatCatalogKnown = false;
  let cheatCatalogStatus = "idle";
  let cheatCatalogStatusBeforeJob = "idle";
  let cheatVariableItems = [];
  let selectedCheatVariableIds = new Set();
  let lastJobMessage = "";
  let reportStickToBottom = true;
  let pollFailureCount = 0;
  const DEFAULT_LAYOUT_BUTTONS = [
    { id: "left", label: "←", keyCode: 37, mode: "hold", x: 0.04, y: 0.80, width: 0.10, height: 0.12, visible: true },
    { id: "up", label: "↑", keyCode: 38, mode: "hold", x: 0.15, y: 0.67, width: 0.10, height: 0.12, visible: true },
    { id: "down", label: "↓", keyCode: 40, mode: "hold", x: 0.15, y: 0.82, width: 0.10, height: 0.12, visible: true },
    { id: "right", label: "→", keyCode: 39, mode: "hold", x: 0.26, y: 0.80, width: 0.10, height: 0.12, visible: true },
    { id: "confirm", label: "OK", keyCode: 13, mode: "tap", x: 0.67, y: 0.58, width: 0.14, height: 0.10, visible: true },
    { id: "cancel", label: "X", keyCode: 88, mode: "tap", x: 0.83, y: 0.58, width: 0.14, height: 0.10, visible: true },
    { id: "esc", label: "ESC", keyCode: 27, mode: "tap", x: 0.67, y: 0.71, width: 0.14, height: 0.10, visible: true },
    { id: "portrait", label: "A", keyCode: 65, mode: "tap", x: 0.83, y: 0.71, width: 0.14, height: 0.10, visible: true },
  ];
  let layoutButtons = DEFAULT_LAYOUT_BUTTONS.map((button) => ({ ...button }));
  let selectedLayoutId = "confirm";
  let layoutDrag = null;

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
    const cheatCatalogPending = cheatCatalogKnown
      && cheatCatalogStatus !== "ready"
      && cheatCatalogStatus !== "unavailable";
    buildButton.disabled = running || !inspected || cheatCatalogPending;
    cancelButton.disabled = !running;
    downloadButtons.forEach((button) => { button.disabled = running; });
    [layoutAddButton, layoutResetButton, layoutSaveButton, layoutDeleteButton,
      layoutSelect, layoutLabel, layoutKey, layoutMode, layoutVisible]
      .forEach((control) => { if (control) control.disabled = running; });
    updateCheatVariableControls(running);
  };

  const resetTranslationChoice = (available) => {
    translationToggle.disabled = !available;
    if (!available) cheatLabelsNeedTranslation = false;
    if (!available) {
      translationToggle.checked = false;
      translationConfirm.checked = false;
      translationOptions.hidden = true;
    } else {
      // The options contain the mandatory cheat-label translation key and
      // confirmation, so they remain visible even when full game-text
      // translation is left unchecked.
      translationOptions.hidden = false;
    }
  };

  const renderTranslationDetection = (profile) => {
    if (!translationDetection) return;
    cheatLabelsNeedTranslation = Boolean(profile?.cheatLabelsNeedTranslation);
    const detected = profile && profile.status === "detected";
    const likelyChinese = Boolean(profile?.likelyChinese || profile?.predominantlyChinese);
    translationDetection.className = `callout translation-detection ${detected && likelyChinese ? "ready" : "pending"}`;
    translationDetection.dataset.languageState = detected ? (likelyChinese ? "chinese" : "mixed") : "unknown";
    const ratio = Number(profile?.hanRatio);
    const ratioText = Number.isFinite(ratio) ? `\u6c49\u5b57\u6bd4\u4f8b\u7ea6 ${(ratio * 100).toFixed(1)}%` : "\u672a\u53d6\u5f97\u6bd4\u4f8b";
    const candidateCount = Number(profile?.nonChineseEntries);
    const candidateText = Number.isFinite(candidateCount)
      ? `\u5c06\u4ec5\u7ffb\u8bd1 ${candidateCount} \u4e2a\u975e\u4e2d\u6587\u5757`
      : "\u5c06\u4ec5\u7ffb\u8bd1\u975e\u4e2d\u6587\u6587\u672c";
    const cheatText = profile?.cheatLabelsNeedTranslation
      ? "高级作弊标签会单独翻译"
      : "高级作弊标签已是中文或无需翻译";
    setText(
      translationDetection.querySelector("strong"),
      detected ? (likelyChinese ? `\u68c0\u6d4b\u5230\u5df2\u6709\u4e2d\u6587\uff08${ratioText}\uff09` : `\u672a\u68c0\u6d4b\u5230\u660e\u663e\u4e2d\u6587\uff08${ratioText}\uff09`) : "\u9879\u76ee\u8bed\u8a00\u6682\u65f6\u65e0\u6cd5\u5224\u65ad",
    );
    setText(
      translationDetection.querySelector("small"),
      detected && likelyChinese
        ? `\u9ed8\u8ba4\u4e0d\u7ffb\u8bd1；${candidateText}；${cheatText}；\u4e2d\u6587\u5757\u4f1a\u4fdd\u6301\u539f\u6587。`
        : `\u7ffb\u8bd1\u662f\u53ef\u9009\u529f\u80fd，${candidateText}；${cheatText}；\u4e2d\u6587\u5757\u4f1a\u4fdd\u6301\u539f\u6587。`,
    );
    resetTranslationChoice(true);
  };

  const normalizeCheatVariable = (value) => {
    if (!value || typeof value !== "object") return null;
    const kind = String(value.kind || "variable").toLowerCase();
    if (kind !== "variable") return null;
    const index = Number(value.index);
    if (!Number.isSafeInteger(index) || index < 1) return null;
    const id = typeof value.id === "string" && value.id.trim()
      ? value.id.trim()
      : `variable:${index}`;
    const sourceLabel = String(value.sourceLabel ?? value.source_label ?? "").trim() || `变量 ${index}`;
    const translatedLabel = String(value.translatedLabel ?? value.translated_label ?? "").trim();
    const displayLabel = String(value.displayLabel ?? value.display_label ?? translatedLabel ?? "").trim()
      || translatedLabel
      || sourceLabel;
    return { id, kind: "variable", index, sourceLabel, translatedLabel, displayLabel };
  };

  const setCheatVariableCallout = (state, title, detail) => {
    cheatVariableCallout.className = `callout ${state === "ready" ? "ready" : "pending"}`;
    cheatVariableCallout.dataset.state = state;
    setText(cheatVariableCallout.querySelector("strong"), title);
    setText(cheatVariableCallout.querySelector("small"), detail);
  };

  const updateCheatVariableSummary = (visibleCount = null) => {
    const selectedCount = cheatVariableItems.reduce(
      (count, item) => count + (selectedCheatVariableIds.has(item.id) ? 1 : 0),
      0,
    );
    const shown = visibleCount == null ? cheatVariableItems.length : visibleCount;
    setText(cheatVariableSummary.querySelector("strong"), `已选 ${selectedCount} / ${cheatVariableItems.length}`);
    setText(
      cheatVariableSummary.querySelector("span"),
      cheatCatalogStatus === "ready"
        ? `${shown === cheatVariableItems.length ? "显示全部" : `当前显示 ${shown} 项`}；构建时仅发送稳定变量编号。`
        : "翻译完成后才可选择；原文仅用于辅助核对。",
    );
  };

  const renderCheatVariableList = () => {
    cheatVariableList.dataset.state = cheatCatalogStatus;
    const query = cheatVariableSearch.value.trim().toLocaleLowerCase("zh-CN");
    const visibleItems = cheatVariableItems.filter((item) => {
      if (!query) return true;
      return `${item.index}\n${item.id}\n${item.displayLabel}\n${item.translatedLabel}\n${item.sourceLabel}`
        .toLocaleLowerCase("zh-CN")
        .includes(query);
    });
    const fragment = document.createDocumentFragment();
    if (!visibleItems.length) {
      const empty = document.createElement("div");
      empty.className = "cheat-variable-empty";
      const mark = document.createElement("span");
      mark.setAttribute("aria-hidden", "true");
      setText(mark, query ? "⌕" : "◇");
      const title = document.createElement("p");
      setText(title, query ? "没有匹配的变量" : "没有发现可加入的高级数值变量");
      const detail = document.createElement("small");
      setText(detail, query ? "换一个译名、原文或编号试试。" : "当前项目无需配置高级数值列表。");
      empty.append(mark, title, detail);
      fragment.append(empty);
    } else {
      visibleItems.forEach((item) => {
        const row = document.createElement("label");
        row.className = "cheat-variable-item";
        row.dataset.variableId = item.id;
        row.dataset.selected = String(selectedCheatVariableIds.has(item.id));
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = selectedCheatVariableIds.has(item.id);
        checkbox.disabled = cheatCatalogStatus !== "ready" || Boolean(currentJobId);
        checkbox.setAttribute("aria-label", `将${item.displayLabel}加入高级作弊菜单`);
        checkbox.addEventListener("change", () => {
          if (checkbox.checked) selectedCheatVariableIds.add(item.id);
          else selectedCheatVariableIds.delete(item.id);
          row.dataset.selected = String(checkbox.checked);
          updateCheatVariableSummary(visibleItems.length);
        });
        const copy = document.createElement("span");
        copy.className = "cheat-variable-copy";
        const name = document.createElement("strong");
        setText(name, item.displayLabel);
        name.title = item.displayLabel;
        const number = document.createElement("code");
        setText(number, `变量 #${item.index} · ${item.id}`);
        const source = document.createElement("small");
        const showSource = item.sourceLabel !== item.displayLabel;
        source.hidden = !showSource;
        setText(source, showSource ? `原文：${item.sourceLabel}` : "");
        if (showSource) source.title = item.sourceLabel;
        copy.append(name, number, source);
        row.append(checkbox, copy);
        fragment.append(row);
      });
    }
    cheatVariableList.replaceChildren(fragment);
    updateCheatVariableSummary(visibleItems.length);
  };

  const updateCheatVariableControls = (running = Boolean(currentJobId)) => {
    const hasItems = cheatVariableItems.length > 0;
    const ready = cheatCatalogStatus === "ready";
    prepareCheatVariablesButton.disabled = running
      || !inspected
      || !cheatCatalogKnown
      || cheatCatalogStatus === "unavailable";
    setText(
      prepareCheatVariablesButton,
      cheatCatalogStatus === "translating"
        ? "正在翻译标签…"
        : (ready ? "重新翻译标签" : "翻译并载入变量"),
    );
    cheatVariableSearch.disabled = running || !ready || !hasItems;
    selectAllCheatVariablesButton.disabled = running || !ready || !hasItems;
    clearCheatVariablesButton.disabled = running || !ready || !hasItems;
    cheatVariableList.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
      checkbox.disabled = running || !ready;
    });
  };

  const resetCheatCatalog = () => {
    cheatCatalogKnown = false;
    cheatCatalogStatus = "idle";
    cheatCatalogStatusBeforeJob = "idle";
    cheatVariableItems = [];
    selectedCheatVariableIds = new Set();
    cheatVariableSearch.value = "";
    setText(cheatVariableState, "等待检查");
    setCheatVariableCallout("idle", "尚未载入变量", "先检查项目，再翻译并载入高级作弊标签；选择始终按变量编号保存。");
    renderCheatVariableList();
    updateCheatVariableControls();
  };

  const restoreCheatCatalogAfterJob = (detail) => {
    cheatCatalogStatus = cheatCatalogStatusBeforeJob === "ready" ? "ready" : "discovered";
    cheatCatalogStatusBeforeJob = cheatCatalogStatus;
    setText(cheatVariableState, cheatCatalogStatus === "ready" ? "可选择" : "待翻译");
    setCheatVariableCallout(
      cheatCatalogStatus,
      cheatCatalogStatus === "ready" ? "保留上一次已翻译标签" : "作弊标签尚未完成翻译",
      detail,
    );
    renderCheatVariableList();
  };

  const renderCheatCatalog = (catalog, { preserveSelection = true } = {}) => {
    if (!catalog || typeof catalog !== "object") {
      resetCheatCatalog();
      return;
    }
    cheatCatalogKnown = true;
    const rawItems = Array.isArray(catalog.items) ? catalog.items : [];
    const seen = new Set();
    const nextItems = rawItems
      .map(normalizeCheatVariable)
      .filter((item) => item && !seen.has(item.id) && seen.add(item.id))
      .sort((left, right) => left.index - right.index);
    const nextIds = new Set(nextItems.map((item) => item.id));
    selectedCheatVariableIds = preserveSelection
      ? new Set([...selectedCheatVariableIds].filter((id) => nextIds.has(id)))
      : new Set(nextIds);
    cheatVariableItems = nextItems;
    cheatCatalogStatus = catalog.status === "ready"
      ? "ready"
      : (catalog.status === "unavailable" ? "unavailable" : "discovered");
    cheatVariableSearch.value = "";
    if (cheatCatalogStatus === "ready") {
      const translatedCount = nextItems.filter((item) => item.translatedLabel).length;
      setText(cheatVariableState, "可选择");
      setCheatVariableCallout(
        "ready",
        `已准备 ${nextItems.length} 个高级数值变量`,
        `其中 ${translatedCount} 个使用翻译名称；默认全部加入，可按需取消或点击“清空”。`,
      );
    } else if (cheatCatalogStatus === "unavailable" || !nextItems.length) {
      cheatCatalogStatus = "unavailable";
      setText(cheatVariableState, "无需配置");
      setCheatVariableCallout("unavailable", "没有可选择的高级数值变量", "构建可继续，游戏内不会显示高级数值变量列表。");
    } else {
      setText(cheatVariableState, "待翻译");
      setCheatVariableCallout(
        "discovered",
        `发现 ${nextItems.length} 个候选变量`,
        "当前显示游戏原始名称；点击“翻译并载入变量”后会换成简体中文名称并开放选择。",
      );
    }
    cheatCatalogStatusBeforeJob = cheatCatalogStatus;
    renderCheatVariableList();
    updateCheatVariableControls();
  };

  const isDirectionalLayoutButton = (id) => ["up", "down", "left", "right"].includes(id);
  const layoutButton = (id) => layoutButtons.find((button) => button.id === id) || null;

  const updateLayoutSelectionStyles = () => {
    layoutPreview.querySelectorAll(".layout-control").forEach((node) => {
      node.dataset.selected = String(node.dataset.buttonId === selectedLayoutId);
    });
  };

  const syncLayoutInspector = () => {
    const selected = layoutButton(selectedLayoutId) || layoutButtons[0];
    if (!selected) return;
    selectedLayoutId = selected.id;
    layoutSelect.value = selected.id;
    layoutLabel.value = selected.label;
    layoutKey.value = String(selected.keyCode);
    layoutMode.value = selected.mode;
    layoutVisible.checked = selected.visible !== false;
    const bindingLocked = isDirectionalLayoutButton(selected.id);
    layoutKey.disabled = bindingLocked || Boolean(currentJobId);
    layoutMode.disabled = bindingLocked || Boolean(currentJobId);
    layoutDeleteButton.disabled = bindingLocked || Boolean(currentJobId);
    setText(layoutState, selected.visible === false ? "已隐藏" : (bindingLocked ? "方向键" : "可编辑"));
    updateLayoutSelectionStyles();
  };

  const renderLayoutSelect = () => {
    const fragment = document.createDocumentFragment();
    layoutButtons.forEach((button) => {
      const option = document.createElement("option");
      option.value = button.id;
      option.textContent = `${button.label} · ${button.id}${button.visible === false ? "（已隐藏）" : ""}`;
      fragment.append(option);
    });
    layoutSelect.replaceChildren(fragment);
    syncLayoutInspector();
  };

  const renderLayoutPreview = () => {
    layoutPreview.querySelectorAll(".layout-control").forEach((node) => node.remove());
    layoutButtons.forEach((button) => {
      const node = document.createElement("button");
      node.type = "button";
      node.className = "layout-control";
      node.dataset.buttonId = button.id;
      node.dataset.side = isDirectionalLayoutButton(button.id) ? "left" : "right";
      node.dataset.visible = String(button.visible !== false);
      node.dataset.selected = String(button.id === selectedLayoutId);
      node.textContent = button.label;
      node.title = `${button.id} · 键码 ${button.keyCode}`;
      node.style.left = `${button.x * 100}%`;
      node.style.top = `${button.y * 100}%`;
      node.style.width = `${button.width * 100}%`;
      node.style.height = `${button.height * 100}%`;
      node.addEventListener("pointerdown", (event) => {
        if (currentJobId) return;
        event.preventDefault();
        selectedLayoutId = button.id;
        syncLayoutInspector();
        layoutDrag = {
          id: button.id,
          node,
          startX: event.clientX,
          startY: event.clientY,
          originX: button.x,
          originY: button.y,
        };
        node.setPointerCapture?.(event.pointerId);
      });
      node.addEventListener("pointermove", (event) => {
        if (!layoutDrag || layoutDrag.node !== node) return;
        const rect = layoutPreview.getBoundingClientRect();
        const current = layoutButton(layoutDrag.id);
        if (!current || !rect.width || !rect.height) return;
        const next = {
          ...current,
          x: Math.max(0, Math.min(1 - current.width,
            layoutDrag.originX + (event.clientX - layoutDrag.startX) / rect.width)),
          y: Math.max(0, Math.min(1 - current.height,
            layoutDrag.originY + (event.clientY - layoutDrag.startY) / rect.height)),
        };
        if (next.visible !== false && layoutButtons.some((other) => (
          other.id !== next.id && other.visible !== false && layoutRectsOverlap(next, other)
        ))) return;
        current.x = next.x;
        current.y = next.y;
        node.style.left = `${current.x * 100}%`;
        node.style.top = `${current.y * 100}%`;
      });
      const finishDrag = () => {
        if (!layoutDrag || layoutDrag.node !== node) return;
        layoutDrag = null;
        renderLayoutSelect();
        renderLayoutPreview();
      };
      node.addEventListener("pointerup", finishDrag);
      node.addEventListener("pointercancel", finishDrag);
      layoutPreview.append(node);
    });
  };

  const renderLayoutEditor = () => {
    renderLayoutSelect();
    renderLayoutPreview();
  };

  const layoutRectsOverlap = (left, right) => (
    left.x < right.x + right.width && right.x < left.x + left.width
      && left.y < right.y + right.height && right.y < left.y + left.height
  );

  const layoutToControlConfig = () => {
    const visible = layoutButtons.filter((button) => button.visible !== false);
    for (let index = 0; index < visible.length; index += 1) {
      for (const other of visible.slice(index + 1)) {
        if (layoutRectsOverlap(visible[index], other)) {
          throw new Error(`按键布局重叠：${visible[index].id} / ${other.id}`);
        }
      }
    }
    return {
      schemaVersion: 1,
      touch: { cancelKeyCode: 27, twoFingerWindowMs: 250, touchSlopPx: 24 },
      overlay: { opacity: 0.38, hiddenByDefault: false },
      buttons: layoutButtons.map((button) => ({ ...button })),
    };
  };

  const saveLayoutButton = () => {
    const selected = layoutButton(selectedLayoutId);
    if (!selected) return;
    const label = layoutLabel.value.trim();
    const keyCode = Number.parseInt(layoutKey.value, 10);
    if (!label || !Number.isInteger(keyCode) || keyCode < 0 || keyCode > 512) {
      log("按键设置无效", "名称不能为空，键码必须是 0–512 的整数。", "warn");
      return;
    }
    selected.label = label;
    selected.visible = layoutVisible.checked;
    if (!isDirectionalLayoutButton(selected.id)) {
      selected.keyCode = keyCode;
      selected.mode = layoutMode.value === "hold" ? "hold" : "tap";
    }
    renderLayoutEditor();
    log("已保存按键布局", "构建时会将当前悬浮按键位置和右侧绑定写入 APK。", "success");
  };

  const addLayoutButton = () => {
    const index = layoutButtons.reduce((max, button) => {
      const match = /^custom_(\d+)$/.exec(button.id);
      return match ? Math.max(max, Number(match[1])) : max;
    }, 0) + 1;
    const id = `custom_${index}`;
    const candidates = [];
    for (const x of [0.67, 0.83]) {
      for (let row = 0; row < 8; row += 1) {
        candidates.push({ x, y: 0.10 + row * 0.105, width: 0.14, height: 0.08 });
      }
    }
    const slot = candidates.find((candidate) => layoutButtons.every((other) => (
      other.visible === false || !layoutRectsOverlap(candidate, other)
    )));
    if (!slot) {
      log("\u65e0\u6cd5\u6dfb\u52a0\u6309\u952e", "\u53f3\u4fa7\u6ca1\u6709\u4e0d\u91cd\u53e0\u7684\u53ef\u7528\u4f4d\u7f6e\uff0c\u8bf7\u5148\u9690\u85cf\u4e00\u4e2a\u53f3\u4fa7\u6309\u952e\u3002", "warn");
      return;
    }
    layoutButtons.push({
      id, label: "自定义", keyCode: 65, mode: "tap",
      ...slot, visible: true,
    });
    selectedLayoutId = id;
    renderLayoutEditor();
    log("已添加右侧按键", `${id} 默认绑定键码 65，可在右侧编辑器中改名、改键或拖动位置。`, "success");
  };

  const deleteLayoutButton = () => {
    const selected = layoutButton(selectedLayoutId);
    if (!selected) return;
    if (isDirectionalLayoutButton(selected.id)) {
      log("方向键不能删除", "左侧四向移动键保留为游戏基础输入；可调整位置但不能移除。", "warn");
      return;
    }
    if (selected.id.startsWith("custom_")) {
      layoutButtons = layoutButtons.filter((button) => button.id !== selected.id);
      selectedLayoutId = "confirm";
    } else {
      selected.visible = false;
    }
    renderLayoutEditor();
    log("已隐藏/删除右侧按键", "如果需要恢复，可点击“恢复默认”或重新添加自定义按键。", "info");
  };

  const resetLayoutEditor = () => {
    layoutButtons = DEFAULT_LAYOUT_BUTTONS.map((button) => ({ ...button }));
    selectedLayoutId = "confirm";
    renderLayoutEditor();
    log("已恢复默认布局", "右侧确认、取消、ESC、立绘键和左侧方向键已恢复。", "info");
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
          resetTranslationChoice(false);
          resetCheatCatalog();
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

  const isCheatCatalogJob = (value) => String(value || "")
    .replace(/[^a-z]/gi, "")
    .toLowerCase() === "cheatcatalog";

  const jsonPreview = (value) => {
    if (!value || typeof value !== "object") return value == null ? "" : String(value);
    const scrubbed = JSON.parse(JSON.stringify(value, (key, item) => (/password|secret|token|key/i.test(key) ? "[已隐藏]" : item)));
    return JSON.stringify(scrubbed, null, 2);
  };

  const finishJob = (job) => {
    const status = job.status;
    const jobKind = job.kind || currentJobKind;
    currentJobId = null;
    currentJobKind = null;
    pollFailureCount = 0;
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    if (status === "completed") {
      const result = job.result || {};
      let completionLabel = "任务完成";
      if (jobKind === "inspect") {
        const inspection = result.inspection || result;
        inspected = typeof result.buildReady === "boolean" ? result.buildReady : inspection?.status !== "blocked";
        renderTranslationDetection(result.translation);
        renderCheatCatalog(result.cheatCatalog, { preserveSelection: false });
        log(inspected ? "检查通过" : "检查被阻止", jsonPreview(inspection), inspected ? "success" : "error");
        completionLabel = inspected ? "检查通过" : "检查失败";
      } else if (jobKind === "download") {
        if (result.health) renderToolchain(result.health);
        log("工具下载并解压完成", jsonPreview(result), "success");
        completionLabel = "工具链已更新";
      } else if (isCheatCatalogJob(jobKind)) {
        renderCheatCatalog(result.cheatCatalog || result.catalog || result);
        const ready = cheatCatalogStatus === "ready" || cheatCatalogStatus === "unavailable";
        completionLabel = ready ? "作弊变量已准备" : "作弊变量准备未完成";
        log(
          ready ? "高级作弊变量已准备" : "高级作弊变量准备未完成",
          ready ? `可选择 ${cheatVariableItems.length} 个高级数值变量。` : jsonPreview(result),
          ready ? "success" : "warn",
        );
      } else {
        const verification = result.verification || {};
        const verificationPassed = result.verificationPassed === true
          || (verification.passed === true && verification.signatureCandidate === true && Boolean(result.distApkPath));
        const buildResource = result.build?.resourcePack;
        const resourcePackPath = result.distResourcePackPath || result.resourcePackPath || result.build?.resourcePackPath;
        completionLabel = verificationPassed
          ? "构建并验收通过"
          : "构建完成，但静态验收未通过";
        log(
          verificationPassed ? "构建并验收通过" : "构建完成，静态验收未通过",
          jsonPreview(result),
          verificationPassed ? "success" : "error",
        );
        if (verificationPassed && buildResource?.mode === "external" && resourcePackPath) {
          const applicationId = verification.metadata?.applicationId || "<applicationId>";
          const devicePath = `/Android/data/${applicationId}/files/${buildResource.deviceRelativePath || `game2apk/${buildResource.fileName}`}`;
          log(
            "外部资源包已生成",
            `APK 只包含运行时。请同时复制资源包：${resourcePackPath}\n手机目标路径：${devicePath}\n资源包 SHA-256：${buildResource.packSha256 || "见验收报告"}`,
            "success",
          );
          completionLabel = "构建完成（APK + 外部资源包）";
        }
      }
      setProgress(1, completionLabel);
      setText(reportState, completionLabel);
    } else if (status === "cancelled") {
      if (isCheatCatalogJob(jobKind)) restoreCheatCatalogAfterJob("任务已取消；已保留现有变量编号与名称，可重新翻译。");
      setProgress(Number(job.fraction) || 0, "任务已取消");
      log("任务已取消", job.message || "后台已安全停止当前工作。", "warn");
    } else {
      if (isCheatCatalogJob(jobKind)) restoreCheatCatalogAfterJob("翻译失败；已保留现有变量编号与名称，可检查日志后重试。");
      setProgress(Number(job.fraction) || 0, "任务失败");
      log("任务失败", job.error || job.message || "后台没有提供更多错误信息。", "error");
    }
    setTaskButtons(false);
  };

  const renderJob = (job) => {
    if (isCheatCatalogJob(job.kind || currentJobKind) && cheatCatalogStatus !== "translating") {
      cheatCatalogStatus = "translating";
      setText(cheatVariableState, "翻译中");
      setCheatVariableCallout("translating", "正在翻译高级作弊标签", "变量编号保持不变；完成后列表会原位更新为简体中文名称。");
      updateCheatVariableControls(true);
    }
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
      const title = kind === "inspect"
        ? "已提交检查"
        : (kind === "download"
          ? "已提交工具下载"
          : (isCheatCatalogJob(kind) ? "已提交作弊标签翻译" : "已提交构建"));
      log(title, `任务编号：${jobId}`, "info");
      void pollJob(jobId);
    } catch (error) {
      if (isCheatCatalogJob(kind)) restoreCheatCatalogAfterJob("无法提交翻译任务；已保留现有变量编号与名称。");
      setTaskButtons(false);
      log("无法提交任务", error instanceof Error ? error.message : "请检查输入后重试。", "error");
    }
  };

  const inspect = () => {
    const source = $("#source-path").value.trim();
    if (!source) { log("需要项目路径", "请先点击“浏览目录”选择游戏根目录或 www 目录。", "warn"); return; }
    inspected = false;
    resetTranslationChoice(false);
    resetCheatCatalog();
    buildButton.disabled = true;
    void startJob("/api/inspect", { source }, "inspect");
  };

  const prepareCheatVariables = () => {
    if (!inspected) { log("需要先通过检查", "检查完成后才能读取该项目的高级数值变量。", "warn"); return; }
    if (!cheatCatalogKnown || cheatCatalogStatus === "unavailable") {
      log("没有可准备的高级数值变量", "当前项目没有返回可选择的变量目录。", "info");
      return;
    }
    if (!translationConfirm.checked) {
      log("需要翻译确认", "请先确认允许向 DeepSeek 发送高级作弊变量名称。", "warn");
      return;
    }
    const source = $("#source-path").value.trim();
    const payload = {
      source,
      confirm: true,
      thinkingEnabled: thinkingMode.value === "enabled",
      reasoningEffort: reasoningEffort.value,
    };
    const deepseekKey = $("#deepseek-key").value;
    if (deepseekKey) payload.apiKey = deepseekKey;
    cheatCatalogStatusBeforeJob = cheatCatalogStatus;
    cheatCatalogStatus = "translating";
    setText(cheatVariableState, "翻译中");
    setCheatVariableCallout("translating", "正在翻译高级作弊标签", "变量编号保持不变；完成后列表会原位更新为简体中文名称。");
    updateCheatVariableControls(true);
    void startJob("/api/cheat-catalog", payload, "cheatCatalog");
  };

  const build = () => {
    if (!inspected) { log("需要先通过检查", "请先检查当前项目；目录或项目变更后需要重新检查。", "warn"); return; }
    if (cheatCatalogKnown && !["ready", "unavailable"].includes(cheatCatalogStatus)) {
      log("需要先准备高级作弊变量", "请先点击“翻译并载入变量”，再选择要加入游戏菜单的变量。", "warn");
      return;
    }
    const source = $("#source-path").value.trim();
    const translate = $("#translate-toggle").checked;
    const confirm = $("#translation-confirm").checked;
    if ((translate || cheatLabelsNeedTranslation) && !confirm) { log("需要翻译确认", translate ? "启用正文翻译前必须确认会向第三方发送待翻译文本。" : "高级作弊标签始终需要翻译；请确认允许在需要时向 DeepSeek 发送变量/开关名称。", "warn"); return; }
    const versionCode = Number.parseInt($("#version-code").value, 10);
    if (!Number.isSafeInteger(versionCode) || versionCode < 1) { log("版本号无效", "Version code 必须是大于 0 的整数。", "warn"); return; }
    let control;
    try {
      control = layoutToControlConfig();
    } catch (error) {
      log("按键布局无效", error instanceof Error ? error.message : "请检查按键是否重叠。", "warn");
      return;
    }
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
      control,
    };
    if (cheatCatalogKnown && cheatCatalogStatus === "ready") {
      payload.advancedCheatVariableIds = cheatVariableItems
        .filter((item) => selectedCheatVariableIds.has(item.id))
        .map((item) => item.id);
    }
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
    prepareCheatVariablesButton.addEventListener("click", prepareCheatVariables);
    selectAllCheatVariablesButton.addEventListener("click", () => {
      selectedCheatVariableIds = new Set(cheatVariableItems.map((item) => item.id));
      renderCheatVariableList();
    });
    clearCheatVariablesButton.addEventListener("click", () => {
      selectedCheatVariableIds.clear();
      renderCheatVariableList();
    });
    cheatVariableSearch.addEventListener("input", renderCheatVariableList);
    layoutSelect.addEventListener("change", () => {
      selectedLayoutId = layoutSelect.value;
      syncLayoutInspector();
    });
    layoutAddButton.addEventListener("click", addLayoutButton);
    layoutResetButton.addEventListener("click", resetLayoutEditor);
    layoutSaveButton.addEventListener("click", saveLayoutButton);
    layoutDeleteButton.addEventListener("click", deleteLayoutButton);
    buildButton.addEventListener("click", build);
    cancelButton.addEventListener("click", () => void cancel());
    // Inspection is tied to the exact source path.  Changing it after a
    // successful check must not unlock a build for a different project.
    const sourceField = $("#source-path");
    sourceField.addEventListener("input", () => {
      inspected = false;
      resetTranslationChoice(false);
      resetCheatCatalog();
      if (!currentJobId) buildButton.disabled = true;
    });
    translationToggle.addEventListener("change", () => { translationOptions.hidden = false; });
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
    resetCheatCatalog();
    renderLayoutEditor();
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
