/**
 * In-document inline AI assist: pending proposal as real content + widget (Accept / Reject).
 */
import { Extension, Mark, mergeAttributes } from "@tiptap/core";
import type { CommandProps, Editor } from "@tiptap/core";

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    inlineAssistPending: {
      applyInlineAssistPending: (opts: {
        kind: "insert" | "replace";
        html: string;
        replaceFrom: number | null;
        replaceTo: number | null;
        evidence: string[];
      }) => ReturnType;
      rejectInlineAssistPending: () => ReturnType;
      acceptInlineAssistPending: () => ReturnType;
      clearInlineAssistPending: () => ReturnType;
    };
  }
}
import { DOMParser as PMDOMParser } from "@tiptap/pm/model";
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey, TextSelection, type Transaction } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

export type InlineAssistPendingKind = "insert" | "replace";

export type AssistPayload = {
  kind: InlineAssistPendingKind;
  pendingFrom: number;
  pendingTo: number;
  replaceFrom: number | null;
  replaceTo: number | null;
  evidence: string[];
};

type AssistPluginState = {
  deco: DecorationSet;
  payload: AssistPayload | null;
};

export const assistPendingPluginKey = new PluginKey<AssistPluginState>("assistPendingWidget");

type SetMeta = { type: "set"; payload: AssistPayload };
type ClearMeta = { type: "clear" };

function docRangeHasAssistPending(doc: PMNode, from: number, to: number): boolean {
  let found = false;
  doc.nodesBetween(from, to, (node) => {
    if (node.isText && node.marks.some((m) => m.type.name === "assistPending")) {
      found = true;
      return false;
    }
    return !found;
  });
  return found;
}

function buildWidgetDeco(pos: number, evidence: string[], runAccept: () => void, runReject: () => void): Decoration {
  return Decoration.widget(
    pos,
    () => {
      const wrap = document.createElement("div");
      wrap.className = "tiptap-assist-inline-widget";
      wrap.contentEditable = "false";
      if (evidence.length) {
        const cap = document.createElement("div");
        cap.className = "tiptap-assist-inline-evidence caption";
        cap.textContent = "Evidence: " + evidence.map((s) => s.split(/[/\\]/).pop() || s).join(", ");
        wrap.appendChild(cap);
      }
      const row = document.createElement("div");
      row.className = "tiptap-assist-inline-actions";
      const btnPair = document.createElement("div");
      btnPair.className = "tiptap-assist-inline-btn-pair";
      const acc = document.createElement("button");
      acc.type = "button";
      acc.className = "btn btn-sm btn-success";
      acc.textContent = "Accept";
      acc.title = "Keep this suggestion in the document";
      acc.addEventListener("mousedown", (e) => e.preventDefault());
      acc.addEventListener("click", (e) => {
        e.preventDefault();
        runAccept();
      });
      const rej = document.createElement("button");
      rej.type = "button";
      rej.className = "btn btn-sm btn-danger tiptap-assist-reject-btn";
      rej.textContent = "Reject";
      rej.title = "Remove this suggestion";
      rej.addEventListener("mousedown", (e) => e.preventDefault());
      rej.addEventListener("click", (e) => {
        e.preventDefault();
        runReject();
      });
      btnPair.appendChild(acc);
      btnPair.appendChild(rej);
      row.appendChild(btnPair);
      wrap.appendChild(row);
      return wrap;
    },
    { side: 1, key: "inline-assist-actions" }
  );
}

export const AssistReplaceSource = Mark.create({
  name: "assistReplaceSource",

  addOptions() {
    return { HTMLAttributes: {} };
  },

  parseHTML() {
    return [{ tag: 'span[data-assist-replace-source="1"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
        class: "massist-replace-source",
        "data-assist-replace-source": "1",
      }),
      0,
    ];
  },
});

export const AssistPending = Mark.create({
  name: "assistPending",

  addAttributes() {
    return {
      kind: { default: "insert" },
      replaceFrom: { default: null },
      replaceTo: { default: null },
    };
  },

  addOptions() {
    return { HTMLAttributes: {} };
  },

  parseHTML() {
    return [{ tag: 'span[data-assist-pending="1"]' }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
        class: "massist-pending",
        "data-assist-pending": "1",
      }),
      0,
    ];
  },
});

function parseHtmlSlice(editor: Editor, html: string) {
  const wrap = document.createElement("div");
  wrap.innerHTML = html.trim() || "<p></p>";
  return PMDOMParser.fromSchema(editor.schema).parseSlice(wrap, { preserveWhitespace: "full" });
}

function appendClearMeta(tr: Transaction): void {
  tr.setMeta(assistPendingPluginKey, { type: "clear" } satisfies ClearMeta);
}

function createAssistPlugin(editor: Editor): Plugin<AssistPluginState> {
  return new Plugin<AssistPluginState>({
    key: assistPendingPluginKey,
    state: {
      init: (): AssistPluginState => ({ deco: DecorationSet.empty, payload: null }),
      apply: (tr: Transaction, value: AssistPluginState, _old, newState): AssistPluginState => {
        const m = tr.getMeta(assistPendingPluginKey) as SetMeta | ClearMeta | undefined;
        if (m?.type === "clear") {
          return { deco: DecorationSet.empty, payload: null };
        }
        if (m?.type === "set" && m.payload) {
          const p = m.payload;
          const dec = DecorationSet.create(newState.doc, [
            buildWidgetDeco(p.pendingTo, p.evidence, () => {
              editor.commands.acceptInlineAssistPending();
            }, () => {
              editor.commands.rejectInlineAssistPending();
            }),
          ]);
          return { deco: dec, payload: p };
        }
        if (!value.payload) {
          return { deco: DecorationSet.empty, payload: null };
        }
        const map = tr.mapping;
        let { pendingFrom, pendingTo, replaceFrom, replaceTo, evidence, kind } = value.payload;
        pendingFrom = map.map(pendingFrom);
        pendingTo = map.map(pendingTo);
        if (replaceFrom != null && replaceTo != null) {
          replaceFrom = map.map(replaceFrom);
          replaceTo = map.map(replaceTo);
        }
        if (
          pendingFrom >= pendingTo ||
          !docRangeHasAssistPending(newState.doc, pendingFrom, pendingTo)
        ) {
          return { deco: DecorationSet.empty, payload: null };
        }
        const payload: AssistPayload = {
          kind,
          pendingFrom,
          pendingTo,
          replaceFrom,
          replaceTo,
          evidence,
        };
        const dec = DecorationSet.create(newState.doc, [
          buildWidgetDeco(pendingTo, evidence, () => {
            editor.commands.acceptInlineAssistPending();
          }, () => {
            editor.commands.rejectInlineAssistPending();
          }),
        ]);
        return { deco: dec, payload };
      },
    },
    props: {
      decorations(state) {
        return assistPendingPluginKey.getState(state)?.deco ?? null;
      },
    },
  });
}

export const InlineAssistPending = Extension.create({
  name: "inlineAssistPending",

  addExtensions() {
    return [AssistReplaceSource, AssistPending];
  },

  addProseMirrorPlugins() {
    return [createAssistPlugin(this.editor)];
  },

  addCommands() {
    return {
      applyInlineAssistPending:
        (opts: {
          kind: InlineAssistPendingKind;
          html: string;
          replaceFrom: number | null;
          replaceTo: number | null;
          evidence: string[];
        }) =>
        (props: CommandProps) => {
          const { state, dispatch, editor } = props;
          const { kind, html, evidence } = opts;
          const replaceFrom = opts.replaceFrom;
          const replaceTo = opts.replaceTo;

          const slice = parseHtmlSlice(editor, html);
          const size = slice.content.size;
          if (size <= 0) return false;

          let tr = state.tr;
          const insertPos = kind === "replace" && replaceFrom != null && replaceTo != null ? replaceTo : state.selection.from;

          if (kind === "replace" && replaceFrom != null && replaceTo != null) {
            const src = state.schema.marks.assistReplaceSource;
            if (src) {
              tr = tr.addMark(replaceFrom, replaceTo, src.create());
            }
          }

          tr = tr.replace(insertPos, insertPos, slice);

          const pendingFrom = insertPos;
          const pendingTo = insertPos + size;
          const markType = state.schema.marks.assistPending;
          if (!markType) return false;

          tr = tr.addMark(
            pendingFrom,
            pendingTo,
            markType.create({
              kind,
              replaceFrom: kind === "replace" ? replaceFrom : null,
              replaceTo: kind === "replace" ? replaceTo : null,
            })
          );

          const payload: AssistPayload = {
            kind,
            pendingFrom,
            pendingTo,
            replaceFrom: kind === "replace" ? replaceFrom : null,
            replaceTo: kind === "replace" ? replaceTo : null,
            evidence,
          };
          tr = tr.setMeta(assistPendingPluginKey, { type: "set", payload } satisfies SetMeta);
          tr.setSelection(TextSelection.create(tr.doc, pendingTo));

          if (dispatch) dispatch(tr);
          return true;
        },

      rejectInlineAssistPending:
        () =>
        ({ state, dispatch }: CommandProps) => {
          const plug = assistPendingPluginKey.getState(state);
          const payload = plug?.payload;
          if (!payload) return true;

          let tr = state.tr;
          const markSrc = state.schema.marks.assistReplaceSource;
          const { pendingFrom, pendingTo, replaceFrom, replaceTo, kind } = payload;

          if (pendingFrom < pendingTo) {
            tr = tr.delete(pendingFrom, pendingTo);
          }
          if (kind === "replace" && replaceFrom != null && replaceTo != null && markSrc) {
            tr = tr.removeMark(replaceFrom, replaceTo, markSrc);
          }
          appendClearMeta(tr);
          if (dispatch) dispatch(tr);
          return true;
        },

      acceptInlineAssistPending:
        () =>
        ({ state, dispatch }: CommandProps) => {
          const plug = assistPendingPluginKey.getState(state);
          const payload = plug?.payload;
          if (!payload) return false;

          const markPending = state.schema.marks.assistPending;
          if (!markPending) return false;

          let tr = state.tr;
          const { pendingFrom, pendingTo, replaceFrom, replaceTo, kind } = payload;

          if (kind === "replace" && replaceFrom != null && replaceTo != null) {
            const len = pendingTo - pendingFrom;
            tr = tr.delete(replaceFrom, replaceTo);
            tr = tr.removeMark(replaceFrom, replaceFrom + len, markPending);
          } else {
            tr = tr.removeMark(pendingFrom, pendingTo, markPending);
          }

          appendClearMeta(tr);
          if (dispatch) dispatch(tr);
          return true;
        },

      clearInlineAssistPending:
        () =>
        ({ state, editor }: CommandProps) => {
          const plug = assistPendingPluginKey.getState(state);
          if (!plug?.payload) return true;
          return editor.commands.rejectInlineAssistPending();
        },
    };
  },
});

export function editorHasPendingAssist(editor: Editor): boolean {
  return !!(assistPendingPluginKey.getState(editor.state)?.payload);
}
