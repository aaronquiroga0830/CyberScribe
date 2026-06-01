"use strict";
/**
 * Mission RAG – Liquid Glass UI
 * TypeScript source; compile to app.js for the browser.
 */
const API = "/api";
const REPORT_TYPES = ["rmp", "timeline", "aar", "sitrep"];
const REPORT_LABELS = {
    rmp: "RMP",
    timeline: "Timeline",
    aar: "AAR",
    sitrep: "SITREP",
};
const MARGINS_STORAGE_KEY = "reportMargins";
function getStoredMargins(missionId, reportType) {
    try {
        const raw = localStorage.getItem(`${MARGINS_STORAGE_KEY}_${missionId}_${reportType}`);
        if (raw) {
            const o = JSON.parse(raw);
            return {
                top: typeof o.top === "number" ? o.top : 1,
                right: typeof o.right === "number" ? o.right : 1,
                bottom: typeof o.bottom === "number" ? o.bottom : 1,
                left: typeof o.left === "number" ? o.left : 1,
            };
        }
    }
    catch (_) { }
    return { top: 1, right: 1, bottom: 1, left: 1 };
}
function setStoredMargins(missionId, reportType, margins) {
    try {
        localStorage.setItem(`${MARGINS_STORAGE_KEY}_${missionId}_${reportType}`, JSON.stringify(margins));
    }
    catch (_) { }
}
function getMarginInputs(prefix) {
    const top = document.getElementById(prefix + "margin-top");
    const right = document.getElementById(prefix + "margin-right");
    const bottom = document.getElementById(prefix + "margin-bottom");
    const left = document.getElementById(prefix + "margin-left");
    if (!top || !right || !bottom || !left)
        return null;
    return {
        top: Math.max(0, parseFloat(top.value) || 0),
        right: Math.max(0, parseFloat(right.value) || 0),
        bottom: Math.max(0, parseFloat(bottom.value) || 0),
        left: Math.max(0, parseFloat(left.value) || 0),
    };
}
/** Cleanup for current report view (close SSE streams when navigating away). */
let currentReportCleanup = null;
/** @deprecated Legacy Quill bundle; unmaintained. Production UI uses Vite + Tiptap (`web/app.ts`). */
/** Quill editor instances by container id; destroyed on navigate or when replacing. */
const quillByContainerId = {};
/** One-time Quill toolbar setup: font, size, bold, italic, underline, lists, indent. */
function initQuillToolbarOptions() {
    const Q = window.Quill;
    if (!Q)
        return undefined;
    if (window._quillToolbarInited) {
        return window._quillToolbarOpts;
    }
    window._quillToolbarInited = true;
    let hasFont = false;
    let hasSize = false;
    try {
        const Font = Q.import("formats/font");
        if (Font) {
            Font.whitelist = ["sans-serif", "serif", "monospace", "times-new-roman", "arial", "georgia"];
            Q.register(Font, true);
            hasFont = true;
        }
    }
    catch (_) { }
    try {
        const Size = Q.import("attributors/style/size");
        if (Size) {
            Size.whitelist = ["10px", "12px", "14px", "16px", "18px", "20px", "24px"];
            Q.register(Size, true);
            hasSize = true;
        }
    }
    catch (_) { }
    const toolbar = [
        ["bold", "italic", "underline"],
        [{ list: "ordered" }, { list: "bullet" }],
        [{ indent: "-1" }, { indent: "+1" }],
        [{ align: [] }],
    ];
    if (hasFont)
        toolbar.unshift([{ font: ["sans-serif", "serif", "monospace", "times-new-roman", "arial", "georgia"] }]);
    if (hasSize)
        toolbar.unshift([{ size: ["10px", "12px", "14px", "16px", "18px", "20px", "24px"] }]);
    const opts = { theme: "snow", modules: { toolbar } };
    window._quillToolbarOpts = opts;
    return opts;
}
function destroyAllQuillEditors() {
    for (const id of Object.keys(quillByContainerId)) {
        try {
            quillByContainerId[id].destroy();
        }
        catch (_) { }
        delete quillByContainerId[id];
    }
}
/** Create Quill editor in containerEl; set initial content (HTML or plain text); return getHtml and destroy. */
function createQuillEditor(containerId, containerEl, initialContent, onSave) {
    const QuillClass = window.Quill;
    if (!QuillClass)
        return null;
    if (quillByContainerId[containerId]) {
        try {
            quillByContainerId[containerId].destroy();
        }
        catch (_) { }
        delete quillByContainerId[containerId];
    }
    containerEl.innerHTML = "";
    const editorRoot = document.createElement("div");
    editorRoot.id = containerId;
    containerEl.appendChild(editorRoot);
    const editorOpts = initQuillToolbarOptions() ?? { theme: "snow" };
    const editor = new QuillClass(editorRoot, editorOpts);
    const root = editor.root;
    if (/^\s*</.test((initialContent || "").trim())) {
        root.innerHTML = (initialContent || "").trim();
    }
    else {
        const text = (initialContent || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const paras = text.split(/\n/).filter((s) => s.length > 0);
        root.innerHTML = paras.length ? paras.map((s) => "<p>" + s + "</p>").join("") : "<p><br></p>";
    }
    const getHtml = () => root.innerHTML;
    const destroy = () => {
        containerEl.innerHTML = "";
        delete quillByContainerId[containerId];
    };
    quillByContainerId[containerId] = { root, getHtml, destroy };
    editorRoot.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === "s") {
            e.preventDefault();
            onSave();
        }
    });
    return { getHtml, destroy };
}
// ---------- Line-based diff for per-section Undo/Keep ----------
const MAX_DIFF_CHARS = 200000;
function computeDiffSegments(oldText, newText) {
    const oldStr = oldText ?? "";
    const newStr = newText ?? "";
    if (oldStr.length > MAX_DIFF_CHARS || newStr.length > MAX_DIFF_CHARS) {
        return [{ type: "change", oldContent: oldStr, newContent: newStr }];
    }
    const oldLines = oldStr.split("\n");
    const newLines = newStr.split("\n");
    const segments = [];
    let i = 0;
    let j = 0;
    while (i < oldLines.length || j < newLines.length) {
        if (i < oldLines.length && j < newLines.length && oldLines[i] === newLines[j]) {
            const startI = i;
            const startJ = j;
            while (i < oldLines.length && j < newLines.length && oldLines[i] === newLines[j]) {
                i++;
                j++;
            }
            segments.push({
                type: "equal",
                oldContent: oldLines.slice(startI, i).join("\n"),
                newContent: newLines.slice(startJ, j).join("\n"),
            });
            continue;
        }
        const startI = i;
        const startJ = j;
        while (i < oldLines.length && j < newLines.length && oldLines[i] !== newLines[j]) {
            const nextJ = newLines.slice(j + 1).indexOf(oldLines[i]);
            const nextI = oldLines.slice(i + 1).indexOf(newLines[j]);
            if (nextJ === -1 && nextI === -1) {
                i++;
                j++;
                break;
            }
            if (nextI === -1 || (nextJ !== -1 && nextJ <= nextI)) {
                j++;
            }
            else {
                i++;
            }
        }
        if (i > startI || j > startJ) {
            segments.push({
                type: "change",
                oldContent: oldLines.slice(startI, i).join("\n"),
                newContent: newLines.slice(startJ, j).join("\n"),
            });
        }
    }
    return segments;
}
/** Build final text from segments; kept[i] = true means use newContent for the i-th change segment. */
function buildMergedFromSegments(segments, kept) {
    let changeIdx = 0;
    const parts = [];
    for (const s of segments) {
        if (s.type === "equal")
            parts.push(s.oldContent);
        else
            parts.push(kept[changeIdx++] ? s.newContent : s.oldContent);
    }
    return parts.join("");
}
// ---------- API helpers ----------
function get(path) {
    return fetch(API + path).then((r) => {
        if (!r.ok)
            throw new Error(r.statusText || "Request failed");
        return r.json();
    });
}
function post(path, body) {
    return fetch(API + path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
    }).then((r) => {
        if (!r.ok)
            return r.json().then((j) => Promise.reject(new Error(j.error || r.statusText)));
        return r.json();
    });
}
function patch(path, body) {
    return fetch(API + path, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    }).then((r) => {
        if (!r.ok)
            throw new Error(r.statusText);
        return r.json();
    });
}
/**
 * Poll until job is completed or failed. Returns a stop function.
 * Completion should drive UI refresh; SSE may still run for live preview only.
 */
function pollPipelineJobUntilTerminal(missionId, jobId, onTerminal, intervalMs = 2000) {
    let stopped = false;
    const stop = () => {
        stopped = true;
    };
    const tick = () => {
        if (stopped)
            return;
        get("/missions/" +
            missionId +
            "/pipeline-jobs/" +
            encodeURIComponent(jobId))
            .then((j) => {
            if (stopped)
                return;
            if (j.status === "completed" || j.status === "failed") {
                onTerminal(j);
                return;
            }
            setTimeout(tick, intervalMs);
        })
            .catch(() => {
            if (!stopped)
                setTimeout(tick, intervalMs);
        });
    };
    tick();
    return stop;
}
function getHash() {
    return window.location.hash.slice(1) || "/";
}
function getHashParts() {
    return getHash().split("/").filter(Boolean);
}
function hashMatchesReport(missionId, reportType) {
    const parts = getHashParts();
    return parts[0] === "mission" && parts[1] === missionId && parts[2] === reportType;
}
function navigate(hash) {
    window.location.hash = hash;
}
function escapeHtml(s) {
    const str = s != null ? String(s) : "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
const MERGE_PLACEHOLDER = "[To be filled from mission data]";
/** Split template HTML into one block per h1–h6 or p element so merge preserves structure. */
function splitTemplateBlocks(html) {
    const re = /<(h[1-6]|p)[^>]*>[\s\S]*?<\/\1>/gi;
    const str = (html || "").trim();
    return Array.from(str.matchAll(re), (m) => m[0]);
}
function mergeLlmIntoDraft(template, llmText) {
    if (!(llmText || "").trim())
        return template || "";
    const draftBlocks = splitTemplateBlocks(template || "");
    const llmBlocks = (llmText || "").replace(/\r\n/g, "\n").trim().split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
    if (!draftBlocks.length)
        return llmText.trim();
    if (!llmBlocks.length)
        return template || "";
    function isFilled(block) {
        if (!block || block.length < 3)
            return false;
        const stripped = block.trim();
        if (stripped.toLowerCase() === MERGE_PLACEHOLDER.toLowerCase())
            return false;
        if (stripped.toLowerCase().includes(MERGE_PLACEHOLDER.toLowerCase()) && stripped.length < 100)
            return false;
        return true;
    }
    const merged = [];
    const n = Math.max(draftBlocks.length, llmBlocks.length);
    for (let i = 0; i < n; i++) {
        const draftBlock = i < draftBlocks.length ? draftBlocks[i] : "";
        const llmBlock = i < llmBlocks.length ? llmBlocks[i] : "";
        merged.push(isFilled(llmBlock) ? llmBlock : draftBlock || llmBlock);
    }
    return merged.join("\n\n");
}
function mergedToDisplayHtml(merged) {
    const blocks = merged.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
    return blocks
        .map((block) => {
        if (block.startsWith("<"))
            return block;
        return "<p>" + escapeHtml(block) + "</p>";
    })
        .join("\n");
}
// ---------- Views ----------
const expandedMissions = new Set();
function renderMissionList(container, currentId, currentSub) {
    get("/missions")
        .then((missions) => {
        container.innerHTML = "";
        if (!missions.length) {
            container.innerHTML = '<p class="empty">No missions yet.</p>';
            return;
        }
        missions.forEach((m) => {
            const isExpanded = expandedMissions.has(m.id);
            const wrap = document.createElement("div");
            wrap.className = "mission-wrap";
            const row = document.createElement("div");
            row.className = "mission-item" + (m.id === currentId ? " active" : "");
            row.dataset.id = m.id;
            row.innerHTML = `
          <span class="mission-toggle" aria-expanded="${isExpanded}">${isExpanded ? "▼" : "▶"}</span>
          <span class="name">${escapeHtml(m.name)}</span>
          <button type="button" class="mission-context-btn" aria-label="Mission options" data-mission-id="${escapeHtml(m.id)}">⋯</button>
        `;
            row.addEventListener("click", (e) => {
                if (e.target.closest(".mission-toggle")) {
                    if (expandedMissions.has(m.id))
                        expandedMissions.delete(m.id);
                    else
                        expandedMissions.add(m.id);
                    renderMissionList(container, currentId, currentSub);
                    return;
                }
                if (e.target.closest(".mission-context-btn"))
                    return;
                navigate("/mission/" + m.id + "/overview");
                render();
            });
            row.querySelector(".mission-context-btn").addEventListener("click", (e) => {
                e.stopPropagation();
                const menu = document.getElementById("mission-context-menu");
                if (menu)
                    menu.remove();
                const rect = e.target.getBoundingClientRect();
                const div = document.createElement("div");
                div.id = "mission-context-menu";
                div.className = "context-menu glass";
                div.innerHTML = `<button type="button" class="context-menu-item" data-action="overview">Overview</button><button type="button" class="context-menu-item" data-action="run-all">Run all reports</button>`;
                div.style.position = "fixed";
                div.style.left = rect.left + "px";
                div.style.top = rect.bottom + 4 + "px";
                div.style.zIndex = "1000";
                document.body.appendChild(div);
                div.querySelector("[data-action=overview]").addEventListener("click", () => { div.remove(); navigate("/mission/" + m.id + "/overview"); render(); });
                div.querySelector("[data-action=run-all]").addEventListener("click", () => { div.remove(); post("/run-pipeline", { mission_id: m.id }).then(() => render()).catch((err) => alert(err.message)); });
                const close = () => { div.remove(); document.removeEventListener("click", close); };
                setTimeout(() => document.addEventListener("click", close), 0);
            });
            wrap.appendChild(row);
            if (isExpanded) {
                const sub = document.createElement("div");
                sub.className = "mission-sub";
                const overviewActive = currentId === m.id && (!currentSub || currentSub === "overview");
                sub.innerHTML = `
            <a href="#/mission/${encodeURIComponent(m.id)}/overview" class="mission-sub-item ${overviewActive ? "active" : ""}" data-nav="overview"><span class="mission-sub-icon" aria-hidden="true">📋</span>Overview</a>
            ${REPORT_TYPES.map((rt) => `<a href="#/mission/${encodeURIComponent(m.id)}/${rt}" class="mission-sub-item ${currentId === m.id && currentSub === rt ? "active" : ""}" data-nav="${rt}"><span class="mission-sub-icon" aria-hidden="true">📄</span>${REPORT_LABELS[rt]}</a>`).join("")}
          `;
                sub.querySelectorAll(".mission-sub-item").forEach((a) => {
                    a.addEventListener("click", (e) => {
                        e.preventDefault();
                        const nav = e.currentTarget.dataset.nav;
                        navigate(nav === "overview" ? "/mission/" + m.id + "/overview" : "/mission/" + m.id + "/" + nav);
                        render();
                    });
                });
                sub.querySelectorAll(".mission-sub-item").forEach((item) => {
                    const nav = item.dataset.nav;
                    if (nav === "overview")
                        return;
                    const reportType = nav;
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "mission-sub-context";
                    btn.innerHTML = "⋯";
                    btn.setAttribute("aria-label", "Options for " + REPORT_LABELS[reportType]);
                    btn.addEventListener("click", (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        const menu = document.getElementById("report-context-menu");
                        if (menu)
                            menu.remove();
                        const rect = e.target.getBoundingClientRect();
                        const div = document.createElement("div");
                        div.id = "report-context-menu";
                        div.className = "context-menu glass";
                        div.innerHTML = `<button type="button" class="context-menu-item" data-action="update">Update</button><button type="button" class="context-menu-item" data-action="reset">Reset</button>`;
                        div.style.position = "fixed";
                        div.style.left = rect.left + "px";
                        div.style.top = rect.bottom + 4 + "px";
                        div.style.zIndex = "1000";
                        document.body.appendChild(div);
                        div.querySelector("[data-action=update]").addEventListener("click", () => {
                            div.remove();
                            document.removeEventListener("click", closeMenu);
                            navigate("/mission/" + m.id + "/" + nav);
                            render();
                            setTimeout(() => document.querySelector("#btn-update-report")?.click(), 300);
                        });
                        div.querySelector("[data-action=reset]").addEventListener("click", () => {
                            div.remove();
                            document.removeEventListener("click", closeMenu);
                            const confirmed = window.confirm("Are you sure you want to reset the draft?");
                            if (confirmed) {
                                post("/missions/" + m.id + "/reports/" + reportType + "/reset")
                                    .then(() => {
                                    navigate("/mission/" + m.id + "/" + nav);
                                    render();
                                })
                                    .catch((err) => alert(err?.message ?? "Failed to reset draft"));
                            }
                        });
                        const closeMenu = () => {
                            div.remove();
                            document.removeEventListener("click", closeMenu);
                        };
                        setTimeout(() => document.addEventListener("click", closeMenu), 0);
                    });
                    item.appendChild(btn);
                });
                wrap.appendChild(sub);
            }
            container.appendChild(wrap);
        });
    })
        .catch(() => {
        container.innerHTML = '<p class="error">Failed to load missions</p>';
    });
}
function renderNewMissionForm(main) {
    main.innerHTML = `
    <div class="glass-strong section" style="max-width: 560px;">
      <h2>New mission</h2>
      <p class="caption">Set mission metadata. Input folder = source documents; Output folder = where drafts are written.</p>
      <form id="form-new-mission">
        <div class="form-group">
          <label>Mission name</label>
          <input type="text" name="name" placeholder="e.g. Alpha CPT 2025" required>
        </div>
        <div class="form-group">
          <label>CPT</label>
          <input type="text" name="cpt" placeholder="Which CPT this mission is from">
        </div>
        <div class="form-group">
          <label>Workflow title</label>
          <input type="text" name="workflow_title" placeholder="Optional; defaults to mission name">
        </div>
        <div class="form-group">
          <label>Start date</label>
          <input type="date" name="start_date">
        </div>
        <div class="form-group">
          <label>End date</label>
          <input type="date" name="end_date">
        </div>
        <div class="form-group">
          <label>Operators (name / role: Host or Network, one per line)</label>
          <textarea name="operators" rows="3" placeholder="e.g. Alice / Host"></textarea>
        </div>
        <div class="form-group">
          <label>MEL (Mission Element Lead)</label>
          <input type="text" name="mel" placeholder="Name">
        </div>
        <div class="form-group">
          <label>CCL Host (comma-separated or one per line)</label>
          <textarea name="ccl_host" rows="2" placeholder="Cyber Crew Lead for Host"></textarea>
        </div>
        <div class="form-group">
          <label>CCL Network (comma-separated or one per line)</label>
          <textarea name="ccl_network" rows="2" placeholder="Cyber Crew Lead for Network"></textarea>
        </div>
        <div class="form-group">
          <label>Input folder (source path)</label>
          <input type="text" name="source_path" placeholder="C:\\path\\to\\mission\\documents" required>
        </div>
        <div class="form-group">
          <label>Output folder (drop-off path)</label>
          <input type="text" name="output_path" placeholder="C:\\path\\to\\output" required>
        </div>
        <div class="form-group">
          <label>Auto-update frequency</label>
          <select name="auto_update_frequency">
            <option value="off">Off (manual only)</option>
            <option value="hourly">Hourly</option>
            <option value="6h">Every 6 hours</option>
            <option value="daily">Daily</option>
          </select>
        </div>
        <div class="actions">
          <button type="submit" class="btn btn-primary">Create mission</button>
          <button type="button" class="btn" id="btn-cancel-new">Cancel</button>
        </div>
      </form>
      <p class="error" id="new-mission-error"></p>
    </div>
  `;
    const formEl = document.getElementById("form-new-mission");
    formEl.addEventListener("submit", (e) => {
        e.preventDefault();
        const errEl = document.getElementById("new-mission-error");
        errEl.textContent = "";
        const form = e.target;
        const name = form.elements.namedItem("name")?.value?.trim() ?? "";
        const source_path = form.elements.namedItem("source_path")?.value?.trim() ?? "";
        const output_path = form.elements.namedItem("output_path")?.value?.trim() ?? "";
        if (!name || !source_path || !output_path) {
            errEl.textContent = "Fill name, input folder, and output folder.";
            return;
        }
        const operatorsRaw = form.elements.namedItem("operators")?.value?.trim();
        const operators = [];
        if (operatorsRaw) {
            operatorsRaw.split(/\n/).forEach((line) => {
                const parts = line.split("/").map((p) => p.trim());
                if (parts.length >= 2)
                    operators.push({ name: parts[0], role: parts[1] });
                else if (parts[0])
                    operators.push({ name: parts[0], role: "Host" });
            });
        }
        const cclHostRaw = form.elements.namedItem("ccl_host")?.value?.trim();
        const ccl_host = cclHostRaw ? cclHostRaw.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean) : undefined;
        const cclNetworkRaw = form.elements.namedItem("ccl_network")?.value?.trim();
        const ccl_network = cclNetworkRaw ? cclNetworkRaw.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean) : undefined;
        const body = {
            name,
            source_path,
            output_path,
            cpt: form.elements.namedItem("cpt")?.value?.trim() || undefined,
            workflow_title: form.elements.namedItem("workflow_title")?.value?.trim() || undefined,
            start_date: form.elements.namedItem("start_date")?.value || undefined,
            end_date: form.elements.namedItem("end_date")?.value || undefined,
            operators: operators.length ? operators : undefined,
            mel: form.elements.namedItem("mel")?.value?.trim() || undefined,
            ccl_host: ccl_host?.length ? ccl_host : undefined,
            ccl_network: ccl_network?.length ? ccl_network : undefined,
            auto_update_frequency: form.elements.namedItem("auto_update_frequency")?.value || "off",
        };
        post("/missions", body)
            .then((data) => {
            expandedMissions.add(data.id);
            navigate("/mission/" + data.id + "/overview");
            render();
        })
            .catch((err) => {
            errEl.textContent = err.message || "Failed to create mission";
        });
    });
    document.getElementById("btn-cancel-new").addEventListener("click", () => {
        navigate("/");
        render();
    });
}
function renderMissionOverview(missionId, main) {
    get("/missions/" + missionId)
        .then((mission) => {
        let operatorsHtml = "";
        try {
            const ops = mission.operators ? JSON.parse(mission.operators) : [];
            if (Array.isArray(ops) && ops.length)
                operatorsHtml = "<ul>" + ops.map((o) => `<li>${escapeHtml(String(o.name || ""))} (${escapeHtml(String(o.role || ""))})</li>`).join("") + "</ul>";
        }
        catch {
            if (mission.operators)
                operatorsHtml = "<p>" + escapeHtml(mission.operators) + "</p>";
        }
        const cclHost = mission.ccl_host ? (typeof mission.ccl_host === "string" && mission.ccl_host.startsWith("[") ? JSON.parse(mission.ccl_host) : mission.ccl_host.split(",")) : [];
        const cclNet = mission.ccl_network ? (typeof mission.ccl_network === "string" && mission.ccl_network.startsWith("[") ? JSON.parse(mission.ccl_network) : mission.ccl_network.split(",")) : [];
        main.innerHTML = `
        <div class="glass-strong section">
          <h2>${escapeHtml(mission.workflow_title || mission.name)}</h2>
          <p class="caption">Mission ID: ${escapeHtml(mission.id)} · ${escapeHtml(mission.status)}</p>
          ${mission.cpt ? "<p><strong>CPT:</strong> " + escapeHtml(mission.cpt) + "</p>" : ""}
          ${mission.start_date || mission.end_date ? "<p><strong>Dates:</strong> " + escapeHtml(mission.start_date || "") + " – " + escapeHtml(mission.end_date || "") + "</p>" : ""}
          ${operatorsHtml ? "<p><strong>Operators</strong></p>" + operatorsHtml : ""}
          ${mission.mel ? "<p><strong>MEL:</strong> " + escapeHtml(mission.mel) + "</p>" : ""}
          ${Array.isArray(cclHost) && cclHost.length ? "<p><strong>CCL Host:</strong> " + escapeHtml(cclHost.join(", ")) + "</p>" : ""}
          ${Array.isArray(cclNet) && cclNet.length ? "<p><strong>CCL Network:</strong> " + escapeHtml(cclNet.join(", ")) + "</p>" : ""}
          <p><strong>Input folder:</strong> ${escapeHtml(mission.source_path)}</p>
          <p><strong>Output folder:</strong> ${escapeHtml(mission.output_path)}</p>
          <p><strong>Auto-update:</strong> ${escapeHtml(mission.auto_update_frequency || "off")}</p>
          <label class="caption" style="display: inline-flex; align-items: center; gap: 0.5rem; margin-top: 0.35rem;">
            Ingest mode (MEL):
            <select id="mission-ingest-mode">
              <option value="auto" ${(mission.ingest_mode || "auto") === "auto" ? "selected" : ""}>Auto</option>
              <option value="manual" ${mission.ingest_mode === "manual" ? "selected" : ""}>Manual</option>
            </select>
          </label>
          <p class="caption" style="margin-top: 0.25rem;">Manual mode is stored for upcoming confirm-ingest UX; the pipeline still rebuilds the index on run until that ships.</p>
          ${mission.last_ingest_at ? "<p class=\"caption\">Last ingest: " + escapeHtml(mission.last_ingest_at) + "</p>" : ""}
          ${mission.last_generated_at ? "<p class=\"caption\">Last generated: " + escapeHtml(mission.last_generated_at) + "</p>" : ""}
        </div>
        <div class="section">
          <p class="caption">Use the sidebar to open a report (RMP, Timeline, AAR, SITREP) and click Update to generate or refresh that draft.</p>
        </div>
      `;
        document.getElementById("mission-ingest-mode")?.addEventListener("change", () => {
            const sel = document.getElementById("mission-ingest-mode");
            const value = sel.value === "manual" ? "manual" : "auto";
            patch("/missions/" + missionId + "/metadata", { ingest_mode: value }).then(() => {
                mission.ingest_mode = value;
            }).catch((err) => alert(err.message || "Failed to update ingest mode"));
        });
    })
        .catch(() => {
        main.innerHTML = '<p class="error">Mission not found.</p>';
    });
}
/** Appends a "Generating…" label and a streaming <pre> to the container (does not clear it). Returns the pre id for onChunk. */
function appendStreamingPreview(container, previewId) {
    const cap = document.createElement("p");
    cap.className = "caption";
    cap.textContent = "Generating…";
    container.appendChild(cap);
    const pre = document.createElement("pre");
    pre.id = previewId;
    pre.className = "streaming-preview";
    pre.style.whiteSpace = "pre-wrap";
    container.appendChild(pre);
}
function connectStream(missionId, reportType, boxEl, onDone, onChunk) {
    const url = API +
        "/stream/" +
        encodeURIComponent(missionId) +
        "/" +
        encodeURIComponent(reportType);
    const es = new EventSource(url);
    let content = "";
    boxEl.classList.add("streaming");
    boxEl.textContent = "Connecting…";
    es.onmessage = function (e) {
        try {
            const d = JSON.parse(e.data);
            if (d.t === "buf") {
                content = d.text ?? "";
            }
            else if (d.t === "chunk") {
                content += d.text ?? "";
            }
            else if (d.t === "done") {
                es.close();
                boxEl.classList.remove("streaming");
                onDone?.();
                return;
            }
            boxEl.textContent = content || "Generating…";
            boxEl.scrollTop = boxEl.scrollHeight;
            onChunk?.(content);
        }
        catch {
            // ignore parse errors
        }
    };
    es.onerror = function () {
        es.close();
        boxEl.classList.remove("streaming");
        if (!content)
            boxEl.textContent = "Disconnected or no stream.";
        onDone?.();
    };
    return function close() {
        es.close();
        boxEl.classList.remove("streaming");
    };
}
/** Single report type page: one draft area; inline diff with per-section Undo/Keep when pending. */
function renderReportView(missionId, reportType, main) {
    let mission = null;
    let closeStream = null;
    let stopPipelineJobPoll = null;
    currentReportCleanup = () => {
        stopPipelineJobPoll?.();
        stopPipelineJobPoll = null;
        closeStream?.();
        destroyAllQuillEditors();
    };
    let proposalSegments = [];
    let proposalKept = [];
    const label = REPORT_LABELS[reportType];
    main.innerHTML = `
    <div class="section"><button type="button" class="btn btn-sm" id="btn-back-report">← Overview</button></div>
    <div class="section"><h2>${escapeHtml(missionId)} · ${label}</h2><p class="caption">Loading report…</p></div>
  `;
    document.getElementById("btn-back-report")?.addEventListener("click", () => {
        navigate("/mission/" + missionId + "/overview");
        render();
    });
    function fetchReport() {
        return get("/missions/" + missionId + "/reports/" + reportType);
    }
    function fetchReportNoCache() {
        return get("/missions/" + missionId + "/reports/" + reportType + "?_=" + Date.now());
    }
    function renderDraftArea(report) {
        const draftEl = document.getElementById("draft-area");
        if (!draftEl)
            return;
        const current = (report?.current_content != null ? String(report.current_content) : "") || "";
        const pending = report?.pending_content != null ? String(report.pending_content) : null;
        if (pending) {
            draftEl.className = "draft-area draft-area-diff";
            draftEl.innerHTML = "";
            const pre = document.createElement("pre");
            pre.className = "draft-segment draft-segment-kept";
            pre.style.whiteSpace = "pre-wrap";
            pre.textContent = pending;
            draftEl.appendChild(pre);
            return;
        }
        draftEl.className = "draft-area";
        draftEl.innerHTML = "";
        const p = document.createElement("p");
        p.className = "caption";
        p.textContent = "Draft (edit and save with Ctrl+S or Save)";
        draftEl.appendChild(p);
        const editorContainer = document.createElement("div");
        editorContainer.className = "quill-draft-container";
        draftEl.appendChild(editorContainer);
        const actions = document.createElement("div");
        actions.className = "actions";
        actions.style.marginTop = "0.5rem";
        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "btn btn-sm";
        saveBtn.id = "btn-save-report";
        saveBtn.textContent = "Save edits to drop-off";
        const statusSpan = document.createElement("span");
        statusSpan.className = "caption";
        statusSpan.style.marginLeft = "0.5rem";
        const doSave = () => {
            const editor = quillByContainerId["quill-report"];
            const content = editor ? editor.getHtml() : document.getElementById("current-report")?.value ?? "";
            const margins = getMarginInputs("");
            const body = margins ? { content, margins } : { content };
            post("/missions/" + missionId + "/reports/" + reportType + "/save", body).then(() => {
                statusSpan.textContent = "Saved.";
            }).catch((err) => {
                statusSpan.textContent = err.message || "Save failed.";
            });
        };
        saveBtn.addEventListener("click", doSave);
        actions.appendChild(saveBtn);
        actions.appendChild(statusSpan);
        draftEl.appendChild(actions);
        const quill = createQuillEditor("quill-report", editorContainer, current, doSave);
        if (!quill) {
            editorContainer.innerHTML = "";
            const textarea = document.createElement("textarea");
            textarea.id = "current-report";
            textarea.rows = 16;
            textarea.value = current;
            editorContainer.appendChild(textarea);
        }
    }
    /** Populate only the proposed-changes panel list (used when draft is Quill so toolbar stays visible). */
    function fillChangesPanelOnly(report, pendingEdits) {
        const listEl = document.getElementById("changes-panel-list");
        const draftEl = document.getElementById("draft-area");
        if (!listEl)
            return;
        listEl.innerHTML = "";
        for (const edit of pendingEdits) {
            const row = document.createElement("div");
            row.className = "change-panel-row " + ((edit.status || "").toLowerCase() === "accepted" ? "change-accepted" : (edit.status || "").toLowerCase() === "rejected" ? "change-rejected" : "");
            row.setAttribute("data-target-block", edit.target_block_id);
            const summary = (edit.reason || (edit.new_html || "").replace(/<[^>]+>/g, "").trim().slice(0, 40) || edit.operation) + (edit.reason && edit.reason.length > 40 ? "…" : "");
            const opBadge = document.createElement("span");
            opBadge.className = "change-op-badge";
            opBadge.textContent = edit.operation;
            const textSpan = document.createElement("span");
            textSpan.className = "change-summary";
            textSpan.textContent = summary;
            const statusSpan = document.createElement("span");
            statusSpan.className = "change-status";
            statusSpan.textContent = edit.status;
            const acceptBtn = document.createElement("button");
            acceptBtn.type = "button";
            acceptBtn.className = "btn btn-sm btn-success";
            acceptBtn.textContent = (edit.status || "").toLowerCase() === "accepted" ? "Accepted" : "Accept";
            if ((edit.status || "").toLowerCase() === "accepted")
                acceptBtn.disabled = true;
            acceptBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                post("/missions/" + missionId + "/reports/" + reportType + "/edits/" + encodeURIComponent(edit.edit_id) + "/accept")
                    .then(() => post("/missions/" + missionId + "/reports/" + reportType + "/apply-edits"))
                    .then(() => fetchReport())
                    .then((r) => get("/missions/" + missionId + "/reports/" + reportType + "/pending-edits?_=" + Date.now())
                    .then((edits) => renderContent(r, false, edits))
                    .catch(() => renderContent(r, false, [])))
                    .catch((err) => alert(err instanceof Error ? err.message : "Failed"));
            });
            const rejectBtn = document.createElement("button");
            rejectBtn.type = "button";
            rejectBtn.className = "btn btn-sm btn-danger";
            rejectBtn.textContent = (edit.status || "").toLowerCase() === "rejected" ? "Rejected" : "Reject";
            if ((edit.status || "").toLowerCase() === "rejected")
                rejectBtn.disabled = true;
            rejectBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                post("/missions/" + missionId + "/reports/" + reportType + "/edits/" + encodeURIComponent(edit.edit_id) + "/reject")
                    .then(() => get("/missions/" + missionId + "/reports/" + reportType + "/pending-edits?_=" + Date.now()))
                    .then((edits) => renderContent(report, false, edits))
                    .catch((err) => alert(err instanceof Error ? err.message : "Failed"));
            });
            row.appendChild(opBadge);
            row.appendChild(textSpan);
            row.appendChild(statusSpan);
            row.appendChild(acceptBtn);
            row.appendChild(rejectBtn);
            row.addEventListener("click", () => {
                if (!draftEl)
                    return;
                const op = (edit.operation || "").toLowerCase();
                const scrollToId = (op === "insert_after" || op === "insert_before") && edit.edit_id ? edit.edit_id : edit.target_block_id;
                const blockEl = draftEl.querySelector("[data-block-id=\"" + scrollToId + "\"]");
                if (blockEl) {
                    blockEl.scrollIntoView({ behavior: "smooth", block: "center" });
                    blockEl.classList.add("block-highlight-temp");
                    setTimeout(() => blockEl.classList.remove("block-highlight-temp"), 2000);
                }
            });
            listEl.appendChild(row);
        }
    }
    function renderDraftAreaWithEdits(report, pendingEdits) {
        const draftEl = document.getElementById("draft-area");
        const listEl = document.getElementById("changes-panel-list");
        if (!draftEl || !listEl)
            return;
        draftEl.className = "draft-area draft-area-blocks";
        draftEl.innerHTML = "<p class=\"caption\">Loading…</p>";
        listEl.innerHTML = "";
        const isPending = (e) => {
            const s = (e.status || "").toLowerCase();
            return s !== "accepted" && s !== "rejected";
        };
        const targetIdsForReplace = new Set(pendingEdits
            .filter((e) => (e.operation || "").toLowerCase() === "replace" && isPending(e))
            .map((e) => e.target_block_id));
        const editsByBlock = new Map();
        for (const edit of pendingEdits) {
            const bid = edit.target_block_id;
            if (!bid)
                continue;
            if (!editsByBlock.has(bid))
                editsByBlock.set(bid, []);
            editsByBlock.get(bid).push(edit);
        }
        fillChangesPanelOnly(report, pendingEdits);
        get("/missions/" + missionId + "/reports/" + reportType + "/blocks")
            .then((res) => {
            draftEl.innerHTML = "";
            const p = document.createElement("p");
            p.className = "caption";
            p.textContent = "Draft (proposed changes highlighted)";
            draftEl.appendChild(p);
            const blocksContainer = document.createElement("div");
            blocksContainer.className = "draft-blocks";
            const blocks = res.blocks;
            for (let i = 0; i < blocks.length; i++) {
                const block = blocks[i];
                const blockEdits = editsByBlock.get(block.block_id) ?? [];
                const replaceEdit = blockEdits.find((e) => (e.operation || "").toLowerCase() === "replace" && (e.new_html ?? "").trim());
                const insertBeforeEdits = blockEdits.filter((e) => (e.operation || "").toLowerCase() === "insert_before" && (e.new_html ?? "").trim());
                for (const e of insertBeforeEdits) {
                    const insWrap = document.createElement("div");
                    insWrap.className = "draft-block block-inserted" + (isPending(e) ? " block-has-edit" : "");
                    insWrap.setAttribute("data-block-id", e.edit_id ?? "insert");
                    insWrap.innerHTML = e.new_html ?? "";
                    blocksContainer.appendChild(insWrap);
                }
                const wrap = document.createElement("div");
                wrap.className = "draft-block" + (targetIdsForReplace.has(block.block_id) ? " block-has-edit" : "");
                wrap.setAttribute("data-block-id", block.block_id);
                wrap.innerHTML = replaceEdit ? (replaceEdit.new_html ?? block.html) : block.html;
                blocksContainer.appendChild(wrap);
                const insertAfterEdits = blockEdits.filter((e) => (e.operation || "").toLowerCase() === "insert_after" && (e.new_html ?? "").trim());
                for (const e of insertAfterEdits) {
                    const insWrap = document.createElement("div");
                    insWrap.className = "draft-block block-inserted" + (isPending(e) ? " block-has-edit" : "");
                    insWrap.setAttribute("data-block-id", e.edit_id ?? "insert");
                    insWrap.innerHTML = e.new_html ?? "";
                    blocksContainer.appendChild(insWrap);
                }
            }
            draftEl.appendChild(blocksContainer);
        })
            .catch(() => {
            draftEl.innerHTML = "<p class=\"caption error\">Failed to load blocks.</p>";
        });
    }
    function renderContent(report, pipelineRunning, pendingEdits = []) {
        if (!report || typeof report !== "object") {
            main.innerHTML = '<p class="error">Report unavailable. Try again.</p><div class="section"><button type="button" class="btn btn-sm" id="btn-back-report">← Overview</button></div>';
            document.getElementById("btn-back-report")?.addEventListener("click", () => { navigate("/mission/" + missionId + "/overview"); render(); });
            return;
        }
        try {
            proposalSegments = [];
            proposalKept = [];
            const label = REPORT_LABELS[reportType];
            const freq = mission?.auto_update_frequency || "off";
            const hasPending = !!(report.pending_content != null && String(report.pending_content).length > 0);
            const hasAnyEdits = (pendingEdits?.length ?? 0) > 0;
            const isPendingEdit = (e) => {
                const s = (e.status || "").toLowerCase();
                return s !== "accepted" && s !== "rejected";
            };
            const hasPendingEdits = hasAnyEdits && pendingEdits.some(isPendingEdit);
            const showEditsPanel = hasPendingEdits;
            main.innerHTML = `
      <div class="section">
        <button type="button" class="btn btn-sm" id="btn-back-report">← Overview</button>
      </div>
      <div class="section">
        <h2>${escapeHtml(String(mission?.name ?? missionId))} · ${label}</h2>
        ${pipelineRunning ? '<p class="pill running">Updating…</p>' : ""}
        <div class="actions" style="margin-bottom: 1rem; flex-wrap: wrap; gap: 0.75rem;">
          <button type="button" class="btn btn-primary" id="btn-update-report">Update</button>
          <label class="caption" style="display: inline-flex; align-items: center; gap: 0.35rem;" title="Use the full indexed corpus instead of incremental new/changed files for this run.">
            <input type="checkbox" id="chk-full-refresh-report" />
            Full source refresh
          </label>
          <label class="caption" style="display: inline-flex; align-items: center; gap: 0.35rem;">
            Auto-update frequency:
            <select id="report-frequency" class="report-frequency-select">
              <option value="off" ${freq === "off" ? "selected" : ""}>Off</option>
              <option value="hourly" ${freq === "hourly" ? "selected" : ""}>Hourly</option>
              <option value="6h" ${freq === "6h" ? "selected" : ""}>Every 6 hours</option>
              <option value="daily" ${freq === "daily" ? "selected" : ""}>Daily</option>
            </select>
          </label>
          ${hasPending ? `
            <button type="button" class="btn btn-success btn-sm" id="btn-accept-all">Accept all</button>
            <button type="button" class="btn btn-danger btn-sm" id="btn-reject-all">Reject all</button>
            <button type="button" class="btn btn-sm" id="btn-apply-merged">Apply</button>
          ` : ""}
          ${hasAnyEdits ? `
            <button type="button" class="btn btn-success btn-sm" id="btn-accept-all-edits">Accept all</button>
            <button type="button" class="btn btn-danger btn-sm" id="btn-reject-all-edits">Reject all</button>
          ` : ""}
        </div>
        <div class="page-margins-row caption" style="display: flex; align-items: center; gap: 0.75rem; margin-top: 0.5rem; flex-wrap: wrap;">
          <span>Page margins (inches):</span>
          <label>Top <input type="number" id="margin-top" min="0" step="0.25" value="1" style="width: 4rem;"></label>
          <label>Right <input type="number" id="margin-right" min="0" step="0.25" value="1" style="width: 4rem;"></label>
          <label>Bottom <input type="number" id="margin-bottom" min="0" step="0.25" value="1" style="width: 4rem;"></label>
          <label>Left <input type="number" id="margin-left" min="0" step="0.25" value="1" style="width: 4rem;"></label>
        </div>
      </div>
      <div class="draft-page ${showEditsPanel ? "draft-page-with-panel" : ""}" id="draft-page-report">
        <div id="draft-area"></div>
        ${hasAnyEdits ? `<div class="changes-panel glass ${showEditsPanel ? "" : "changes-panel-hidden"}" id="changes-panel"><h3 class="changes-panel-title">Proposed changes</h3><div id="changes-panel-list"></div></div>` : ""}
        <div class="stream-box" id="stream-report" style="display: none;">Connecting…</div>
      </div>
    `;
            const draftArea = document.getElementById("draft-area");
            const streamEl = document.getElementById("stream-report");
            const draftPageEl = document.getElementById("draft-page-report");
            const stored = getStoredMargins(missionId, reportType);
            for (const k of ["top", "right", "bottom", "left"]) {
                const inp = document.getElementById("margin-" + k);
                if (inp)
                    inp.value = String(stored[k]);
            }
            function applyMarginsToDraftPage() {
                const m = getMarginInputs("");
                if (m && draftPageEl) {
                    const px = (inch) => Math.round(inch * 96);
                    draftPageEl.style.padding = `${px(m.top)}px ${px(m.right)}px ${px(m.bottom)}px ${px(m.left)}px`;
                    setStoredMargins(missionId, reportType, m);
                }
            }
            applyMarginsToDraftPage();
            for (const k of ["top", "right", "bottom", "left"]) {
                document.getElementById("margin-" + k)?.addEventListener("change", applyMarginsToDraftPage);
                document.getElementById("margin-" + k)?.addEventListener("input", applyMarginsToDraftPage);
            }
            if (hasAnyEdits) {
                streamEl.style.display = "none";
                renderDraftArea(report);
                const q0 = quillByContainerId["quill-report"];
                if (q0?.root)
                    q0.root.innerHTML = "<p><em>Loading proposed changes…</em></p>";
                fillChangesPanelOnly(report, pendingEdits);
                get("/missions/" + missionId + "/reports/" + reportType + "/preview")
                    .then((data) => {
                    const q = quillByContainerId["quill-report"];
                    const html = data.preview_html != null ? String(data.preview_html) : "";
                    if (q?.root)
                        q.root.innerHTML = html || "<p><br></p>";
                })
                    .catch(() => {
                    const q = quillByContainerId["quill-report"];
                    if (q?.root)
                        q.root.innerHTML = (report.current_content ?? "") || "<p><br></p>";
                });
                document.getElementById("btn-accept-all-edits").addEventListener("click", () => {
                    post("/missions/" + missionId + "/reports/" + reportType + "/accept-all-edits")
                        .then(() => post("/missions/" + missionId + "/reports/" + reportType + "/apply-edits"))
                        .then(() => fetchReport())
                        .then((r) => renderContent(r, false, []))
                        .catch((err) => alert(err instanceof Error ? err.message : "Failed"));
                });
                document.getElementById("btn-reject-all-edits").addEventListener("click", () => {
                    post("/missions/" + missionId + "/reports/" + reportType + "/reject-all-edits")
                        .then(() => fetchReport())
                        .then((r) => renderContent(r, false, []))
                        .catch((err) => alert(err instanceof Error ? err.message : "Failed"));
                });
            }
            else if (pipelineRunning) {
                streamEl.style.display = "none";
                renderDraftArea(report);
                const hiddenStream = document.createElement("div");
                hiddenStream.style.display = "none";
                hiddenStream.setAttribute("aria-hidden", "true");
                document.body.appendChild(hiddenStream);
                const updateBtn = document.getElementById("btn-update-report");
                if (updateBtn) {
                    updateBtn.disabled = true;
                    updateBtn.textContent = "Updating…";
                }
                const initialTemplate = (report.current_content ?? "").trim() || "";
                let resumeFinalized = false;
                function refreshReportAfterResume() {
                    if (resumeFinalized)
                        return;
                    resumeFinalized = true;
                    stopPipelineJobPoll?.();
                    stopPipelineJobPoll = null;
                    try {
                        hiddenStream.remove();
                    }
                    catch (_) { }
                    if (!hashMatchesReport(missionId, reportType)) {
                        render();
                        return;
                    }
                    fetchReport()
                        .then((r) => {
                        return get("/missions/" + missionId + "/reports/" + reportType + "/pending-edits")
                            .then((edits) => ({ r, pendingEdits: edits }))
                            .catch(() => ({ r, pendingEdits: [] }));
                    })
                        .then(({ r, pendingEdits }) => {
                        destroyAllQuillEditors();
                        setTimeout(() => {
                            try {
                                renderContent(r, false, pendingEdits);
                            }
                            catch (e) {
                                console.error(e);
                                if (updateBtn) {
                                    updateBtn.disabled = false;
                                    updateBtn.textContent = "Update";
                                }
                                alert("Failed to render report after update.");
                            }
                        }, 0);
                    })
                        .catch((err) => {
                        const msg = err instanceof Error ? err.message : String(err);
                        if (updateBtn) {
                            updateBtn.disabled = false;
                            updateBtn.textContent = "Update";
                        }
                        alert(msg || "Failed to load report after update.");
                    });
                }
                get("/missions/" + missionId + "/pipeline-jobs?limit=1")
                    .then((data) => {
                    const row = data.jobs?.[0];
                    if (row?.id && (row.status === "running" || row.status === "queued")) {
                        stopPipelineJobPoll = pollPipelineJobUntilTerminal(missionId, row.id, (j) => {
                            if (resumeFinalized)
                                return;
                            if (j.status === "failed") {
                                resumeFinalized = true;
                                stopPipelineJobPoll?.();
                                stopPipelineJobPoll = null;
                                try {
                                    hiddenStream.remove();
                                }
                                catch (_) { }
                                const fk = j.failure_kind ? String(j.failure_kind) + ": " : "";
                                alert(fk + (j.error_message || "Update failed"));
                                if (updateBtn) {
                                    updateBtn.disabled = false;
                                    updateBtn.textContent = "Update";
                                }
                                render();
                                return;
                            }
                            if (j.status === "completed") {
                                refreshReportAfterResume();
                            }
                        });
                    }
                })
                    .catch(() => { });
                closeStream = connectStream(missionId, reportType, hiddenStream, undefined, (content) => {
                    const merged = mergeLlmIntoDraft(initialTemplate, content);
                    const html = mergedToDisplayHtml(merged);
                    const quill = quillByContainerId["quill-report"];
                    if (quill?.root)
                        quill.root.innerHTML = html;
                });
            }
            else if (hasPending) {
                streamEl.style.display = "none";
                renderDraftArea(report);
                document.getElementById("btn-accept-all").addEventListener("click", () => {
                    post("/missions/" + missionId + "/reports/" + reportType + "/accept").then(() => fetchReport().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load report.")));
                });
                document.getElementById("btn-reject-all").addEventListener("click", () => {
                    post("/missions/" + missionId + "/reports/" + reportType + "/reject").then(() => fetchReport().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load report.")));
                });
                document.getElementById("btn-apply-merged").addEventListener("click", () => {
                    let segments;
                    if (proposalSegments.length) {
                        segments = proposalSegments;
                    }
                    else {
                        try {
                            segments = computeDiffSegments(report.current_content ?? "", report.pending_content ?? "");
                        }
                        catch (_) {
                            segments = [{ type: "change", oldContent: report.current_content ?? "", newContent: report.pending_content ?? "" }];
                        }
                    }
                    const changeCount = segments.filter((s) => s.type === "change").length;
                    const kept = proposalKept.length === changeCount ? proposalKept : Array(changeCount).fill(true);
                    const merged = changeCount === 0 ? (report.pending_content ?? report.current_content ?? "") : buildMergedFromSegments(segments, kept);
                    const margins = getMarginInputs("");
                    const body = margins ? { content: merged, margins } : { content: merged };
                    post("/missions/" + missionId + "/reports/" + reportType + "/save", body)
                        .then(() => post("/missions/" + missionId + "/reports/" + reportType + "/reject"))
                        .then(() => fetchReport().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load report.")))
                        .catch((err) => alert(err.message || "Failed to apply"));
                });
            }
            else {
                streamEl.style.display = "none";
                renderDraftArea(report);
            }
            document.getElementById("btn-back-report").addEventListener("click", () => {
                closeStream?.();
                navigate("/mission/" + missionId + "/overview");
                render();
            });
            document.getElementById("btn-update-report").addEventListener("click", () => {
                const updateBtn = document.getElementById("btn-update-report");
                const fullRefreshEl = document.getElementById("chk-full-refresh-report");
                closeStream?.();
                streamEl.style.display = "none";
                if (updateBtn) {
                    updateBtn.disabled = true;
                    updateBtn.textContent = "Updating…";
                }
                const updatingPill = document.createElement("p");
                updatingPill.className = "pill running";
                updatingPill.textContent = "Updating…";
                draftPageEl?.prepend(updatingPill);
                const hiddenStream = document.createElement("div");
                hiddenStream.style.display = "none";
                hiddenStream.setAttribute("aria-hidden", "true");
                document.body.appendChild(hiddenStream);
                const initialTemplate = (report.current_content ?? "").trim() || "";
                const UPDATE_TIMEOUT_MS = 5 * 60 * 1000;
                let updateTimeoutId = setTimeout(() => {
                    updateTimeoutId = null;
                    try {
                        hiddenStream.remove();
                        updatingPill.remove();
                    }
                    catch (_) { }
                    if (updateBtn) {
                        updateBtn.disabled = false;
                        updateBtn.textContent = "Update";
                    }
                    alert("Update is taking longer than usual (5 min). You can try again or check the server.");
                }, UPDATE_TIMEOUT_MS);
                let finalized = false;
                function cleanupUi() {
                    try {
                        hiddenStream.remove();
                        updatingPill.remove();
                    }
                    catch (_) { }
                    if (updateBtn) {
                        updateBtn.disabled = false;
                        updateBtn.textContent = "Update";
                    }
                }
                function finalizeSuccess() {
                    if (finalized)
                        return;
                    finalized = true;
                    if (updateTimeoutId != null) {
                        clearTimeout(updateTimeoutId);
                        updateTimeoutId = null;
                    }
                    stopPipelineJobPoll?.();
                    stopPipelineJobPoll = null;
                    closeStream?.();
                    cleanupUi();
                    if (!hashMatchesReport(missionId, reportType)) {
                        render();
                        return;
                    }
                    const refetchAndRender = () => {
                        fetchReportNoCache()
                            .then((r) => {
                            return get("/missions/" + missionId + "/reports/" + reportType + "/pending-edits")
                                .then((edits) => ({ r, pendingEdits: edits }))
                                .catch(() => ({ r, pendingEdits: [] }));
                        })
                            .then(({ r, pendingEdits }) => {
                            destroyAllQuillEditors();
                            setTimeout(() => {
                                try {
                                    renderContent(r, false, pendingEdits);
                                }
                                catch (e) {
                                    console.error(e);
                                    alert("Failed to render report after update.");
                                }
                            }, 0);
                        })
                            .catch((err) => {
                            const msg = err instanceof Error ? err.message : String(err);
                            alert(msg || "Failed to load report after update.");
                        });
                    };
                    setTimeout(refetchAndRender, 150);
                }
                function finalizeFailure(msg) {
                    if (finalized)
                        return;
                    finalized = true;
                    if (updateTimeoutId != null) {
                        clearTimeout(updateTimeoutId);
                        updateTimeoutId = null;
                    }
                    stopPipelineJobPoll?.();
                    stopPipelineJobPoll = null;
                    closeStream?.();
                    cleanupUi();
                    alert(msg);
                }
                closeStream = connectStream(missionId, reportType, hiddenStream, undefined, (content) => {
                    const merged = mergeLlmIntoDraft(initialTemplate, content);
                    const html = mergedToDisplayHtml(merged);
                    const quill = quillByContainerId["quill-report"];
                    if (quill?.root)
                        quill.root.innerHTML = html;
                });
                const updateBody = fullRefreshEl?.checked === true ? { update_intent: "full_refresh" } : {};
                post("/missions/" + missionId + "/reports/" + reportType + "/update", updateBody)
                    .then((res) => {
                    if (res.job_id) {
                        stopPipelineJobPoll = pollPipelineJobUntilTerminal(missionId, res.job_id, (j) => {
                            if (finalized)
                                return;
                            if (j.status === "failed") {
                                const fk = j.failure_kind ? String(j.failure_kind) + ": " : "";
                                finalizeFailure(fk + (j.error_message || "Update failed"));
                                return;
                            }
                            if (j.status === "completed") {
                                finalizeSuccess();
                            }
                        });
                    }
                    else {
                        finalizeFailure("No job id returned; cannot track update status.");
                    }
                })
                    .catch((err) => {
                    if (updateTimeoutId != null) {
                        clearTimeout(updateTimeoutId);
                        updateTimeoutId = null;
                    }
                    closeStream?.();
                    stopPipelineJobPoll?.();
                    stopPipelineJobPoll = null;
                    try {
                        updatingPill.remove();
                    }
                    catch (_) { }
                    if (updateBtn) {
                        updateBtn.disabled = false;
                        updateBtn.textContent = "Update";
                    }
                    alert(err.message || "Failed to start update");
                });
            });
            document.getElementById("report-frequency").addEventListener("change", () => {
                const sel = document.getElementById("report-frequency");
                const value = sel.value;
                patch("/missions/" + missionId + "/metadata", { auto_update_frequency: value }).then(() => {
                    if (mission)
                        mission.auto_update_frequency = value;
                }).catch((err) => alert(err.message || "Failed to update frequency"));
            });
        }
        catch (e) {
            console.error(e);
            main.innerHTML = '<p class="error">Something went wrong loading the report.</p><div class="section"><button type="button" class="btn btn-sm" id="btn-back-report">← Overview</button></div>';
            document.getElementById("btn-back-report")?.addEventListener("click", () => { navigate("/mission/" + missionId + "/overview"); render(); });
        }
    }
    get("/missions/" + missionId)
        .then((m) => {
        mission = m;
        return get("/status");
    })
        .then((status) => {
        const pipelineRunning = status.running_mission_id === missionId;
        return fetchReport().then((report) => ({ report, pipelineRunning }));
    })
        .then(({ report, pipelineRunning }) => {
        return get("/missions/" + missionId + "/reports/" + reportType + "/pending-edits")
            .then((pendingEdits) => ({ report, pipelineRunning, pendingEdits }))
            .catch(() => ({ report, pipelineRunning, pendingEdits: [] }));
    })
        .then(({ report, pipelineRunning, pendingEdits }) => {
        if (!hashMatchesReport(missionId, reportType)) {
            render();
            return;
        }
        try {
            renderContent(report, pipelineRunning, pendingEdits);
        }
        catch (e) {
            console.error(e);
            main.innerHTML = '<p class="error">Something went wrong loading this report.</p><div class="section"><button type="button" class="btn btn-sm" id="btn-back-report">← Overview</button></div>';
            document.getElementById("btn-back-report")?.addEventListener("click", () => { navigate("/mission/" + missionId + "/overview"); render(); });
        }
    })
        .catch(() => {
        const backBtn = '<div class="section"><button type="button" class="btn btn-sm" id="btn-back-report">← Overview</button></div>';
        if (!mission) {
            main.innerHTML = '<p class="error">Mission not found.</p>' + backBtn;
        }
        else {
            main.innerHTML = '<p class="error">Report unavailable. Try again.</p>' + backBtn;
        }
        document.getElementById("btn-back-report")?.addEventListener("click", () => { navigate("/mission/" + missionId + "/overview"); render(); });
    });
}
/** Legacy: combined RMP + Timeline documents view; same single-draft + per-section Undo/Keep as report view. */
function renderDocumentsView(missionId, main) {
    let mission = null;
    let closeRmp = null;
    let closeTimeline = null;
    let stopDocsJobPoll = null;
    currentReportCleanup = () => {
        stopDocsJobPoll?.();
        stopDocsJobPoll = null;
        closeRmp?.();
        closeTimeline?.();
        destroyAllQuillEditors();
    };
    let rmpSegments = [];
    let rmpKept = [];
    let timelineSegments = [];
    let timelineKept = [];
    let currentReports = null;
    function fetchReports() {
        return Promise.all([
            get("/missions/" + missionId + "/reports/rmp"),
            get("/missions/" + missionId + "/reports/timeline"),
        ]).then(([rmp, timeline]) => ({ rmp, timeline }));
    }
    function renderDocDraftArea(type, report, draftEl, segmentsRef, keptRef) {
        const current = report.current_content ?? "";
        const pending = report.pending_content;
        draftEl.innerHTML = "";
        if (pending) {
            if (segmentsRef.current.length === 0) {
                const segs = computeDiffSegments(current, pending);
                segmentsRef.current.length = 0;
                segmentsRef.current.push(...segs);
                keptRef.current = segs.filter((s) => s.type === "change").map(() => true);
            }
            let changeIdx = 0;
            draftEl.className = "draft-area draft-area-diff";
            for (const seg of segmentsRef.current) {
                if (seg.type === "equal") {
                    const pre = document.createElement("pre");
                    pre.className = "draft-segment draft-segment-equal";
                    pre.style.whiteSpace = "pre-wrap";
                    pre.textContent = seg.oldContent;
                    draftEl.appendChild(pre);
                }
                else {
                    const kept = keptRef.current[changeIdx] !== false;
                    const content = kept ? seg.newContent : seg.oldContent;
                    const wrap = document.createElement("div");
                    wrap.className = "draft-hunk " + (kept ? "draft-hunk-kept" : "draft-hunk-undo");
                    const pre = document.createElement("pre");
                    pre.style.whiteSpace = "pre-wrap";
                    pre.textContent = content;
                    const ctrls = document.createElement("div");
                    ctrls.className = "draft-hunk-controls";
                    const undoBtn = document.createElement("button");
                    undoBtn.type = "button";
                    undoBtn.className = "btn btn-sm";
                    undoBtn.textContent = "Undo";
                    undoBtn.setAttribute("aria-label", "Undo change " + (changeIdx + 1));
                    const keepBtn = document.createElement("button");
                    keepBtn.type = "button";
                    keepBtn.className = "btn btn-sm btn-success";
                    keepBtn.textContent = "Keep";
                    keepBtn.setAttribute("aria-label", "Keep change " + (changeIdx + 1));
                    const thisChangeIdx = changeIdx;
                    undoBtn.addEventListener("click", () => {
                        keptRef.current[thisChangeIdx] = false;
                        if (currentReports)
                            renderDocDraftArea(type, type === "rmp" ? currentReports.rmp : currentReports.timeline, draftEl, segmentsRef, keptRef);
                    });
                    keepBtn.addEventListener("click", () => {
                        keptRef.current[thisChangeIdx] = true;
                        if (currentReports)
                            renderDocDraftArea(type, type === "rmp" ? currentReports.rmp : currentReports.timeline, draftEl, segmentsRef, keptRef);
                    });
                    ctrls.appendChild(undoBtn);
                    ctrls.appendChild(keepBtn);
                    wrap.appendChild(pre);
                    wrap.appendChild(ctrls);
                    draftEl.appendChild(wrap);
                    changeIdx++;
                }
            }
            return;
        }
        draftEl.className = "draft-area";
        draftEl.innerHTML = "";
        const p = document.createElement("p");
        p.className = "caption";
        p.textContent = "Draft (edit and save with Ctrl+S or Save)";
        draftEl.appendChild(p);
        const editorContainer = document.createElement("div");
        editorContainer.className = "quill-draft-container";
        draftEl.appendChild(editorContainer);
        const actions = document.createElement("div");
        actions.className = "actions";
        actions.style.marginTop = "0.5rem";
        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "btn btn-sm";
        saveBtn.id = "btn-save-" + type;
        saveBtn.textContent = "Save edits to drop-off";
        const statusSpan = document.createElement("span");
        statusSpan.className = "caption";
        statusSpan.style.marginLeft = "0.5rem";
        const doSave = () => {
            const editor = quillByContainerId["quill-" + type];
            const content = editor ? editor.getHtml() : document.getElementById("current-" + type)?.value ?? "";
            const margins = getMarginInputs(type + "-");
            const body = margins ? { content, margins } : { content };
            post("/missions/" + missionId + "/reports/" + type + "/save", body).then(() => {
                statusSpan.textContent = "Saved.";
            }).catch((err) => {
                statusSpan.textContent = err.message || "Save failed.";
            });
        };
        saveBtn.addEventListener("click", doSave);
        actions.appendChild(saveBtn);
        actions.appendChild(statusSpan);
        draftEl.appendChild(actions);
        const quill = createQuillEditor("quill-" + type, editorContainer, current, doSave);
        if (!quill) {
            editorContainer.innerHTML = "";
            const textarea = document.createElement("textarea");
            textarea.id = "current-" + type;
            textarea.rows = 10;
            textarea.value = current;
            editorContainer.appendChild(textarea);
        }
    }
    function renderContent(reports, pipelineRunning) {
        currentReports = reports;
        rmpSegments = [];
        rmpKept = [];
        timelineSegments = [];
        timelineKept = [];
        const rmp = reports.rmp;
        const timeline = reports.timeline;
        const missionName = mission?.name ?? missionId;
        const rmpPending = !!rmp.pending_content;
        const timelinePending = !!timeline.pending_content;
        main.innerHTML = `
      <div class="section">
        <button type="button" class="btn btn-sm" id="btn-back-docs">← Mission overview</button>
      </div>
      <div class="section">
        <h2>${escapeHtml(String(missionName))} · RMP & Timeline</h2>
        ${pipelineRunning ? '<p class="pill running">Updating…</p>' : ""}
        <div class="actions" style="margin-bottom: 1rem; flex-wrap: wrap; gap: 0.75rem;">
          <button type="button" class="btn btn-primary" id="btn-run-pipeline-docs">Run pipeline now (all reports)</button>
          <label class="caption" style="display: inline-flex; align-items: center; gap: 0.35rem;" title="Use the full indexed corpus instead of incremental new/changed files for this run.">
            <input type="checkbox" id="chk-full-refresh-pipeline" />
            Full source refresh
          </label>
        </div>
      </div>

      <div class="draft-page" id="draft-page-rmp">
        <h3>Risk Mitigation Plan (RMP)</h3>
        <div class="page-margins-row caption" style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; flex-wrap: wrap;">
          <span>Margins (in):</span>
          <label>T <input type="number" id="rmp-margin-top" min="0" step="0.25" value="1" style="width: 3.5rem;"></label>
          <label>R <input type="number" id="rmp-margin-right" min="0" step="0.25" value="1" style="width: 3.5rem;"></label>
          <label>B <input type="number" id="rmp-margin-bottom" min="0" step="0.25" value="1" style="width: 3.5rem;"></label>
          <label>L <input type="number" id="rmp-margin-left" min="0" step="0.25" value="1" style="width: 3.5rem;"></label>
        </div>
        ${rmpPending ? `<div class="actions" style="margin-bottom: 0.5rem;"><button type="button" class="btn btn-success btn-sm btn-accept-rmp">Accept all</button><button type="button" class="btn btn-danger btn-sm btn-reject-rmp">Reject all</button><button type="button" class="btn btn-sm btn-apply-rmp">Apply</button></div>` : ""}
        <div id="draft-area-rmp"></div>
        <div class="stream-box" id="stream-rmp" data-report="rmp" style="display: none;">Connecting…</div>
      </div>

      <div class="draft-page" id="draft-page-timeline">
        <h3>Mission Timeline</h3>
        <div class="page-margins-row caption" style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; flex-wrap: wrap;">
          <span>Margins (in):</span>
          <label>T <input type="number" id="timeline-margin-top" min="0" step="0.25" value="1" style="width: 3.5rem;"></label>
          <label>R <input type="number" id="timeline-margin-right" min="0" step="0.25" value="1" style="width: 3.5rem;"></label>
          <label>B <input type="number" id="timeline-margin-bottom" min="0" step="0.25" value="1" style="width: 3.5rem;"></label>
          <label>L <input type="number" id="timeline-margin-left" min="0" step="0.25" value="1" style="width: 3.5rem;"></label>
        </div>
        ${timelinePending ? `<div class="actions" style="margin-bottom: 0.5rem;"><button type="button" class="btn btn-success btn-sm btn-accept-timeline">Accept all</button><button type="button" class="btn btn-danger btn-sm btn-reject-timeline">Reject all</button><button type="button" class="btn btn-sm btn-apply-timeline">Apply</button></div>` : ""}
        <div id="draft-area-timeline"></div>
        <div class="stream-box" id="stream-timeline" data-report="timeline" style="display: none;">Connecting…</div>
      </div>
    `;
        const draftRmp = document.getElementById("draft-area-rmp");
        const draftTimeline = document.getElementById("draft-area-timeline");
        const streamRmp = document.getElementById("stream-rmp");
        const streamTimeline = document.getElementById("stream-timeline");
        const draftPageRmp = document.getElementById("draft-page-rmp");
        const draftPageTimeline = document.getElementById("draft-page-timeline");
        function applyDocMargins(prefix) {
            const m = getMarginInputs(prefix + "-");
            const el = prefix === "rmp" ? draftPageRmp : draftPageTimeline;
            if (m && el) {
                const px = (inch) => Math.round(inch * 96);
                el.style.padding = `${px(m.top)}px ${px(m.right)}px ${px(m.bottom)}px ${px(m.left)}px`;
                setStoredMargins(missionId, prefix, m);
            }
        }
        for (const prefix of ["rmp", "timeline"]) {
            const stored = getStoredMargins(missionId, prefix);
            for (const k of ["top", "right", "bottom", "left"]) {
                const inp = document.getElementById(prefix + "-margin-" + k);
                if (inp)
                    inp.value = String(stored[k]);
            }
            applyDocMargins(prefix);
            for (const k of ["top", "right", "bottom", "left"]) {
                document.getElementById(prefix + "-margin-" + k)?.addEventListener("change", () => applyDocMargins(prefix));
                document.getElementById(prefix + "-margin-" + k)?.addEventListener("input", () => applyDocMargins(prefix));
            }
        }
        streamRmp.style.display = "none";
        streamTimeline.style.display = "none";
        renderDocDraftArea("rmp", rmp, draftRmp, { current: rmpSegments }, { current: rmpKept });
        renderDocDraftArea("timeline", timeline, draftTimeline, { current: timelineSegments }, { current: timelineKept });
        if (pipelineRunning) {
            const hiddenRmp = document.createElement("div");
            hiddenRmp.style.display = "none";
            hiddenRmp.setAttribute("aria-hidden", "true");
            const hiddenTimeline = document.createElement("div");
            hiddenTimeline.style.display = "none";
            hiddenTimeline.setAttribute("aria-hidden", "true");
            document.body.appendChild(hiddenRmp);
            document.body.appendChild(hiddenTimeline);
            let resumeFinalized = false;
            function refreshAfterResume() {
                if (resumeFinalized)
                    return;
                resumeFinalized = true;
                stopDocsJobPoll?.();
                stopDocsJobPoll = null;
                try {
                    hiddenRmp.remove();
                    hiddenTimeline.remove();
                }
                catch (_) { }
                fetchReports()
                    .then((r) => {
                    destroyAllQuillEditors();
                    setTimeout(() => {
                        try {
                            renderContent(r, false);
                        }
                        catch (e) {
                            console.error(e);
                            alert("Failed to render reports after update.");
                        }
                    }, 0);
                })
                    .catch((err) => {
                    const msg = err instanceof Error ? err.message : String(err);
                    alert(msg || "Failed to load reports after update.");
                });
            }
            get("/missions/" + missionId + "/pipeline-jobs?limit=1")
                .then((data) => {
                const row = data.jobs?.[0];
                if (row?.id && (row.status === "running" || row.status === "queued")) {
                    stopDocsJobPoll = pollPipelineJobUntilTerminal(missionId, row.id, (j) => {
                        if (resumeFinalized)
                            return;
                        if (j.status === "failed") {
                            resumeFinalized = true;
                            stopDocsJobPoll?.();
                            stopDocsJobPoll = null;
                            try {
                                hiddenRmp.remove();
                                hiddenTimeline.remove();
                            }
                            catch (_) { }
                            const fk = j.failure_kind ? String(j.failure_kind) + ": " : "";
                            alert(fk + (j.error_message || "Pipeline failed"));
                            render();
                            return;
                        }
                        if (j.status === "completed") {
                            refreshAfterResume();
                        }
                    });
                }
            })
                .catch(() => { });
            const initialRmp = (rmp.current_content ?? "").trim() || "";
            const initialTimeline = (timeline.current_content ?? "").trim() || "";
            closeRmp = connectStream(missionId, "rmp", hiddenRmp, undefined, (content) => {
                const merged = mergeLlmIntoDraft(initialRmp, content);
                const html = mergedToDisplayHtml(merged);
                const quill = quillByContainerId["quill-rmp"];
                if (quill?.root)
                    quill.root.innerHTML = html;
            });
            closeTimeline = connectStream(missionId, "timeline", hiddenTimeline, undefined, (content) => {
                const merged = mergeLlmIntoDraft(initialTimeline, content);
                const html = mergedToDisplayHtml(merged);
                const quill = quillByContainerId["quill-timeline"];
                if (quill?.root)
                    quill.root.innerHTML = html;
            });
        }
        else {
            if (rmpPending) {
                document.querySelector(".btn-accept-rmp")?.addEventListener("click", () => {
                    post("/missions/" + missionId + "/reports/rmp/accept").then(() => fetchReports().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load reports.")));
                });
                document.querySelector(".btn-reject-rmp")?.addEventListener("click", () => {
                    post("/missions/" + missionId + "/reports/rmp/reject").then(() => fetchReports().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load reports.")));
                });
                document.querySelector(".btn-apply-rmp")?.addEventListener("click", () => {
                    const segs = rmpSegments.length ? rmpSegments : computeDiffSegments(rmp.current_content ?? "", rmp.pending_content ?? "");
                    const n = segs.filter((s) => s.type === "change").length;
                    const kept = rmpKept.length === n ? rmpKept : Array(n).fill(true);
                    const merged = n === 0 ? (rmp.pending_content ?? rmp.current_content ?? "") : buildMergedFromSegments(segs, kept);
                    const margins = getMarginInputs("rmp-");
                    const body = margins ? { content: merged, margins } : { content: merged };
                    post("/missions/" + missionId + "/reports/rmp/save", body)
                        .then(() => post("/missions/" + missionId + "/reports/rmp/reject"))
                        .then(() => fetchReports().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load reports.")))
                        .catch((err) => alert(err.message || "Failed to apply"));
                });
            }
            if (timelinePending) {
                document.querySelector(".btn-accept-timeline")?.addEventListener("click", () => {
                    post("/missions/" + missionId + "/reports/timeline/accept").then(() => fetchReports().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load reports.")));
                });
                document.querySelector(".btn-reject-timeline")?.addEventListener("click", () => {
                    post("/missions/" + missionId + "/reports/timeline/reject").then(() => fetchReports().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load reports.")));
                });
                document.querySelector(".btn-apply-timeline")?.addEventListener("click", () => {
                    const segs = timelineSegments.length ? timelineSegments : computeDiffSegments(timeline.current_content ?? "", timeline.pending_content ?? "");
                    const n = segs.filter((s) => s.type === "change").length;
                    const kept = timelineKept.length === n ? timelineKept : Array(n).fill(true);
                    const merged = n === 0 ? (timeline.pending_content ?? timeline.current_content ?? "") : buildMergedFromSegments(segs, kept);
                    const margins = getMarginInputs("timeline-");
                    const body = margins ? { content: merged, margins } : { content: merged };
                    post("/missions/" + missionId + "/reports/timeline/save", body)
                        .then(() => post("/missions/" + missionId + "/reports/timeline/reject"))
                        .then(() => fetchReports().then((r) => renderContent(r, false)).catch((err) => alert(err instanceof Error ? err.message : "Failed to load reports.")))
                        .catch((err) => alert(err.message || "Failed to apply"));
                });
            }
        }
        document.getElementById("btn-back-docs").addEventListener("click", () => {
            closeRmp?.();
            closeTimeline?.();
            navigate("/mission/" + missionId + "/overview");
            render();
        });
        document.getElementById("btn-run-pipeline-docs").addEventListener("click", () => {
            const runBtn = document.getElementById("btn-run-pipeline-docs");
            const fullRefreshEl = document.getElementById("chk-full-refresh-pipeline");
            closeRmp?.();
            closeTimeline?.();
            if (runBtn) {
                runBtn.disabled = true;
                runBtn.textContent = "Updating…";
            }
            const updatingPill = document.createElement("p");
            updatingPill.className = "pill running";
            updatingPill.textContent = "Updating…";
            draftPageRmp?.prepend(updatingPill);
            const hiddenRmp = document.createElement("div");
            hiddenRmp.style.display = "none";
            hiddenRmp.setAttribute("aria-hidden", "true");
            const hiddenTimeline = document.createElement("div");
            hiddenTimeline.style.display = "none";
            hiddenTimeline.setAttribute("aria-hidden", "true");
            document.body.appendChild(hiddenRmp);
            document.body.appendChild(hiddenTimeline);
            let finalized = false;
            function cleanupRunUi() {
                try {
                    hiddenRmp.remove();
                    hiddenTimeline.remove();
                    updatingPill.remove();
                }
                catch (_) { }
                if (runBtn) {
                    runBtn.disabled = false;
                    runBtn.textContent = "Run pipeline now (all reports)";
                }
            }
            function finalizeRunSuccess() {
                if (finalized)
                    return;
                finalized = true;
                stopDocsJobPoll?.();
                stopDocsJobPoll = null;
                closeRmp?.();
                closeTimeline?.();
                cleanupRunUi();
                fetchReports()
                    .then((r) => {
                    destroyAllQuillEditors();
                    setTimeout(() => {
                        try {
                            renderContent(r, false);
                        }
                        catch (e) {
                            console.error(e);
                            alert("Failed to render reports after update.");
                        }
                    }, 0);
                })
                    .catch((err) => {
                    const msg = err instanceof Error ? err.message : String(err);
                    alert(msg || "Failed to load reports after update.");
                });
            }
            function finalizeRunFailure(msg) {
                if (finalized)
                    return;
                finalized = true;
                stopDocsJobPoll?.();
                stopDocsJobPoll = null;
                closeRmp?.();
                closeTimeline?.();
                cleanupRunUi();
                alert(msg);
            }
            const initialRmp = (rmp.current_content ?? "").trim() || "";
            const initialTimeline = (timeline.current_content ?? "").trim() || "";
            closeRmp = connectStream(missionId, "rmp", hiddenRmp, undefined, (content) => {
                const merged = mergeLlmIntoDraft(initialRmp, content);
                const html = mergedToDisplayHtml(merged);
                const quill = quillByContainerId["quill-rmp"];
                if (quill?.root)
                    quill.root.innerHTML = html;
            });
            closeTimeline = connectStream(missionId, "timeline", hiddenTimeline, undefined, (content) => {
                const merged = mergeLlmIntoDraft(initialTimeline, content);
                const html = mergedToDisplayHtml(merged);
                const quill = quillByContainerId["quill-timeline"];
                if (quill?.root)
                    quill.root.innerHTML = html;
            });
            const runBody = { mission_id: missionId };
            if (fullRefreshEl?.checked === true) {
                runBody.update_intent = "full_refresh";
            }
            post("/run-pipeline", runBody)
                .then((res) => {
                if (res.job_id) {
                    stopDocsJobPoll = pollPipelineJobUntilTerminal(missionId, res.job_id, (j) => {
                        if (finalized)
                            return;
                        if (j.status === "failed") {
                            const fk = j.failure_kind ? String(j.failure_kind) + ": " : "";
                            finalizeRunFailure(fk + (j.error_message || "Pipeline failed"));
                            return;
                        }
                        if (j.status === "completed") {
                            finalizeRunSuccess();
                        }
                    });
                }
                else {
                    finalizeRunFailure("No job id returned; cannot track pipeline status.");
                }
            })
                .catch((err) => {
                closeRmp?.();
                closeTimeline?.();
                stopDocsJobPoll?.();
                stopDocsJobPoll = null;
                try {
                    updatingPill.remove();
                }
                catch (_) { }
                if (runBtn) {
                    runBtn.disabled = false;
                    runBtn.textContent = "Run pipeline now (all reports)";
                }
                alert(err.message || "Failed to start pipeline");
            });
        });
    }
    get("/missions/" + missionId)
        .then((m) => {
        mission = m;
        return get("/status");
    })
        .then((status) => {
        const pipelineRunning = status.running_mission_id === missionId;
        return fetchReports().then((reports) => ({
            reports,
            pipelineRunning,
        }));
    })
        .then(({ reports, pipelineRunning }) => {
        renderContent(reports, pipelineRunning);
    })
        .catch(() => {
        main.innerHTML = '<p class="error">Mission not found.</p>';
    });
}
function render() {
    const main = document.getElementById("main");
    const parts = getHashParts();
    const listEl = document.getElementById("mission-list");
    if (parts[0] === "new") {
        renderNewMissionForm(main);
        renderMissionList(listEl, null, null);
        return;
    }
    if (parts[0] === "mission" && parts[1]) {
        currentReportCleanup?.();
        currentReportCleanup = null;
        const missionId = parts[1];
        const sub = parts[2] || "overview";
        expandedMissions.add(missionId);
        renderMissionList(listEl, missionId, sub === "overview" ? "overview" : sub);
        if (sub === "documents") {
            renderDocumentsView(missionId, main);
        }
        else if (REPORT_TYPES.includes(sub)) {
            renderReportView(missionId, sub, main);
        }
        else {
            renderMissionOverview(missionId, main);
        }
        return;
    }
    renderMissionList(listEl, null, null);
    main.innerHTML =
        '<div id="view-placeholder"><p class="empty">Select a mission or create one.</p></div>';
}
// ---------- Init ----------
const SIDEBAR_COLLAPSED_KEY = "sidebarCollapsed";
function applySidebarCollapsed(collapsed) {
    const app = document.querySelector(".app");
    const btn = document.getElementById("sidebar-toggle");
    if (app)
        app.classList.toggle("sidebar-collapsed", collapsed);
    if (btn) {
        btn.setAttribute("aria-expanded", String(!collapsed));
        btn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
        btn.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");
    }
}
function initSidebarToggle() {
    const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (stored === "true")
        applySidebarCollapsed(true);
    const btn = document.getElementById("sidebar-toggle");
    if (!btn)
        return;
    btn.addEventListener("click", () => {
        const app = document.querySelector(".app");
        const currentlyCollapsed = app?.classList.contains("sidebar-collapsed") ?? false;
        const collapsed = !currentlyCollapsed;
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
        applySidebarCollapsed(collapsed);
    });
}
document.getElementById("btn-new-mission").addEventListener("click", () => {
    navigate("/new");
    render();
});
initSidebarToggle();
function updateSidebarStatus() {
    get("/status")
        .then((s) => {
        const el = document.getElementById("sidebar-status");
        if (s.running_mission_id)
            el.textContent = "Pipeline running…";
        else
            el.textContent = "";
    })
        .catch(() => { });
    setTimeout(updateSidebarStatus, 5000);
}
window.addEventListener("hashchange", render);
window.addEventListener("unhandledrejection", (e) => {
    console.error("Unhandled promise rejection:", e.reason);
});
window.onerror = (_message, _source, _lineno, _colno, error) => {
    console.error("Unhandled error:", error ?? _message);
    return false;
};
updateSidebarStatus();
render();
