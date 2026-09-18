/**
 * CyberScribe – Liquid Glass UI
 * Phase 2: bundled with Vite; Tiptap report editor (`tiptap-editor.ts`).
 */

import {
  createReportEditor,
  destroyAllReportEditors,
  getReportEditor,
  type InlineAssistRunner,
} from "./tiptap-editor";
import {
  applyCommentHighlights,
  buildAnchorPayload,
  type CommentAnchorJson,
} from "./report-comment-extension";

const API = "/api";

/** Shown in Mission Control hub header. */
const APP_VERSION = "0.1.1";

/** Set after /auth/me succeeds (planning pack: session cookie auth). */
type LoggedInUser = {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  has_mel_role?: boolean;
};
let currentUser: LoggedInUser | null = null;

const REPORT_TYPES = ["rmp", "timeline", "aar", "sitrep"] as const;
type ReportType = (typeof REPORT_TYPES)[number];

const REPORT_LABELS: Record<ReportType, string> = {
  rmp: "RMP",
  timeline: "Timeline",
  aar: "AAR",
  sitrep: "SITREP",
};

const MARGINS_STORAGE_KEY = "reportMargins";

function getStoredMargins(missionId: string, reportType: string): { top: number; right: number; bottom: number; left: number } {
  try {
    const raw = localStorage.getItem(`${MARGINS_STORAGE_KEY}_${missionId}_${reportType}`);
    if (raw) {
      const o = JSON.parse(raw) as { top?: number; right?: number; bottom?: number; left?: number };
      return {
        top: typeof o.top === "number" ? o.top : 1,
        right: typeof o.right === "number" ? o.right : 1,
        bottom: typeof o.bottom === "number" ? o.bottom : 1,
        left: typeof o.left === "number" ? o.left : 1,
      };
    }
  } catch (_) {}
  return { top: 1, right: 1, bottom: 1, left: 1 };
}

function setStoredMargins(missionId: string, reportType: string, margins: { top: number; right: number; bottom: number; left: number }): void {
  try {
    localStorage.setItem(`${MARGINS_STORAGE_KEY}_${missionId}_${reportType}`, JSON.stringify(margins));
  } catch (_) {}
}

function getMarginInputs(prefix: string): { top: number; right: number; bottom: number; left: number } | null {
  const top = document.getElementById(prefix + "margin-top") as HTMLInputElement | null;
  const right = document.getElementById(prefix + "margin-right") as HTMLInputElement | null;
  const bottom = document.getElementById(prefix + "margin-bottom") as HTMLInputElement | null;
  const left = document.getElementById(prefix + "margin-left") as HTMLInputElement | null;
  if (!top || !right || !bottom || !left) return null;
  return {
    top: Math.max(0, parseFloat(top.value) || 0),
    right: Math.max(0, parseFloat(right.value) || 0),
    bottom: Math.max(0, parseFloat(bottom.value) || 0),
    left: Math.max(0, parseFloat(left.value) || 0),
  };
}

/** Cleanup for current report view (close SSE streams when navigating away). */
let currentReportCleanup: (() => void) | null = null;
let overviewPresenceTimer: ReturnType<typeof setInterval> | null = null;

/** Incremented on every `render()` to drop stale `renderMissionOverview` async completions. */
let missionOverviewEpoch = 0;

function stopOverviewPresence(): void {
  if (overviewPresenceTimer) {
    clearInterval(overviewPresenceTimer);
    overviewPresenceTimer = null;
  }
}

let overviewTeamRailSyncObserver: ResizeObserver | null = null;
let overviewTeamRailSyncRaf = 0;

function teardownOverviewTeamRailSync(): void {
  if (overviewTeamRailSyncObserver) {
    overviewTeamRailSyncObserver.disconnect();
    overviewTeamRailSyncObserver = null;
  }
  if (overviewTeamRailSyncRaf) {
    cancelAnimationFrame(overviewTeamRailSyncRaf);
    overviewTeamRailSyncRaf = 0;
  }
  window.removeEventListener("resize", scheduleOverviewTeamRailSync);
}

function scheduleOverviewTeamRailSync(): void {
  if (overviewTeamRailSyncRaf) cancelAnimationFrame(overviewTeamRailSyncRaf);
  overviewTeamRailSyncRaf = requestAnimationFrame(() => {
    overviewTeamRailSyncRaf = 0;
    syncOverviewTeamListHeightToReportGrid();
  });
}

/** Desktop: stretch Team list band so Quick actions divider aligns with report card row top. */
function syncOverviewTeamListHeightToReportGrid(): void {
  const grid = document.getElementById("overview-report-cards");
  const cardEl = document.querySelector(".overview-rail-card--team-quick");
  const card = cardEl instanceof HTMLElement ? cardEl : null;
  const divider = cardEl?.querySelector(".overview-rail-divider");
  const list = cardEl?.querySelector(".overview-team-list") as HTMLElement | null;
  if (!grid || !card || !divider || !list) return;

  if (!window.matchMedia("(min-width: 961px)").matches) {
    card.style.removeProperty("--overview-team-list-height");
    return;
  }

  const rootFs = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const baseRem = 15;
  const basePx = baseRem * rootFs;

  card.style.removeProperty("--overview-team-list-height");
  void list.offsetHeight;

  const firstCard = grid.querySelector(".overview-report-card");
  const anchor = firstCard ?? grid;
  const gridTop = anchor.getBoundingClientRect().top;
  const dividerTop = divider.getBoundingClientRect().top;
  const delta = gridTop - dividerTop;
  const newPx = Math.max(basePx, Math.round(basePx + delta));
  card.style.setProperty("--overview-team-list-height", `${newPx}px`);
}

function setupOverviewTeamRailSync(): void {
  teardownOverviewTeamRailSync();
  const dashboard = document.querySelector(".overview-dashboard");
  if (!dashboard) return;
  overviewTeamRailSyncObserver = new ResizeObserver(() => scheduleOverviewTeamRailSync());
  overviewTeamRailSyncObserver.observe(dashboard);
  window.addEventListener("resize", scheduleOverviewTeamRailSync);
  scheduleOverviewTeamRailSync();
}

// ---------- API response types ----------

interface Mission {
  id: string;
  name: string;
  source_path: string;
  output_path: string;
  status: string;
  lifecycle_status?: string | null;
  last_ingest_at?: string | null;
  last_generated_at?: string | null;
  cpt?: string | null;
  workflow_title?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  operators?: string | null; // JSON
  mel?: string | null;
  ccl_host?: string | null;
  ccl_network?: string | null;
  auto_update_frequency?: string | null;
  /** Phase 1: auto (default) | manual — manual confirm UX comes in a later phase */
  ingest_mode?: string | null;
  operator_count?: number;
  /** Current user's role on this mission (from list API); null for admins listing all missions. */
  membership_role?: string | null;
}

interface Report {
  current_content: string | null;
  pending_content: string | null;
  pending_at: string | null;
  pending_sources: string | null;
  current_updated_at: string | null;
  current_revision_id?: string | null;
  /** Phase 5: draft → in_review → crew_lead_approved → mel_approved → final */
  review_status?: string | null;
  /** Optional ProseMirror JSON string (dual-write). */
  content_json?: string | null;
}

/** Phase 5 threaded comments */
interface ReportCommentRow {
  id: string;
  parent_id?: string | null;
  anchor_section_key?: string | null;
  author_label?: string | null;
  body: string;
  created_at: string;
  /** Parsed from anchor_json (range anchor for gutter). */
  anchor?: CommentAnchorJson | null;
}

interface ApprovalEventRow {
  id: string;
  event_type: string;
  from_status?: string | null;
  to_status?: string | null;
  actor_label?: string | null;
  detail?: Record<string, unknown> | null;
  created_at: string;
}

/** Structured edit proposal (collaborative editor Phase 1). */
interface PendingEdit {
  edit_id: string;
  section_id?: string | null;
  target_block_id: string;
  operation: string;
  reason?: string | null;
  evidence_refs?: string[];
  old_html?: string | null;
  new_html?: string | null;
  status: string;
  ord: number;
  suggestion_type?: string | null;
  source_job_id?: string | null;
  created_against_revision_id?: string | null;
}

interface ReportBlocksResponse {
  blocks: { block_id: string; section_id: string; html: string; order: number }[];
}

interface StatusResponse {
  running_mission_id: string | null;
}

interface CreateMissionResponse {
  id: string;
  name: string;
}

interface ApiErrorBody {
  error?: string;
  detail?: string | Array<{ msg?: string }>;
}

/** Phase 5: allowed PATCH targets from each status (final uses reopen to draft; mel_approved → final via Finalize). */
const REVIEW_TRANSITIONS_FROM: Record<string, string[]> = {
  draft: ["in_review"],
  in_review: ["draft", "crew_lead_approved"],
  crew_lead_approved: ["in_review", "mel_approved"],
  mel_approved: ["in_review"],
  final: ["draft"],
};

const REVIEW_STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  in_review: "In review",
  crew_lead_approved: "Crew lead approved",
  mel_approved: "MEL approved",
  final: "Final",
};

const KNOWN_REVIEW_STATUSES = new Set(Object.keys(REVIEW_TRANSITIONS_FROM));

function normalizeReviewStatus(raw: string | null | undefined): string {
  const s = (raw || "draft").trim().toLowerCase();
  return KNOWN_REVIEW_STATUSES.has(s) ? s : "draft";
}

function reviewStatusLabel(st: string): string {
  return REVIEW_STATUS_LABELS[st] || st;
}

/** API `current_updated_at` → `<time datetime>` + human-readable label. */
function reportLastUpdatedParts(
  iso: string | null | undefined
): { datetime: string; display: string } | null {
  if (!iso || !String(iso).trim()) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return {
    datetime: d.toISOString(),
    display: d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }),
  };
}

function parseApiErrorBody(j: ApiErrorBody, r: Response, fallback: string): string {
  if (typeof j.error === "string" && j.error.trim()) return j.error;
  const d = j.detail;
  if (typeof d === "string" && d.trim()) return d;
  if (Array.isArray(d)) {
    const m = d.map((x) => x.msg).filter(Boolean).join("; ");
    if (m) return m;
  }
  return fallback || r.statusText || "Request failed";
}

interface MissionMemberRow {
  user_id: string;
  role: string;
  affiliation?: string | null;
  display_name?: string | null;
  username?: string | null;
}

interface MissionActivityEvent extends Record<string, unknown> {
  kind?: string;
  created_at?: string;
  finished_at?: string;
}

interface SSEEvent {
  t: "buf" | "chunk" | "done" | "ping";
  text?: string;
}

// ---------- Line-based diff for per-section Undo/Keep ----------
const MAX_DIFF_CHARS = 200_000;

function computeDiffSegments(oldText: string, newText: string): { type: "equal" | "change"; oldContent: string; newContent: string }[] {
  const oldStr = oldText ?? "";
  const newStr = newText ?? "";
  if (oldStr.length > MAX_DIFF_CHARS || newStr.length > MAX_DIFF_CHARS) {
    return [{ type: "change", oldContent: oldStr, newContent: newStr }];
  }
  const oldLines = oldStr.split("\n");
  const newLines = newStr.split("\n");
  const segments: { type: "equal" | "change"; oldContent: string; newContent: string }[] = [];
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
      } else {
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

type DiffSegment = { type: "equal" | "change"; oldContent: string; newContent: string };

/** Build final text from segments; kept[i] = true means use newContent for the i-th change segment. */
function buildMergedFromSegments(
  segments: DiffSegment[],
  kept: boolean[]
): string {
  let changeIdx = 0;
  const parts: string[] = [];
  for (const s of segments) {
    if (s.type === "equal") parts.push(s.oldContent);
    else parts.push(kept[changeIdx++] ? s.newContent : s.oldContent);
  }
  return parts.join("");
}

// ---------- API helpers ----------

function get<T>(path: string): Promise<T> {
  return fetch(API + path, { credentials: "include" }).then(async (r) => {
    if (r.status === 401) {
      redirectUnauthenticated();
      throw new Error("Session expired; sign in again.");
    }
    if (!r.ok) throw new Error(r.statusText || "Request failed");
    return r.json() as Promise<T>;
  });
}

function post<T>(path: string, body?: object): Promise<T> {
  return fetch(API + path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  }).then(async (r) => {
    if (r.status === 401) {
      redirectUnauthenticated();
      throw new Error("Session expired; sign in again.");
    }
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as ApiErrorBody;
      throw new Error(parseApiErrorBody(j, r, r.statusText));
    }
    return r.json() as Promise<T>;
  });
}

/** Phase 3: POST inline-assist; surfaces FastAPI `detail` on error. */
function makeInlineAssistRunner(missionId: string, reportType: ReportType): InlineAssistRunner {
  return async (req) => {
    const r = await fetch(
      API + "/missions/" + missionId + "/reports/" + reportType + "/inline-assist",
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      }
    );
    const data = (await r.json().catch(() => ({}))) as {
      detail?: string | Array<{ msg?: string }>;
      suggestion?: string;
      evidence_sources?: string[];
      evidence_chunks?: Array<{ chunk_id: string; source: string }>;
      grounding_warnings?: string[];
    };
    if (!r.ok) {
      if (r.status === 401) {
        redirectUnauthenticated();
      }
      const d = data.detail;
      const msg =
        typeof d === "string"
          ? d
          : Array.isArray(d)
            ? d.map((x) => x.msg).filter(Boolean).join("; ")
            : "";
      throw new Error(msg || r.statusText || "Assist failed");
    }
    return {
      suggestion: data.suggestion ?? "",
      evidence_sources: data.evidence_sources,
      evidence_chunks: data.evidence_chunks,
      grounding_warnings: data.grounding_warnings,
    };
  };
}

function patch<T>(path: string, body: object): Promise<T> {
  return fetch(API + path, {
    method: "PATCH",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(async (r) => {
    if (r.status === 401) {
      redirectUnauthenticated();
      throw new Error("Session expired; sign in again.");
    }
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as ApiErrorBody;
      throw new Error(parseApiErrorBody(j, r, r.statusText));
    }
    return r.json() as Promise<T>;
  });
}

function httpDelete<T>(path: string): Promise<T> {
  return fetch(API + path, {
    method: "DELETE",
    credentials: "include",
  }).then(async (r) => {
    if (r.status === 401) {
      redirectUnauthenticated();
      throw new Error("Session expired; sign in again.");
    }
    if (!r.ok) {
      const j = (await r.json().catch(() => ({}))) as ApiErrorBody;
      throw new Error(parseApiErrorBody(j, r, r.statusText));
    }
    const ct = r.headers.get("content-type") || "";
    if (!ct.includes("application/json")) {
      return {} as T;
    }
    const text = await r.text();
    if (!text.trim()) return {} as T;
    return JSON.parse(text) as T;
  });
}

/** Durable pipeline job row (GET …/pipeline-jobs/:id). Used for polling, not SSE-only progress. */
type PipelineJobRow = {
  id: string;
  status: string;
  error_message?: string | null;
  failure_kind?: string | null;
};

/**
 * Poll until job is completed or failed. Returns a stop function.
 * Completion should drive UI refresh; SSE may still run for live preview only.
 */
function pollPipelineJobUntilTerminal(
  missionId: string,
  jobId: string,
  onTerminal: (job: PipelineJobRow) => void,
  intervalMs = 2000
): () => void {
  let stopped = false;
  const stop = (): void => {
    stopped = true;
  };
  const tick = (): void => {
    if (stopped) return;
    get<PipelineJobRow>(
      "/missions/" +
        missionId +
        "/pipeline-jobs/" +
        encodeURIComponent(jobId)
    )
      .then((j) => {
        if (stopped) return;
        if (j.status === "completed" || j.status === "failed") {
          onTerminal(j);
          return;
        }
        setTimeout(tick, intervalMs);
      })
      .catch(() => {
        if (!stopped) setTimeout(tick, intervalMs);
      });
  };
  tick();
  return stop;
}

function getHash(): string {
  return window.location.hash.slice(1) || "/";
}

function getHashParts(): string[] {
  return getHash().split("/").filter(Boolean);
}

function hashMatchesReport(missionId: string, reportType: string): boolean {
  const parts = getHashParts();
  return parts[0] === "mission" && parts[1] === missionId && parts[2] === reportType;
}

function navigate(hash: string): void {
  window.location.hash = hash;
}

/** Session invalid: send user to login hash (or no-op on login page to avoid wiping the form). */
function redirectUnauthenticated(): void {
  currentUser = null;
  if (getHashParts()[0] === "login") {
    return;
  }
  navigate("/login");
}

function escapeHtml(s: string | null | undefined): string {
  const str = s != null ? String(s) : "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function formatHubDate(iso: string | null | undefined): string {
  if (iso == null || String(iso).trim() === "") return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function closeHubMissionMenus(): void {
  document.querySelectorAll(".hub-card-menu-dropdown.is-open").forEach((el) => {
    el.classList.remove("is-open");
    el.setAttribute("hidden", "");
  });
  document.querySelectorAll(".hub-card-menu-btn").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
  });
}

function renderHubTopbarHtml(u: LoggedInUser): string {
  const who = escapeHtml((u.display_name || "").trim() || u.username);
  return `
      <header class="hub-topbar glass" role="banner">
        <div class="hub-topbar-inner">
          <button type="button" class="hub-topbar-left hub-brand-logo-btn" aria-label="RAG Pipeline — Mission Control">
            <img src="/logo.png" width="48" height="48" alt="" class="hub-topbar-logo" decoding="async" />
            <span class="hub-pipeline-title">RAG Pipeline</span>
          </button>
          <div class="hub-topbar-right">
            <span class="hub-user-name">${who}</span>
            <span class="hub-version" title="App version">v${APP_VERSION}</span>
            <details class="hub-user-menu">
              <summary class="hub-menu-trigger" aria-label="Account menu">Menu</summary>
              <div class="hub-menu-panel glass">
                ${u.is_admin ? `<a href="#/admin/debug" class="hub-menu-item hub-menu-item--link">Debug</a>` : ""}
                <a href="#/settings" class="hub-menu-item hub-menu-item--link">Settings</a>
                <button type="button" class="hub-menu-item hub-menu-item--btn" id="hub-btn-logout">Log out</button>
              </div>
            </details>
          </div>
        </div>
      </header>`;
}

function wireHubTopbarListeners(root: ParentNode): void {
  root.querySelector("#hub-btn-logout")?.addEventListener("click", () => {
    post("/auth/logout", {}).finally(() => {
      currentUser = null;
      stopOverviewPresence();
      navigate("/login");
      render();
    });
  });
  root.querySelector(".hub-brand-logo-btn")?.addEventListener("click", () => navigateFromBrandLogo());
}

const NEW_MISSION_LOGIN_RE = /^[a-z0-9._@+-]{1,128}$/;

function normalizedLoginFromFullNameParts(firstName: string, lastName: string): string | null {
  const ft = firstName.trim().split(/\s+/)[0] ?? "";
  const lt = lastName.trim().split(/\s+/)[0] ?? "";
  if (!ft || !lt) return null;
  return `${ft.toLowerCase()}.${lt.toLowerCase()}`;
}

function loginIdValidForApi(login: string): boolean {
  return NEW_MISSION_LOGIN_RE.test(login);
}

function canAccessMissionHub(): boolean {
  if (!currentUser) return false;
  return currentUser.is_admin || !!currentUser.has_mel_role;
}

/** Logo / RAG Pipeline title: MEL & admin → Mission Control; operators → current mission overview. */
function navigateFromBrandLogo(): void {
  if (!currentUser) return;
  if (canAccessMissionHub()) {
    navigate("/");
    render();
    return;
  }
  const parts = getHashParts();
  if (parts[0] === "mission" && parts[1]) {
    navigate("/mission/" + parts[1] + "/overview");
    render();
    return;
  }
  navigate("/");
  render();
}

function setAppHubMode(enabled: boolean): void {
  document.querySelector(".app")?.classList.toggle("app-hub", enabled);
}

function setMissionWorkspaceMode(enabled: boolean): void {
  document.querySelector(".app")?.classList.toggle("app-mission-workspace", enabled);
}

/** Which mission tab appears active (documents route highlights none). */
function missionWorkspaceActiveTabKey(sub: string | undefined): string {
  const s = (sub || "overview").toLowerCase();
  if (s === "documents") return "documents";
  if (s === "overview") return "overview";
  if ((REPORT_TYPES as readonly string[]).includes(s)) return s;
  return "overview";
}

function renderMissionWorkspaceShell(main: HTMLElement, missionId: string, hashSub: string | undefined): void {
  const u = currentUser!;
  const who = escapeHtml((u.display_name || "").trim() || u.username);
  const activeKey = missionWorkspaceActiveTabKey(hashSub);
  const tabCls = (navKey: string) =>
    "mission-tab" + (activeKey !== "documents" && activeKey === navKey ? " mission-tab--active" : "");
  const mid = encodeURIComponent(missionId);
  const hubLink = canAccessMissionHub()
    ? `<a href="#/" class="hub-menu-item hub-menu-item--link">Mission Control</a>`
    : "";
  const tabsHtml = [
    `<a href="#/mission/${mid}/overview" class="${tabCls("overview")}">Overview</a>`,
    ...REPORT_TYPES.map(
      (rt) =>
        `<a href="#/mission/${mid}/${rt}" class="${tabCls(rt)}">${escapeHtml(REPORT_LABELS[rt])}</a>`
    ),
  ].join("");
  main.innerHTML = `
    <div class="mission-workspace-page">
      <header class="mission-workspace-topbar glass" role="banner">
        <div class="mission-workspace-topbar-inner">
          <button type="button" class="mission-workspace-brand hub-brand-logo-btn" aria-label="RAG Pipeline — go to home for your role">
            <img src="/logo.png" width="48" height="48" alt="" class="hub-topbar-logo" decoding="async" />
            <span class="hub-pipeline-title">RAG Pipeline</span>
          </button>
          <nav class="mission-workspace-tabs" aria-label="Mission sections">${tabsHtml}</nav>
          <div class="mission-workspace-user hub-topbar-right">
            <span class="hub-user-name">${who}</span>
            <span class="hub-version" title="App version">v${APP_VERSION}</span>
            <details class="hub-user-menu">
              <summary class="hub-menu-trigger" aria-label="Account menu">Menu</summary>
              <div class="hub-menu-panel glass">
                ${hubLink}
                ${u.is_admin ? `<a href="#/admin/debug" class="hub-menu-item hub-menu-item--link">Debug</a>` : ""}
                <a href="#/settings" class="hub-menu-item hub-menu-item--link">Settings</a>
                <button type="button" class="hub-menu-item hub-menu-item--btn" id="mission-shell-logout">Log out</button>
              </div>
            </details>
          </div>
        </div>
      </header>
      <div class="mission-workspace-body-outer">
        <div id="mission-workspace-body" class="mission-workspace-body"></div>
      </div>
    </div>`;
  document.getElementById("mission-shell-logout")?.addEventListener("click", () => {
    post("/auth/logout", {}).finally(() => {
      currentUser = null;
      stopOverviewPresence();
      navigate("/login");
    });
  });
  document.querySelector(".hub-brand-logo-btn")?.addEventListener("click", () => navigateFromBrandLogo());
}

const MERGE_PLACEHOLDER = "[To be filled from mission data]";

/** Split template HTML into one block per h1–h6 or p element so merge preserves structure. */
function splitTemplateBlocks(html: string): string[] {
  const re = /<(h[1-6]|p)[^>]*>[\s\S]*?<\/\1>/gi;
  const str = (html || "").trim();
  return Array.from(str.matchAll(re), (m) => m[0]);
}

function mergeLlmIntoDraft(template: string, llmText: string): string {
  if (!(llmText || "").trim()) return template || "";
  const draftBlocks = splitTemplateBlocks(template || "");
  const llmBlocks = (llmText || "").replace(/\r\n/g, "\n").trim().split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  if (!draftBlocks.length) return llmText.trim();
  if (!llmBlocks.length) return template || "";

  function isFilled(block: string): boolean {
    if (!block || block.length < 3) return false;
    const stripped = block.trim();
    if (stripped.toLowerCase() === MERGE_PLACEHOLDER.toLowerCase()) return false;
    if (stripped.toLowerCase().includes(MERGE_PLACEHOLDER.toLowerCase()) && stripped.length < 100) return false;
    return true;
  }

  const merged: string[] = [];
  const n = Math.max(draftBlocks.length, llmBlocks.length);
  for (let i = 0; i < n; i++) {
    const draftBlock = i < draftBlocks.length ? draftBlocks[i] : "";
    const llmBlock = i < llmBlocks.length ? llmBlocks[i] : "";
    merged.push(isFilled(llmBlock) ? llmBlock : draftBlock || llmBlock);
  }
  return merged.join("\n\n");
}

function mergedToDisplayHtml(merged: string): string {
  const blocks = merged.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  return blocks
    .map((block) => {
      if (block.startsWith("<")) return block;
      return "<p>" + escapeHtml(block) + "</p>";
    })
    .join("\n");
}

// ---------- Views ----------

const expandedMissions = new Set<string>();

function renderMissionList(
  container: HTMLElement,
  currentId: string | null,
  currentSub: string | null
): void {
  if (!currentUser) {
    container.innerHTML = "";
    return;
  }
  get<Mission[]>("/missions")
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
          if ((e.target as HTMLElement).closest(".mission-toggle")) {
            if (expandedMissions.has(m.id)) expandedMissions.delete(m.id);
            else expandedMissions.add(m.id);
            renderMissionList(container, currentId, currentSub);
            return;
          }
          if ((e.target as HTMLElement).closest(".mission-context-btn")) return;
          navigate("/mission/" + m.id + "/overview");
          render();
        });
        row.querySelector(".mission-context-btn")!.addEventListener("click", (e) => {
          e.stopPropagation();
          const menu = document.getElementById("mission-context-menu");
          if (menu) menu.remove();
          const rect = (e.target as HTMLElement).getBoundingClientRect();
          const div = document.createElement("div");
          div.id = "mission-context-menu";
          div.className = "context-menu glass";
          div.innerHTML = `<button type="button" class="context-menu-item" data-action="overview">Overview</button><button type="button" class="context-menu-item" data-action="run-all">Run all reports</button>`;
          div.style.position = "fixed";
          div.style.left = rect.left + "px";
          div.style.top = rect.bottom + 4 + "px";
          div.style.zIndex = "1000";
          document.body.appendChild(div);
          div.querySelector("[data-action=overview]")!.addEventListener("click", () => { div.remove(); navigate("/mission/" + m.id + "/overview"); render(); });
          div.querySelector("[data-action=run-all]")!.addEventListener("click", () => { div.remove(); post("/run-pipeline", { mission_id: m.id }).then(() => render()).catch((err: Error) => alert(err.message)); });
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
            ${REPORT_TYPES.map(
              (rt) =>
                `<a href="#/mission/${encodeURIComponent(m.id)}/${rt}" class="mission-sub-item ${currentId === m.id && currentSub === rt ? "active" : ""}" data-nav="${rt}"><span class="mission-sub-icon" aria-hidden="true">📄</span>${REPORT_LABELS[rt]}</a>`
            ).join("")}
          `;
          sub.querySelectorAll(".mission-sub-item").forEach((a) => {
            a.addEventListener("click", (e) => {
              e.preventDefault();
              const nav = (e.currentTarget as HTMLElement).dataset.nav!;
              navigate(nav === "overview" ? "/mission/" + m.id + "/overview" : "/mission/" + m.id + "/" + nav);
              render();
            });
          });
          sub.querySelectorAll(".mission-sub-item").forEach((item) => {
            const nav = (item as HTMLElement).dataset.nav!;
            if (nav === "overview") return;
            const reportType = nav as ReportType;
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "mission-sub-context";
            btn.innerHTML = "⋯";
            btn.setAttribute("aria-label", "Options for " + REPORT_LABELS[reportType]);
            btn.addEventListener("click", (e) => {
              e.preventDefault();
              e.stopPropagation();
              const menu = document.getElementById("report-context-menu");
              if (menu) menu.remove();
              const rect = (e.target as HTMLElement).getBoundingClientRect();
              const div = document.createElement("div");
              div.id = "report-context-menu";
              div.className = "context-menu glass";
              div.innerHTML = `<button type="button" class="context-menu-item" data-action="update">Update</button><button type="button" class="context-menu-item" data-action="reset">Reset</button>`;
              div.style.position = "fixed";
              div.style.left = rect.left + "px";
              div.style.top = rect.bottom + 4 + "px";
              div.style.zIndex = "1000";
              document.body.appendChild(div);
              div.querySelector("[data-action=update]")!.addEventListener("click", () => {
                div.remove();
                document.removeEventListener("click", closeMenu);
                navigate("/mission/" + m.id + "/" + nav);
                render();
                setTimeout(() => document.querySelector<HTMLButtonElement>("#btn-update-report")?.click(), 300);
              });
              div.querySelector("[data-action=reset]")!.addEventListener("click", () => {
                div.remove();
                document.removeEventListener("click", closeMenu);
                const confirmed = window.confirm(
                  "Reset this document to the skeleton template?\n\n" +
                    "All draft text, pending AI suggestions, and incremental update tracking for this report will be cleared. " +
                    "Review status returns to Draft.\n\nThis cannot be undone."
                );
                if (confirmed) {
                  post("/missions/" + m.id + "/reports/" + reportType + "/reset")
                    .then(() => {
                      navigate("/mission/" + m.id + "/" + nav);
                      render();
                    })
                    .catch((err: Error) => alert(err?.message ?? "Failed to reset draft"));
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
      const strip = document.getElementById("auth-strip");
      if (strip && currentUser) {
        strip.innerHTML = `<span>${escapeHtml(currentUser.username)}</span> · <button type="button" class="btn btn-sm" id="btn-logout">Log out</button>${
          currentUser.is_admin
            ? ` · <a href="#/admin/debug" id="link-admin-debug">Debug</a>`
            : ""
        }`;
        document.getElementById("btn-logout")?.addEventListener("click", () => {
          post("/auth/logout", {}).finally(() => {
            currentUser = null;
            stopOverviewPresence();
            navigate("/login");
          });
        });
        document.getElementById("link-admin-debug")?.addEventListener("click", (e) => {
          e.preventDefault();
          navigate("/admin/debug");
          render();
        });
      }
    })
    .catch(() => {
      container.innerHTML = '<p class="error">Failed to load missions</p>';
    });
}

function renderLoginPage(main: HTMLElement): void {
  main.innerHTML = `
    <div class="login-page-card glass-strong">
      <header class="login-brand">
        <div class="login-logo">
          <img src="/logo.png" width="144" height="144" alt="CyberScribe" class="login-logo-img" decoding="async" />
        </div>
        <h1 class="login-brand-title">CyberScribe</h1>
        <p class="login-brand-tagline">Mission-scoped drafting, grounded AI, human-reviewed output</p>
      </header>

      <section class="login-signin" aria-labelledby="login-signin-heading">
        <h2 id="login-signin-heading" class="login-section-heading">Sign in</h2>
        <div class="login-field-group">
          <label class="login-label" for="login-username">Username</label>
          <input class="login-field" type="text" id="login-username" autocomplete="username" placeholder="Username" spellcheck="false" />
        </div>
        <div class="login-field-group">
          <label class="login-label" for="login-password">Password</label>
          <input class="login-field" type="password" id="login-password" autocomplete="current-password" placeholder="Password" />
        </div>
        <button type="button" class="login-btn-primary" id="btn-login">Sign in</button>
        <p class="error login-error" id="login-error" role="alert"></p>
      </section>

      <hr class="login-divider" />

      <footer class="login-footer">
        <p class="login-footer-prompt">First deployment?</p>
        <button type="button" class="login-btn-ghost" id="btn-toggle-bootstrap" aria-expanded="false" aria-controls="login-bootstrap-panel">
          Create initial admin
        </button>
        <div id="login-bootstrap-panel" class="login-bootstrap-panel" hidden>
          <p class="login-bootstrap-hint">Only when no users exist yet.</p>
          <div class="login-field-group">
            <label class="login-label" for="bootstrap-name">Display name</label>
            <input class="login-field" type="text" id="bootstrap-name" placeholder="Admin" autocomplete="off" />
          </div>
          <div class="login-field-group">
            <label class="login-label" for="bootstrap-username">Admin username</label>
            <input class="login-field" type="text" id="bootstrap-username" placeholder="Username" autocomplete="off" spellcheck="false" />
          </div>
          <div class="login-field-group">
            <label class="login-label" for="bootstrap-password">Admin password</label>
            <input class="login-field" type="password" id="bootstrap-password" autocomplete="new-password" />
          </div>
          <button type="button" class="login-btn-primary login-btn-primary--subtle" id="btn-bootstrap">Create admin account</button>
          <p class="error login-error" id="bootstrap-error" role="alert"></p>
        </div>
      </footer>
    </div>
  `;
  const err = (id: string, msg: string) => {
    const el = document.getElementById(id);
    if (el) el.textContent = msg;
  };
  document.getElementById("btn-login")?.addEventListener("click", async () => {
    err("login-error", "");
    const username = (document.getElementById("login-username") as HTMLInputElement).value.trim();
    const password = (document.getElementById("login-password") as HTMLInputElement).value;
    try {
      const r = await fetch(API + "/auth/login", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = (await r.json().catch(() => ({}))) as {
        user?: typeof currentUser;
        detail?: string;
      };
      if (!r.ok) {
        err("login-error", typeof data.detail === "string" ? data.detail : "Login failed");
        return;
      }
      if (data.user) currentUser = data.user as typeof currentUser;
      else {
        const me = await get<NonNullable<typeof currentUser>>("/auth/me");
        currentUser = me;
      }
      navigate("/");
    } catch (e) {
      err("login-error", e instanceof Error ? e.message : "Login failed");
    }
  });
  const bootstrapPanel = document.getElementById("login-bootstrap-panel");
  const toggleBootstrap = document.getElementById("btn-toggle-bootstrap");
  toggleBootstrap?.addEventListener("click", () => {
    if (!bootstrapPanel) return;
    const next = bootstrapPanel.hidden;
    bootstrapPanel.hidden = !next;
    toggleBootstrap.setAttribute("aria-expanded", next ? "true" : "false");
  });

  document.getElementById("btn-bootstrap")?.addEventListener("click", async () => {
    const bootMsg = document.getElementById("bootstrap-error");
    if (bootMsg) {
      bootMsg.classList.remove("login-bootstrap-success");
      bootMsg.classList.add("error");
    }
    err("bootstrap-error", "");
    const display_name = (document.getElementById("bootstrap-name") as HTMLInputElement).value.trim() || undefined;
    const username = (document.getElementById("bootstrap-username") as HTMLInputElement).value.trim();
    const password = (document.getElementById("bootstrap-password") as HTMLInputElement).value;
    try {
      const r = await fetch(API + "/auth/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, display_name }),
      });
      const data = (await r.json().catch(() => ({}))) as { detail?: string };
      if (!r.ok) {
        err("bootstrap-error", typeof data.detail === "string" ? data.detail : "Bootstrap failed");
        return;
      }
      const bootEl = document.getElementById("bootstrap-error");
      if (bootEl) {
        bootEl.textContent = "Account created. Sign in above.";
        bootEl.classList.remove("error");
        bootEl.classList.add("login-bootstrap-success");
      }
    } catch (e) {
      err("bootstrap-error", e instanceof Error ? e.message : "Bootstrap failed");
    }
  });
}

type NewMissionNamePill = { first: string; last: string; username: string };
type NewMissionOpPill = NewMissionNamePill & { affiliation: "Host" | "Network" };

function newMissionPillAvatarHtml(): string {
  return `<svg class="new-mission-pill-avatar-icon" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false"><circle cx="24" cy="24" r="24" fill="#c5c9d1"/><g transform="translate(0 3.25)"><circle cx="24" cy="17" r="7.5" fill="#4f545c"/><path d="M6 45.5c1.6-10.5 8-16.5 18-16.5s16.4 6 18 16.5" fill="#4f545c"/></g></svg>`;
}

function buildNewMissionUserPill(opts: {
  displayName: string;
  username: string;
  roleLabel: string;
  removeLabel: string;
  onRemove: () => void;
}): HTMLElement {
  const row = document.createElement("div");
  row.className = "new-mission-user-pill";
  const av = document.createElement("div");
  av.className = "new-mission-pill-avatar";
  av.innerHTML = newMissionPillAvatarHtml();
  const text = document.createElement("div");
  text.className = "new-mission-pill-text";
  const l1 = document.createElement("div");
  l1.className = "new-mission-pill-name";
  l1.textContent = opts.displayName;
  const lu = document.createElement("div");
  lu.className = "new-mission-pill-login";
  lu.textContent = opts.username;
  const lr = document.createElement("div");
  lr.className = "new-mission-pill-role";
  lr.textContent = opts.roleLabel;
  text.append(l1, lu, lr);
  const rm = document.createElement("button");
  rm.type = "button";
  rm.className = "btn new-mission-pill-remove";
  rm.textContent = "Remove";
  rm.setAttribute("aria-label", opts.removeLabel);
  rm.addEventListener("click", opts.onRemove);
  row.append(av, text, rm);
  return row;
}

function renderNewMissionForm(main: HTMLElement): void {
  const u = currentUser;
  if (!u) return;

  const teamState: {
    mel: NewMissionNamePill | null;
    cclHost: NewMissionNamePill[];
    cclNetwork: NewMissionNamePill[];
    operators: NewMissionOpPill[];
  } = {
    mel: null,
    cclHost: [],
    cclNetwork: [],
    operators: [],
  };

  main.innerHTML = `
    <div class="hub-page new-mission-hub-page">
      ${renderHubTopbarHtml(u)}
      <div class="hub-shell new-mission-hub-shell">
        <section class="new-mission-card glass">
          <header class="new-mission-card-head">
            <h2 class="new-mission-title">Create New Mission</h2>
            <p class="new-mission-sub caption">Set mission metadata, assign team, and configure automation settings.</p>
            <div class="new-mission-card-divider" aria-hidden="true"></div>
          </header>
          <form id="form-new-mission" class="new-mission-form">
            <details class="new-mission-section" open>
              <summary class="new-mission-section-summary">Mission details</summary>
              <div class="new-mission-section-body">
                <div class="new-mission-details-grid">
                  <section
                    class="new-mission-subsection"
                    aria-labelledby="nm-sub-mission-heading"
                  >
                    <h4 class="new-mission-subsection-heading" id="nm-sub-mission-heading">
                      Mission
                    </h4>
                    <div class="new-mission-subpanel">
                      <div class="form-group">
                        <label>Mission name</label>
                        <input type="text" name="name" placeholder="e.g. Alpha CPT 2025" required>
                      </div>
                      <div class="form-row new-mission-date-row">
                        <div class="form-group">
                          <label>Start date</label>
                          <input type="date" name="start_date">
                        </div>
                        <div class="form-group">
                          <label>End date</label>
                          <input type="date" name="end_date">
                        </div>
                      </div>
                    </div>
                  </section>
                  <section
                    class="new-mission-subsection"
                    aria-labelledby="nm-sub-cpt-heading"
                  >
                    <h4 class="new-mission-subsection-heading" id="nm-sub-cpt-heading">
                      CPT &amp; workflow
                    </h4>
                    <div class="new-mission-subpanel">
                      <div class="form-group">
                        <label>CPT</label>
                        <input type="text" name="cpt" placeholder="Which CPT this mission is from">
                      </div>
                      <div class="form-group">
                        <label>Workflow title</label>
                        <input type="text" name="workflow_title" placeholder="Optional; defaults to mission name">
                      </div>
                    </div>
                  </section>
                </div>
              </div>
            </details>

            <details class="new-mission-section" open>
              <summary class="new-mission-section-summary">Team &amp; roles</summary>
              <div class="new-mission-section-body">
                <div class="new-mission-team-grid">
                  <section
                    class="new-mission-team-subsection new-mission-team-subsection-leads"
                    aria-labelledby="nm-sub-leads-heading"
                  >
                    <h4 class="new-mission-team-subsection-heading" id="nm-sub-leads-heading">
                      Leadership
                    </h4>
                    <div class="new-mission-team-col new-mission-team-leads">
                      <div class="new-mission-team-subblock" data-slot="mel">
                        <h4 class="new-mission-team-subtitle">Mission Element Lead</h4>
                        <div class="new-mission-team-input-row">
                          <input type="text" id="nm-mel-first" class="new-mission-inline-input" placeholder="First name" aria-label="Mission Element Lead first name">
                          <input type="text" id="nm-mel-last" class="new-mission-inline-input" placeholder="Last name" aria-label="Mission Element Lead last name">
                          <button type="button" class="btn btn-primary" id="nm-mel-add">Add</button>
                        </div>
                        <div class="new-mission-pill-scroll" id="nm-mel-scroll"></div>
                      </div>
                      <div class="new-mission-team-subblock" data-slot="ccl-host">
                        <h4 class="new-mission-team-subtitle">Host Cyber Crew Lead</h4>
                        <div class="new-mission-team-input-row">
                          <input type="text" id="nm-cch-first" class="new-mission-inline-input" placeholder="First name" aria-label="Host CCL first name">
                          <input type="text" id="nm-cch-last" class="new-mission-inline-input" placeholder="Last name" aria-label="Host CCL last name">
                          <button type="button" class="btn btn-primary" id="nm-cch-add">Add</button>
                        </div>
                        <div class="new-mission-pill-scroll" id="nm-cch-scroll"></div>
                      </div>
                      <div class="new-mission-team-subblock" data-slot="ccl-network">
                        <h4 class="new-mission-team-subtitle">Network Cyber Crew Lead</h4>
                        <div class="new-mission-team-input-row">
                          <input type="text" id="nm-ccn-first" class="new-mission-inline-input" placeholder="First name" aria-label="Network CCL first name">
                          <input type="text" id="nm-ccn-last" class="new-mission-inline-input" placeholder="Last name" aria-label="Network CCL last name">
                          <button type="button" class="btn btn-primary" id="nm-ccn-add">Add</button>
                        </div>
                        <div class="new-mission-pill-scroll" id="nm-ccn-scroll"></div>
                      </div>
                    </div>
                  </section>
                  <section
                    class="new-mission-team-subsection new-mission-team-subsection-operators"
                    aria-labelledby="nm-sub-ops-heading"
                  >
                    <h4 class="new-mission-team-subsection-heading" id="nm-sub-ops-heading">
                      Operators
                    </h4>
                    <div class="new-mission-team-col new-mission-team-operators">
                      <div class="new-mission-team-input-row">
                        <input type="text" id="nm-op-first" class="new-mission-inline-input" placeholder="First name" aria-label="Operator first name">
                        <input type="text" id="nm-op-last" class="new-mission-inline-input" placeholder="Last name" aria-label="Operator last name">
                        <select id="nm-op-type" class="new-mission-inline-select" aria-label="Operator type">
                          <option value="Host">Host</option>
                          <option value="Network">Network</option>
                        </select>
                        <button type="button" class="btn btn-primary" id="nm-op-add">Add</button>
                      </div>
                      <div class="new-mission-pill-scroll" id="nm-op-scroll"></div>
                    </div>
                  </section>
                </div>
              </div>
            </details>

            <details class="new-mission-section" open>
              <summary class="new-mission-section-summary">Data sources</summary>
              <div class="new-mission-section-body">
                <div class="new-mission-data-sources">
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
                </div>
              </div>
            </details>

            <div class="new-mission-footer-actions">
              <button type="button" class="btn" id="btn-cancel-new">Cancel</button>
              <button type="submit" class="btn btn-primary">Create mission</button>
            </div>
            <p class="error" id="new-mission-error"></p>
          </form>
        </section>
      </div>
    </div>`;

  wireHubTopbarListeners(main);

  const errEl = document.getElementById("new-mission-error")!;
  const melScroll = document.getElementById("nm-mel-scroll")!;
  const melAdd = document.getElementById("nm-mel-add") as HTMLButtonElement;
  const melFirst = document.getElementById("nm-mel-first") as HTMLInputElement;
  const melLast = document.getElementById("nm-mel-last") as HTMLInputElement;

  const cchScroll = document.getElementById("nm-cch-scroll")!;
  const cchAdd = document.getElementById("nm-cch-add")!;
  const cchFirst = document.getElementById("nm-cch-first") as HTMLInputElement;
  const cchLast = document.getElementById("nm-cch-last") as HTMLInputElement;

  const ccnScroll = document.getElementById("nm-ccn-scroll")!;
  const ccnAdd = document.getElementById("nm-ccn-add")!;
  const ccnFirst = document.getElementById("nm-ccn-first") as HTMLInputElement;
  const ccnLast = document.getElementById("nm-ccn-last") as HTMLInputElement;

  const opScroll = document.getElementById("nm-op-scroll")!;
  const opAdd = document.getElementById("nm-op-add")!;
  const opFirst = document.getElementById("nm-op-first") as HTMLInputElement;
  const opLast = document.getElementById("nm-op-last") as HTMLInputElement;
  const opType = document.getElementById("nm-op-type") as HTMLSelectElement;

  function syncMelAddState(): void {
    melAdd.disabled = teamState.mel !== null;
  }

  function clearTeamErr(): void {
    errEl.textContent = "";
  }

  function tryReadNamePill(
    firstEl: HTMLInputElement,
    lastEl: HTMLInputElement,
    scrollEl: HTMLElement,
    list: NewMissionNamePill[] | null,
    roleLabel: string,
    duplicateCheck: Set<string>
  ): boolean {
    clearTeamErr();
    const first = firstEl.value.trim();
    const last = lastEl.value.trim();
    if (!first || !last) {
      errEl.textContent = "Enter first and last name.";
      return false;
    }
    const username = normalizedLoginFromFullNameParts(first, last);
    if (!username || !loginIdValidForApi(username)) {
      errEl.textContent = "Username must be firstname.lastname using letters, numbers, and . _ - + only (1–128 chars).";
      return false;
    }
    if (duplicateCheck.has(username)) {
      errEl.textContent = "That user is already listed in this section.";
      return false;
    }
    const display = `${first} ${last}`.trim();
    const entry: NewMissionNamePill = { first, last, username };
    if (list === null) {
      teamState.mel = entry;
      melScroll.innerHTML = "";
      const pill = buildNewMissionUserPill({
        displayName: display,
        username,
        roleLabel,
        removeLabel: `Remove ${display}`,
        onRemove: () => {
          teamState.mel = null;
          melScroll.innerHTML = "";
          syncMelAddState();
        },
      });
      melScroll.appendChild(pill);
      firstEl.value = "";
      lastEl.value = "";
      syncMelAddState();
      return true;
    }
    duplicateCheck.add(username);
    list.push(entry);
    const pill = buildNewMissionUserPill({
      displayName: display,
      username,
      roleLabel,
      removeLabel: `Remove ${display}`,
      onRemove: () => {
        const i = list.findIndex((p) => p.username === username);
        if (i >= 0) list.splice(i, 1);
        duplicateCheck.delete(username);
        pill.remove();
      },
    });
    scrollEl.appendChild(pill);
    firstEl.value = "";
    lastEl.value = "";
    return true;
  }

  const cchNames = new Set<string>();
  const ccnNames = new Set<string>();
  const opNames = new Set<string>();

  melAdd.addEventListener("click", () => {
    if (teamState.mel) return;
    tryReadNamePill(melFirst, melLast, melScroll, null, "Mission Element Lead", new Set());
  });

  cchAdd.addEventListener("click", () => {
    tryReadNamePill(cchFirst, cchLast, cchScroll, teamState.cclHost, "Host Cyber Crew Lead", cchNames);
  });

  ccnAdd.addEventListener("click", () => {
    tryReadNamePill(ccnFirst, ccnLast, ccnScroll, teamState.cclNetwork, "Network Cyber Crew Lead", ccnNames);
  });

  opAdd.addEventListener("click", () => {
    clearTeamErr();
    const first = opFirst.value.trim();
    const last = opLast.value.trim();
    const aff = opType.value as "Host" | "Network";
    if (!first || !last) {
      errEl.textContent = "Enter first and last name.";
      return;
    }
    const username = normalizedLoginFromFullNameParts(first, last);
    if (!username || !loginIdValidForApi(username)) {
      errEl.textContent =
        "Username must be firstname.lastname using letters, numbers, and . _ - + only (1–128 chars).";
      return;
    }
    if (opNames.has(username)) {
      errEl.textContent = "That user is already listed as an operator.";
      return;
    }
    const display = `${first} ${last}`.trim();
    const roleLabel = aff === "Host" ? "Host Operator" : "Network Operator";
    const entry: NewMissionOpPill = { first, last, username, affiliation: aff };
    teamState.operators.push(entry);
    opNames.add(username);
    const pill = buildNewMissionUserPill({
      displayName: display,
      username,
      roleLabel,
      removeLabel: `Remove ${display}`,
      onRemove: () => {
        const i = teamState.operators.findIndex((p) => p.username === username);
        if (i >= 0) teamState.operators.splice(i, 1);
        opNames.delete(username);
        pill.remove();
      },
    });
    opScroll.appendChild(pill);
    opFirst.value = "";
    opLast.value = "";
  });

  const formEl = document.getElementById("form-new-mission") as HTMLFormElement;
  formEl.addEventListener("submit", (e) => {
    e.preventDefault();
    errEl.textContent = "";
    const form = e.target as HTMLFormElement;
    const name = (form.elements.namedItem("name") as HTMLInputElement)?.value?.trim() ?? "";
    const source_path = (form.elements.namedItem("source_path") as HTMLInputElement)?.value?.trim() ?? "";
    const output_path = (form.elements.namedItem("output_path") as HTMLInputElement)?.value?.trim() ?? "";
    if (!name || !source_path || !output_path) {
      errEl.textContent = "Fill name, input folder, and output folder.";
      return;
    }
    const mel = teamState.mel ? `${teamState.mel.first} ${teamState.mel.last}`.trim() : undefined;
    const ccl_host = teamState.cclHost.length ? teamState.cclHost.map((p) => p.username) : undefined;
    const ccl_network = teamState.cclNetwork.length ? teamState.cclNetwork.map((p) => p.username) : undefined;
    const operators = teamState.operators.length
      ? teamState.operators.map((o) => ({
          name: `${o.first} ${o.last}`.trim(),
          role: o.affiliation,
          username: o.username,
        }))
      : undefined;
    const body = {
      name,
      source_path,
      output_path,
      cpt: (form.elements.namedItem("cpt") as HTMLInputElement)?.value?.trim() || undefined,
      workflow_title: (form.elements.namedItem("workflow_title") as HTMLInputElement)?.value?.trim() || undefined,
      start_date: (form.elements.namedItem("start_date") as HTMLInputElement)?.value || undefined,
      end_date: (form.elements.namedItem("end_date") as HTMLInputElement)?.value || undefined,
      operators,
      mel: mel || undefined,
      mel_username: teamState.mel?.username || undefined,
      ccl_host,
      ccl_network,
      auto_update_frequency: (form.elements.namedItem("auto_update_frequency") as HTMLSelectElement)?.value || "off",
    };
    post<CreateMissionResponse>("/missions", body)
      .then((data) => {
        expandedMissions.add(data.id);
        navigate("/mission/" + data.id + "/overview");
        render();
      })
      .catch((err: Error) => {
        errEl.textContent = err.message || "Failed to create mission";
      });
  });

  document.getElementById("btn-cancel-new")!.addEventListener("click", () => {
    navigate("/");
    render();
  });

  syncMelAddState();
}

function memberDisplayRole(role: string, affiliation: string | null | undefined): string {
  const r = (role || "").toLowerCase();
  const a = (affiliation || "").toLowerCase();
  if (r === "mel") return "Mission Element Lead";
  if (r === "viewer") return "Viewer";
  if (r === "operator") {
    if (a === "network") return "Network Operator";
    if (a === "host") return "Host Operator";
    return "Operator";
  }
  if (r === "crew_lead") {
    if (a === "network") return "Network Cyber Crew Lead";
    return "Host Cyber Crew Lead";
  }
  return role;
}

function missionLengthDescription(m: Mission): string {
  const a = m.start_date ? new Date(String(m.start_date)) : null;
  const b = m.end_date ? new Date(String(m.end_date)) : null;
  if (a && !Number.isNaN(a.getTime()) && b && !Number.isNaN(b.getTime())) {
    const days = Math.max(0, Math.round((b.getTime() - a.getTime()) / 86400000));
    return `${formatHubDate(m.start_date)} — ${formatHubDate(m.end_date)} (${days} day${days === 1 ? "" : "s"})`;
  }
  if (m.start_date || m.end_date) return `${formatHubDate(m.start_date)} — ${formatHubDate(m.end_date)}`;
  return "—";
}

function composeMissionSummaryHtml(m: Mission): string {
  const lines: string[] = [];
  if (m.cpt) lines.push(`CPT / unit reference: ${escapeHtml(m.cpt)}`);
  lines.push(
    `Operational status: ${escapeHtml(m.status)} · Lifecycle: ${escapeHtml((m.lifecycle_status || "active").toString())}`
  );
  lines.push(`Input folder: ${escapeHtml(m.source_path)}`);
  lines.push(`Output folder: ${escapeHtml(m.output_path)}`);
  lines.push(
    `Ingest mode: ${escapeHtml(m.ingest_mode || "auto")} · Scheduled auto-update: ${escapeHtml(m.auto_update_frequency || "off")}`
  );
  if (m.last_ingest_at) lines.push(`Last ingest: ${escapeHtml(m.last_ingest_at)}`);
  if (m.last_generated_at) lines.push(`Last generated: ${escapeHtml(m.last_generated_at)}`);
  if (m.mel) lines.push(`MEL (from mission form): ${escapeHtml(m.mel)}`);
  return lines.map((l) => `<p class="overview-summary-line">${l}</p>`).join("");
}

/** Placeholder user avatar (circle + silhouette) for overview team list. */
function overviewTeamMemberAvatarSvg(): string {
  return `<svg class="overview-team-avatar-icon" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false"><circle cx="24" cy="24" r="24" fill="#c5c9d1"/><g transform="translate(0 3.25)"><circle cx="24" cy="17" r="7.5" fill="#4f545c"/><path d="M6 45.5c1.6-10.5 8-16.5 18-16.5s16.4 6 18 16.5" fill="#4f545c"/></g></svg>`;
}

function formatActivityEventUi(ev: MissionActivityEvent): string {
  const kind = String(ev.kind || "");
  const ts = String(ev.finished_at || ev.created_at || "").slice(0, 19);
  if (kind === "pipeline_job") {
    const err = ev.error_message ? " — " + String(ev.error_message) : "";
    return `${ts} · Pipeline ${String(ev.status || "")} ${String(ev.report_types || "")}${err}`;
  }
  if (kind === "approval") {
    return `${ts} · ${String(ev.report_type || "")}: ${String(ev.event_type || "")} → ${String(ev.to_status || "")}`;
  }
  if (kind === "comment") {
    const body = String(ev.body || "").replace(/\s+/g, " ").slice(0, 72);
    return `${ts} · Comment (${String(ev.report_type || "")}) ${String(ev.author_label || "")}: ${body}`;
  }
  if (kind === "chat") {
    return `${ts} · Chat: ${String(ev.content || "").replace(/\s+/g, " ").slice(0, 72)}`;
  }
  return `${ts} · ${kind}`;
}

function renderMissionOverview(missionId: string, main: HTMLElement): void {
  stopOverviewPresence();
  teardownOverviewTeamRailSync();
  const overviewCommitEpoch = missionOverviewEpoch;
  get<Mission>("/missions/" + missionId)
    .then((mission) => {
      if (overviewCommitEpoch !== missionOverviewEpoch) {
        return;
      }
      const title = escapeHtml(mission.workflow_title || mission.name);
      const len = escapeHtml(missionLengthDescription(mission));
      main.innerHTML = `
        <div class="overview-dashboard">
          <div class="overview-dashboard-main glass">
            <header class="overview-mission-head">
              <div class="overview-mission-title-row">
                <h1 class="overview-mission-title">${title}</h1>
                <span class="overview-mission-id caption">Mission ID: ${escapeHtml(mission.id)}</span>
              </div>
              <p class="overview-mission-length"><strong>Mission length</strong> · ${len}</p>
            </header>
            <section class="overview-section overview-section-mission-summary" aria-labelledby="ov-summary-heading">
              <h2 id="ov-summary-heading" class="overview-section-title">Mission summary</h2>
              <div class="overview-summary-split">
                <div class="overview-summary-main">
                  <div class="overview-summary-body caption">${composeMissionSummaryHtml(mission)}</div>
                </div>
                <div class="overview-summary-rail">
                  <div class="overview-summary-aside-block glass">
                    <section class="overview-ops overview-ops--in-summary" aria-labelledby="ov-ops-heading">
                      <h3 id="ov-ops-heading" class="overview-summary-aside-title">Mission operations</h3>
                      <div class="overview-ops-body caption">
                        <label class="overview-ingest-label">Ingest mode (MEL)
                          <select id="mission-ingest-mode">
                            <option value="auto" ${(mission.ingest_mode || "auto") === "auto" ? "selected" : ""}>Auto</option>
                            <option value="manual" ${mission.ingest_mode === "manual" ? "selected" : ""}>Manual</option>
                          </select>
                        </label>
                        <p class="caption">Manual mode is stored for upcoming confirm-ingest UX; the pipeline still rebuilds the index on run until that ships.</p>
                        <p id="overview-presence-line">Presence: …</p>
                        <div class="overview-ops-actions">
                          <button type="button" class="btn btn-sm btn-primary" id="btn-overview-build-index">Confirm index build</button>
                          <button type="button" class="btn btn-sm" id="btn-overview-debug">Mission debug</button>
                          <button type="button" class="btn btn-sm" id="btn-overview-zip" style="display: none;">Download output zip</button>
                        </div>
                        <div id="mel-only-tools" style="display: none;">
                          <div class="overview-mel-lifecycle-row">
                            <span class="overview-mel-lifecycle-title"><strong>MEL</strong> — lifecycle</span>
                            <div class="overview-mel-lifecycle-controls">
                              <label class="overview-mel-lifecycle-field">Lifecycle
                                <select id="mission-lifecycle-select"><option value="active">Active</option><option value="archived">Archived (read-only)</option></select>
                              </label>
                              <button type="button" class="btn btn-sm" id="btn-lifecycle-save">Save lifecycle</button>
                            </div>
                          </div>
                          <div class="overview-aux-block">
                            <strong>Auxiliary file</strong> (merged into RAG for allowed reports)
                            <ul id="auxiliary-list-ui"></ul>
                            <input type="text" id="aux-label-inp" placeholder="Label" class="overview-aux-input" />
                            <input type="text" id="aux-path-inp" placeholder="Full file path" class="overview-aux-input overview-aux-input--wide" />
                            <button type="button" class="btn btn-sm" id="btn-aux-add">Add</button>
                          </div>
                        </div>
                      </div>
                    </section>
                  </div>
                </div>
              </div>
            </section>
            <section class="overview-section" aria-labelledby="ov-reports-heading">
              <h2 id="ov-reports-heading" class="overview-section-title">Report status</h2>
              <div class="overview-report-grid" id="overview-report-cards"></div>
            </section>
            <section class="overview-section" aria-labelledby="ov-evidence-heading">
              <h2 id="ov-evidence-heading" class="overview-section-title">Evidence</h2>
              <div id="overview-evidence-list" class="overview-evidence-list"></div>
            </section>
          </div>
          <aside class="overview-dashboard-rail">
            <section class="overview-rail-card overview-rail-card--team-quick glass">
              <div class="overview-rail-pane">
                <h2 class="overview-section-title">Team</h2>
                <ul id="overview-team-list" class="overview-team-list"></ul>
              </div>
              <div class="overview-rail-divider" role="separator" aria-hidden="true"></div>
              <div class="overview-rail-pane">
                <h2 class="overview-section-title">Quick actions</h2>
                <div class="overview-qa-buttons">
                  <div class="overview-qa-report-wrap">
                    <button
                      type="button"
                      class="btn btn-sm"
                      id="overview-qa-open-report"
                      aria-expanded="false"
                      aria-controls="overview-qa-report-list"
                      aria-haspopup="listbox"
                    >
                      Update report
                    </button>
                    <ul id="overview-qa-report-list" class="overview-qa-report-list" role="listbox" aria-labelledby="overview-qa-open-report" hidden>
                      ${REPORT_TYPES.map(
                        (rt) =>
                          `<li role="none">
                            <button type="button" role="option" class="overview-qa-report-pick btn btn-sm" data-report-type="${escapeHtml(rt)}">${escapeHtml(REPORT_LABELS[rt])}</button>
                          </li>`
                      ).join("")}
                    </ul>
                  </div>
                  <div class="overview-qa-upload-wrap">
                    <button
                      type="button"
                      class="btn btn-sm"
                      id="overview-qa-upload-trigger"
                      aria-expanded="false"
                      aria-controls="overview-qa-upload-popover"
                    >
                      Upload files
                    </button>
                    <div
                      id="overview-qa-upload-popover"
                      class="overview-qa-upload-popover"
                      hidden
                      role="region"
                      aria-label="Upload files"
                      aria-live="polite"
                    >
                      <p class="overview-qa-upload-popover-text">Coming soon — server upload is not enabled yet.</p>
                    </div>
                  </div>
                  <button type="button" class="btn btn-sm" id="overview-qa-view-source">View source files</button>
                  <button type="button" class="btn btn-sm" id="overview-qa-copy-path">Copy input path</button>
                </div>
              </div>
            </section>
            <section class="overview-rail-card glass">
              <h2 class="overview-section-title">Recent activity</h2>
              <ul id="overview-activity-list" class="overview-activity-list caption"></ul>
            </section>
          </aside>
        </div>`;

      Promise.all(
        REPORT_TYPES.map((rt) =>
          get<Report>("/missions/" + missionId + "/reports/" + rt).catch(() => null)
        )
      ).then((reports) => {
        const host = document.getElementById("overview-report-cards");
        if (!host) return;
        host.innerHTML = "";
        REPORT_TYPES.forEach((rt, i) => {
          const rep = reports[i];
          const st = rep ? normalizeReviewStatus(rep.review_status) : "draft";
          const lu = rep ? reportLastUpdatedParts(rep.current_updated_at) : null;
          const timeHtml = lu
            ? `<time class="overview-report-card-time" datetime="${escapeHtml(lu.datetime)}">${escapeHtml(lu.display)}</time>`
            : `<span class="overview-report-card-time-empty">Not yet saved</span>`;
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "overview-report-card glass";
          btn.innerHTML = `<div class="overview-report-card-head"><span class="overview-report-card-title">${escapeHtml(REPORT_LABELS[rt])}</span><span class="overview-report-card-status-line"><span class="overview-report-card-status-prefix">Status:</span> <span class="overview-report-card-status">${escapeHtml(reviewStatusLabel(st))}</span></span></div><div class="overview-report-card-updated"><span class="overview-report-card-updated-label">Last updated:</span> ${timeHtml}</div>`;
          btn.addEventListener("click", () => {
            navigate("/mission/" + missionId + "/" + rt);
            render();
          });
          host.appendChild(btn);
        });
        scheduleOverviewTeamRailSync();
      });

      get<{ files?: { path: string; doc_type: string; in_manifest: boolean }[] }>(
        "/missions/" + missionId + "/documents"
      )
        .then((d) => {
          const host = document.getElementById("overview-evidence-list");
          if (!host) return;
          host.innerHTML = "";
          const files = d.files || [];
          if (!files.length) {
            host.innerHTML = '<p class="caption">No supported files found in the input folder.</p>';
            scheduleOverviewTeamRailSync();
            return;
          }
          for (const f of files.slice(0, 300)) {
            const row = document.createElement("div");
            row.className = "overview-evidence-item glass";
            const manifestNote = f.in_manifest ? "" : " · not in manifest";
            row.innerHTML = `<span class="overview-evidence-name">${escapeHtml(f.path)}</span><span class="caption">${escapeHtml(String(f.doc_type || ""))}${manifestNote}</span>`;
            host.appendChild(row);
          }
          scheduleOverviewTeamRailSync();
        })
        .catch(() => {
          const host = document.getElementById("overview-evidence-list");
          if (host) host.innerHTML = '<p class="error">Could not load evidence list.</p>';
        });

      get<{ events: MissionActivityEvent[] }>("/missions/" + missionId + "/activity?limit=50")
        .then((data) => {
          const ul = document.getElementById("overview-activity-list");
          if (!ul) return;
          ul.innerHTML = "";
          const evs = data.events || [];
          if (!evs.length) {
            ul.innerHTML = '<li class="overview-activity-empty">No recent activity.</li>';
            return;
          }
          for (const ev of evs.slice(0, 40)) {
            const li = document.createElement("li");
            li.className = "overview-activity-item";
            li.textContent = formatActivityEventUi(ev);
            ul.appendChild(li);
          }
        })
        .catch(() => {
          const ul = document.getElementById("overview-activity-list");
          if (ul) ul.innerHTML = '<li>Could not load activity.</li>';
        });

      const ingestSel = document.getElementById("mission-ingest-mode") as HTMLSelectElement | null;
      const lcSel = document.getElementById("mission-lifecycle-select") as HTMLSelectElement | null;
      if (lcSel) {
        lcSel.value =
          (mission.lifecycle_status || "active").toLowerCase() === "archived" ? "archived" : "active";
      }
      get<{ members: MissionMemberRow[] }>("/missions/" + missionId + "/members")
        .then((mem) => {
          const isMel = mem.members?.some(
            (m) => m.user_id === currentUser?.id && m.role === "mel"
          );
          if (ingestSel) ingestSel.disabled = !isMel;
          const melBox = document.getElementById("mel-only-tools");
          if (melBox) melBox.style.display = isMel ? "block" : "none";
          const zipBtn = document.getElementById("btn-overview-zip");
          if (zipBtn) zipBtn.style.display = isMel ? "inline-block" : "none";
          const teamUl = document.getElementById("overview-team-list");
          if (teamUl) {
            teamUl.innerHTML = "";
            const order: Record<string, number> = { mel: 0, crew_lead: 1, operator: 2, viewer: 3 };
            const sorted = [...(mem.members || [])].sort(
              (a, b) =>
                (order[(a.role || "").toLowerCase()] ?? 9) - (order[(b.role || "").toLowerCase()] ?? 9) ||
                (a.display_name || a.username || "").localeCompare(b.display_name || b.username || "")
            );
            if (!sorted.length) {
              teamUl.innerHTML = '<li class="caption">No members linked yet.</li>';
            } else {
              for (const row of sorted) {
                const li = document.createElement("li");
                li.className = "overview-team-item glass";
                const displayName = escapeHtml((row.display_name || "").trim() || "?");
                const loginLine = escapeHtml((row.username || "").trim() || "—");
                const rl = memberDisplayRole(row.role, row.affiliation);
                li.innerHTML = `<span class="overview-team-avatar">${overviewTeamMemberAvatarSvg()}</span><div class="overview-team-body"><span class="overview-team-name">${displayName}</span><span class="overview-team-login">${loginLine}</span><span class="overview-team-role">${escapeHtml(rl)}</span></div>`;
                teamUl.appendChild(li);
              }
            }
          }
          scheduleOverviewTeamRailSync();
        })
        .catch(() => {});
      function tickPresence(): void {
        if (!document.getElementById("overview-presence-line")) return;
        post("/missions/" + missionId + "/presence", {})
          .then(() =>
            get<{ presence: { display_name?: string; username?: string }[] }>(
              "/missions/" + missionId + "/presence"
            )
          )
          .then((p) => {
            const el = document.getElementById("overview-presence-line");
            if (!el) return;
            const names = (p.presence || []).map((x) => x.display_name || x.username || "?");
            el.textContent = names.length ? "Active recently: " + names.join(", ") : "No other active editors (last 90s).";
          })
          .catch(() => {});
      }
      tickPresence();
      overviewPresenceTimer = setInterval(tickPresence, 25000);

      setupOverviewTeamRailSync();

      document.getElementById("btn-overview-build-index")?.addEventListener("click", () => {
        post("/missions/" + missionId + "/build-index", {})
          .then(() => alert("Index build completed."))
          .catch((e: Error) => alert(e.message || "Index build failed"));
      });
      document.getElementById("btn-overview-debug")?.addEventListener("click", () => {
        get<Record<string, unknown>>("/missions/" + missionId + "/debug")
          .then((d) => alert(JSON.stringify(d, null, 2)))
          .catch((e: Error) => alert(e.message || "Debug failed"));
      });
      document.getElementById("btn-overview-zip")?.addEventListener("click", () => {
        fetch(API + "/missions/" + missionId + "/export/bundle", { credentials: "include" })
          .then((r) => {
            if (!r.ok) throw new Error(r.statusText);
            return r.blob();
          })
          .then((blob) => {
            const u = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = u;
            a.download = missionId + "_bundle.zip";
            a.click();
            URL.revokeObjectURL(u);
          })
          .catch((e: Error) => alert(e.message || "Export failed"));
      });
      const reportListEl = document.getElementById("overview-qa-report-list");
      const reportToggleBtn = document.getElementById("overview-qa-open-report");
      const reportWrapEl = document.querySelector(".overview-qa-report-wrap");
      const uploadPopoverEl = document.getElementById("overview-qa-upload-popover");
      const uploadToggleBtn = document.getElementById("overview-qa-upload-trigger");
      const uploadWrapEl = document.querySelector(".overview-qa-upload-wrap");

      function setReportListOpen(open: boolean): void {
        if (!reportListEl || !reportToggleBtn) return;
        if (open) {
          reportListEl.removeAttribute("hidden");
          reportToggleBtn.setAttribute("aria-expanded", "true");
        } else {
          reportListEl.setAttribute("hidden", "");
          reportToggleBtn.setAttribute("aria-expanded", "false");
        }
      }

      function setUploadPopoverOpen(open: boolean): void {
        if (!uploadPopoverEl || !uploadToggleBtn) return;
        if (open) {
          uploadPopoverEl.removeAttribute("hidden");
          uploadToggleBtn.setAttribute("aria-expanded", "true");
        } else {
          uploadPopoverEl.setAttribute("hidden", "");
          uploadToggleBtn.setAttribute("aria-expanded", "false");
        }
      }

      let reportListOutsideClose: ((ev: MouseEvent) => void) | null = null;
      let uploadPopoverOutsideClose: ((ev: MouseEvent) => void) | null = null;

      function closeReportListCompletely(): void {
        if (reportListOutsideClose) {
          document.removeEventListener("click", reportListOutsideClose);
          reportListOutsideClose = null;
        }
        setReportListOpen(false);
      }

      function closeUploadPopoverCompletely(): void {
        if (uploadPopoverOutsideClose) {
          document.removeEventListener("click", uploadPopoverOutsideClose);
          uploadPopoverOutsideClose = null;
        }
        setUploadPopoverOpen(false);
      }

      reportToggleBtn?.addEventListener("click", (e) => {
        e.stopPropagation();
        closeUploadPopoverCompletely();
        const isClosed = reportListEl?.hasAttribute("hidden") ?? true;
        if (reportListOutsideClose) {
          document.removeEventListener("click", reportListOutsideClose);
          reportListOutsideClose = null;
        }
        if (isClosed) {
          setReportListOpen(true);
          const onDocClick = (ev: MouseEvent) => {
            if (!reportWrapEl?.contains(ev.target as Node)) {
              closeReportListCompletely();
            }
          };
          reportListOutsideClose = onDocClick;
          window.setTimeout(() => document.addEventListener("click", onDocClick), 0);
        } else {
          setReportListOpen(false);
        }
      });

      reportListEl?.querySelectorAll<HTMLButtonElement>(".overview-qa-report-pick").forEach((pickBtn) => {
        pickBtn.addEventListener("click", () => {
          closeReportListCompletely();
          closeUploadPopoverCompletely();
          const raw = pickBtn.getAttribute("data-report-type") || "rmp";
          const rt = ((REPORT_TYPES as readonly string[]).includes(raw) ? raw : "rmp") as ReportType;
          navigate("/mission/" + missionId + "/" + rt);
          render();
        });
      });

      uploadToggleBtn?.addEventListener("click", (e) => {
        e.stopPropagation();
        closeReportListCompletely();
        const isClosed = uploadPopoverEl?.hasAttribute("hidden") ?? true;
        if (uploadPopoverOutsideClose) {
          document.removeEventListener("click", uploadPopoverOutsideClose);
          uploadPopoverOutsideClose = null;
        }
        if (isClosed) {
          setUploadPopoverOpen(true);
          const onDocClick = (ev: MouseEvent) => {
            if (!uploadWrapEl?.contains(ev.target as Node)) {
              closeUploadPopoverCompletely();
            }
          };
          uploadPopoverOutsideClose = onDocClick;
          window.setTimeout(() => document.addEventListener("click", onDocClick), 0);
        } else {
          setUploadPopoverOpen(false);
        }
      });
      document.getElementById("overview-qa-view-source")?.addEventListener("click", () => {
        navigate("/mission/" + missionId + "/documents");
        render();
      });
      document.getElementById("overview-qa-copy-path")?.addEventListener("click", () => {
        const p = mission.source_path || "";
        if (!p) return;
        void navigator.clipboard.writeText(p).then(
          () => alert("Input path copied to clipboard."),
          () => alert(p)
        );
      });
      document.getElementById("btn-lifecycle-save")?.addEventListener("click", () => {
        const v = (document.getElementById("mission-lifecycle-select") as HTMLSelectElement)?.value;
        patch("/missions/" + missionId + "/metadata", { lifecycle_status: v }).then(() => {
          alert("Lifecycle updated.");
          render();
        }).catch((err: Error) => alert(err.message || "Failed"));
      });
      function refreshAuxList(): void {
        get<{ sources: { id: string; label: string; path: string }[] }>(
          "/missions/" + missionId + "/auxiliary"
        )
          .then((d) => {
            const ul = document.getElementById("auxiliary-list-ui");
            if (!ul) return;
            ul.innerHTML = "";
            for (const s of d.sources || []) {
              const li = document.createElement("li");
              li.textContent = s.label + " — " + s.path + " ";
              const del = document.createElement("button");
              del.type = "button";
              del.className = "btn btn-sm btn-danger";
              del.textContent = "Remove";
              del.addEventListener("click", () => {
                fetch(API + "/missions/" + missionId + "/auxiliary/" + encodeURIComponent(s.id), {
                  method: "DELETE",
                  credentials: "include",
                })
                  .then(() => refreshAuxList())
                  .catch((e: Error) => alert(e.message));
              });
              li.appendChild(del);
              ul.appendChild(li);
            }
          })
          .catch(() => {});
      }
      refreshAuxList();
      document.getElementById("btn-aux-add")?.addEventListener("click", () => {
        const label = (document.getElementById("aux-label-inp") as HTMLInputElement)?.value?.trim() || "note";
        const path = (document.getElementById("aux-path-inp") as HTMLInputElement)?.value?.trim() ?? "";
        if (!path) {
          alert("Enter a file path.");
          return;
        }
        post("/missions/" + missionId + "/auxiliary", { label, path })
          .then(() => refreshAuxList())
          .catch((e: Error) => alert(e.message || "Failed"));
      });

      ingestSel?.addEventListener("change", () => {
        const sel = document.getElementById("mission-ingest-mode") as HTMLSelectElement;
        const value = sel.value === "manual" ? "manual" : "auto";
        patch("/missions/" + missionId + "/metadata", { ingest_mode: value }).then(() => {
          mission.ingest_mode = value;
        }).catch((err: Error) => alert(err.message || "Failed to update ingest mode"));
      });
    })
    .catch(() => {
      main.innerHTML = '<p class="error">Mission not found.</p>';
    });
}

/** Appends a "Generating…" label and a streaming <pre> to the container (does not clear it). Returns the pre id for onChunk. */
function appendStreamingPreview(container: HTMLElement, previewId: string): void {
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

function connectStream(
  missionId: string,
  reportType: string,
  boxEl: HTMLElement,
  onDone?: () => void,
  onChunk?: (accumulatedContent: string) => void
): () => void {
  const url =
    API +
    "/stream/" +
    encodeURIComponent(missionId) +
    "/" +
    encodeURIComponent(reportType);
  const es = new EventSource(url, { withCredentials: true });
  let content = "";

  boxEl.classList.add("streaming");
  boxEl.textContent = "Connecting…";

  es.onmessage = function (e: MessageEvent) {
    try {
      const d = JSON.parse(e.data) as SSEEvent;
      if (d.t === "buf") {
        content = d.text ?? "";
      } else if (d.t === "chunk") {
        content += d.text ?? "";
      } else if (d.t === "done") {
        es.close();
        boxEl.classList.remove("streaming");
        onDone?.();
        return;
      }
      boxEl.textContent = content || "Generating…";
      boxEl.scrollTop = boxEl.scrollHeight;
      onChunk?.(content);
    } catch {
      // ignore parse errors
    }
  };

  es.onerror = function () {
    es.close();
    boxEl.classList.remove("streaming");
    if (!content) boxEl.textContent = "Disconnected or no stream.";
    onDone?.();
  };

  return function close() {
    es.close();
    boxEl.classList.remove("streaming");
  };
}

/** Single report type page: one draft area; inline diff with per-section Undo/Keep when pending. */
function renderReportView(missionId: string, reportType: ReportType, main: HTMLElement): void {
  teardownOverviewTeamRailSync();
  let mission: Mission | null = null;
  let closeStream: (() => void) | null = null;
  let stopPipelineJobPoll: (() => void) | null = null;
  let commentDraftRange: { from: number; to: number; sectionKey?: string } | null = null;
  let commentReplyParentId: string | null = null;
  let scheduleReportCommentLayout: () => void = () => {};
  let detachCommentScrollSync: (() => void) | null = null;
  currentReportCleanup = () => {
    detachCommentScrollSync?.();
    detachCommentScrollSync = null;
    stopPipelineJobPoll?.();
    stopPipelineJobPoll = null;
    closeStream?.();
    destroyAllReportEditors();
  };
  let proposalSegments: DiffSegment[] = [];
  let proposalKept: boolean[] = [];

  function syncCommentComposerVisibility(): void {
    const box = document.getElementById("report-comment-composer");
    if (!box) return;
    const show = commentDraftRange != null || commentReplyParentId != null;
    box.style.display = show ? "block" : "none";
    if (!show) {
      const ta = document.getElementById("report-comment-composer-body") as HTMLTextAreaElement | null;
      if (ta) ta.value = "";
    }
  }

  const label = REPORT_LABELS[reportType];
  main.innerHTML = `<div class="section report-workspace-loading"><h2 class="report-view-title">${escapeHtml(label)}</h2><p class="caption">Loading report…</p></div>`;

  function fetchReport(): Promise<Report> {
    return get<Report>("/missions/" + missionId + "/reports/" + reportType);
  }

  function fetchReportNoCache(): Promise<Report> {
    return get<Report>("/missions/" + missionId + "/reports/" + reportType + "?_=" + Date.now());
  }

  function renderDraftArea(report: Report, contentLocked: boolean, aiLocked: boolean): void {
    const draftEl = document.getElementById("draft-area");
    if (!draftEl) return;
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
    editorContainer.className = "tiptap-draft-container";
    draftEl.appendChild(editorContainer);
    const actions = document.createElement("div");
    actions.className = "actions";
    actions.style.marginTop = "0.5rem";
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "btn btn-sm";
    saveBtn.id = "btn-save-report";
    saveBtn.textContent = "Save edits to drop-off";
    saveBtn.disabled = contentLocked;
    if (contentLocked) saveBtn.title = "Report is final; reopen to draft to save.";
    const statusSpan = document.createElement("span");
    statusSpan.className = "caption";
    statusSpan.style.marginLeft = "0.5rem";
    const doSave = (): void => {
      if (contentLocked) return;
      const editor = getReportEditor("report-editor");
      if (editor?.hasPendingAssist()) {
        statusSpan.textContent = "Accept or reject the inline AI suggestion in the document before saving.";
        return;
      }
      const content = editor ? editor.getHtml() : (document.getElementById("current-report") as HTMLTextAreaElement)?.value ?? "";
      const content_json = editor ? editor.getJson() : undefined;
      const margins = getMarginInputs("");
      const body = margins
        ? { content, margins, ...(content_json ? { content_json } : {}) }
        : { content, ...(content_json ? { content_json } : {}) };
      post("/missions/" + missionId + "/reports/" + reportType + "/save", body).then(() => {
        statusSpan.textContent = "Saved.";
      }).catch((err: Error) => {
        statusSpan.textContent = err.message || "Save failed.";
      });
    };
    saveBtn.addEventListener("click", doSave);
    actions.appendChild(saveBtn);
    actions.appendChild(statusSpan);
    draftEl.appendChild(actions);
    const assistOpt =
      aiLocked ? undefined : { run: makeInlineAssistRunner(missionId, reportType) };
    const mounted = createReportEditor("report-editor", editorContainer, current, doSave, {
      inlineAssist: assistOpt,
      documentComments: contentLocked
        ? undefined
        : {
            onOpenComposer: (ctx) => {
              commentDraftRange = { from: ctx.from, to: ctx.to, sectionKey: ctx.sectionKey };
              commentReplyParentId = null;
              syncCommentComposerVisibility();
              (document.getElementById("report-comment-composer-body") as HTMLTextAreaElement | null)?.focus();
            },
          },
    });
    if (mounted) {
      const ed = mounted.getEditor();
      ed?.on("transaction", () => scheduleReportCommentLayout());
    }
    if (!mounted) {
      editorContainer.innerHTML = "";
      const textarea = document.createElement("textarea");
      textarea.id = "current-report";
      textarea.rows = 16;
      textarea.value = current;
      editorContainer.appendChild(textarea);
    }
  }

  /** Populate only the proposed-changes panel list (used when Tiptap draft keeps toolbar visible). */
  function fillChangesPanelOnly(
    report: Report,
    pendingEdits: PendingEdit[],
    contentLocked: boolean
  ): void {
    const listEl = document.getElementById("changes-panel-list");
    const draftEl = document.getElementById("draft-area");
    if (!listEl) return;
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
      if ((edit.status || "").toLowerCase() === "accepted") acceptBtn.disabled = true;
      if (contentLocked) acceptBtn.disabled = true;
        acceptBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          if (contentLocked) return;
          post("/missions/" + missionId + "/reports/" + reportType + "/edits/" + encodeURIComponent(edit.edit_id) + "/accept")
            .then(() => post("/missions/" + missionId + "/reports/" + reportType + "/apply-edits"))
            .then(() => fetchReport())
            .then((r) =>
              get<PendingEdit[]>("/missions/" + missionId + "/reports/" + reportType + "/pending-edits?_=" + Date.now())
                .then((edits) => renderContent(r, false, edits))
                .catch(() => renderContent(r, false, []))
            )
            .catch((err: unknown) => alert(err instanceof Error ? err.message : "Failed"));
        });
      const rejectBtn = document.createElement("button");
      rejectBtn.type = "button";
      rejectBtn.className = "btn btn-sm btn-danger";
      rejectBtn.textContent = (edit.status || "").toLowerCase() === "rejected" ? "Rejected" : "Reject";
      if ((edit.status || "").toLowerCase() === "rejected") rejectBtn.disabled = true;
      if (contentLocked) rejectBtn.disabled = true;
      rejectBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (contentLocked) return;
        post("/missions/" + missionId + "/reports/" + reportType + "/edits/" + encodeURIComponent(edit.edit_id) + "/reject")
          .then(() => get<PendingEdit[]>("/missions/" + missionId + "/reports/" + reportType + "/pending-edits?_=" + Date.now()))
          .then((edits) => renderContent(report, false, edits))
          .catch((err: unknown) => alert(err instanceof Error ? err.message : "Failed"));
      });
      row.appendChild(opBadge);
      row.appendChild(textSpan);
      row.appendChild(statusSpan);
      row.appendChild(acceptBtn);
      row.appendChild(rejectBtn);
      row.addEventListener("click", () => {
        const evEl = document.getElementById("rr-evidence-body");
        if (evEl) {
          const refs = edit.evidence_refs || [];
          evEl.textContent = refs.length
            ? refs.map((r) => String(r)).join("\n\n")
            : "(No evidence_refs on this suggestion.)";
        }
        if (!draftEl) return;
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

  function renderDraftAreaWithEdits(report: Report, pendingEdits: PendingEdit[]): void {
    const draftEl = document.getElementById("draft-area");
    const listEl = document.getElementById("changes-panel-list");
    if (!draftEl || !listEl) return;
    draftEl.className = "draft-area draft-area-blocks";
    draftEl.innerHTML = "<p class=\"caption\">Loading…</p>";
    listEl.innerHTML = "";
    const isPending = (e: PendingEdit) => {
      const s = (e.status || "").toLowerCase();
      return s !== "accepted" && s !== "rejected";
    };
    const targetIdsForReplace = new Set(
      pendingEdits
        .filter((e) => (e.operation || "").toLowerCase() === "replace" && isPending(e))
        .map((e) => e.target_block_id)
    );
    const editsByBlock = new Map<string, PendingEdit[]>();
    for (const edit of pendingEdits) {
      const bid = edit.target_block_id;
      if (!bid) continue;
      if (!editsByBlock.has(bid)) editsByBlock.set(bid, []);
      editsByBlock.get(bid)!.push(edit);
    }
    fillChangesPanelOnly(report, pendingEdits, false);

    get<ReportBlocksResponse>("/missions/" + missionId + "/reports/" + reportType + "/blocks")
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

  function renderContent(report: Report, pipelineRunning: boolean, pendingEdits: PendingEdit[] = []): void {
    if (!report || typeof report !== "object") {
      main.innerHTML = '<p class="error">Report unavailable. Try again.</p>';
      return;
    }
    try {
    proposalSegments = [];
    proposalKept = [];
    const label = REPORT_LABELS[reportType];
    const freq = mission?.auto_update_frequency || "off";
    const hasPending = !!(report.pending_content != null && String(report.pending_content).length > 0);
    const hasAnyEdits = (pendingEdits?.length ?? 0) > 0;
    const isPendingEdit = (e: PendingEdit) => {
      const s = (e.status || "").toLowerCase();
      return s !== "accepted" && s !== "rejected";
    };
    const hasPendingEdits = hasAnyEdits && pendingEdits!.some(isPendingEdit);
    const reviewSt = normalizeReviewStatus(report.review_status);
    const contentLocked = reviewSt === "final";
    const aiLocked = reviewSt === "mel_approved" || reviewSt === "final";
    const transitionOpts = (REVIEW_TRANSITIONS_FROM[reviewSt] || [])
      .map(
        (v) =>
          `<option value="${escapeHtml(v)}">${escapeHtml(reviewStatusLabel(v))}</option>`
      )
      .join("");
    main.innerHTML = `
      <div class="section">
        <h2 class="report-view-title">${escapeHtml(label)}</h2>
        ${pipelineRunning ? '<p class="pill running">Updating…</p>' : ""}
        <div class="report-toolbar glass" style="margin-bottom: 1rem; padding: 0.75rem 1rem; border-radius: 8px;">
          <div class="actions" style="margin-top: 0; margin-bottom: 0; flex-wrap: wrap; gap: 0.75rem; align-items: center;">
            <button type="button" class="btn btn-primary" id="btn-update-report">Update</button>
            <label class="caption" style="display: inline-flex; align-items: center; gap: 0.35rem;" title="Use the full indexed corpus instead of incremental new/changed files for this run.">
              <input type="checkbox" id="chk-full-refresh-report" />
              Full source refresh
            </label>
            <span class="caption">Status</span>
            <span class="pill" id="review-status-pill">${escapeHtml(reviewStatusLabel(reviewSt))}</span>
            <label class="caption" style="display: inline-flex; align-items: center; gap: 0.35rem;">
              Transition to
              <select id="review-transition-select" class="report-frequency-select">
                <option value="">Choose…</option>
                ${transitionOpts}
              </select>
            </label>
            <button type="button" class="btn btn-sm btn-primary" id="btn-finalize-report" ${reviewSt === "mel_approved" ? "" : 'style="display: none;"'}>Finalize export</button>
            ${aiLocked ? '<span class="caption" id="review-ai-lock-note">AI update &amp; assist off (MEL approved / final).</span>' : ""}
            ${contentLocked ? '<span class="caption error" id="review-content-lock-note">Content locked — reopen to draft to edit.</span>' : ""}
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
            <button type="button" class="btn btn-sm report-approval-log-pill" id="btn-approval-log-toggle" aria-expanded="false" aria-controls="report-approval-log-panel">Approval log</button>
            <button type="button" class="btn btn-sm" id="btn-export-pdf" title="Export current HTML to PDF">Export PDF</button>
            <button type="button" class="btn btn-sm btn-danger" id="btn-reset-report" title="Restore the skeleton template with placeholders" ${contentLocked ? "disabled" : ""}>Reset to template</button>
          </div>
          <div id="report-status-confirm" class="report-status-confirm" style="display: none; margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px solid var(--glass-border, rgba(255,255,255,0.12));">
            <div style="display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: flex-start;">
              <button type="button" class="btn btn-sm" id="btn-review-apply">Apply status</button>
              <label class="caption report-status-confirm-comment" style="display: flex; flex-direction: column; gap: 0.35rem; flex: 1; min-width: 12rem;">
                Additional comments (optional)
                <textarea id="review-transition-comment" rows="3" style="width: 100%; max-width: 28rem; font: inherit;" placeholder=""></textarea>
              </label>
            </div>
          </div>
        </div>
        <div id="report-approval-log-panel" class="report-approval-log-panel glass" role="region" aria-label="Approval log" hidden>
          <div id="report-approval-log" class="caption report-approval-log-body"></div>
        </div>
        <div class="report-workspace" id="report-workspace">
          <div class="report-workspace-main">
            <div class="report-doc-zone">
              <div class="report-doc-scroll" id="report-doc-scroll">
                <div class="report-doc-column" id="report-doc-column">
                  <div class="report-editor-pane" id="report-editor-pane">
                    <div class="draft-page" id="draft-page-report">
                      <div id="draft-area"></div>
                      <div class="stream-box" id="stream-report" style="display: none;">Connecting…</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <aside class="report-comment-gutter" id="report-comment-gutter" aria-label="Document comments">
              <div id="report-comment-composer" class="report-comment-composer glass" style="display: none;">
                <div class="caption" style="margin-bottom: 0.35rem;">New comment</div>
                <textarea id="report-comment-composer-body" rows="3" style="width: 100%; font: inherit;" placeholder="Write a comment…"></textarea>
                <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap;">
                  <button type="button" class="btn btn-sm btn-primary" id="btn-gutter-comment-post">Post</button>
                  <button type="button" class="btn btn-sm" id="btn-gutter-comment-cancel">Cancel</button>
                </div>
              </div>
              <div class="report-comment-gutter-inner" id="report-comment-gutter-inner"></div>
            </aside>
          </div>
        </div>
        <div class="report-margins-and-rail-row">
          <div class="page-margins-row caption report-margins-cluster" style="display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;">
            <span>Page margins (inches):</span>
            <label>Top <input type="number" id="margin-top" min="0" step="0.25" value="1" style="width: 4rem;"></label>
            <label>Right <input type="number" id="margin-right" min="0" step="0.25" value="1" style="width: 4rem;"></label>
            <label>Bottom <input type="number" id="margin-bottom" min="0" step="0.25" value="1" style="width: 4rem;"></label>
            <label>Left <input type="number" id="margin-left" min="0" step="0.25" value="1" style="width: 4rem;"></label>
          </div>
          <aside class="report-right-rail glass report-right-rail--inline" id="report-right-rail">
            <div class="rr-tabs" style="display: flex; gap: 0.25rem; flex-wrap: wrap; margin-bottom: 0.5rem;">
              <button type="button" class="btn btn-sm rr-tab active" data-rr="suggestions">Suggestions</button>
              <button type="button" class="btn btn-sm rr-tab" data-rr="evidence">Evidence</button>
              <button type="button" class="btn btn-sm rr-tab" data-rr="chat">Chat</button>
              <button type="button" class="btn btn-sm rr-tab" data-rr="activity">Activity</button>
            </div>
            <div id="rr-panel-suggestions" class="rr-panel">
              <h3 class="changes-panel-title">Proposed changes</h3>
              <div id="changes-panel-list"></div>
            </div>
            <div id="rr-panel-evidence" class="rr-panel hidden">
              <p class="caption">Select a suggestion to view evidence_refs.</p>
              <div id="rr-evidence-body" class="caption" style="white-space: pre-wrap; font-size: 0.9em;"></div>
            </div>
            <div id="rr-panel-chat" class="rr-panel hidden">
              <div id="rr-chat-log" class="caption" style="max-height: 14rem; overflow-y: auto; margin-bottom: 0.5rem; font-size: 0.88em;"></div>
              <textarea id="rr-chat-input" rows="2" style="width: 100%; font: inherit;" placeholder="Ask about this report (suggestions are review-only)…"></textarea>
              <button type="button" class="btn btn-sm btn-primary" id="btn-rr-chat-send" style="margin-top: 0.35rem;">Send</button>
            </div>
            <div id="rr-panel-activity" class="rr-panel hidden">
              <div id="rr-activity-body" class="caption" style="font-size: 0.88em;">Loading…</div>
            </div>
          </aside>
        </div>
      </div>
    `;

    const draftArea = document.getElementById("draft-area")!;
    const streamEl = document.getElementById("stream-report")!;
    const draftPageEl = document.getElementById("draft-page-report");

    const stored = getStoredMargins(missionId, reportType);
    for (const k of ["top", "right", "bottom", "left"] as const) {
      const inp = document.getElementById("margin-" + k) as HTMLInputElement | null;
      if (inp) inp.value = String(stored[k]);
    }
    function applyMarginsToDraftPage(): void {
      const m = getMarginInputs("");
      if (m && draftPageEl) {
        const px = (inch: number) => Math.round(inch * 96);
        draftPageEl.style.padding = `${px(m.top)}px ${px(m.right)}px ${px(m.bottom)}px ${px(m.left)}px`;
        setStoredMargins(missionId, reportType, m);
        const inchToPx = 96;
        const inner = Math.max(240, Math.round(11 * inchToPx - (m.top + m.bottom) * inchToPx));
        draftPageEl.style.setProperty("--report-page-inner-height", `${inner}px`);
      }
    }
    applyMarginsToDraftPage();
    for (const k of ["top", "right", "bottom", "left"] as const) {
      document.getElementById("margin-" + k)?.addEventListener("change", applyMarginsToDraftPage);
      document.getElementById("margin-" + k)?.addEventListener("input", applyMarginsToDraftPage);
    }

    const approvalLogPanel = document.getElementById("report-approval-log-panel") as HTMLElement | null;
    const approvalLogToggle = document.getElementById("btn-approval-log-toggle") as HTMLButtonElement | null;
    if (approvalLogPanel && approvalLogToggle) {
      approvalLogToggle.addEventListener("click", () => {
        const opening = approvalLogPanel.hidden;
        approvalLogPanel.hidden = !opening;
        approvalLogToggle.setAttribute("aria-expanded", opening ? "true" : "false");
        approvalLogToggle.classList.toggle("report-approval-log-pill--open", opening);
      });
    }

    const updateBtnEl = document.getElementById("btn-update-report") as HTMLButtonElement | null;
    if (updateBtnEl && !pipelineRunning) {
      updateBtnEl.disabled = aiLocked;
      if (aiLocked) updateBtnEl.title = "MEL approved or final: pipeline update disabled.";
    }
    const fullRefreshChk = document.getElementById("chk-full-refresh-report") as HTMLInputElement | null;
    if (fullRefreshChk) fullRefreshChk.disabled = aiLocked;

    function syncReportStatusConfirmRow(): void {
      const sel = document.getElementById("review-transition-select") as HTMLSelectElement | null;
      const row = document.getElementById("report-status-confirm") as HTMLElement | null;
      const ta = document.getElementById("review-transition-comment") as HTMLTextAreaElement | null;
      if (!sel || !row) return;
      if (!sel.value?.trim()) {
        row.style.display = "none";
        if (ta) ta.value = "";
      } else {
        row.style.display = "";
      }
    }

    function threadCommentRootId(row: ReportCommentRow, byId: Map<string, ReportCommentRow>): string {
      let cur: ReportCommentRow | undefined = row;
      const seen = new Set<string>();
      while (cur?.parent_id && !seen.has(cur.id)) {
        seen.add(cur.id);
        cur = byId.get(cur.parent_id);
      }
      return cur?.id ?? row.id;
    }

    function layoutCommentGutterCards(): void {
      const scrollEl = document.getElementById("report-doc-scroll");
      const inner = document.getElementById("report-comment-gutter-inner");
      const editor = getReportEditor("report-editor")?.getEditor() ?? null;
      if (!scrollEl || !inner) return;
      inner.style.minHeight = `${Math.max(scrollEl.offsetHeight, scrollEl.scrollHeight, 400)}px`;
      if (!editor) return;
      const scrollRect = scrollEl.getBoundingClientRect();
      const cards = inner.querySelectorAll<HTMLElement>(".report-comment-card[data-anchor-from]");
      const positions: { el: HTMLElement; top: number }[] = [];
      cards.forEach((el) => {
        const from = Number(el.dataset.anchorFrom);
        if (!Number.isFinite(from)) return;
        try {
          const c = editor.view.coordsAtPos(from);
          const top = c.top - scrollRect.top;
          positions.push({ el, top });
        } catch {
          el.style.top = "0px";
        }
      });
      positions.sort((a, b) => a.top - b.top);
      let lastB = 0;
      for (const p of positions) {
        let t = p.top;
        if (t < lastB + 8) t = lastB + 8;
        p.el.style.top = `${t}px`;
        lastB = t + p.el.offsetHeight;
      }
    }

    scheduleReportCommentLayout = (): void => {
      requestAnimationFrame(() => layoutCommentGutterCards());
    };

    function refreshApprovalLog(): void {
      const logEl = document.getElementById("report-approval-log");
      get<{ events: ApprovalEventRow[] }>(
        "/missions/" + missionId + "/reports/" + reportType + "/approval-log?limit=50&_=" + Date.now()
      )
        .then((data) => {
          if (!logEl) return;
          const evs = data.events || [];
          if (!evs.length) {
            logEl.textContent = "No events yet.";
            return;
          }
          logEl.innerHTML = evs
            .map((e) => {
              const tc =
                e.detail && typeof e.detail.transition_comment === "string"
                  ? e.detail.transition_comment.trim()
                  : "";
              const parts = [
                escapeHtml(e.created_at),
                escapeHtml(e.event_type),
                e.from_status && e.to_status
                  ? escapeHtml(e.from_status) + " → " + escapeHtml(e.to_status)
                  : "",
                e.actor_label ? "@" + escapeHtml(e.actor_label) : "",
                tc ? escapeHtml(tc) : "",
              ].filter(Boolean);
              return `<div style="margin-bottom: 0.35rem;">${parts.join(" · ")}</div>`;
            })
            .join("");
        })
        .catch(() => {
          if (logEl) logEl.textContent = "Failed to load approval log.";
        });
    }

    function refreshCommentGutter(): void {
      const inner = document.getElementById("report-comment-gutter-inner");
      if (!inner) return;
      get<{ comments: ReportCommentRow[] }>(
        "/missions/" + missionId + "/reports/" + reportType + "/comments?_=" + Date.now()
      )
        .then((data) => {
          const rows = data.comments || [];
          if (!rows.length) {
            inner.innerHTML = "";
            const ed0 = getReportEditor("report-editor")?.getEditor() ?? null;
            if (ed0) applyCommentHighlights(ed0, []);
            scheduleReportCommentLayout();
            syncCommentComposerVisibility();
            return;
          }
          const byId = new Map(rows.map((r) => [r.id, r]));
          const groups = new Map<string, ReportCommentRow[]>();
          for (const r of rows) {
            const rid = threadCommentRootId(r, byId);
            const g = groups.get(rid) ?? [];
            g.push(r);
            groups.set(rid, g);
          }
          for (const g of groups.values()) {
            g.sort((a, b) => a.created_at.localeCompare(b.created_at));
          }

          inner.innerHTML = "";
          const rootOrder = rows.filter((r) => !r.parent_id).map((r) => r.id);
          for (const rootId of rootOrder) {
            const members = groups.get(rootId);
            if (!members?.length) continue;
            const anchorRow = members.find((m) => m.anchor && typeof m.anchor.from === "number");
            const anchor = anchorRow?.anchor;
            const card = document.createElement("div");
            card.className = "report-comment-card glass";
            card.dataset.threadRoot = rootId;
            if (anchor && typeof anchor.from === "number" && typeof anchor.to === "number") {
              card.dataset.anchorFrom = String(anchor.from);
              card.dataset.anchorTo = String(anchor.to);
            }
            for (const c of members) {
              const chunk = document.createElement("div");
              chunk.className = "report-comment-card-entry";

              const head = document.createElement("div");
              head.className = "report-comment-entry-head";

              const meta = document.createElement("div");
              meta.className = "report-comment-meta";
              const who = c.author_label ? escapeHtml(c.author_label) : "—";
              const sk = c.anchor_section_key
                ? ` · @${escapeHtml(c.anchor_section_key)}`
                : "";
              meta.innerHTML = `<span class="report-comment-author">${who}</span><span class="caption">${sk} · ${escapeHtml(c.created_at)}</span>`;
              head.appendChild(meta);

              if (!contentLocked) {
                const menu = document.createElement("details");
                menu.className = "report-comment-menu-details";
                const sum = document.createElement("summary");
                sum.className = "report-comment-menu-summary";
                sum.setAttribute("aria-label", "Comment actions");
                sum.textContent = "⋮";
                const panel = document.createElement("div");
                panel.className = "report-comment-menu-panel";
                const delBtn = document.createElement("button");
                delBtn.type = "button";
                delBtn.className = "btn btn-sm report-comment-menu-delete";
                delBtn.textContent = "Delete";
                delBtn.addEventListener("click", (ev) => {
                  ev.preventDefault();
                  menu.open = false;
                  const isRoot = !c.parent_id || String(c.parent_id).trim() === "";
                  const msg = isRoot
                    ? "Delete this comment and all replies?"
                    : "Delete this comment?";
                  if (!confirm(msg)) return;
                  httpDelete<{ ok: boolean }>(
                    "/missions/" +
                      missionId +
                      "/reports/" +
                      reportType +
                      "/comments/" +
                      encodeURIComponent(c.id)
                  )
                    .then(() => refreshCommentsUi())
                    .catch((err: unknown) => alert(err instanceof Error ? err.message : "Delete failed"));
                });
                panel.appendChild(delBtn);
                menu.appendChild(sum);
                menu.appendChild(panel);
                menu.addEventListener("toggle", () => {
                  if (menu.open && inner) {
                    inner.querySelectorAll("details.report-comment-menu-details").forEach((d) => {
                      if (d !== menu) (d as HTMLDetailsElement).open = false;
                    });
                  }
                });
                head.appendChild(menu);
              }

              const bodyEl = document.createElement("div");
              bodyEl.className = "report-comment-body";
              bodyEl.textContent = c.body;

              chunk.appendChild(head);
              chunk.appendChild(bodyEl);
              card.appendChild(chunk);
            }
            const replyBtn = document.createElement("button");
            replyBtn.type = "button";
            replyBtn.className = "btn btn-sm";
            replyBtn.style.marginTop = "0.35rem";
            replyBtn.textContent = "Reply";
            replyBtn.addEventListener("click", () => {
              commentReplyParentId = rootId;
              commentDraftRange = null;
              syncCommentComposerVisibility();
              (document.getElementById("report-comment-composer-body") as HTMLTextAreaElement | null)?.focus();
            });
            card.appendChild(replyBtn);
            inner.appendChild(card);
          }

          const ed = getReportEditor("report-editor")?.getEditor() ?? null;
          if (ed) {
            applyCommentHighlights(
              ed,
              rows.filter((r) => !r.parent_id).map((r) => ({ id: r.id, anchor: r.anchor }))
            );
          }
          scheduleReportCommentLayout();
          syncCommentComposerVisibility();
        })
        .catch(() => {
          inner.textContent = "Failed to load comments.";
        });
    }

    function refreshCommentsUi(): void {
      refreshApprovalLog();
      refreshCommentGutter();
    }

    document.getElementById("review-transition-select")?.addEventListener("change", syncReportStatusConfirmRow);
    syncReportStatusConfirmRow();

    document.getElementById("btn-review-apply")?.addEventListener("click", () => {
      const sel = document.getElementById("review-transition-select") as HTMLSelectElement | null;
      const v = sel?.value?.trim();
      if (!v) {
        alert("Choose a target status.");
        return;
      }
      const ta = document.getElementById("review-transition-comment") as HTMLTextAreaElement | null;
      const tc = ta?.value?.trim();
      const patchBody: { status: string; transition_comment?: string } = { status: v };
      if (tc) patchBody.transition_comment = tc;
      patch<{ ok: boolean; review_status: string }>(
        "/missions/" + missionId + "/reports/" + reportType + "/review-status",
        patchBody
      )
        .then(() => fetchReport())
        .then((r) =>
          get<PendingEdit[]>("/missions/" + missionId + "/reports/" + reportType + "/pending-edits")
            .then((edits) => ({ r, edits }))
            .catch(() => ({ r, edits: [] as PendingEdit[] }))
        )
        .then(({ r, edits }) => renderContent(r, false, edits))
        .catch((err: unknown) => alert(err instanceof Error ? err.message : "Transition failed"));
    });

    document.getElementById("btn-finalize-report")?.addEventListener("click", () => {
      const rev = report.current_revision_id != null ? String(report.current_revision_id) : undefined;
      const finalizeBody: { current_revision_id?: string } = {};
      if (rev) finalizeBody.current_revision_id = rev;
      post<{ ok: boolean }>("/missions/" + missionId + "/reports/" + reportType + "/finalize", finalizeBody)
        .then(() => fetchReport())
        .then((r) =>
          get<PendingEdit[]>("/missions/" + missionId + "/reports/" + reportType + "/pending-edits")
            .then((edits) => ({ r, edits }))
            .catch(() => ({ r, edits: [] as PendingEdit[] }))
        )
        .then(({ r, edits }) => renderContent(r, false, edits))
        .catch((err: unknown) => alert(err instanceof Error ? err.message : "Finalize failed"));
    });

    document.getElementById("btn-gutter-comment-cancel")?.addEventListener("click", () => {
      commentDraftRange = null;
      commentReplyParentId = null;
      syncCommentComposerVisibility();
    });

    document.getElementById("btn-gutter-comment-post")?.addEventListener("click", () => {
      const ta = document.getElementById("report-comment-composer-body") as HTMLTextAreaElement | null;
      const body = ta?.value?.trim() ?? "";
      if (!body) return;
      const editor = getReportEditor("report-editor")?.getEditor() ?? null;
      const parent_id = commentReplyParentId?.trim() || undefined;
      let anchor_json: CommentAnchorJson | undefined;
      let anchor_section_key: string | undefined;
      if (!parent_id && commentDraftRange && editor) {
        anchor_json = buildAnchorPayload(editor, commentDraftRange.from, commentDraftRange.to);
        anchor_section_key = anchor_json.sectionKey;
      }
      post<{ ok: boolean; id: string }>("/missions/" + missionId + "/reports/" + reportType + "/comments", {
        body,
        parent_id,
        anchor_json,
        anchor_section_key,
      })
        .then(() => {
          if (ta) ta.value = "";
          commentDraftRange = null;
          commentReplyParentId = null;
          syncCommentComposerVisibility();
          refreshCommentsUi();
        })
        .catch((err: unknown) => alert(err instanceof Error ? err.message : "Failed to post"));
    });

    fillChangesPanelOnly(report, pendingEdits, contentLocked);

    function switchRrPanel(name: string): void {
      document.querySelectorAll(".rr-tab").forEach((b) => {
        b.classList.toggle("active", (b as HTMLElement).dataset.rr === name);
      });
      (["suggestions", "evidence", "chat", "activity"] as const).forEach((id) => {
        const p = document.getElementById("rr-panel-" + id);
        if (p) p.classList.toggle("hidden", id !== name);
      });
    }
    document.querySelectorAll(".rr-tab").forEach((b) => {
      b.addEventListener("click", () => {
        const name = (b as HTMLElement).dataset.rr || "suggestions";
        switchRrPanel(name);
        if (name === "activity") {
          get<{ events: unknown[] }>("/missions/" + missionId + "/activity?limit=40")
            .then((d) => {
              const el = document.getElementById("rr-activity-body");
              if (el) el.textContent = JSON.stringify(d.events || [], null, 2);
            })
            .catch(() => {
              const el = document.getElementById("rr-activity-body");
              if (el) el.textContent = "Failed to load activity.";
            });
        }
        if (name === "chat") {
          get<{ messages: { role: string; content: string; created_at?: string }[] }>(
            "/missions/" + missionId + "/reports/" + reportType + "/chat-messages?limit=30"
          )
            .then((d) => {
              const el = document.getElementById("rr-chat-log");
              if (!el) return;
              const lines = (d.messages || []).map(
                (m) => (m.created_at || "") + " [" + m.role + "] " + m.content
              );
              el.textContent = lines.length ? lines.join("\n\n") : "(No messages yet.)";
            })
            .catch(() => {
              const el = document.getElementById("rr-chat-log");
              if (el) el.textContent = "Could not load chat.";
            });
        }
      });
    });

    document.getElementById("btn-export-pdf")?.addEventListener("click", () => {
      fetch(API + "/missions/" + missionId + "/reports/" + reportType + "/export/pdf", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ use_preview: hasAnyEdits }),
      })
        .then((r) => {
          if (r.status === 401) {
            redirectUnauthenticated();
            throw new Error("Unauthorized");
          }
          if (!r.ok) throw new Error(r.statusText);
          return r.blob();
        })
        .then((blob) => {
          const u = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = u;
          a.download = reportType + "_" + missionId + ".pdf";
          a.click();
          URL.revokeObjectURL(u);
        })
        .catch((e: unknown) => alert(e instanceof Error ? e.message : "PDF export failed"));
    });

    document.getElementById("btn-reset-report")?.addEventListener("click", () => {
      if (contentLocked) return;
      const confirmed = window.confirm(
        "Reset this document to the skeleton template?\n\n" +
          "All draft text, pending AI suggestions, and incremental update tracking for this report will be cleared. " +
          "Review status returns to Draft.\n\nThis cannot be undone."
      );
      if (!confirmed) return;
      const resetBtn = document.getElementById("btn-reset-report") as HTMLButtonElement | null;
      if (resetBtn) resetBtn.disabled = true;
      post("/missions/" + missionId + "/reports/" + reportType + "/reset")
        .then(() => {
          if (hashMatchesReport(missionId, reportType)) render();
        })
        .catch((err: Error) => alert(err?.message ?? "Failed to reset draft"))
        .finally(() => {
          if (resetBtn && !contentLocked) resetBtn.disabled = false;
        });
    });

    document.getElementById("btn-rr-chat-send")?.addEventListener("click", () => {
      const ta = document.getElementById("rr-chat-input") as HTMLTextAreaElement | null;
      const msg = ta?.value?.trim() ?? "";
      if (!msg) return;
      post<{ reply: string }>("/missions/" + missionId + "/reports/" + reportType + "/chat", {
        scope: "report",
        message: msg,
      })
        .then((res) => {
          if (ta) ta.value = "";
          const el = document.getElementById("rr-chat-log");
          if (el) el.textContent += "\n\n[assistant] " + (res.reply || "");
        })
        .catch((e: unknown) => alert(e instanceof Error ? e.message : "Chat failed"));
    });

    if (hasAnyEdits) {
      streamEl.style.display = "none";
      renderDraftArea(report, contentLocked, aiLocked);
      const q0 = getReportEditor("report-editor");
      if (q0) q0.setContent("<p><em>Loading proposed changes…</em></p>");
      get<{ preview_html: string }>("/missions/" + missionId + "/reports/" + reportType + "/preview")
        .then((data) => {
          const q = getReportEditor("report-editor");
          const html = data.preview_html != null ? String(data.preview_html) : "";
          if (q) q.setContent(html || "<p><br></p>");
        })
        .catch(() => {
          const q = getReportEditor("report-editor");
          if (q) q.setContent((report.current_content ?? "") || "<p><br></p>");
        });
      const accAll = document.getElementById("btn-accept-all-edits") as HTMLButtonElement | null;
      const rejAll = document.getElementById("btn-reject-all-edits") as HTMLButtonElement | null;
      if (accAll) {
        accAll.disabled = contentLocked;
        accAll.addEventListener("click", () => {
          if (contentLocked) return;
          post("/missions/" + missionId + "/reports/" + reportType + "/accept-all-edits")
            .then(() => post("/missions/" + missionId + "/reports/" + reportType + "/apply-edits"))
            .then(() => fetchReport())
            .then((r) => renderContent(r, false, []))
            .catch((err: unknown) => alert(err instanceof Error ? err.message : "Failed"));
        });
      }
      if (rejAll) {
        rejAll.disabled = contentLocked;
        rejAll.addEventListener("click", () => {
          if (contentLocked) return;
          post("/missions/" + missionId + "/reports/" + reportType + "/reject-all-edits")
            .then(() => fetchReport())
            .then((r) => renderContent(r, false, []))
            .catch((err: unknown) => alert(err instanceof Error ? err.message : "Failed"));
        });
      }
    } else if (pipelineRunning) {
      streamEl.style.display = "none";
      renderDraftArea(report, contentLocked, aiLocked);
      const hiddenStream = document.createElement("div");
      hiddenStream.style.display = "none";
      hiddenStream.setAttribute("aria-hidden", "true");
      document.body.appendChild(hiddenStream);
      const updateBtn = document.getElementById("btn-update-report") as HTMLButtonElement | null;
      if (updateBtn) {
        updateBtn.disabled = true;
        updateBtn.textContent = "Updating…";
      }
      const initialTemplate = (report.current_content ?? "").trim() || "";
      let resumeFinalized = false;
      function refreshReportAfterResume(): void {
        if (resumeFinalized) return;
        resumeFinalized = true;
        stopPipelineJobPoll?.();
        stopPipelineJobPoll = null;
        try {
          hiddenStream.remove();
        } catch (_) {}
        if (!hashMatchesReport(missionId, reportType)) {
          render();
          return;
        }
        fetchReport()
          .then((r) => {
            return get<PendingEdit[]>("/missions/" + missionId + "/reports/" + reportType + "/pending-edits")
              .then((edits) => ({ r, pendingEdits: edits }))
              .catch(() => ({ r, pendingEdits: [] as PendingEdit[] }));
          })
          .then(({ r, pendingEdits }) => {
            destroyAllReportEditors();
            setTimeout(() => {
              try {
                renderContent(r, false, pendingEdits);
              } catch (e) {
                console.error(e);
                if (updateBtn) {
                  updateBtn.disabled = aiLocked;
                  updateBtn.textContent = "Update";
                }
                alert("Failed to render report after update.");
              }
            }, 0);
          })
          .catch((err: unknown) => {
            const msg = err instanceof Error ? err.message : String(err);
            if (updateBtn) {
              updateBtn.disabled = aiLocked;
              updateBtn.textContent = "Update";
            }
            alert(msg || "Failed to load report after update.");
          });
      }
      get<{ jobs: PipelineJobRow[] }>("/missions/" + missionId + "/pipeline-jobs?limit=1")
        .then((data) => {
          const row = data.jobs?.[0];
          if (row?.id && (row.status === "running" || row.status === "queued")) {
            stopPipelineJobPoll = pollPipelineJobUntilTerminal(missionId, row.id, (j) => {
              if (resumeFinalized) return;
              if (j.status === "failed") {
                resumeFinalized = true;
                stopPipelineJobPoll?.();
                stopPipelineJobPoll = null;
                try {
                  hiddenStream.remove();
                } catch (_) {}
                const fk = j.failure_kind ? String(j.failure_kind) + ": " : "";
                alert(fk + (j.error_message || "Update failed"));
                if (updateBtn) {
                  updateBtn.disabled = aiLocked;
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
        .catch(() => {});
      closeStream = connectStream(missionId, reportType, hiddenStream, undefined, (content) => {
        const merged = mergeLlmIntoDraft(initialTemplate, content);
        const html = mergedToDisplayHtml(merged);
        getReportEditor("report-editor")?.setContent(html);
      });
    } else if (hasPending) {
      streamEl.style.display = "none";
      renderDraftArea(report, contentLocked, aiLocked);
      const bAcc = document.getElementById("btn-accept-all") as HTMLButtonElement | null;
      const bRej = document.getElementById("btn-reject-all") as HTMLButtonElement | null;
      const bApp = document.getElementById("btn-apply-merged") as HTMLButtonElement | null;
      if (bAcc) {
        bAcc.disabled = contentLocked;
        bAcc.addEventListener("click", () => {
          if (contentLocked) return;
          post("/missions/" + missionId + "/reports/" + reportType + "/accept").then(() =>
            fetchReport().then((r) => renderContent(r, false)).catch((err: unknown) =>
              alert(err instanceof Error ? err.message : "Failed to load report.")
            )
          );
        });
      }
      if (bRej) {
        bRej.disabled = contentLocked;
        bRej.addEventListener("click", () => {
          if (contentLocked) return;
          post("/missions/" + missionId + "/reports/" + reportType + "/reject").then(() =>
            fetchReport().then((r) => renderContent(r, false)).catch((err: unknown) =>
              alert(err instanceof Error ? err.message : "Failed to load report.")
            )
          );
        });
      }
      if (bApp) {
        bApp.disabled = contentLocked;
        bApp.addEventListener("click", () => {
          if (contentLocked) return;
        let segments: DiffSegment[];
        if (proposalSegments.length) {
          segments = proposalSegments;
        } else {
          try {
            segments = computeDiffSegments(report.current_content ?? "", report.pending_content ?? "") as DiffSegment[];
          } catch (_) {
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
          .then(() => fetchReport().then((r) => renderContent(r, false)).catch((err: unknown) =>
            alert(err instanceof Error ? err.message : "Failed to load report.")
          ))
          .catch((err: Error) => alert(err.message || "Failed to apply"));
        });
      }
    } else {
      streamEl.style.display = "none";
      renderDraftArea(report, contentLocked, aiLocked);
    }

    refreshCommentsUi();
    {
      const scrollEl =
        document.querySelector(".mission-workspace-body-outer") ??
        document.getElementById("main");
      detachCommentScrollSync?.();
      detachCommentScrollSync = null;
      const onMainScroll = (): void => scheduleReportCommentLayout();
      if (scrollEl) {
        scrollEl.addEventListener("scroll", onMainScroll, { passive: true });
        detachCommentScrollSync = () => scrollEl.removeEventListener("scroll", onMainScroll);
      }
    }

    document.getElementById("btn-update-report")!.addEventListener("click", () => {
      const updateBtn = document.getElementById("btn-update-report") as HTMLButtonElement | null;
      const fullRefreshEl = document.getElementById("chk-full-refresh-report") as HTMLInputElement | null;
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
      let updateTimeoutId: ReturnType<typeof setTimeout> | null = setTimeout(() => {
        updateTimeoutId = null;
        try {
          hiddenStream.remove();
          updatingPill.remove();
        } catch (_) {}
        if (updateBtn) {
          updateBtn.disabled = aiLocked;
          updateBtn.textContent = "Update";
        }
        alert("Update is taking longer than usual (5 min). You can try again or check the server.");
      }, UPDATE_TIMEOUT_MS);
      let finalized = false;
      function cleanupUi(): void {
        try {
          hiddenStream.remove();
          updatingPill.remove();
        } catch (_) {}
        if (updateBtn) {
          updateBtn.disabled = aiLocked;
          updateBtn.textContent = "Update";
        }
      }
      function finalizeSuccess(): void {
        if (finalized) return;
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
        const refetchAndRender = (): void => {
          fetchReportNoCache()
            .then((r) => {
              return get<PendingEdit[]>("/missions/" + missionId + "/reports/" + reportType + "/pending-edits")
                .then((edits) => ({ r, pendingEdits: edits }))
                .catch(() => ({ r, pendingEdits: [] as PendingEdit[] }));
            })
            .then(({ r, pendingEdits }) => {
              destroyAllReportEditors();
              setTimeout(() => {
                try {
                  renderContent(r, false, pendingEdits);
                } catch (e) {
                  console.error(e);
                  alert("Failed to render report after update.");
                }
              }, 0);
            })
            .catch((err: unknown) => {
              const msg = err instanceof Error ? err.message : String(err);
              alert(msg || "Failed to load report after update.");
            });
        };
        setTimeout(refetchAndRender, 150);
      }
      function finalizeFailure(msg: string): void {
        if (finalized) return;
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
        getReportEditor("report-editor")?.setContent(html);
      });
      const updateBody =
        fullRefreshEl?.checked === true ? { update_intent: "full_refresh" } : {};
      post<{ ok: boolean; job_id?: string }>(
        "/missions/" + missionId + "/reports/" + reportType + "/update",
        updateBody
      )
        .then((res) => {
          if (res.job_id) {
            stopPipelineJobPoll = pollPipelineJobUntilTerminal(missionId, res.job_id, (j) => {
              if (finalized) return;
              if (j.status === "failed") {
                const fk = j.failure_kind ? String(j.failure_kind) + ": " : "";
                finalizeFailure(fk + (j.error_message || "Update failed"));
                return;
              }
              if (j.status === "completed") {
                finalizeSuccess();
              }
            });
          } else {
            finalizeFailure("No job id returned; cannot track update status.");
          }
        })
        .catch((err: Error) => {
          if (updateTimeoutId != null) {
            clearTimeout(updateTimeoutId);
            updateTimeoutId = null;
          }
          closeStream?.();
          stopPipelineJobPoll?.();
          stopPipelineJobPoll = null;
          try {
            updatingPill.remove();
          } catch (_) {}
          if (updateBtn) {
            updateBtn.disabled = aiLocked;
            updateBtn.textContent = "Update";
          }
          alert(err.message || "Failed to start update");
        });
    });

    document.getElementById("report-frequency")!.addEventListener("change", () => {
      const sel = document.getElementById("report-frequency") as HTMLSelectElement;
      const value = sel.value;
      patch("/missions/" + missionId + "/metadata", { auto_update_frequency: value }).then(() => {
        if (mission) mission.auto_update_frequency = value;
      }).catch((err: Error) => alert(err.message || "Failed to update frequency"));
    });
    } catch (e) {
      console.error(e);
      main.innerHTML = '<p class="error">Something went wrong loading the report.</p>';
    }
  }

  get<Mission>("/missions/" + missionId)
    .then((m) => {
      mission = m;
      return get<StatusResponse>("/status");
    })
    .then((status) => {
      const pipelineRunning = status.running_mission_id === missionId;
      return fetchReport().then((report) => ({ report, pipelineRunning }));
    })
    .then(({ report, pipelineRunning }) => {
      return get<PendingEdit[]>("/missions/" + missionId + "/reports/" + reportType + "/pending-edits")
        .then((pendingEdits) => ({ report, pipelineRunning, pendingEdits }))
        .catch(() => ({ report, pipelineRunning, pendingEdits: [] as PendingEdit[] }));
    })
    .then(({ report, pipelineRunning, pendingEdits }) => {
      if (!hashMatchesReport(missionId, reportType)) {
        render();
        return;
      }
      try {
        renderContent(report, pipelineRunning, pendingEdits);
      } catch (e) {
        console.error(e);
        main.innerHTML = '<p class="error">Something went wrong loading this report.</p>';
      }
    })
    .catch(() => {
      if (!mission) {
        main.innerHTML = '<p class="error">Mission not found.</p>';
      } else {
        main.innerHTML = '<p class="error">Report unavailable. Try again.</p>';
      }
    });
}

/** Legacy: combined RMP + Timeline documents view; same single-draft + per-section Undo/Keep as report view. */
function renderDocumentsView(missionId: string, main: HTMLElement): void {
  teardownOverviewTeamRailSync();
  let mission: Mission | null = null;
  let closeRmp: (() => void) | null = null;
  let closeTimeline: (() => void) | null = null;
  let stopDocsJobPoll: (() => void) | null = null;
  currentReportCleanup = () => {
    stopDocsJobPoll?.();
    stopDocsJobPoll = null;
    closeRmp?.();
    closeTimeline?.();
    destroyAllReportEditors();
  };
  let rmpSegments: DiffSegment[] = [];
  let rmpKept: boolean[] = [];
  let timelineSegments: DiffSegment[] = [];
  let timelineKept: boolean[] = [];
  let currentReports: { rmp: Report; timeline: Report } | null = null;

  function fetchReports(): Promise<{ rmp: Report; timeline: Report }> {
    return Promise.all([
      get<Report>("/missions/" + missionId + "/reports/rmp"),
      get<Report>("/missions/" + missionId + "/reports/timeline"),
    ]).then(([rmp, timeline]) => ({ rmp, timeline }));
  }

  function renderDocDraftArea(
    type: "rmp" | "timeline",
    report: Report,
    draftEl: HTMLElement,
    segmentsRef: { current: DiffSegment[] },
    keptRef: { current: boolean[] }
  ): void {
    const current = report.current_content ?? "";
    const pending = report.pending_content;
    draftEl.innerHTML = "";
    if (pending) {
      if (segmentsRef.current.length === 0) {
        const segs = computeDiffSegments(current, pending) as DiffSegment[];
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
        } else {
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
            if (currentReports) renderDocDraftArea(type, type === "rmp" ? currentReports.rmp : currentReports.timeline, draftEl, segmentsRef, keptRef);
          });
          keepBtn.addEventListener("click", () => {
            keptRef.current[thisChangeIdx] = true;
            if (currentReports) renderDocDraftArea(type, type === "rmp" ? currentReports.rmp : currentReports.timeline, draftEl, segmentsRef, keptRef);
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
    editorContainer.className = "tiptap-draft-container";
    draftEl.appendChild(editorContainer);
    const actions = document.createElement("div");
    actions.className = "actions";
    actions.style.marginTop = "0.5rem";
    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "btn btn-sm";
    saveBtn.id = "btn-save-" + type;
    saveBtn.textContent = "Save edits to drop-off";
    const rs = normalizeReviewStatus(report.review_status);
    const docContentLocked = rs === "final";
    const docAiLocked = rs === "mel_approved" || rs === "final";
    saveBtn.disabled = docContentLocked;
    if (docContentLocked) saveBtn.title = "Report is final; reopen to draft to save.";
    const statusSpan = document.createElement("span");
    statusSpan.className = "caption";
    statusSpan.style.marginLeft = "0.5rem";
    const doSave = (): void => {
      if (docContentLocked) return;
      const editor = getReportEditor("report-editor-" + type);
      if (editor?.hasPendingAssist()) {
        statusSpan.textContent = "Accept or reject the inline AI suggestion in the document before saving.";
        return;
      }
      const content = editor ? editor.getHtml() : (document.getElementById("current-" + type) as HTMLTextAreaElement)?.value ?? "";
      const margins = getMarginInputs(type + "-");
      const body = margins ? { content, margins } : { content };
      post("/missions/" + missionId + "/reports/" + type + "/save", body).then(() => {
        statusSpan.textContent = "Saved.";
      }).catch((err: Error) => {
        statusSpan.textContent = err.message || "Save failed.";
      });
    };
    saveBtn.addEventListener("click", doSave);
    actions.appendChild(saveBtn);
    actions.appendChild(statusSpan);
    draftEl.appendChild(actions);
    const docAssist = docAiLocked ? undefined : { run: makeInlineAssistRunner(missionId, type) };
    const mounted = createReportEditor("report-editor-" + type, editorContainer, current, doSave, {
      inlineAssist: docAssist,
    });
    if (!mounted) {
      editorContainer.innerHTML = "";
      const textarea = document.createElement("textarea");
      textarea.id = "current-" + type;
      textarea.rows = 10;
      textarea.value = current;
      editorContainer.appendChild(textarea);
    }
  }

  function renderContent(
    reports: { rmp: Report; timeline: Report },
    pipelineRunning: boolean
  ): void {
    currentReports = reports;
    rmpSegments = [];
    rmpKept = [];
    timelineSegments = [];
    timelineKept = [];
    const rmp = reports.rmp;
    const timeline = reports.timeline;
    const rmpPending = !!rmp.pending_content;
    const timelinePending = !!timeline.pending_content;

    main.innerHTML = `
      <div class="section">
        <h2 class="report-view-title">Source files / RMP &amp; Timeline</h2>
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

    const draftRmp = document.getElementById("draft-area-rmp")!;
    const draftTimeline = document.getElementById("draft-area-timeline")!;
    const streamRmp = document.getElementById("stream-rmp")!;
    const streamTimeline = document.getElementById("stream-timeline")!;
    const draftPageRmp = document.getElementById("draft-page-rmp");
    const draftPageTimeline = document.getElementById("draft-page-timeline");

    function applyDocMargins(prefix: "rmp" | "timeline"): void {
      const m = getMarginInputs(prefix + "-");
      const el = prefix === "rmp" ? draftPageRmp : draftPageTimeline;
      if (m && el) {
        const px = (inch: number) => Math.round(inch * 96);
        el.style.padding = `${px(m.top)}px ${px(m.right)}px ${px(m.bottom)}px ${px(m.left)}px`;
        setStoredMargins(missionId, prefix, m);
      }
    }
    for (const prefix of ["rmp", "timeline"] as const) {
      const stored = getStoredMargins(missionId, prefix);
      for (const k of ["top", "right", "bottom", "left"] as const) {
        const inp = document.getElementById(prefix + "-margin-" + k) as HTMLInputElement | null;
        if (inp) inp.value = String(stored[k]);
      }
      applyDocMargins(prefix);
      for (const k of ["top", "right", "bottom", "left"] as const) {
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
      function refreshAfterResume(): void {
        if (resumeFinalized) return;
        resumeFinalized = true;
        stopDocsJobPoll?.();
        stopDocsJobPoll = null;
        try {
          hiddenRmp.remove();
          hiddenTimeline.remove();
        } catch (_) {}
        fetchReports()
          .then((r) => {
            destroyAllReportEditors();
            setTimeout(() => {
              try {
                renderContent(r, false);
              } catch (e) {
                console.error(e);
                alert("Failed to render reports after update.");
              }
            }, 0);
          })
          .catch((err: unknown) => {
            const msg = err instanceof Error ? err.message : String(err);
            alert(msg || "Failed to load reports after update.");
          });
      }
      get<{ jobs: PipelineJobRow[] }>("/missions/" + missionId + "/pipeline-jobs?limit=1")
        .then((data) => {
          const row = data.jobs?.[0];
          if (row?.id && (row.status === "running" || row.status === "queued")) {
            stopDocsJobPoll = pollPipelineJobUntilTerminal(missionId, row.id, (j) => {
              if (resumeFinalized) return;
              if (j.status === "failed") {
                resumeFinalized = true;
                stopDocsJobPoll?.();
                stopDocsJobPoll = null;
                try {
                  hiddenRmp.remove();
                  hiddenTimeline.remove();
                } catch (_) {}
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
        .catch(() => {});
      const initialRmp = (rmp.current_content ?? "").trim() || "";
      const initialTimeline = (timeline.current_content ?? "").trim() || "";
      closeRmp = connectStream(missionId, "rmp", hiddenRmp, undefined, (content) => {
        const merged = mergeLlmIntoDraft(initialRmp, content);
        const html = mergedToDisplayHtml(merged);
        getReportEditor("report-editor-rmp")?.setContent(html);
      });
      closeTimeline = connectStream(missionId, "timeline", hiddenTimeline, undefined, (content) => {
        const merged = mergeLlmIntoDraft(initialTimeline, content);
        const html = mergedToDisplayHtml(merged);
        getReportEditor("report-editor-timeline")?.setContent(html);
      });
    } else {
      if (rmpPending) {
        document.querySelector(".btn-accept-rmp")?.addEventListener("click", () => {
          post("/missions/" + missionId + "/reports/rmp/accept").then(() =>
            fetchReports().then((r) => renderContent(r, false)).catch((err: unknown) =>
              alert(err instanceof Error ? err.message : "Failed to load reports.")
            )
          );
        });
        document.querySelector(".btn-reject-rmp")?.addEventListener("click", () => {
          post("/missions/" + missionId + "/reports/rmp/reject").then(() =>
            fetchReports().then((r) => renderContent(r, false)).catch((err: unknown) =>
              alert(err instanceof Error ? err.message : "Failed to load reports.")
            )
          );
        });
        document.querySelector(".btn-apply-rmp")?.addEventListener("click", () => {
          const segs = rmpSegments.length ? rmpSegments : (computeDiffSegments(rmp.current_content ?? "", rmp.pending_content ?? "") as DiffSegment[]);
          const n = segs.filter((s) => s.type === "change").length;
          const kept = rmpKept.length === n ? rmpKept : Array(n).fill(true);
          const merged = n === 0 ? (rmp.pending_content ?? rmp.current_content ?? "") : buildMergedFromSegments(segs, kept);
          const margins = getMarginInputs("rmp-");
          const body = margins ? { content: merged, margins } : { content: merged };
          post("/missions/" + missionId + "/reports/rmp/save", body)
            .then(() => post("/missions/" + missionId + "/reports/rmp/reject"))
            .then(() =>
              fetchReports().then((r) => renderContent(r, false)).catch((err: unknown) =>
                alert(err instanceof Error ? err.message : "Failed to load reports.")
              )
            )
            .catch((err: Error) => alert(err.message || "Failed to apply"));
        });
      }
      if (timelinePending) {
        document.querySelector(".btn-accept-timeline")?.addEventListener("click", () => {
          post("/missions/" + missionId + "/reports/timeline/accept").then(() =>
            fetchReports().then((r) => renderContent(r, false)).catch((err: unknown) =>
              alert(err instanceof Error ? err.message : "Failed to load reports.")
            )
          );
        });
        document.querySelector(".btn-reject-timeline")?.addEventListener("click", () => {
          post("/missions/" + missionId + "/reports/timeline/reject").then(() =>
            fetchReports().then((r) => renderContent(r, false)).catch((err: unknown) =>
              alert(err instanceof Error ? err.message : "Failed to load reports.")
            )
          );
        });
        document.querySelector(".btn-apply-timeline")?.addEventListener("click", () => {
          const segs = timelineSegments.length ? timelineSegments : (computeDiffSegments(timeline.current_content ?? "", timeline.pending_content ?? "") as DiffSegment[]);
          const n = segs.filter((s) => s.type === "change").length;
          const kept = timelineKept.length === n ? timelineKept : Array(n).fill(true);
          const merged = n === 0 ? (timeline.pending_content ?? timeline.current_content ?? "") : buildMergedFromSegments(segs, kept);
          const margins = getMarginInputs("timeline-");
          const body = margins ? { content: merged, margins } : { content: merged };
          post("/missions/" + missionId + "/reports/timeline/save", body)
            .then(() => post("/missions/" + missionId + "/reports/timeline/reject"))
            .then(() =>
              fetchReports().then((r) => renderContent(r, false)).catch((err: unknown) =>
                alert(err instanceof Error ? err.message : "Failed to load reports.")
              )
            )
            .catch((err: Error) => alert(err.message || "Failed to apply"));
        });
      }
    }

    document.getElementById("btn-run-pipeline-docs")!.addEventListener("click", () => {
      const runBtn = document.getElementById("btn-run-pipeline-docs") as HTMLButtonElement | null;
      const fullRefreshEl = document.getElementById("chk-full-refresh-pipeline") as HTMLInputElement | null;
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
      function cleanupRunUi(): void {
        try {
          hiddenRmp.remove();
          hiddenTimeline.remove();
          updatingPill.remove();
        } catch (_) {}
        if (runBtn) {
          runBtn.disabled = false;
          runBtn.textContent = "Run pipeline now (all reports)";
        }
      }
      function finalizeRunSuccess(): void {
        if (finalized) return;
        finalized = true;
        stopDocsJobPoll?.();
        stopDocsJobPoll = null;
        closeRmp?.();
        closeTimeline?.();
        cleanupRunUi();
        fetchReports()
          .then((r) => {
            destroyAllReportEditors();
            setTimeout(() => {
              try {
                renderContent(r, false);
              } catch (e) {
                console.error(e);
                alert("Failed to render reports after update.");
              }
            }, 0);
          })
          .catch((err: unknown) => {
            const msg = err instanceof Error ? err.message : String(err);
            alert(msg || "Failed to load reports after update.");
          });
      }
      function finalizeRunFailure(msg: string): void {
        if (finalized) return;
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
        getReportEditor("report-editor-rmp")?.setContent(html);
      });
      closeTimeline = connectStream(missionId, "timeline", hiddenTimeline, undefined, (content) => {
        const merged = mergeLlmIntoDraft(initialTimeline, content);
        const html = mergedToDisplayHtml(merged);
        getReportEditor("report-editor-timeline")?.setContent(html);
      });
      const runBody: { mission_id: string; update_intent?: string } = { mission_id: missionId };
      if (fullRefreshEl?.checked === true) {
        runBody.update_intent = "full_refresh";
      }
      post<{ ok: boolean; job_id?: string }>("/run-pipeline", runBody)
        .then((res) => {
          if (res.job_id) {
            stopDocsJobPoll = pollPipelineJobUntilTerminal(missionId, res.job_id, (j) => {
              if (finalized) return;
              if (j.status === "failed") {
                const fk = j.failure_kind ? String(j.failure_kind) + ": " : "";
                finalizeRunFailure(fk + (j.error_message || "Pipeline failed"));
                return;
              }
              if (j.status === "completed") {
                finalizeRunSuccess();
              }
            });
          } else {
            finalizeRunFailure("No job id returned; cannot track pipeline status.");
          }
        })
        .catch((err: Error) => {
          closeRmp?.();
          closeTimeline?.();
          stopDocsJobPoll?.();
          stopDocsJobPoll = null;
          try {
            updatingPill.remove();
          } catch (_) {}
          if (runBtn) {
            runBtn.disabled = false;
            runBtn.textContent = "Run pipeline now (all reports)";
          }
          alert(err.message || "Failed to start pipeline");
        });
    });
  }

  get<Mission>("/missions/" + missionId)
    .then((m) => {
      mission = m;
      return get<StatusResponse>("/status");
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

function renderMissionHub(main: HTMLElement): void {
  const u = currentUser!;
  main.innerHTML = `
    <div class="hub-page">
      ${renderHubTopbarHtml(u)}
      <div class="hub-shell">
        <section class="hub-mission-control glass" aria-labelledby="hub-hero-heading">
          <header class="hub-mission-control-head">
            <h2 id="hub-hero-heading" class="hub-hero-title">Mission Control</h2>
            <p class="hub-hero-sub caption">Open an existing mission or create a new one.</p>
            <label class="hub-search-label" for="hub-search">Search missions</label>
            <input type="search" id="hub-search" class="hub-search" placeholder="Filter by name or id…" autocomplete="off" />
          </header>
          <div class="hub-grid-scroll">
            <div id="hub-mission-grid" class="hub-grid" aria-live="polite"></div>
          </div>
        </section>
      </div>
    </div>`;

  wireHubTopbarListeners(main);

  get<Mission[]>("/missions")
    .then((missions) => {
      const hubGrid = document.getElementById("hub-mission-grid");
      const search = document.getElementById("hub-search") as HTMLInputElement | null;
      if (!hubGrid) return;
      const gridEl: HTMLElement = hubGrid;
      const all = missions.slice();
      let filtered = all.slice();

      function refetchMissions(): void {
        get<Mission[]>("/missions")
          .then((list) => {
            all.length = 0;
            all.push(...list);
            const q = search?.value.trim().toLowerCase() ?? "";
            filtered = q
              ? all.filter((m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q))
              : all.slice();
            paint();
          })
          .catch(() => {
            /* keep existing grid */
          });
      }

      function paint(): void {
        gridEl.innerHTML = "";
        for (const m of filtered) {
          const op = typeof m.operator_count === "number" ? m.operator_count : 0;
          const canManage = u.is_admin || (m.membership_role || "").toLowerCase() === "mel";
          const isArchived = (m.lifecycle_status || "active").toLowerCase() === "archived";
          const card = document.createElement("article");
          card.className = "hub-card hub-card--mission glass";
          const headActions = canManage
            ? `<div class="hub-card-head-actions">
              <div class="hub-card-meta" title="Operator count">${op}<span class="hub-card-people" aria-hidden="true"> 👤</span></div>
              <div class="hub-card-menu-wrap">
                <button type="button" class="hub-card-menu-btn" aria-label="Mission actions" aria-expanded="false" aria-haspopup="true"><span aria-hidden="true">⋯</span></button>
                <div class="hub-card-menu-dropdown" role="menu" hidden>
                  <button type="button" role="menuitem" class="hub-card-menu-item"${isArchived ? " disabled" : ""} data-action="archive">Archive mission</button>
                  <button type="button" role="menuitem" class="hub-card-menu-item hub-card-menu-item--danger" data-action="delete">Delete mission</button>
                </div>
              </div>
            </div>`
            : `<div class="hub-card-meta" title="Operator count">${op}<span class="hub-card-people" aria-hidden="true"> 👤</span></div>`;
          card.innerHTML = `
            <div class="hub-card-head">
              <div class="hub-card-titles">
                <h3 class="hub-card-name">${escapeHtml(m.name)}</h3>
                <p class="hub-card-id">${escapeHtml(m.id)}</p>
              </div>
              ${headActions}
            </div>
            <p class="hub-card-active">Active: ${formatHubDate(m.start_date)} — ${formatHubDate(m.end_date)}</p>
            <button type="button" class="btn btn-primary hub-card-open">Open Mission</button>`;
          card.querySelector(".hub-card-open")!.addEventListener("click", () => {
            navigate("/mission/" + m.id + "/overview");
            render();
          });
          if (canManage) {
            const trigger = card.querySelector(".hub-card-menu-btn") as HTMLButtonElement | null;
            const dropdown = card.querySelector(".hub-card-menu-dropdown") as HTMLElement | null;
            trigger?.addEventListener("click", (e) => {
              e.preventDefault();
              e.stopPropagation();
              const wasOpen = dropdown?.classList.contains("is-open");
              closeHubMissionMenus();
              if (!wasOpen && dropdown && trigger) {
                dropdown.classList.add("is-open");
                dropdown.removeAttribute("hidden");
                trigger.setAttribute("aria-expanded", "true");
                requestAnimationFrame(() => {
                  document.addEventListener(
                    "click",
                    () => {
                      closeHubMissionMenus();
                    },
                    { once: true }
                  );
                });
              }
            });
            card.querySelector('[data-action="archive"]')?.addEventListener("click", (ev) => {
              ev.stopPropagation();
              if (isArchived) return;
              closeHubMissionMenus();
              patch("/missions/" + encodeURIComponent(m.id) + "/metadata", { lifecycle_status: "archived" })
                .then(() => refetchMissions())
                .catch((err: unknown) => {
                  alert(err instanceof Error ? err.message : "Archive failed");
                });
            });
            card.querySelector('[data-action="delete"]')?.addEventListener("click", (ev) => {
              ev.stopPropagation();
              closeHubMissionMenus();
              const ok = confirm(
                `Delete mission "${m.name}" permanently? This removes its data from the database. Team members who belong only to this mission will have their accounts removed. Admin accounts are never deleted. Source/output folders on disk are not removed.`
              );
              if (!ok) return;
              httpDelete("/missions/" + encodeURIComponent(m.id))
                .then(() => refetchMissions())
                .catch((err: unknown) => {
                  alert(err instanceof Error ? err.message : "Delete failed");
                });
            });
          }
          gridEl.appendChild(card);
        }
        const newBtn = document.createElement("button");
        newBtn.type = "button";
        newBtn.className = "hub-card hub-card--new glass";
        newBtn.innerHTML =
          '<span class="hub-card-plus" aria-hidden="true">+</span><span class="hub-card-new-title">New Mission</span><span class="hub-card-new-cta">Create new mission</span>';
        newBtn.addEventListener("click", () => {
          navigate("/new");
          render();
        });
        gridEl.appendChild(newBtn);
      }

      paint();
      search?.addEventListener("input", () => {
        const q = search.value.trim().toLowerCase();
        filtered = q ? all.filter((m) => m.name.toLowerCase().includes(q) || m.id.toLowerCase().includes(q)) : all.slice();
        paint();
      });
    })
    .catch(() => {
      const grid = document.getElementById("hub-mission-grid");
      if (grid) grid.innerHTML = '<p class="error">Failed to load missions</p>';
    });
}

function renderAdminDebug(main: HTMLElement): void {
  if (!currentUser?.is_admin) {
    main.innerHTML = '<p class="error">Administrator access only.</p>';
    return;
  }
  get<Record<string, unknown>>("/debug/global")
    .then((snap) => {
      main.innerHTML = `<div class="section glass"><h2>Global debug</h2><pre class="caption" style="white-space: pre-wrap;">${escapeHtml(
        JSON.stringify(snap, null, 2)
      )}</pre></div>`;
    })
    .catch(() => {
      main.innerHTML = '<p class="error">Could not load debug snapshot.</p>';
    });
}

function render(): void {
  const main = document.getElementById("main")!;
  const parts = getHashParts();
  const listEl = document.getElementById("mission-list")!;
  const strip = document.getElementById("auth-strip");
  const appShell = document.querySelector(".app");

  stopOverviewPresence();
  missionOverviewEpoch++;

  if (currentUser && parts[0] === "login") {
    appShell?.classList.remove("app-login");
    navigate("/");
    return;
  }

  if (!currentUser) {
    if (parts[0] !== "login") {
      appShell?.classList.remove("app-login");
      navigate("/login");
      return;
    }
    appShell?.classList.add("app-login");
    if (strip) strip.innerHTML = "";
    renderLoginPage(main);
    listEl.innerHTML = "";
    return;
  }

  appShell?.classList.remove("app-login");
  setMissionWorkspaceMode(false);

  if (parts[0] === "admin" && parts[1] === "debug") {
    setAppHubMode(false);
    renderAdminDebug(main);
    renderMissionList(listEl, null, null);
    return;
  }

  if (parts[0] === "settings") {
    setAppHubMode(false);
    renderMissionList(listEl, null, null);
    main.innerHTML = `<div class="section glass hub-settings-stub">
      <h2>Settings</h2>
      <p class="caption">Coming soon.</p>
      <p><a href="#/">Back to home</a></p>
    </div>`;
    return;
  }

  if (parts[0] === "new") {
    setAppHubMode(true);
    if (strip) strip.innerHTML = "";
    listEl.innerHTML = "";
    renderNewMissionForm(main);
    return;
  }

  if (parts[0] === "mission" && parts[1]) {
    setAppHubMode(false);
    setMissionWorkspaceMode(true);
    currentReportCleanup?.();
    currentReportCleanup = null;
    const missionId = parts[1];
    const sub = parts[2] || "overview";
    expandedMissions.add(missionId);
    if (strip) strip.innerHTML = "";
    listEl.innerHTML = "";
    renderMissionWorkspaceShell(main, missionId, sub);
    const workspaceBody = document.getElementById("mission-workspace-body")!;
    if (sub === "documents") {
      renderDocumentsView(missionId, workspaceBody);
    } else if ((REPORT_TYPES as readonly string[]).includes(sub)) {
      renderReportView(missionId, sub as ReportType, workspaceBody);
    } else {
      renderMissionOverview(missionId, workspaceBody);
    }
    return;
  }

  if (!parts.length) {
    if (canAccessMissionHub()) {
      setAppHubMode(true);
      if (strip) strip.innerHTML = "";
      listEl.innerHTML = "";
      renderMissionHub(main);
    } else {
      setAppHubMode(false);
      listEl.innerHTML = "";
      if (strip && currentUser) {
        strip.innerHTML = `<span>${escapeHtml(currentUser.username)}</span> · <button type="button" class="btn btn-sm" id="btn-logout">Log out</button>${
          currentUser.is_admin
            ? ` · <a href="#/admin/debug" id="link-admin-debug">Debug</a>`
            : ""
        }`;
        document.getElementById("btn-logout")?.addEventListener("click", () => {
          post("/auth/logout", {}).finally(() => {
            currentUser = null;
            stopOverviewPresence();
            navigate("/login");
          });
        });
        document.getElementById("link-admin-debug")?.addEventListener("click", (e) => {
          e.preventDefault();
          navigate("/admin/debug");
          render();
        });
      }
      main.innerHTML = '<div id="view-placeholder"><p class="empty">Loading…</p></div>';
      get<Mission[]>("/missions")
        .then((missions) => {
          if (getHashParts().length !== 0 || !currentUser || canAccessMissionHub()) return;
          if (missions.length > 0) {
            // First list entry = newest mission for this user (server orders by created_at DESC).
            navigate("/mission/" + encodeURIComponent(missions[0].id) + "/overview");
            return;
          }
          main.innerHTML =
            '<div id="view-placeholder"><p class="empty">You don’t have access to any missions. Contact your administrator if this is unexpected.</p></div>';
        })
        .catch(() => {
          if (getHashParts().length !== 0 || !currentUser || canAccessMissionHub()) return;
          main.innerHTML =
            '<div id="view-placeholder"><p class="error">Could not load your missions. Try again later or contact an administrator.</p></div>';
        });
    }
    return;
  }

  setAppHubMode(false);
  renderMissionList(listEl, null, null);
  main.innerHTML = '<div id="view-placeholder"><p class="empty">Select a mission or create one.</p></div>';
}

// ---------- Init ----------

const SIDEBAR_COLLAPSED_KEY = "sidebarCollapsed";

function applySidebarCollapsed(collapsed: boolean): void {
  const app = document.querySelector(".app");
  const btn = document.getElementById("sidebar-toggle");
  if (app) app.classList.toggle("sidebar-collapsed", collapsed);
  if (btn) {
    btn.setAttribute("aria-expanded", String(!collapsed));
    btn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    btn.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");
  }
}

function initSidebarToggle(): void {
  const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
  if (stored === "true") applySidebarCollapsed(true);

  const btn = document.getElementById("sidebar-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const app = document.querySelector(".app");
    const currentlyCollapsed = app?.classList.contains("sidebar-collapsed") ?? false;
    const collapsed = !currentlyCollapsed;
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
    applySidebarCollapsed(collapsed);
  });
}

document.getElementById("btn-new-mission")!.addEventListener("click", () => {
  navigate("/new");
  render();
});

initSidebarToggle();

function updateSidebarStatus(): void {
  if (!currentUser) {
    setTimeout(updateSidebarStatus, 5000);
    return;
  }
  get<StatusResponse>("/status")
    .then((s) => {
      const el = document.getElementById("sidebar-status")!;
      if (s.running_mission_id) el.textContent = "Pipeline running…";
      else el.textContent = "";
    })
    .catch(() => {});
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
async function boot(): Promise<void> {
  try {
    const r = await fetch(API + "/auth/me", { credentials: "include" });
    if (r.ok) {
      currentUser = (await r.json()) as NonNullable<typeof currentUser>;
    } else {
      currentUser = null;
    }
  } catch {
    currentUser = null;
  }
  let redirectedToLogin = false;
  if (!currentUser && getHashParts()[0] !== "login") {
    navigate("/login");
    redirectedToLogin = true;
  }
  if (!redirectedToLogin) {
    render();
  }
  updateSidebarStatus();
}

boot();
