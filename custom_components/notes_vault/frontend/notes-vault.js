/*
 * Notes Vault frontend.
 *
 * One note editor, `notes-vault-note`, used everywhere: in the more-info dialog of
 * every entity, as a card on device and area pages, in the automation, script and
 * scene editors, in `custom:notes-vault-card`, and in the Notes panel in the
 * sidebar, which lists every note in the vault.
 *
 * Home Assistant has no extension point for the dialog or the device and area pages,
 * so the editor is appended to the frontend's own DOM there. Every lookup is
 * defensive: if a frontend update moves things around, the notes stop showing up in
 * that spot, nothing breaks.
 *
 * Everything visible is a stock Home Assistant element (ha-card, ha-expansion-panel,
 * ha-markdown, ha-form, ha-button, ha-icon-button, ha-list, ha-input-search,
 * ha-top-app-bar-fixed, ha-spinner, ha-alert), except the editor: CodeMirror with an
 * Obsidian-style live preview, in editor.js, loaded the first time a note is edited.
 * Its source and build are in frontend-src/.
 */

const VERSION = "0.1.0";
const POLL_MS = 700;
const PANEL_PATH = "/notes-vault";

const getHass = () => document.querySelector("home-assistant")?.hass;

let infoPromise;
const getInfo = (hass) => {
  if (!infoPromise) {
    infoPromise = hass
      .callWS({ type: "notes_vault/info" })
      .catch(() => ({ loaded: false }))
      .then((info) => {
        // Ask again next time until the integration is up, so a page opened while
        // Home Assistant is still starting picks the notes up later.
        if (!info.loaded) infoPromise = undefined;
        return info;
      });
  }
  return infoPromise;
};

let editorModule;
/** The live-preview editor. Loaded on first use, with the same cache-busting query. */
const loadEditor = () => {
  editorModule ??= import(new URL(`./editor.js${new URL(import.meta.url).search}`, import.meta.url).href);
  return editorModule;
};

let notesCache;
/** Every note in the vault, for link completion and for links typed since the last save. */
const listNotes = (hass) => {
  if (!notesCache || Date.now() - notesCache.at > 30000) {
    notesCache = {
      at: Date.now(),
      notes: hass
        .callWS({ type: "notes_vault/tree" })
        .then((result) => result.notes)
        .catch(() => []),
    };
  }
  return notesCache.notes;
};

/** How long the panel waits after the last keystroke before saving. */
const AUTOSAVE_MS = 1000;
const CONFLICT =
  "This note changed while you were editing it. Copy anything you want to keep, then load the new version.";

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const fileName = (path) => (path || "").split("/").pop().replace(/\.md$/, "");

/** Navigate inside the app, the way Home Assistant's own links do. */
const navigate = (href) => {
  history.pushState(null, "", href);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
};

const panelHref = (path) => `${PANEL_PATH}?path=${encodeURIComponent(path)}`;

/** Where a link to an entity, device, area or integration goes in Home Assistant. */
const haHref = (ha) => {
  if (!ha) return null;
  if (ha.type === "entity") return `#notes-vault-entity=${ha.id}`;
  if (ha.type === "device") return `/config/devices/device/${encodeURIComponent(ha.id)}`;
  if (ha.type === "area") return `/config/areas/area/${encodeURIComponent(ha.id)}`;
  if (ha.type === "integration") return `/config/integrations/integration/${encodeURIComponent(ha.id)}`;
  return null;
};

/**
 * Obsidian wikilinks mean nothing to Home Assistant's Markdown renderer. The server
 * resolves each target to the note behind it, and for generated notes to the entity,
 * device or area. In the panel every link opens its note; elsewhere links go to the
 * entity's dialog or the device or area page, and other notes open in the panel.
 */
const renderWikilinks = (text, links, { inPanel, canBrowse }) =>
  text
    .replace(/!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/g, (_m, target, label) => `*${label || fileName(target)}*`)
    .replace(/\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|([^\]]*))?\]\]/g, (_m, target, label) => {
      const shown = label || fileName(target);
      const link = links?.[target.trim()];
      let href = null;
      if (link && inPanel) href = `#notes-vault-path=${encodeURIComponent(link.path)}`;
      else if (link) href = haHref(link) || (canBrowse ? panelHref(link.path) : null);
      return href ? `[${shown}](${href})` : `**${shown}**`;
    });

const STYLE = `
  :host { display: block; }
  ha-expansion-panel { margin-top: 16px; }
  .body { display: flex; flex-direction: column; gap: 8px; }
  .panel-body { padding: 0 16px 16px; }
  .path, .empty { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); }
  .empty { font-size: inherit; }
  .path { word-break: break-all; }
  ha-markdown { overflow-wrap: anywhere; }
  .editor { min-height: 96px; cursor: text; }
  :host(:not([variant="panel"])) .editor {
    border: 1px solid var(--divider-color);
    border-radius: var(--ha-border-radius-md, 8px);
    padding: 8px 12px;
  }
  :host([variant="panel"]) .editor { min-height: 50vh; }
  .status { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); }
  .actions, .card-actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; }
  .card-actions .spacer, .actions .spacer { flex: 1; }
  ha-spinner { align-self: center; }
  ha-card + ha-card { margin-top: 16px; }
  ha-list { --mdc-list-vertical-padding: 0; }
`;

const NOTE_FIELD = { name: "note", selector: { text: { multiline: true } } };
const BLANK = "__blank__";
const MDI_CHECK = "M21,7L9,19L3.5,13.5L4.91,12.09L9,16.17L19.59,5.59L21,7Z";


/**
 * The note editor. `setTarget({entity_id})`, `{device_id}`, `{area_id}` or `{path}`.
 * `variant` is `inline` (more-info dialog), `card` (pages and dashboards) or `panel`.
 * Fires `notes-vault-open` with a path when a link to another note is followed in the
 * panel, and `notes-vault-changed` after a save or delete.
 */
class NotesVaultNote extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._target = null;
    this._state = { loading: true };
    this._unsub = null;
    // Capture phase: Home Assistant's textarea handles keys before they bubble out.
    this.shadowRoot.addEventListener(
      "keydown",
      (ev) => {
        if (!this._state.editing) return;
        if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
          ev.preventDefault();
          ev.stopPropagation();
          this._save();
        } else if (ev.key === "Escape") {
          // The completion list closes first, and the panel has nothing to cancel.
          if (this._autosaves || this.shadowRoot.querySelector(".cm-tooltip-autocomplete")) return;
          // Close the editor, not the dialog around it.
          ev.preventDefault();
          ev.stopPropagation();
          this._cancel();
        }
      },
      true,
    );
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
  }

  set hass(hass) {
    this._hass = hass;
    const form = this.shadowRoot.querySelector("ha-form");
    if (form) form.hass = hass;
  }

  get hass() {
    return this._hass || getHass();
  }

  get _variant() {
    return this.getAttribute("variant") || "card";
  }

  /** The panel saves as you type, the way Obsidian does. Everywhere else has Save. */
  get _autosaves() {
    return this._variant === "panel" && !!this._state.canEdit;
  }

  setTarget(target) {
    const key = JSON.stringify(target);
    if (key === this._targetKey) return;
    // Anything typed into the note being left is saved on the way out.
    if (this._autosaves && this._state.editing) this._autosave();
    this._destroyEditor();
    this._target = target;
    this._targetKey = key;
    this._state = { loading: true };
    this._render();
    this._load();
  }

  connectedCallback() {
    this._subscribe();
  }

  disconnectedCallback() {
    if (this._autosaves && this._state.editing) this._autosave();
    this._destroyEditor();
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
  }

  async _subscribe() {
    const hass = this.hass;
    if (!hass || this._unsub) return;
    const info = await getInfo(hass);
    // Only administrators may subscribe to arbitrary events.
    if (!info.can_edit || !this.isConnected) return;
    this._unsub = hass.connection
      .subscribeEvents((ev) => {
        if (!this._state.path || ev.data.path !== this._state.path || ev.data.source === "ui") return;
        // An open editor with nothing unsaved follows the change. One with unsaved
        // text keeps it, and the save that follows reports the conflict.
        const idle = this._autosaves && !this._saving && this._state.draft === this._base;
        if (!this._state.editing || idle) this._load();
      }, "notes_vault_updated")
      .catch(() => {});
  }

  async _load() {
    const hass = this.hass;
    const target = this._target;
    if (!hass || !target) return;
    try {
      const info = await getInfo(hass);
      if (!info.loaded) {
        this._state = { unavailable: true };
        setTimeout(() => this.isConnected && target === this._target && this._load(), 10000);
      } else {
        const result = await hass.callWS({ type: "notes_vault/get", ...target });
        if (target !== this._target) return;
        this._state = { ...result, canEdit: info.can_edit };
        // The panel opens every note straight into the editor, and focuses one that
        // doesn't exist yet, since that's one being created.
        if (this._variant === "panel" && info.can_edit) {
          this._edit({ focus: !result.exists });
          return;
        }
      }
    } catch (err) {
      this._state = { error: err.message || String(err) };
    }
    this._render();
  }

  async _save() {
    const note = this._state.draft ?? "";
    this._state = { ...this._state, saving: true, error: undefined };
    this._render();
    try {
      // The version being edited, so a save can't silently replace a change made
      // meanwhile by an assistant, Obsidian or another tab.
      const mtime = this._state.exists ? (this._state.mtime ?? null) : null;
      const result = await this.hass.callWS({ type: "notes_vault/set", note, mtime, ...this._target });
      this._destroyEditor();
      this._state = { ...result, canEdit: this._state.canEdit };
      this._fire("notes-vault-changed", { path: result.path });
    } catch (err) {
      this._state = { ...this._state, saving: false, error: err.message || String(err) };
    }
    this._render();
  }

  async _delete() {
    if (!this._state.confirmDelete) {
      this._state = { ...this._state, confirmDelete: true };
      this._render();
      return;
    }
    try {
      await this.hass.callWS({ type: "notes_vault/delete", path: this._state.path });
      this._fire("notes-vault-changed", { path: this._state.path, deleted: true });
    } catch (err) {
      this._state = { ...this._state, confirmDelete: false, error: err.message || String(err) };
      this._render();
    }
  }

  async _edit({ focus = true } = {}) {
    const starting = !this._state.note;
    this._focusOnMount = focus;
    this._state = { ...this._state, editing: true, draft: this._state.note || "", templates: undefined };
    // A new note on an entity, device or area starts from the template that fits it,
    // or the one it was pre-filled with, with the others on offer.
    if (starting) {
      const current = this._state.template;
      try {
        const result = await this.hass.callWS({ type: "notes_vault/template", ...this._target });
        this._state.templates = result.templates;
        const template = current || result.template;
        this._state.templateName = template?.name ?? BLANK;
        this._state.draft = template?.body ?? "";
      } catch (err) {
        if (current) this._state.draft = current.body;
      }
    }
    // What's on disk, or the template a new note starts from: nothing to save yet.
    this._base = this._state.draft;
    this._editor?.setValue(this._state.draft);
    this._render();
    if (this._state.plain && focus) {
      // ha-form loads the text selector lazily; focus once it has rendered.
      setTimeout(() => this.shadowRoot.querySelector("ha-form")?.focus?.(), 200);
    }
  }

  /** Show the live-preview editor in its slot, creating it the first time. */
  _mountEditor() {
    const slot = this.shadowRoot.querySelector(".editor-slot");
    if (!slot) return;
    const hadFocus = this._editor?.view.hasFocus;
    if (!this._editorHost) {
      const host = document.createElement("div");
      host.className = "editor";
      // Clicking the empty space below the text puts the cursor at the end.
      host.addEventListener("mousedown", (ev) => {
        if (ev.target !== host || !this._editor) return;
        ev.preventDefault();
        const { view } = this._editor;
        view.focus();
        view.dispatch({ selection: { anchor: view.state.doc.length } });
      });
      // Home Assistant's keyboard shortcuts ("e" for the entity search, "c" for
      // commands) only stand down for inputs and textareas, and can't see the
      // editor inside this shadow root. Keys typed into it stop here, after the
      // editor has handled them.
      host.addEventListener("keydown", (ev) => ev.stopPropagation());
      this._editorHost = host;
      loadEditor()
        .then((mod) => {
          if (host !== this._editorHost) return;
          this._editor = mod.createEditor({
            parent: host,
            root: this.shadowRoot,
            doc: this._state.draft ?? "",
            resolveLink: (target) => this._resolveLink(target),
            listNotes: () => this._noteOptions(),
            onChange: (text) => this._changed(text),
            hint: "Start writing. Type [[ to link a note, an entity, a device or an area.",
          });
          if (this._focusOnMount) this._editor.focus();
          this._focusOnMount = false;
          // Links typed since the last save resolve against the note list.
          this._noteOptions().then(() => this._editor?.refreshLinks());
        })
        .catch(() => {
          // No editor (an old browser, a failed download): the plain text box.
          this._destroyEditor();
          this._state.plain = true;
          this._render();
        });
    }
    slot.replaceWith(this._editorHost);
    if (this._editor) {
      this._editor.view.requestMeasure();
      if (hadFocus) this._editor.focus();
    }
  }

  _destroyEditor() {
    clearTimeout(this._timer);
    this._timer = null;
    this._editor?.destroy();
    this._editor = null;
    this._editorHost = null;
  }

  _changed(text) {
    this._state.draft = text;
    if (text !== this._base) this.shadowRoot.querySelector(".template-menu")?.remove();
    if (!this._autosaves || this._state.conflict) return;
    this._setStatus();
    clearTimeout(this._timer);
    this._timer = setTimeout(() => this._autosave(), AUTOSAVE_MS);
  }

  /** Save the panel's note if it changed, without redrawing the editor. */
  async _autosave() {
    clearTimeout(this._timer);
    this._timer = null;
    if (this._saving) {
      this._saveAgain = true;
      return;
    }
    const draft = this._state.draft ?? "";
    if (draft === this._base || this._state.conflict) return;
    const target = this._target;
    const mtime = this._state.exists ? (this._state.mtime ?? null) : null;
    this._saving = true;
    this._setStatus();
    try {
      const result = await this.hass.callWS({ type: "notes_vault/set", note: draft, mtime, ...target });
      if (target !== this._target) return;
      const created = !this._state.exists;
      this._base = draft;
      const { backlinks } = this._state;
      Object.assign(this._state, result, { backlinks: result.backlinks ?? backlinks, draft: this._state.draft });
      this._editor?.refreshLinks();
      if (created) this._fire("notes-vault-changed", { path: result.path });
    } catch (err) {
      if (target !== this._target) return;
      this._state.conflict = err.code === "changed";
      this._state.error = this._state.conflict ? CONFLICT : err.message || String(err);
      this._render();
    } finally {
      this._saving = false;
      this._setStatus();
      if (this._saveAgain) {
        this._saveAgain = false;
        this._autosave();
      }
    }
  }

  _setStatus() {
    const status = this.shadowRoot.querySelector(".status");
    if (status) status.textContent = this._statusText();
  }

  _statusText() {
    if (this._saving) return "Saving…";
    if (this._state.draft !== this._base) return "Unsaved";
    return this._state.exists ? "Saved" : "";
  }

  /** Throw away what's unsaved and load the note as it is now. */
  _reload() {
    this._destroyEditor();
    this._state = { loading: true };
    this._render();
    this._load();
  }

  /** Where a wikilink in the editor goes, and the name to show for it. */
  _resolveLink(target) {
    const inPanel = this._variant === "panel";
    const known = this._state.links?.[target];
    const path = known?.path || this._notePaths?.get(target);
    if (!path) {
      // A link to a note that doesn't exist yet creates it, as in Obsidian.
      const newPath = `${target}.md`;
      let href = null;
      if (inPanel) href = `#notes-vault-path=${encodeURIComponent(newPath)}`;
      else if (this._state.canEdit) href = panelHref(newPath);
      return { href, exists: false };
    }
    const href = inPanel
      ? `#notes-vault-path=${encodeURIComponent(path)}`
      : (known && haHref(known)) || panelHref(path);
    return { href, label: this._noteNames?.get(path), exists: true };
  }

  /**
   * The notes a `[[` can complete to. A link uses the file name when that's
   * unique in the vault, as Obsidian does, and the full path otherwise.
   */
  async _noteOptions() {
    const notes = await listNotes(this.hass);
    const counts = new Map();
    for (const note of notes) {
      const name = fileName(note.path);
      counts.set(name, (counts.get(name) || 0) + 1);
    }
    this._notePaths = new Map();
    this._noteNames = new Map();
    const options = notes.map((note) => {
      const full = note.path.replace(/\.md$/, "");
      const name = fileName(note.path);
      this._notePaths.set(full, note.path);
      if (!this._notePaths.has(name)) this._notePaths.set(name, note.path);
      if (note.name) this._noteNames.set(note.path, note.name);
      return {
        target: counts.get(name) > 1 ? full : name,
        label: note.name || name,
        detail: note.path.includes("/") ? note.path.slice(0, note.path.lastIndexOf("/")) : "",
      };
    });
    return options;
  }

  async _pickTemplate(name) {
    this._state.templateName = name;
    if (name === BLANK) {
      this._state.draft = "";
    } else {
      const result = await this.hass.callWS({ type: "notes_vault/template", name, ...this._target });
      this._state.draft = result.template?.body ?? "";
    }
    // Another template is still an untouched note, not something to save.
    this._base = this._state.draft;
    this._editor?.setValue(this._state.draft);
    this._render();
  }

  _cancel() {
    if (this._target.path && !this._state.exists) {
      // Nothing to go back to: the note was never saved.
      this._fire("notes-vault-changed", { path: this._state.path, deleted: true });
      return;
    }
    this._destroyEditor();
    this._state = {
      ...this._state,
      editing: false,
      draft: undefined,
      error: undefined,
      templates: undefined,
      templateName: undefined,
    };
    this._render();
  }

  _rename() {
    this._fire("notes-vault-rename", { path: this._state.path });
  }

  _openInHa() {
    const href = haHref(this._state.ha);
    if (href?.startsWith("#notes-vault-entity=")) {
      this._fire("hass-more-info", { entityId: href.split("=")[1] });
    } else if (href) {
      navigate(href);
    }
  }

  _fire(type, detail) {
    this.dispatchEvent(new CustomEvent(type, { detail, bubbles: true, composed: true }));
  }

  _onClick(ev) {
    const anchor = ev.composedPath().find((el) => el.tagName === "A");
    const href = anchor?.getAttribute("href") || "";
    const action = ev.composedPath().find((el) => el.dataset?.action)?.dataset.action;
    const open = ev.composedPath().find((el) => el.dataset?.open)?.dataset.open;
    if (href.startsWith("#notes-vault-entity=")) {
      ev.preventDefault();
      ev.stopPropagation();
      this._fire("hass-more-info", { entityId: href.slice("#notes-vault-entity=".length) });
    } else if (href.startsWith("#notes-vault-path=")) {
      ev.preventDefault();
      ev.stopPropagation();
      this._fire("notes-vault-open", { path: decodeURIComponent(href.slice("#notes-vault-path=".length)) });
    } else if (href.startsWith("/config/") || href.startsWith(`${PANEL_PATH}?`)) {
      // Close the more-info dialog if the note is in one, then go.
      ev.preventDefault();
      ev.stopPropagation();
      this._fire("hass-more-info", { entityId: null });
      navigate(href);
    } else if (open) {
      this._fire("notes-vault-open", { path: open });
    } else if (action && this[`_${action}`]) {
      this[`_${action}`]();
    }
  }

  /**
   * The template menu, offered while the note is still a template: the first
   * keystroke makes it yours, and switching then would throw the text away.
   */
  _templateMenu() {
    const s = this._state;
    if (!s.editing || !s.templates?.length || s.draft !== this._base) return "";
    if (!customElements.get("ha-dropdown")) return "";
    const items = [...s.templates, BLANK]
      .map(
        (t) =>
          // A tick on the current one only: a checkbox on every item reads as
          // "pick several".
          `<ha-dropdown-item value="${escapeHtml(t)}"><ha-svg-icon slot="icon" ${t === s.templateName ? `path="${MDI_CHECK}"` : ""}></ha-svg-icon>${escapeHtml(t === BLANK ? "Blank" : t)}</ha-dropdown-item>`,
      )
      .join("");
    return `<ha-dropdown class="template-menu" placement="top-start"><ha-button slot="trigger" size="s" appearance="plain" with-caret>Template</ha-button>${items}</ha-dropdown>`;
  }

  _button(action, label, { appearance = "plain", variant, disabled = false } = {}) {
    return `<ha-button size="s" appearance="${appearance}" ${variant ? `variant="${variant}"` : ""} data-action="${action}" ${disabled ? "disabled" : ""}>${escapeHtml(label)}</ha-button>`;
  }

  _render() {
    const s = this._state;
    if (s.unavailable) {
      this.shadowRoot.innerHTML = "";
      return;
    }
    const variant = this._variant;
    const inPanel = variant === "panel";
    const title = inPanel
      ? s.frontmatter?.name || fileName(s.path || this._target?.path) || "Notes"
      : this.getAttribute("heading") || "Notes";

    let body;
    if (s.loading) {
      body = `<ha-spinner size="small"></ha-spinner>`;
    } else if (s.editing) {
      const form = s.plain ? `<ha-form></ha-form>` : "";
      const editor = s.plain ? "" : `<div class="editor-slot"></div>`;
      const reload = s.conflict ? `<ha-button slot="action" size="s" data-action="reload">Load the new version</ha-button>` : "";
      const error = s.error ? `<ha-alert alert-type="${s.conflict ? "warning" : "error"}">${escapeHtml(s.error)}${reload}</ha-alert>` : "";
      body = `${form}${editor}${error}`;
    } else if (s.error) {
      body = `<ha-alert alert-type="error">${escapeHtml(s.error)}</ha-alert>`;
    } else if (s.note || (inPanel && s.template?.body)) {
      body = `<ha-markdown breaks></ha-markdown>`;
    } else {
      body = `<span class="empty">No notes yet.</span>`;
    }
    const showPath = s.path && (inPanel || s.editing || s.note);
    const path = showPath ? `<span class="path">${escapeHtml(s.path)}</span>` : "";

    let actions = "";
    const menu = this._templateMenu();
    if (s.editing && !this._autosaves) {
      actions =
        (menu ? `${menu}<span class="spacer"></span>` : "") +
        this._button("cancel", "Cancel", { disabled: s.saving }) +
        this._button("save", s.saving ? "Saving…" : "Save", { appearance: "filled", disabled: s.saving });
    } else if (!s.loading && (!s.error || s.editing) && s.canEdit) {
      const extra = [];
      if (inPanel && s.ha) {
        const label = { entity: "Show entity", device: "Go to device", area: "Go to area", integration: "Go to integration" }[s.ha.type];
        extra.push(this._button("openInHa", label));
      }
      // Generated notes are named after what they're about, so only the user's
      // own notes can be renamed.
      if (inPanel && s.exists && !s.ha) extra.push(this._button("rename", "Rename"));
      if (inPanel && s.exists && !s.ha) {
        extra.push(
          this._button("delete", s.confirmDelete ? "Delete for good" : "Delete", {
            variant: "danger",
            appearance: s.confirmDelete ? "filled" : "plain",
          }),
        );
      }
      const hasText = s.note || (inPanel && s.template?.body);
      if (menu) extra.push(menu);
      const end = this._autosaves
        ? `<span class="status">${escapeHtml(this._statusText())}</span>`
        : this._button("edit", hasText ? "Edit" : "Add note");
      actions = extra.join("") + `<span class="spacer"></span>` + end;
    }

    const content = `<div class="body">${path}${body}</div>`;
    const card = `
      <ha-card header="${escapeHtml(title)}">
        <div class="card-content">${content}</div>
        ${actions ? `<div class="card-actions">${actions}</div>` : ""}
      </ha-card>`;

    let backlinks = "";
    if (inPanel && s.backlinks?.length && (!s.editing || this._autosaves)) {
      backlinks = `
        <ha-card header="Linked mentions">
          <ha-list>
            ${s.backlinks
              .map(
                (b) => `
              <ha-list-item twoline data-open="${escapeHtml(b.path)}">
                <span>${escapeHtml(b.name || fileName(b.path))}</span>
                <span slot="secondary">${escapeHtml(b.snippet)}</span>
              </ha-list-item>`,
              )
              .join("")}
          </ha-list>
        </ha-card>`;
    }

    this.shadowRoot.innerHTML =
      variant === "inline"
        ? `<style>${STYLE}</style>
           <ha-expansion-panel outlined expanded header="${escapeHtml(title)}">
             <div class="panel-body">${content}${actions ? `<div class="actions">${actions}</div>` : ""}</div>
           </ha-expansion-panel>`
        : `<style>${STYLE}</style>${card}${backlinks}`;

    const md = this.shadowRoot.querySelector("ha-markdown");
    if (md) {
      md.hass = this.hass;
      // The panel shows a note as it is on disk, so an untouched template shows too.
      const text = s.note || (inPanel ? s.template?.body : "") || "";
      md.content = renderWikilinks(text, s.links, { inPanel, canBrowse: s.canEdit });
    }

    if (s.editing && !s.plain) this._mountEditor();
    this.shadowRoot
      .querySelector(".template-menu")
      ?.addEventListener("wa-select", (ev) => this._pickTemplate(ev.detail.item.value));

    const form = this.shadowRoot.querySelector("ha-form");
    if (form) {
      form.hass = this.hass;
      form.schema = [NOTE_FIELD];
      form.data = { note: s.draft ?? "" };
      form.disabled = !!s.saving;
      form.computeLabel = () => "";
      form.computeHelper = (field) =>
        field.name === "note" ? "Markdown. Link with [[light.kitchen]] or [[Device name]]." : "";
      form.addEventListener("value-changed", (ev) => {
        this._changed(ev.detail.value.note ?? "");
        form.data = { note: this._state.draft };
      });
    }
  }
}

if (!customElements.get("notes-vault-note")) {
  customElements.define("notes-vault-note", NotesVaultNote);
}

/* -- Notes panel ------------------------------------------------------------------ */

const PANEL_STYLE = `
  :host { display: block; height: 100%; }
  .layout { display: flex; height: calc(100vh - var(--header-height, 56px)); }
  .sidebar {
    width: 320px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--divider-color);
    background: var(--card-background-color);
  }
  .sidebar ha-input-search { margin: 8px; }
  .list { flex: 1; overflow-y: auto; }
  .main { flex: 1; overflow-y: auto; padding: 16px; box-sizing: border-box; }
  .main > * { max-width: 900px; margin: 0 auto; }
  :host([narrow]) .sidebar { width: 100%; border-right: none; }
  :host([narrow]) .layout.showing-note .sidebar, :host([narrow]) .layout:not(.showing-note) .main { display: none; }
  .empty { color: var(--secondary-text-color); padding: 32px 16px; text-align: center; }
  .secondary { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); word-break: break-all; }
  .card-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .card-actions .spacer { flex: 1; }
  ha-alert { display: block; margin-top: 8px; }
  ha-list-item { --mdc-list-item-graphic-margin: 16px; }
`;

const parentOf = (path) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
const baseName = (path) => path.split("/").pop();

/**
 * The Notes panel: the vault as a tree on the left, the note or folder on the right.
 * `?path=` opens a note, `?folder=` a folder.
 */
class NotesVaultPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._notes = [];
    this._folders = [];
    this._locked = new Set();
    this._query = "";
    this._results = null;
    this._form = null;
    try {
      this._expanded = new Set(JSON.parse(localStorage.getItem("notes-vault-expanded") || "[]"));
    } catch (err) {
      this._expanded = new Set();
    }
    this._onLocation = () => this._syncFromUrl();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._init();
    for (const el of this.shadowRoot.querySelectorAll("ha-menu-button, notes-vault-note, ha-form")) el.hass = hass;
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this.toggleAttribute("narrow", !!narrow);
    this._renderNav();
  }

  set route(route) {
    this._route = route;
    if (this._hass) this._syncFromUrl();
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    window.addEventListener("location-changed", this._onLocation);
    window.addEventListener("popstate", this._onLocation);
  }

  disconnectedCallback() {
    window.removeEventListener("location-changed", this._onLocation);
    window.removeEventListener("popstate", this._onLocation);
  }

  _init() {
    this.shadowRoot.innerHTML = `
      <style>${PANEL_STYLE}</style>
      <ha-top-app-bar-fixed>
        <span slot="navigationIcon" class="nav"></span>
        <div slot="title">Notes</div>
        <ha-icon-button slot="actionItems" label="New folder" data-action="newFolder">
          <ha-icon icon="mdi:folder-plus-outline"></ha-icon>
        </ha-icon-button>
        <ha-icon-button slot="actionItems" label="New note" data-action="newNote">
          <ha-icon icon="mdi:note-plus-outline"></ha-icon>
        </ha-icon-button>
        <div class="layout">
          <div class="sidebar">
            <ha-input-search appearance="outlined" placeholder="Search notes" with-clear></ha-input-search>
            <div class="list"></div>
          </div>
          <div class="main"></div>
        </div>
      </ha-top-app-bar-fixed>`;
    const search = this.shadowRoot.querySelector("ha-input-search");
    search.addEventListener("input", (ev) => this._onSearch(ev.target.value ?? search.value));
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
    this.shadowRoot.addEventListener("notes-vault-open", (ev) => {
      ev.stopPropagation();
      this._go({ path: ev.detail.path });
    });
    this.shadowRoot.addEventListener("notes-vault-rename", (ev) => {
      ev.stopPropagation();
      this._renameForm(ev.detail.path, false);
    });
    this.shadowRoot.addEventListener("notes-vault-changed", (ev) => {
      ev.stopPropagation();
      if (ev.detail.deleted) this._go({ folder: parentOf(ev.detail.path) || null });
      this._loadTree();
    });
    this._renderNav();
    this._loadTree();
    this._syncFromUrl();
  }

  // -- Navigation ----------------------------------------------------------------

  _selection() {
    const params = new URLSearchParams(location.search);
    return { path: params.get("path"), folder: params.get("folder") };
  }

  _syncFromUrl() {
    if (!location.pathname.startsWith(PANEL_PATH)) return;
    const { path, folder } = this._selection();
    if (path !== (this._path ?? null) || folder !== (this._folder ?? null) || this._form) {
      this._show({ path, folder });
    }
  }

  /** Open a note or a folder, and put it in the URL. */
  _go({ path = null, folder = null }) {
    let url = PANEL_PATH;
    if (path) url = panelHref(path);
    else if (folder) url = `${PANEL_PATH}?folder=${encodeURIComponent(folder)}`;
    history.pushState(null, "", url);
    this._show({ path, folder });
  }

  _show({ path, folder }) {
    this._path = path || null;
    this._folder = path ? null : folder || null;
    this._form = null;
    this._confirmDelete = false;
    // Reveal the selection in the tree: open its parents, not the folder itself,
    // which the user toggles.
    const target = parentOf(path || folder || "");
    const parts = target ? target.split("/") : [];
    parts.forEach((_p, i) => this._expanded.add(parts.slice(0, i + 1).join("/")));
    this._renderMain();
    this._renderList();
    this._renderNav();
  }

  _renderNav() {
    const nav = this.shadowRoot.querySelector(".nav");
    if (!nav) return;
    const showBack = this._narrow && (this._path || this._folder || this._form);
    nav.innerHTML = showBack
      ? `<ha-icon-button label="Back" data-action="back"><ha-icon icon="mdi:arrow-left"></ha-icon></ha-icon-button>`
      : `<ha-menu-button></ha-menu-button>`;
    const menu = nav.querySelector("ha-menu-button");
    if (menu) {
      menu.hass = this._hass;
      menu.narrow = this._narrow;
    }
    this.shadowRoot.querySelector(".layout")?.classList.toggle("showing-note", !!showBack);
  }

  // -- Data ----------------------------------------------------------------------

  async _loadTree() {
    try {
      const result = await this._hass.callWS({ type: "notes_vault/tree" });
      this._notes = result.notes;
      this._folders = result.folders;
      this._locked = new Set(result.locked);
      this._treeError = null;
    } catch (err) {
      this._notes = [];
      this._treeError = err.message || String(err);
    }
    this._renderList();
    if (this._folder && !this._form) this._renderMain();
  }

  _allFolders() {
    const folders = new Set(this._folders);
    for (const n of this._notes) {
      const parts = n.path.split("/").slice(0, -1);
      parts.forEach((_p, i) => folders.add(parts.slice(0, i + 1).join("/")));
    }
    return [...folders].sort((a, b) => a.localeCompare(b));
  }

  _isLocked(folder) {
    return [...this._locked].some((l) => l === folder || l.startsWith(`${folder}/`));
  }

  // -- Main pane -----------------------------------------------------------------

  _renderMain() {
    const main = this.shadowRoot.querySelector(".main");
    if (!main) return;
    if (this._form) {
      this._renderForm(main);
      return;
    }
    if (this._folder) {
      this._renderFolder(main);
      return;
    }
    if (!this._path) {
      main.innerHTML = `<div class="empty">Pick a note, or create one.</div>`;
      return;
    }
    let note = main.querySelector("notes-vault-note");
    if (!note) {
      main.innerHTML = "";
      note = document.createElement("notes-vault-note");
      note.setAttribute("variant", "panel");
      main.appendChild(note);
    }
    note.hass = this._hass;
    note.setTarget({ path: this._path });
  }

  _renderFolder(main) {
    const folder = this._folder;
    const prefix = `${folder}/`;
    const notes = this._notes.filter((n) => n.path.startsWith(prefix)).length;
    const folders = this._allFolders().filter((f) => f.startsWith(prefix)).length;
    const locked = this._isLocked(folder);
    const empty = !notes && !folders;
    const count = [notes && `${notes} ${notes === 1 ? "note" : "notes"}`, folders && `${folders} ${folders === 1 ? "folder" : "folders"}`]
      .filter(Boolean)
      .join(", ");
    main.innerHTML = `
      <ha-card header="${escapeHtml(baseName(folder))}">
        <div class="card-content">
          <div class="secondary">${escapeHtml(folder)}</div>
          <p>${escapeHtml(count || "Empty folder.")}</p>
          ${locked ? `<ha-alert alert-type="info">Home Assistant writes the generated notes here. Change where they go in the integration's options.</ha-alert>` : ""}
          ${!locked && !empty && this._confirmDelete ? `<ha-alert alert-type="warning">Only empty folders can be deleted here. Move or delete what's inside first.</ha-alert>` : ""}
        </div>
        <div class="card-actions">
          <ha-button size="s" appearance="plain" data-action="newNote">New note here</ha-button>
          <ha-button size="s" appearance="plain" data-action="newFolder">New folder here</ha-button>
          <span class="spacer"></span>
          ${locked ? "" : `<ha-button size="s" appearance="plain" data-action="renameFolder">Rename</ha-button>`}
          ${locked ? "" : `<ha-button size="s" appearance="${this._confirmDelete && empty ? "filled" : "plain"}" variant="danger" data-action="deleteFolder">${this._confirmDelete && empty ? "Delete for good" : "Delete"}</ha-button>`}
        </div>
      </ha-card>`;
  }

  /** One form for new notes, new folders and renames. */
  _renderForm(main) {
    const f = this._form;
    main.innerHTML = `
      <ha-card header="${escapeHtml(f.title)}">
        <div class="card-content">
          <ha-form></ha-form>
          ${f.error ? `<ha-alert alert-type="error">${escapeHtml(f.error)}</ha-alert>` : ""}
        </div>
        <div class="card-actions">
          <span class="spacer"></span>
          <ha-button size="s" appearance="plain" data-action="cancelForm">Cancel</ha-button>
          <ha-button size="s" appearance="filled" data-action="submitForm">${escapeHtml(f.submit)}</ha-button>
        </div>
      </ha-card>`;
    const form = main.querySelector("ha-form");
    const folders = this._allFolders().filter((x) => !f.excludeFolder || (x !== f.excludeFolder && !x.startsWith(`${f.excludeFolder}/`)));
    form.hass = this._hass;
    form.schema = [
      { name: "name", required: true, selector: { text: {} } },
      {
        name: "folder",
        selector: {
          select: {
            mode: "dropdown",
            custom_value: true,
            options: ["", ...folders].map((x) => ({ value: x, label: x || "Top level" })),
          },
        },
      },
    ];
    form.data = f.data;
    form.computeLabel = (field) => ({ name: "Name", folder: "Folder" })[field.name];
    form.addEventListener("value-changed", (ev) => {
      f.data = ev.detail.value;
      form.data = f.data;
    });
    form.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") this._submitForm();
    });
    // ha-form renders its fields asynchronously; focus the name once they exist.
    form.updateComplete?.then(() =>
      setTimeout(() => {
        const field = form.shadowRoot?.querySelector("ha-selector")?.shadowRoot?.querySelector("*");
        (field?.focus ? field : form).focus?.();
      }, 150),
    );
  }

  _openForm(form) {
    this._form = form;
    this._renderMain();
    this._renderNav();
  }

  _currentFolder() {
    if (this._folder) return this._folder;
    if (this._path) return parentOf(this._path);
    return "";
  }

  _renameForm(path, isFolder) {
    this._openForm({
      title: isFolder ? "Rename folder" : "Rename note",
      submit: "Rename",
      data: { name: isFolder ? baseName(path) : baseName(path).replace(/\.md$/, ""), folder: parentOf(path) },
      excludeFolder: isFolder ? path : null,
      run: async ({ name, folder }) => {
        const to = [folder, isFolder ? name : `${name.replace(/\.md$/, "")}.md`].filter(Boolean).join("/");
        const result = await this._hass.callWS({ type: "notes_vault/move", path, to });
        await this._loadTree();
        this._go(isFolder ? { folder: result.path } : { path: result.path });
      },
    });
  }

  async _submitForm() {
    const f = this._form;
    const name = (f.data.name || "").trim();
    if (!name) return;
    try {
      await f.run({ ...f.data, name });
    } catch (err) {
      f.error = err.message || String(err);
      this._renderMain();
    }
  }

  // -- Search --------------------------------------------------------------------

  _onSearch(value) {
    this._query = value || "";
    clearTimeout(this._searchTimer);
    if (!this._query.trim()) {
      this._results = null;
      this._renderList();
      return;
    }
    this._searchTimer = setTimeout(async () => {
      const query = this._query;
      const result = await this._hass.callWS({ type: "notes_vault/search", query });
      if (query === this._query) {
        this._results = result.results;
        this._renderList();
      }
    }, 250);
  }

  // -- Clicks --------------------------------------------------------------------

  async _onClick(ev) {
    const path = ev.composedPath();
    const action = path.find((el) => el.dataset?.action)?.dataset.action;
    const folder = path.find((el) => el.hasAttribute?.("data-folder"))?.dataset.folder;
    const file = path.find((el) => el.hasAttribute?.("data-file"))?.dataset.file;
    if (action === "newNote") {
      this._openForm({
        title: "New note",
        submit: "Create",
        data: { name: "", folder: this._currentFolder() },
        run: async ({ name, folder: parent }) => {
          const target = [parent, `${name.replace(/\.md$/, "")}.md`].filter(Boolean).join("/");
          this._go({ path: target });
        },
      });
    } else if (action === "newFolder") {
      this._openForm({
        title: "New folder",
        submit: "Create",
        data: { name: "", folder: this._currentFolder() },
        run: async ({ name, folder: parent }) => {
          const result = await this._hass.callWS({
            type: "notes_vault/mkdir",
            path: [parent, name].filter(Boolean).join("/"),
          });
          await this._loadTree();
          this._go({ folder: result.path });
        },
      });
    } else if (action === "renameFolder") {
      this._renameForm(this._folder, true);
    } else if (action === "deleteFolder") {
      if (!this._confirmDelete) {
        this._confirmDelete = true;
        this._renderMain();
        return;
      }
      const folder = this._folder;
      const prefix = `${folder}/`;
      if (this._notes.some((n) => n.path.startsWith(prefix)) || this._allFolders().some((f) => f.startsWith(prefix))) return;
      await this._hass.callWS({ type: "notes_vault/delete", path: folder });
      this._confirmDelete = false;
      await this._loadTree();
      this._go({ folder: parentOf(folder) || null });
    } else if (action === "submitForm") {
      this._submitForm();
    } else if (action === "cancelForm") {
      this._form = null;
      this._renderMain();
      this._renderNav();
    } else if (action === "back") {
      this._go({});
    } else if (folder !== undefined) {
      if (this._expanded.has(folder)) this._expanded.delete(folder);
      else this._expanded.add(folder);
      try {
        localStorage.setItem("notes-vault-expanded", JSON.stringify([...this._expanded]));
      } catch (err) {
        // Private mode: the tree just won't remember.
      }
      this._go({ folder });
    } else if (file) {
      this._go({ path: file });
    }
  }

  // -- Tree ----------------------------------------------------------------------

  _renderList() {
    const list = this.shadowRoot.querySelector(".list");
    if (!list) return;
    if (this._treeError) {
      list.innerHTML = `<ha-alert alert-type="error">${escapeHtml(this._treeError)}</ha-alert>`;
      return;
    }
    if (this._results) {
      list.innerHTML = this._results.length
        ? `<ha-list>${this._results
            .map(
              (r) => `
            <ha-list-item twoline graphic="icon" data-file="${escapeHtml(r.path)}" ${r.path === this._path ? "activated" : ""}>
              <ha-icon slot="graphic" icon="mdi:file-document-outline"></ha-icon>
              <span>${escapeHtml(this._displayName(r.path))}</span>
              <span slot="secondary">${escapeHtml(r.snippet || r.path)}</span>
            </ha-list-item>`,
            )
            .join("")}</ha-list>`
        : `<div class="empty">No notes match.</div>`;
      return;
    }
    list.innerHTML = `<ha-list>${this._treeRows("", 0).join("")}</ha-list>`;
  }

  _displayName(path) {
    return this._notes.find((n) => n.path === path)?.name || fileName(path);
  }

  /** Rows for one folder level: subfolders first, then notes, sorted by name. */
  _treeRows(folder, depth) {
    const folders = this._allFolders().filter((f) => parentOf(f) === folder);
    const files = this._notes.filter((n) => parentOf(n.path) === folder);
    const indent = `style="--mdc-list-side-padding-left: ${16 + depth * 20}px"`;
    const rows = [];
    for (const full of folders) {
      const open = this._expanded.has(full);
      rows.push(`
        <ha-list-item graphic="icon" data-folder="${escapeHtml(full)}" ${indent} ${full === this._folder ? "activated" : ""}>
          <ha-icon slot="graphic" icon="${open ? "mdi:folder-open-outline" : "mdi:folder-outline"}"></ha-icon>
          ${escapeHtml(baseName(full))}
        </ha-list-item>`);
      if (open) rows.push(...this._treeRows(full, depth + 1));
    }
    const label = (n) => n.name || fileName(n.path);
    for (const note of files.sort((a, b) => label(a).localeCompare(label(b)))) {
      rows.push(`
        <ha-list-item graphic="icon" data-file="${escapeHtml(note.path)}" ${indent} ${note.path === this._path ? "activated" : ""}>
          <ha-icon slot="graphic" icon="mdi:file-document-outline"></ha-icon>
          ${escapeHtml(label(note))}
        </ha-list-item>`);
    }
    return rows;
  }
}

if (!customElements.get("notes-vault-panel")) {
  customElements.define("notes-vault-panel", NotesVaultPanel);
}

/* -- Dashboard card ------------------------------------------------------------- */

class NotesVaultCard extends HTMLElement {
  setConfig(config) {
    const keys = ["entity", "device_id", "area_id"].filter((k) => config[k]);
    if (keys.length !== 1) {
      throw new Error("Set exactly one of entity, device_id or area_id");
    }
    this._config = config;
    if (!this._note) {
      this._note = document.createElement("notes-vault-note");
      this._note.setAttribute("variant", "card");
      this.appendChild(this._note);
    }
    this._note.setAttribute("heading", config.title || "Notes");
    this._note.setTarget(
      config.entity ? { entity_id: config.entity } : config.device_id ? { device_id: config.device_id } : { area_id: config.area_id },
    );
  }

  set hass(hass) {
    if (this._note) this._note.hass = hass;
  }

  getCardSize() {
    return 3;
  }

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states)[0];
    return { entity };
  }
}

if (!customElements.get("notes-vault-card")) {
  customElements.define("notes-vault-card", NotesVaultCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "notes-vault-card",
    name: "Notes Vault",
    description: "Shows and edits the note of an entity, device or area.",
  });
}

/* -- Injection into the Home Assistant UI --------------------------------------- */

/** Breadth-first search through shadow roots, bounded so a miss stays cheap. */
const deepFind = (root, selector, maxNodes = 4000) => {
  const queue = [root];
  let seen = 0;
  while (queue.length && seen < maxNodes) {
    const node = queue.shift();
    const scope = node.shadowRoot || node;
    const hit = scope.querySelector?.(selector);
    if (hit) return hit;
    for (const child of scope.querySelectorAll?.("*") || []) {
      seen += 1;
      if (child.shadowRoot) queue.push(child.shadowRoot.host === child ? child : child.shadowRoot);
    }
  }
  return null;
};

const ensureNote = (container, before, target, variant, style) => {
  let note = container.querySelector(":scope > notes-vault-note");
  if (!note) {
    note = document.createElement("notes-vault-note");
    note.setAttribute("variant", variant);
    if (style) note.setAttribute("style", style);
    if (before) container.insertBefore(note, before);
    else container.appendChild(note);
  }
  note.hass = getHass();
  note.setTarget(target);
};

const injectMoreInfo = (ha) => {
  const dialog = ha.shadowRoot?.querySelector("ha-more-info-dialog");
  const info = dialog?.shadowRoot?.querySelector("ha-more-info-info");
  const content = info?.shadowRoot?.querySelector("div.content");
  if (!content || !info.entityId) return;
  ensureNote(content, null, { entity_id: info.entityId }, "inline");
};

/** The entity of an automation or scene, found by the config ID in the editor URL. */
const entityByConfigId = (hass, domain, id) =>
  Object.values(hass.states).find((s) => s.entity_id.startsWith(`${domain}.`) && s.attributes.id === id)
    ?.entity_id;

/** Line the notes up with the editors' own cards. */
const EDITOR_STYLE = "margin: 8px 8px 24px";

/**
 * Pages that get a notes section. `target` turns the URL into the object the note
 * is about, `place` finds where the section goes: a container and the element to
 * insert before (null appends).
 */
const PAGES = [
  {
    path: /^\/config\/devices\/device\/([^/]+)/,
    tag: "ha-config-device-page",
    variant: "card",
    target: (id) => ({ device_id: id }),
    // Right below the device's own info card.
    place: (root) => {
      const column = root.querySelector(".column");
      return column && [column, column.querySelector(":scope > ha-device-info-card")?.nextElementSibling];
    },
  },
  {
    path: /^\/config\/areas\/area\/([^/]+)/,
    tag: "ha-config-area-page",
    variant: "card",
    target: (id) => ({ area_id: id }),
    // At the top of the first column.
    place: (root) => {
      const column = root.querySelector(".column");
      return column && [column, column.querySelector(":scope > ha-card")];
    },
  },
  {
    path: /^\/config\/automation\/edit\/([^/]+)/,
    tag: "ha-automation-editor",
    variant: "inline",
    style: EDITOR_STYLE,
    target: (id, hass) => {
      const entityId = entityByConfigId(hass, "automation", id);
      return entityId && { entity_id: entityId };
    },
    // Below the triggers, conditions and actions.
    place: (root) => {
      const editor = root.querySelector("manual-automation-editor, blueprint-automation-editor");
      return editor && [editor.parentElement, null];
    },
  },
  {
    path: /^\/config\/script\/edit\/([^/]+)/,
    tag: "ha-script-editor",
    variant: "inline",
    style: EDITOR_STYLE,
    target: (id, hass) => (hass.states[`script.${id}`] ? { entity_id: `script.${id}` } : null),
    place: (root) => {
      const editor = root.querySelector("manual-script-editor, blueprint-script-editor");
      return editor && [editor.parentElement, null];
    },
  },
  {
    path: /^\/config\/scene\/edit\/([^/]+)/,
    tag: "ha-scene-editor",
    variant: "inline",
    style: EDITOR_STYLE,
    target: (id, hass) => {
      const entityId = entityByConfigId(hass, "scene", id);
      return entityId && { entity_id: entityId };
    },
    // After the last section of the scene editor.
    place: (root) => {
      const sections = root.querySelectorAll("ha-config-section");
      const last = sections[sections.length - 1];
      return last && [last.parentElement, null];
    },
  },
];

let pageCache = { path: null, page: null };

const injectPage = (ha) => {
  const path = location.pathname;
  let match = null;
  const spec = PAGES.find((p) => (match = path.match(p.path)));
  if (!spec) {
    pageCache = { path: null, page: null };
    return;
  }
  const target = spec.target(decodeURIComponent(match[1]), ha.hass);
  if (!target) return;
  let page = pageCache.path === path && pageCache.page?.isConnected ? pageCache.page : null;
  if (!page) {
    page = deepFind(ha, spec.tag);
    pageCache = { path, page };
  }
  const spot = page?.shadowRoot && spec.place(page.shadowRoot);
  if (!spot) return;
  ensureNote(spot[0], spot[1] || null, target, spec.variant, spec.style);
};

const tick = () => {
  const ha = document.querySelector("home-assistant");
  if (!ha?.hass) return;
  try {
    injectMoreInfo(ha);
    injectPage(ha);
  } catch (err) {
    // Log once: a frontend change must not turn into an error every tick.
    if (!window.__notesVaultWarned) {
      window.__notesVaultWarned = true;
      console.warn("Notes Vault could not attach to this page", err);
    }
  }
};

if (!window.__notesVaultStarted) {
  window.__notesVaultStarted = true;
  setInterval(tick, POLL_MS);
  console.info(`%c NOTES-VAULT %c ${VERSION} `, "background:#7c3aed;color:#fff;border-radius:3px 0 0 3px", "background:#ddd;color:#333;border-radius:0 3px 3px 0");
}
