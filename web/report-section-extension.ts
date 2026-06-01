/**
 * Explicit report section wrappers (Phase 2 §8.4).
 * Parses/serializes <section class="report-section" data-section-key data-section-policy>.
 */
import { mergeAttributes, Node } from "@tiptap/core";

export const ReportSection = Node.create({
  name: "reportSection",
  group: "block",
  content: "block+",
  defining: true,

  addAttributes() {
    return {
      sectionKey: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-section-key"),
        renderHTML: (attrs) => {
          if (!attrs.sectionKey) return {};
          return { "data-section-key": attrs.sectionKey as string };
        },
      },
      sectionPolicy: {
        default: "editable",
        parseHTML: (el) => el.getAttribute("data-section-policy") || "editable",
        renderHTML: (attrs) => ({
          "data-section-policy": (attrs.sectionPolicy as string) || "editable",
        }),
      },
    };
  },

  parseHTML() {
    return [{ tag: "section[data-section-key]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "section",
      mergeAttributes(HTMLAttributes, { class: "report-section" }),
      0,
    ];
  },
});
