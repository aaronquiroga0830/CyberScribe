/**
 * Phase 2–3 — Tiptap / ProseMirror report editor + inline assist (in-document pending AI).
 * HTML in / out for existing save + DOCX pipeline (8.5).
 */
import type { AnyExtension } from "@tiptap/core";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import { TextStyle } from "@tiptap/extension-text-style";
import FontFamily from "@tiptap/extension-font-family";
import Color from "@tiptap/extension-color";
import Image from "@tiptap/extension-image";
import { Table, TableRow, TableHeader, TableCell } from "@tiptap/extension-table";
import Placeholder from "@tiptap/extension-placeholder";
import { ReportSection } from "./report-section-extension";
import { editorHasPendingAssist, InlineAssistPending } from "./inline-assist-pending";
import {
  buildAnchorPayload,
  ReportCommentHighlight,
  stripReportCommentSpansFromHtml,
} from "./report-comment-extension";

export interface ReportEditorHandle {
  root: HTMLElement;
  getHtml: () => string;
  /** ProseMirror document JSON string (dual-write to server). */
  getJson: () => string;
  destroy: () => void;
  setContent: (html: string) => void;
  /** True while an inline AI proposal is in the document (Accept/Reject in the doc first). */
  hasPendingAssist: () => boolean;
  /** ProseMirror editor; null after destroy(). */
  getEditor: () => Editor | null;
}

const handles = new Map<string, ReportEditorHandle>();

/** Phase 3: request/response for POST .../inline-assist */
export type InlineAssistRequest = {
  action: string;
  selection: string;
  before_cursor: string;
  after_cursor: string;
  /** Full report HTML for server-side duplication / grounding checks (optional). */
  current_draft_html?: string;
};

export type InlineAssistEvidenceChunk = {
  chunk_id: string;
  source: string;
};

export type InlineAssistResponse = {
  suggestion: string;
  evidence_sources?: string[];
  evidence_chunks?: InlineAssistEvidenceChunk[];
  grounding_warnings?: string[];
};

export type InlineAssistRunner = (req: InlineAssistRequest) => Promise<InlineAssistResponse>;

export type DocumentCommentsCallbacks = {
  onOpenComposer: (ctx: { from: number; to: number; quote: string; sectionKey?: string }) => void;
};

export type ReportEditorOptions = {
  /** When set, shows selection bubble + cursor assist row; suggestions apply only after Accept. */
  inlineAssist?: { run: InlineAssistRunner };
  /** Selection “Comment” bubble → open gutter composer in app. */
  documentComments?: DocumentCommentsCallbacks;
};

function escapeHtmlText(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Turn model plain text into safe HTML fragments for insertContent. */
function suggestionToHtmlFragment(text: string): string {
  const t = (text || "").trim();
  if (!t) return "<p></p>";
  const lines = t.split(/\n/);
  const bulletLines = lines.filter((l) => /^\s*[-*•]\s+/.test(l));
  if (bulletLines.length >= 2 && bulletLines.length === lines.filter((l) => l.trim()).length) {
    const items = lines
      .map((l) => l.replace(/^\s*[-*•]\s+/, "").trim())
      .filter(Boolean)
      .map((l) => `<li><p>${escapeHtmlText(l)}</p></li>`)
      .join("");
    return `<ul>${items}</ul>`;
  }
  const paras = t.split(/\n\n+/).map((p) => p.trim()).filter(Boolean);
  if (paras.length === 0) return "<p></p>";
  return paras.map((p) => `<p>${escapeHtmlText(p).replace(/\n/g, "<br>")}</p>`).join("");
}

function readAssistContext(editor: Editor): {
  from: number;
  to: number;
  selection: string;
  before_cursor: string;
  after_cursor: string;
} {
  const { from, to } = editor.state.selection;
  const doc = editor.state.doc;
  const selection = from === to ? "" : doc.textBetween(from, to, "\n");
  const before_cursor = doc.textBetween(Math.max(0, from - 8000), from, "\n");
  const after_cursor = doc.textBetween(from, Math.min(doc.content.size, from + 2000), "\n");
  return { from, to, selection, before_cursor, after_cursor };
}

function attachDocumentCommentBubble(
  editor: Editor,
  _wrap: HTMLElement,
  callbacks: DocumentCommentsCallbacks
): () => void {
  const bubble = document.createElement("div");
  bubble.className = "tiptap-comment-bubble";
  bubble.style.display = "none";
  bubble.setAttribute("role", "toolbar");
  bubble.addEventListener("mousedown", (e) => e.preventDefault());
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "tiptap-tb-btn";
  btn.textContent = "Comment";
  btn.title = "Comment on selection";
  bubble.appendChild(btn);
  document.body.appendChild(bubble);

  function positionBubble(): void {
    const { from, to } = editor.state.selection;
    if (from === to || !editor.isEditable) {
      bubble.style.display = "none";
      return;
    }
    try {
      const c1 = editor.view.coordsAtPos(from);
      const c2 = editor.view.coordsAtPos(to);
      const left = (c1.left + c2.right) / 2;
      const top = Math.max(c1.bottom, c2.bottom) + 8;
      bubble.style.position = "fixed";
      bubble.style.left = `${left}px`;
      bubble.style.top = `${top}px`;
      bubble.style.transform = "translateX(-50%)";
      bubble.style.display = "flex";
      bubble.style.zIndex = "101";
      bubble.style.gap = "0.35rem";
      bubble.style.alignItems = "center";
    } catch {
      bubble.style.display = "none";
    }
  }

  btn.addEventListener("click", (e) => {
    e.preventDefault();
    const { from, to } = editor.state.selection;
    if (from === to) return;
    const payload = buildAnchorPayload(editor, from, to);
    callbacks.onOpenComposer({
      from,
      to,
      quote: payload.quote ?? "",
      ...(payload.sectionKey ? { sectionKey: payload.sectionKey } : {}),
    });
  });

  editor.on("selectionUpdate", positionBubble);
  editor.on("transaction", positionBubble);
  const onScroll = (): void => {
    positionBubble();
  };
  window.addEventListener("scroll", onScroll, true);

  return () => {
    editor.off("selectionUpdate", positionBubble);
    editor.off("transaction", positionBubble);
    window.removeEventListener("scroll", onScroll, true);
    bubble.remove();
  };
}

/**
 * Bubble (selection actions) + dock (cursor actions). Proposals appear in-document with Accept/Reject widget.
 */
function attachInlineAssist(editor: Editor, wrap: HTMLElement, runner: InlineAssistRunner): () => void {
  let busy = false;

  const bubble = document.createElement("div");
  bubble.className = "tiptap-assist-bubble";
  bubble.setAttribute("role", "toolbar");
  bubble.style.display = "none";
  bubble.addEventListener("mousedown", (e) => e.preventDefault());

  const sel = document.createElement("select");
  sel.className = "tiptap-tb-select tiptap-assist-select";
  sel.title = "AI assist on selection";
  sel.innerHTML = `
    <option value="">Assist selection…</option>
    <option value="rewrite">Rewrite</option>
    <option value="shorten">Shorten</option>
    <option value="expand">Expand</option>
    <option value="formalize">Formalize</option>
    <option value="operationalize">Operationalize</option>
    <option value="to_bullets">→ Bullets</option>
    <option value="to_paragraph">→ Paragraph</option>
  `;
  const runSelBtn = document.createElement("button");
  runSelBtn.type = "button";
  runSelBtn.className = "tiptap-tb-btn";
  runSelBtn.textContent = "Run";
  runSelBtn.title = "Run assist on selected text";
  bubble.appendChild(sel);
  bubble.appendChild(runSelBtn);

  const dock = document.createElement("div");
  dock.className = "tiptap-assist-dock";
  const dockLabel = document.createElement("span");
  dockLabel.className = "tiptap-assist-dock-label";
  dockLabel.textContent = "Cursor assist";
  dock.appendChild(dockLabel);
  const addDock = (label: string, action: string, title: string): void => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tiptap-tb-btn";
    b.textContent = label;
    b.title = title;
    b.addEventListener("click", (e) => {
      e.preventDefault();
      void runCursorAction(action);
    });
    dock.appendChild(b);
  };
  addDock("Next sentence", "suggest_next_sentence", "Suggest one sentence after the cursor");
  addDock("New ¶", "insert_paragraph", "Insert a short new paragraph after the cursor");
  addDock("Fill placeholder", "fill_placeholder", "Suggest text for [brackets] / placeholders near cursor");

  const statusRow = document.createElement("div");
  statusRow.className = "tiptap-assist-status caption";
  statusRow.style.display = "none";
  dock.appendChild(statusRow);
  let statusTimer: ReturnType<typeof setTimeout> | null = null;

  function showAssistStatus(message: string, kind: "error" | "info" | "warn"): void {
    if (statusTimer) {
      clearTimeout(statusTimer);
      statusTimer = null;
    }
    statusRow.textContent = message;
    statusRow.style.display = "block";
    if (kind === "error") {
      statusRow.style.color = "var(--danger, #c62828)";
    } else if (kind === "warn") {
      statusRow.style.color = "var(--warning, #b45309)";
    } else {
      statusRow.style.color = "";
    }
    statusTimer = setTimeout(() => {
      statusRow.style.display = "none";
      statusRow.textContent = "";
      statusTimer = null;
    }, 6000);
  }

  function setBusy(v: boolean): void {
    busy = v;
    runSelBtn.disabled = v;
    sel.disabled = v;
    dock.querySelectorAll("button").forEach((btn) => {
      (btn as HTMLButtonElement).disabled = v;
    });
  }

  function positionBubble(): void {
    const { from, to } = editor.state.selection;
    if (from === to || !editor.isEditable) {
      bubble.style.display = "none";
      return;
    }
    try {
      const c1 = editor.view.coordsAtPos(from);
      const c2 = editor.view.coordsAtPos(to);
      const left = (c1.left + c2.right) / 2;
      const top = Math.min(c1.top, c2.top);
      bubble.style.position = "fixed";
      bubble.style.left = `${left}px`;
      bubble.style.top = `${top - 4}px`;
      bubble.style.transform = "translate(-50%, -100%)";
      bubble.style.display = "flex";
      bubble.style.zIndex = "100";
    } catch {
      bubble.style.display = "none";
    }
  }

  async function runSelectionAction(action: string): Promise<void> {
    const { from, to, selection, before_cursor, after_cursor } = readAssistContext(editor);
    if (!action || from === to) return;
    editor.chain().focus().clearInlineAssistPending().run();
    setBusy(true);
    showAssistStatus("Assist running…", "info");
    try {
      const res = await runner({
        action,
        selection,
        before_cursor,
        after_cursor,
        current_draft_html: editor.getHTML(),
      });
      statusRow.style.display = "none";
      const html = suggestionToHtmlFragment(res.suggestion);
      editor
        .chain()
        .focus()
        .applyInlineAssistPending({
          kind: "replace",
          html,
          replaceFrom: from,
          replaceTo: to,
          evidence: res.evidence_sources ?? [],
        })
        .run();
      if (res.grounding_warnings?.length) {
        showAssistStatus(res.grounding_warnings.join(" "), "warn");
      }
    } catch (e) {
      showAssistStatus(e instanceof Error ? e.message : "Assist failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function runCursorAction(action: string): Promise<void> {
    editor.chain().focus().run();
    editor.chain().focus().clearInlineAssistPending().run();
    const { selection, before_cursor, after_cursor } = readAssistContext(editor);
    setBusy(true);
    showAssistStatus("Assist running…", "info");
    try {
      const res = await runner({
        action,
        selection,
        before_cursor,
        after_cursor,
        current_draft_html: editor.getHTML(),
      });
      statusRow.style.display = "none";
      const html = suggestionToHtmlFragment(res.suggestion);
      editor
        .chain()
        .focus()
        .applyInlineAssistPending({
          kind: "insert",
          html,
          replaceFrom: null,
          replaceTo: null,
          evidence: res.evidence_sources ?? [],
        })
        .run();
      if (res.grounding_warnings?.length) {
        showAssistStatus(res.grounding_warnings.join(" "), "warn");
      }
    } catch (e) {
      showAssistStatus(e instanceof Error ? e.message : "Assist failed", "error");
    } finally {
      setBusy(false);
    }
  }

  runSelBtn.addEventListener("click", (e) => {
    e.preventDefault();
    const action = sel.value;
    if (action) void runSelectionAction(action);
  });

  const onSelUpdate = (): void => {
    positionBubble();
  };
  const onScroll = (): void => {
    positionBubble();
  };

  editor.on("selectionUpdate", onSelUpdate);
  window.addEventListener("scroll", onScroll, true);

  const toolbarEl = wrap.querySelector(".tiptap-toolbar");
  const pageShell = wrap.querySelector(".tiptap-page-shell");
  if (toolbarEl) {
    toolbarEl.insertAdjacentElement("afterend", dock);
  } else if (pageShell) {
    wrap.insertBefore(dock, pageShell);
  } else {
    wrap.prepend(dock);
  }
  document.body.appendChild(bubble);

  return () => {
    if (statusTimer) clearTimeout(statusTimer);
    editor.off("selectionUpdate", onSelUpdate);
    window.removeEventListener("scroll", onScroll, true);
    bubble.remove();
    dock.remove();
  };
}

function normalizeInitialHtml(raw: string): string {
  const t = (raw || "").trim();
  if (!t) return "<p></p>";
  if (/^\s*</.test(t)) return t;
  const text = t
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const paras = text.split(/\n/).filter((s) => s.length > 0);
  return paras.length ? paras.map((s) => `<p>${s}</p>`).join("") : "<p></p>";
}

function buildToolbar(editor: Editor): HTMLElement {
  const bar = document.createElement("div");
  bar.className = "tiptap-toolbar";

  const addBtn = (label: string, title: string, onClick: () => void): void => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "tiptap-tb-btn";
    b.textContent = label;
    b.title = title;
    b.addEventListener("click", (e) => {
      e.preventDefault();
      onClick();
    });
    bar.appendChild(b);
  };

  const sep = (): void => {
    const s = document.createElement("span");
    s.className = "tiptap-tb-sep";
    s.textContent = "|";
    bar.appendChild(s);
  };

  addBtn("B", "Bold", () => editor.chain().focus().toggleBold().run());
  addBtn("I", "Italic", () => editor.chain().focus().toggleItalic().run());
  addBtn("U", "Underline", () => editor.chain().focus().toggleUnderline().run());
  sep();
  addBtn("H1", "Heading 1", () => editor.chain().focus().toggleHeading({ level: 1 }).run());
  addBtn("H2", "Heading 2", () => editor.chain().focus().toggleHeading({ level: 2 }).run());
  addBtn("H3", "Heading 3", () => editor.chain().focus().toggleHeading({ level: 3 }).run());
  addBtn("¶", "Paragraph", () => editor.chain().focus().setParagraph().run());
  sep();
  addBtn("•", "Bullet list", () => editor.chain().focus().toggleBulletList().run());
  addBtn("1.", "Ordered list", () => editor.chain().focus().toggleOrderedList().run());
  addBtn("→", "Indent", () => editor.chain().focus().sinkListItem("listItem").run());
  addBtn("←", "Outdent", () => editor.chain().focus().liftListItem("listItem").run());
  sep();
  addBtn("❝", "Blockquote", () => editor.chain().focus().toggleBlockquote().run());
  addBtn("</>", "Code block", () => editor.chain().focus().toggleCodeBlock().run());
  sep();
  addBtn("↶", "Undo", () => editor.chain().focus().undo().run());
  addBtn("↷", "Redo", () => editor.chain().focus().redo().run());
  sep();
  addBtn("▦", "Insert table", () =>
    editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
  );
  addBtn("🖼", "Image from URL", () => {
    const u = window.prompt("Image URL");
    if (u) editor.chain().focus().setImage({ src: u.trim() }).run();
  });
  sep();

  const font = document.createElement("select");
  font.className = "tiptap-tb-select";
  font.title = "Font";
  font.innerHTML = `
    <option value="">Font</option>
    <option value="Georgia, serif">Serif</option>
    <option value="system-ui, sans-serif">Sans</option>
    <option value="ui-monospace, monospace">Mono</option>
  `;
  font.addEventListener("change", () => {
    const v = font.value;
    if (v) editor.chain().focus().setFontFamily(v).run();
    else editor.chain().focus().unsetFontFamily().run();
  });
  bar.appendChild(font);

  const color = document.createElement("input");
  color.type = "color";
  color.className = "tiptap-tb-color";
  color.title = "Text color";
  color.value = "#1a1a1a";
  color.addEventListener("input", () => {
    editor.chain().focus().setColor(color.value).run();
  });
  bar.appendChild(color);

  return bar;
}

function createExtensions(): AnyExtension[] {
  return [
    StarterKit.configure({
      heading: { levels: [1, 2, 3, 4, 5, 6] },
    }),
    Underline,
    TextStyle,
    FontFamily.configure({ types: ["textStyle"] }),
    Color.configure({ types: ["textStyle"] }),
    Image.configure({ allowBase64: true, inline: true }),
    Table.configure({ resizable: false }),
    TableRow,
    TableHeader,
    TableCell,
    ReportSection,
    ReportCommentHighlight,
    Placeholder.configure({ placeholder: "Edit report…" }),
    InlineAssistPending,
  ];
}

export function createReportEditor(
  containerId: string,
  containerEl: HTMLElement,
  initialContent: string,
  onSave: () => void,
  options?: ReportEditorOptions
): ReportEditorHandle | null {
  const prev = handles.get(containerId);
  if (prev) {
    prev.destroy();
    handles.delete(containerId);
  }

  containerEl.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "tiptap-editor-wrap";

  const page = document.createElement("div");
  page.className = "tiptap-page-shell";
  const mount = document.createElement("div");
  mount.className = "tiptap-mount";
  mount.id = containerId;
  page.appendChild(mount);
  wrap.appendChild(page);
  containerEl.appendChild(wrap);

  const editor = new Editor({
    element: mount,
    extensions: createExtensions(),
    content: normalizeInitialHtml(initialContent),
    injectCSS: true,
  });
  let editorRef: Editor | null = editor;

  const toolbar = buildToolbar(editor);
  wrap.insertBefore(toolbar, page);

  let detachComments: (() => void) | undefined;
  if (options?.documentComments) {
    detachComments = attachDocumentCommentBubble(editor, wrap, options.documentComments);
  }

  let detachAssist: (() => void) | undefined;
  if (options?.inlineAssist?.run) {
    detachAssist = attachInlineAssist(editor, wrap, options.inlineAssist.run);
  }

  mount.addEventListener("keydown", (e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      onSave();
    }
  });

  const handle: ReportEditorHandle = {
    root: page,
    getHtml: () => stripReportCommentSpansFromHtml(editor.getHTML()),
    getJson: () => JSON.stringify(editor.getJSON()),
    hasPendingAssist: () => editorHasPendingAssist(editor),
    getEditor: () => editorRef,
    setContent: (html: string) => {
      editor.commands.setContent(normalizeInitialHtml(html), { emitUpdate: false });
    },
    destroy: () => {
      detachComments?.();
      detachAssist?.();
      editor.destroy();
      editorRef = null;
      handles.delete(containerId);
      containerEl.innerHTML = "";
    },
  };
  handles.set(containerId, handle);
  return handle;
}

export function getReportEditor(containerId: string): ReportEditorHandle | null {
  return handles.get(containerId) ?? null;
}

export function destroyAllReportEditors(): void {
  for (const h of [...handles.values()]) {
    try {
      h.destroy();
    } catch (_) {}
  }
  handles.clear();
}
