/*
 * The Notes Vault editor: CodeMirror 6 with an Obsidian-style live preview.
 *
 * Markdown is rendered where it is written. Headings are headings, emphasis is
 * emphasis, links and [[wikilinks]] are links, tasks are checkboxes. The syntax
 * comes back on the line the cursor is on, so it can be edited, and only there.
 *
 * Built into custom_components/notes_vault/frontend/editor.js by `npm run build`
 * and loaded by notes-vault.js the first time a note is edited, so pages that only
 * show notes never download it.
 */

import { autocompletion, closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import {
  deleteMarkupBackward,
  insertNewlineContinueMarkup,
  markdownLanguage,
} from "@codemirror/lang-markdown";
import {
  HighlightStyle,
  LanguageSupport,
  syntaxHighlighting,
  syntaxTree,
} from "@codemirror/language";
import { EditorState, StateEffect } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  ViewPlugin,
  WidgetType,
  keymap,
  placeholder,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";

const WIKILINK = /(!?)\[\[([^\]|#^\n]+)([#^][^\]|\n]*)?(?:\|([^\]\n]*))?\]\]/g;

/** Nodes whose text is code, where nothing else is rendered. */
const CODE_NODES = new Set(["InlineCode", "FencedCode", "CodeBlock", "CodeText"]);

/** Tells the live preview to rebuild, when link targets resolve differently. */
const refreshLinks = StateEffect.define();

const fileName = (path) => (path || "").split("/").pop().replace(/\.md$/, "");

class LinkWidget extends WidgetType {
  constructor(label, href, { external = false, unresolved = false } = {}) {
    super();
    this.label = label;
    this.href = href;
    this.external = external;
    this.unresolved = unresolved;
  }

  eq(other) {
    return (
      other.label === this.label &&
      other.href === this.href &&
      other.unresolved === this.unresolved
    );
  }

  toDOM() {
    const el = document.createElement(this.href ? "a" : "span");
    el.className = `cm-np-link${this.unresolved ? " cm-np-unresolved" : ""}`;
    el.textContent = this.label;
    if (this.href) {
      el.setAttribute("href", this.href);
      if (this.external) {
        el.target = "_blank";
        el.rel = "noopener noreferrer";
      }
    }
    return el;
  }

  // Clicks go to the link, not to the editor: the note element follows it.
  ignoreEvent() {
    return true;
  }
}

class CheckboxWidget extends WidgetType {
  constructor(checked, pos) {
    super();
    this.checked = checked;
    this.pos = pos;
  }

  eq(other) {
    return other.checked === this.checked && other.pos === this.pos;
  }

  toDOM(view) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "cm-np-task";
    box.checked = this.checked;
    box.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      view.dispatch({
        changes: { from: this.pos + 1, to: this.pos + 2, insert: this.checked ? " " : "x" },
      });
    });
    return box;
  }

  // The checkbox toggles itself; the editor mustn't also move the cursor onto it,
  // which would swap it back to `[ ]` mid-click.
  ignoreEvent() {
    return true;
  }
}

class BulletWidget extends WidgetType {
  eq() {
    return true;
  }

  toDOM() {
    const el = document.createElement("span");
    el.className = "cm-np-bullet";
    el.textContent = "•";
    return el;
  }
}

class RuleWidget extends WidgetType {
  eq() {
    return true;
  }

  toDOM() {
    const el = document.createElement("span");
    el.className = "cm-np-rule";
    return el;
  }
}

const hide = Decoration.replace({});

/** Line numbers the cursor or selection touches, where the syntax shows. */
const activeLines = (view) => {
  const lines = new Set();
  if (!view.hasFocus) return lines;
  for (const range of view.state.selection.ranges) {
    const first = view.state.doc.lineAt(range.from).number;
    const last = view.state.doc.lineAt(range.to).number;
    for (let n = first; n <= last; n++) lines.add(n);
  }
  return lines;
};

const buildDecorations = (view, resolveLink) => {
  const { state } = view;
  const doc = state.doc;
  const active = activeLines(view);
  const isActive = (pos) => active.has(doc.lineAt(pos).number);
  const decorations = [];
  const lineClass = (pos, cls) =>
    decorations.push(Decoration.line({ class: cls }).range(doc.lineAt(pos).from));
  const code = [];

  for (const { from, to } of view.visibleRanges) {
    syntaxTree(state).iterate({
      from,
      to,
      enter: (node) => {
        const name = node.name;
        if (CODE_NODES.has(name)) code.push([node.from, node.to]);

        const heading = /^(?:ATX|Setext)Heading(\d)$/.exec(name);
        if (heading) {
          lineClass(node.from, `cm-np-h cm-np-h${heading[1]}`);
          return;
        }
        switch (name) {
          case "HeaderMark": {
            if (isActive(node.from)) return;
            // The marks of an ATX heading, and the space after the opening ones.
            const next = doc.sliceString(node.to, node.to + 1);
            decorations.push(hide.range(node.from, next === " " ? node.to + 1 : node.to));
            return;
          }
          case "EmphasisMark":
          case "StrikethroughMark":
          case "CodeMark": {
            if (node.node.parent?.name === "FencedCode") return;
            if (!isActive(node.from)) decorations.push(hide.range(node.from, node.to));
            return;
          }
          case "QuoteMark": {
            lineClass(node.from, "cm-np-quote");
            if (isActive(node.from)) return;
            const next = doc.sliceString(node.to, node.to + 1);
            decorations.push(hide.range(node.from, next === " " ? node.to + 1 : node.to));
            return;
          }
          case "ListMark": {
            if (isActive(node.from)) return;
            const parent = node.node.parent?.parent?.name;
            const item = node.node.parent;
            // A task shows its checkbox instead of a bullet.
            if (item?.getChild("Task")) {
              const next = doc.sliceString(node.to, node.to + 1);
              decorations.push(hide.range(node.from, next === " " ? node.to + 1 : node.to));
            } else if (parent === "BulletList") {
              decorations.push(
                Decoration.replace({ widget: new BulletWidget() }).range(node.from, node.to),
              );
            }
            return;
          }
          case "TaskMarker": {
            const checked = /x/i.test(doc.sliceString(node.from, node.to));
            if (checked) {
              const line = doc.lineAt(node.from);
              decorations.push(
                Decoration.mark({ class: "cm-np-done" }).range(node.to, line.to),
              );
            }
            if (isActive(node.from)) return;
            decorations.push(
              Decoration.replace({ widget: new CheckboxWidget(checked, node.from) }).range(
                node.from,
                node.to,
              ),
            );
            return;
          }
          case "HorizontalRule": {
            if (isActive(node.from)) return;
            decorations.push(
              Decoration.replace({ widget: new RuleWidget() }).range(node.from, node.to),
            );
            return;
          }
          case "FencedCode": {
            for (let pos = node.from; pos <= node.to; ) {
              const line = doc.lineAt(pos);
              lineClass(line.from, "cm-np-codeblock");
              pos = line.to + 1;
            }
            return false;
          }
          case "Link": {
            if (isActive(node.from)) return;
            const text = doc.sliceString(node.from, node.to);
            const match = /^\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)$/.exec(text);
            if (!match) return;
            decorations.push(
              Decoration.replace({
                widget: new LinkWidget(match[1] || match[2], match[2], {
                  external: /^[a-z][a-z0-9+.-]*:/i.test(match[2]),
                }),
              }).range(node.from, node.to),
            );
            return false;
          }
          default:
            return undefined;
        }
      },
    });

    // Wikilinks aren't CommonMark, so they're found by pattern, outside code.
    const text = doc.sliceString(from, to);
    for (const match of text.matchAll(WIKILINK)) {
      const start = from + match.index;
      const end = start + match[0].length;
      if (code.some(([a, b]) => start < b && end > a)) continue;
      if (isActive(start) || isActive(end)) {
        decorations.push(Decoration.mark({ class: "cm-np-wikisource" }).range(start, end));
        continue;
      }
      const target = match[2].trim();
      const resolved = resolveLink?.(target) || null;
      const label = match[4] || resolved?.label || fileName(target);
      decorations.push(
        Decoration.replace({
          widget: new LinkWidget(match[1] ? `🖼 ${label}` : label, resolved?.href || null, {
            unresolved: !resolved?.exists,
          }),
        }).range(start, end),
      );
    }
  }
  return Decoration.set(decorations, true);
};

const livePreview = (resolveLink) =>
  ViewPlugin.fromClass(
    class {
      constructor(view) {
        this.decorations = buildDecorations(view, resolveLink);
      }

      update(update) {
        if (
          update.docChanged ||
          update.selectionSet ||
          update.viewportChanged ||
          update.focusChanged ||
          update.transactions.some((tr) => tr.effects.some((e) => e.is(refreshLinks))) ||
          syntaxTree(update.startState) !== syntaxTree(update.state)
        ) {
          this.decorations = buildDecorations(update.view, resolveLink);
        }
      }
    },
    { decorations: (plugin) => plugin.decorations },
  );

/** Markdown styling that holds whether or not the syntax is showing. */
const highlight = HighlightStyle.define([
  { tag: tags.strong, fontWeight: "bold" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.strikethrough, textDecoration: "line-through" },
  { tag: tags.monospace, fontFamily: "var(--ha-font-family-code, monospace)", fontSize: "0.9em" },
  { tag: tags.link, color: "var(--primary-color)" },
  { tag: tags.url, color: "var(--secondary-text-color)" },
  { tag: tags.processingInstruction, color: "var(--secondary-text-color)" },
  { tag: tags.quote, color: "var(--secondary-text-color)" },
]);

/** Home Assistant's own theme variables, so the editor looks like the rest of it. */
const theme = EditorView.theme({
  "&": {
    color: "var(--primary-text-color)",
    backgroundColor: "transparent",
    fontSize: "var(--ha-font-size-m, 14px)",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": {
    fontFamily: "var(--ha-font-family-body, inherit)",
    lineHeight: "1.6",
  },
  ".cm-content": { padding: "0", caretColor: "var(--primary-color)" },
  ".cm-line": { padding: "0" },
  ".cm-cursor": { borderLeftColor: "var(--primary-color)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection": {
    backgroundColor: "rgba(var(--rgb-primary-color, 3, 169, 244), 0.25) !important",
  },
  ".cm-placeholder": { color: "var(--secondary-text-color)" },
  ".cm-np-h": { fontWeight: "bold", lineHeight: "1.3" },
  ".cm-np-h1": { fontSize: "1.6em", paddingTop: "0.4em !important" },
  ".cm-np-h2": { fontSize: "1.35em", paddingTop: "0.35em !important" },
  ".cm-np-h3": { fontSize: "1.15em", paddingTop: "0.3em !important" },
  ".cm-np-h4, .cm-np-h5, .cm-np-h6": { fontSize: "1em" },
  ".cm-np-quote": {
    borderLeft: "3px solid var(--divider-color)",
    paddingLeft: "12px !important",
    color: "var(--secondary-text-color)",
  },
  ".cm-np-codeblock": {
    fontFamily: "var(--ha-font-family-code, monospace)",
    fontSize: "0.9em",
    backgroundColor: "var(--code-editor-background-color, var(--secondary-background-color))",
    padding: "0 8px !important",
  },
  ".cm-np-link": {
    color: "var(--primary-color)",
    textDecoration: "none",
    cursor: "pointer",
  },
  ".cm-np-link:hover": { textDecoration: "underline" },
  ".cm-np-unresolved": { opacity: "0.7" },
  ".cm-np-wikisource": { color: "var(--primary-color)" },
  ".cm-np-bullet": { color: "var(--secondary-text-color)", padding: "0 4px" },
  ".cm-np-task": { margin: "0 6px 0 0", verticalAlign: "middle", cursor: "pointer" },
  ".cm-np-done": { color: "var(--secondary-text-color)", textDecoration: "line-through" },
  ".cm-np-rule": {
    display: "inline-block",
    width: "100%",
    borderTop: "1px solid var(--divider-color)",
    verticalAlign: "middle",
  },
  ".cm-tooltip": {
    border: "1px solid var(--divider-color)",
    backgroundColor: "var(--card-background-color, var(--primary-background-color))",
    color: "var(--primary-text-color)",
  },
  ".cm-tooltip.cm-tooltip-autocomplete > ul": {
    fontFamily: "var(--ha-font-family-body, inherit)",
    maxWidth: "min(480px, 90vw)",
  },
  ".cm-tooltip-autocomplete ul li": { padding: "4px 8px" },
  ".cm-completionMatchedText": { textDecoration: "none", fontWeight: "bold" },
  ".cm-tooltip-autocomplete ul li[aria-selected]": {
    backgroundColor: "var(--primary-color)",
    color: "var(--text-primary-color, white)",
  },
  ".cm-completionDetail": { color: "var(--secondary-text-color)", marginLeft: "8px" },
});

/** Offer notes to link to after `[[`, inserting a link Obsidian understands. */
const wikilinkCompletion = (listNotes) => async (context) => {
  const before = context.matchBefore(/\[\[[^\]|#\n]*$/);
  if (!before) return null;
  const notes = (await listNotes?.()) || [];
  const closed = context.state.sliceDoc(context.pos, context.pos + 2) === "]]";
  return {
    from: before.from + 2,
    options: notes.map((note) => {
      const target = note.target;
      const alias = note.label && note.label !== target ? `|${note.label}` : "";
      return {
        label: note.label || target,
        detail: note.detail,
        apply: `${target}${alias}${closed ? "" : "]]"}`,
      };
    }),
    validFor: /^[^\]|#\n]*$/,
  };
};

/**
 * Create an editor in `parent`.
 *
 * `resolveLink(target)` returns `{href, label, exists}` for a wikilink target, or
 * null. `listNotes()` resolves to `[{target, label, detail}]` for completion.
 * `onChange(text)` fires on every edit. `root` is the shadow root the editor lives
 * in, which CodeMirror needs to put its styles where they apply.
 */
export function createEditor({ parent, root, doc = "", resolveLink, listNotes, onChange, hint }) {
  const view = new EditorView({
    parent,
    root,
    state: EditorState.create({
      doc,
      extensions: [
        history(),
        closeBrackets(),
        // The language alone: markdown() also bundles the HTML, CSS and JavaScript
        // parsers for code embedded in notes, three times the size of the rest.
        new LanguageSupport(markdownLanguage),
        syntaxHighlighting(highlight),
        livePreview(resolveLink),
        autocompletion({ override: [wikilinkCompletion(listNotes)], icons: false }),
        keymap.of([
          // Enter continues a list or a quote, Backspace takes the marker away.
          { key: "Enter", run: insertNewlineContinueMarkup },
          { key: "Backspace", run: deleteMarkupBackward },
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        EditorView.lineWrapping,
        placeholder(hint || ""),
        theme,
        EditorView.updateListener.of((update) => {
          if (update.docChanged) onChange?.(update.state.doc.toString());
        }),
      ],
    }),
  });

  return {
    view,
    getValue: () => view.state.doc.toString(),
    /** Replace the text, keeping the cursor where it was as far as possible. */
    setValue(text) {
      const cursor = Math.min(view.state.selection.main.head, text.length);
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: text },
        selection: { anchor: cursor },
      });
    },
    /** Re-render links, after their targets resolved differently. */
    refreshLinks: () => view.dispatch({ effects: refreshLinks.of(null) }),
    focus: () => view.focus(),
    destroy: () => view.destroy(),
  };
}
