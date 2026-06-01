/**
 * Inline comment highlight mark (Google Docs–style anchors; stripped from saved HTML).
 */
import type { Editor } from "@tiptap/core";
import { Mark, mergeAttributes } from "@tiptap/core";

export const ReportCommentHighlight = Mark.create({
  name: "reportCommentHighlight",
  inclusive: false,
  addAttributes() {
    return {
      commentId: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-report-comment"),
        renderHTML: (attrs) => {
          if (!attrs.commentId) return {};
          return { "data-report-comment": String(attrs.commentId) };
        },
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-report-comment]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { class: "report-comment-highlight" }), 0];
  },
});

export interface CommentAnchorJson {
  from?: number;
  to?: number;
  sectionKey?: string;
  quote?: string;
}

export function buildAnchorPayload(editor: Editor, from: number, to: number): CommentAnchorJson {
  const doc = editor.state.doc;
  const quote = doc.textBetween(from, to, "\n", " ").slice(0, 200);
  let sectionKey: string | undefined;
  const $from = doc.resolve(from);
  for (let d = $from.depth; d > 0; d--) {
    const n = $from.node(d);
    if (n.type.name === "reportSection") {
      const k = n.attrs.sectionKey;
      if (k && typeof k === "string") {
        sectionKey = k;
        break;
      }
    }
  }
  const out: CommentAnchorJson = { from, to, quote };
  if (sectionKey) out.sectionKey = sectionKey;
  return out;
}

export function resolveAnchorRange(
  editor: Editor,
  anchor: CommentAnchorJson | null | undefined
): { from: number; to: number } | null {
  if (!anchor) return null;
  const doc = editor.state.doc;
  const size = doc.content.size;
  const from = anchor.from;
  const to = anchor.to;
  if (typeof from === "number" && typeof to === "number" && from >= 0 && to <= size && to > from) {
    return { from, to };
  }
  return null;
}

export function applyCommentHighlights(
  editor: Editor,
  items: Array<{ id: string; anchor?: CommentAnchorJson | null }>
): void {
  const type = editor.schema.marks.reportCommentHighlight;
  if (!type) return;

  let tr = editor.state.tr;
  tr.setMeta("addToHistory", false);
  editor.state.doc.descendants((node, pos) => {
    if (!node.isText) return;
    if (node.marks.some((m) => m.type === type)) {
      tr = tr.removeMark(pos, pos + node.nodeSize, type);
    }
  });
  editor.view.dispatch(tr);

  const ranges: Array<{ from: number; to: number; id: string }> = [];
  for (const it of items) {
    if (!it.anchor) continue;
    const r = resolveAnchorRange(editor, it.anchor);
    if (r) ranges.push({ ...r, id: it.id });
  }
  if (!ranges.length) return;
  let chain = editor.chain().focus();
  for (const r of ranges) {
    chain = chain
      .setTextSelection({ from: r.from, to: r.to })
      .setMark("reportCommentHighlight", { commentId: r.id });
  }
  chain.run();
}

export function stripReportCommentSpansFromHtml(html: string): string {
  const d = document.createElement("div");
  d.innerHTML = html;
  d.querySelectorAll("span[data-report-comment]").forEach((el) => {
    const parent = el.parentNode;
    if (!parent) return;
    while (el.firstChild) parent.insertBefore(el.firstChild, el);
    parent.removeChild(el);
  });
  return d.innerHTML;
}
