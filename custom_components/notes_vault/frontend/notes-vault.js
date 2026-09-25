/*
 * Notes Vault frontend.
 *
 * One note editor, `notes-vault-note`, used everywhere: in the more-info dialog of
 * every entity, as a card on device and area pages, in `custom:notes-vault-card`, and
 * in the Notes panel in the sidebar, which lists every note in the vault.
 *
 * Home Assistant has no extension point for the dialog or the device and area pages,
 * so the editor is appended to the frontend's own DOM there. Every lookup is
 * defensive: if a frontend update moves things around, the notes stop showing up in
 * that spot, nothing breaks.
 *
 * Everything visible is a stock Home Assistant element (ha-card, ha-expansion-panel,
 * ha-markdown, ha-form, ha-button, ha-icon-button, ha-list, ha-input-search,
 * ha-top-app-bar-fixed, ha-spinner, ha-alert). The CSS here is layout and spacing
 * only, so the notes look like the rest of the UI and follow its theme.
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

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const fileName = (path) => (path || "").split("/").pop().replace(/\.md$/, "");

/** Navigate inside the app, the way Home Assistant's own links do. */
const navigate = (href) => {
  history.pushState(null, "", href);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
};

const panelHref = (path) => `${PANEL_PATH}?path=${encodeURIComponent(path)}`;

/** Where a link to an entity, device or area goes in Home Assistant. */
const haHref = (ha) => {
  if (!ha) return null;
  if (ha.type === "entity") return `#notes-vault-entity=${ha.id}`;
  if (ha.type === "device") return `/config/devices/device/${encodeURIComponent(ha.id)}`;
  if (ha.type === "area") return `/config/areas/area/${encodeURIComponent(ha.id)}`;
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
  .actions, .card-actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; }
  .card-actions .spacer { flex: 1; }
  ha-spinner { align-self: center; }
  ha-card + ha-card { margin-top: 16px; }
  ha-list { --mdc-list-vertical-padding: 0; }
`;

const NOTE_FIELD = { name: "note", selector: { text: { multiline: true } } };
const BLANK = "__blank__";

/** The editor's fields: a template picker while starting a note, then the text. */
const editorSchema = (templates) =>
  templates?.length
    ? [
        {
          name: "template",
          required: true,
          selector: {
            select: {
              mode: "dropdown",
              options: [...templates.map((t) => ({ value: t, label: t })), { value: BLANK, label: "Blank" }],
            },
          },
        },
        NOTE_FIELD,
      ]
    : [NOTE_FIELD];

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

  setTarget(target) {
    const key = JSON.stringify(target);
    if (key === this._targetKey) return;
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
        if (this._state.editing || !this._state.path) return;
        if (ev.data.path === this._state.path && ev.data.source !== "ui") this._load();
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
        // A note that doesn't exist yet, opened in the panel, is one being created.
        if (target.path && !result.exists && info.can_edit) {
          this._edit();
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
      const result = await this.hass.callWS({ type: "notes_vault/set", note, ...this._target });
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

  async _edit() {
    const starting = !this._state.note;
    this._state = { ...this._state, editing: true, draft: this._state.note || "", templates: undefined };
    // A new note on an entity, device or area starts from the template that fits it.
    if (starting && !this._target.path) {
      try {
        const result = await this.hass.callWS({ type: "notes_vault/template", ...this._target });
        this._state.templates = result.templates;
        this._state.templateName = result.template?.name ?? BLANK;
        this._state.draft = result.template?.body ?? "";
      } catch (err) {
        // No templates: start blank.
      }
    }
    this._render();
    // ha-form loads the text selector lazily; focus once it has rendered.
    setTimeout(() => this.shadowRoot.querySelector("ha-form")?.focus?.(), 200);
  }

  async _pickTemplate(name) {
    this._state.templateName = name;
    if (name === BLANK) {
      this._state.draft = "";
    } else {
      const result = await this.hass.callWS({ type: "notes_vault/template", name, ...this._target });
      this._state.draft = result.template?.body ?? "";
    }
    this._render();
  }

  _cancel() {
    if (this._target.path && !this._state.exists) {
      // Nothing to go back to: the note was never saved.
      this._fire("notes-vault-changed", { path: this._state.path, deleted: true });
      return;
    }
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
      body = `<ha-form></ha-form>${s.error ? `<ha-alert alert-type="error">${escapeHtml(s.error)}</ha-alert>` : ""}`;
    } else if (s.error) {
      body = `<ha-alert alert-type="error">${escapeHtml(s.error)}</ha-alert>`;
    } else if (s.note) {
      body = `<ha-markdown breaks></ha-markdown>`;
    } else {
      body = `<span class="empty">No notes yet.</span>`;
    }
    const showPath = s.path && (inPanel || s.editing || s.note);
    const path = showPath ? `<span class="path">${escapeHtml(s.path)}</span>` : "";

    let actions = "";
    if (s.editing) {
      actions =
        this._button("cancel", "Cancel", { disabled: s.saving }) +
        this._button("save", s.saving ? "Saving…" : "Save", { appearance: "filled", disabled: s.saving });
    } else if (!s.loading && !s.error && s.canEdit) {
      const extra = [];
      if (inPanel && s.ha) {
        const label = { entity: "Show entity", device: "Go to device", area: "Go to area" }[s.ha.type];
        extra.push(this._button("openInHa", label));
      }
      if (inPanel && s.exists && !s.ha) {
        extra.push(
          this._button("delete", s.confirmDelete ? "Delete for good" : "Delete", {
            variant: "danger",
            appearance: s.confirmDelete ? "filled" : "plain",
          }),
        );
      }
      actions = extra.join("") + `<span class="spacer"></span>` + this._button("edit", s.note ? "Edit" : "Add note");
    }

    const content = `<div class="body">${path}${body}</div>`;
    const card = `
      <ha-card header="${escapeHtml(title)}">
        <div class="card-content">${content}</div>
        ${actions ? `<div class="card-actions">${actions}</div>` : ""}
      </ha-card>`;

    let backlinks = "";
    if (inPanel && s.backlinks?.length && !s.editing) {
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
      md.content = renderWikilinks(s.note, s.links, { inPanel, canBrowse: s.canEdit });
    }

    const form = this.shadowRoot.querySelector("ha-form");
    if (form) {
      form.hass = this.hass;
      form.schema = editorSchema(s.templates);
      form.data = { note: s.draft ?? "", template: s.templateName };
      form.disabled = !!s.saving;
      form.computeLabel = (field) => (field.name === "template" ? "Template" : "");
      form.computeHelper = (field) =>
        field.name === "note" ? "Markdown. Link with [[light.kitchen]] or [[Device name]]." : "";
      form.addEventListener("value-changed", (ev) => {
        const value = ev.detail.value;
        if (value.template && value.template !== this._state.templateName) {
          this._pickTemplate(value.template);
          return;
        }
        this._state.draft = value.note ?? "";
        form.data = { note: this._state.draft, template: this._state.templateName };
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
  ha-list-item { --mdc-list-item-graphic-margin: 16px; }
`;

class NotesVaultPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._notes = [];
    this._query = "";
    this._results = null;
    this._creating = false;
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
    const menu = this.shadowRoot.querySelector("ha-menu-button");
    if (menu) menu.narrow = narrow;
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
        <ha-icon-button slot="actionItems" label="New note" data-action="new">
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
      this._open(ev.detail.path);
    });
    this.shadowRoot.addEventListener("notes-vault-changed", (ev) => {
      ev.stopPropagation();
      if (ev.detail.deleted) this._open(null);
      this._loadTree();
    });
    this._renderNav();
    this._loadTree();
    this._syncFromUrl();
  }

  _renderNav() {
    const nav = this.shadowRoot.querySelector(".nav");
    if (!nav) return;
    const showBack = this._narrow && (this._path || this._creating);
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

  async _loadTree() {
    try {
      const result = await this._hass.callWS({ type: "notes_vault/tree" });
      this._notes = result.notes;
    } catch (err) {
      this._notes = [];
      this._treeError = err.message || String(err);
    }
    this._renderList();
  }

  _syncFromUrl() {
    if (!location.pathname.startsWith(PANEL_PATH)) return;
    const path = new URLSearchParams(location.search).get("path");
    if (path !== (this._path ?? null)) this._show(path);
  }

  _open(path) {
    const url = path ? panelHref(path) : PANEL_PATH;
    history.pushState(null, "", url);
    this._show(path);
  }

  _show(path) {
    this._path = path || null;
    this._creating = false;
    // Reveal the note in the tree.
    if (path) {
      const parts = path.split("/").slice(0, -1);
      parts.forEach((_p, i) => this._expanded.add(parts.slice(0, i + 1).join("/")));
    }
    this._renderMain();
    this._renderList();
    this._renderNav();
  }

  _renderMain() {
    const main = this.shadowRoot.querySelector(".main");
    if (!main) return;
    if (this._creating) {
      main.innerHTML = `
        <ha-card header="New note">
          <div class="card-content"><ha-form></ha-form></div>
          <div class="card-actions" style="display:flex;justify-content:flex-end;gap:8px">
            <ha-button size="s" appearance="plain" data-action="back">Cancel</ha-button>
            <ha-button size="s" appearance="filled" data-action="create">Create</ha-button>
          </div>
        </ha-card>`;
      const folders = [...new Set(this._notes.map((n) => n.path.split("/").slice(0, -1).join("/")))]
        .filter((f) => f)
        .sort();
      const form = main.querySelector("ha-form");
      form.hass = this._hass;
      form.schema = [
        { name: "name", required: true, selector: { text: {} } },
        {
          name: "folder",
          selector: { select: { mode: "dropdown", custom_value: true, options: ["", ...folders].map((f) => ({ value: f, label: f || "Top level" })) } },
        },
      ];
      form.data = this._newNote || { name: "", folder: "" };
      form.computeLabel = (field) => ({ name: "Name", folder: "Folder" })[field.name];
      form.addEventListener("value-changed", (ev) => {
        this._newNote = ev.detail.value;
        form.data = this._newNote;
      });
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

  _onClick(ev) {
    const path = ev.composedPath();
    const action = path.find((el) => el.dataset?.action)?.dataset.action;
    const folder = path.find((el) => el.hasAttribute?.("data-folder"))?.dataset.folder;
    const file = path.find((el) => el.hasAttribute?.("data-file"))?.dataset.file;
    if (action === "new") {
      this._creating = true;
      this._newNote = { name: "", folder: this._path ? this._path.split("/").slice(0, -1).join("/") : "" };
      this._renderMain();
      this._renderNav();
    } else if (action === "back") {
      this._creating = false;
      this._open(null);
    } else if (action === "create") {
      const name = (this._newNote?.name || "").trim().replace(/\.md$/, "");
      if (!name) return;
      const target = [this._newNote.folder, `${name}.md`].filter((p) => p).join("/");
      this._open(target);
    } else if (folder !== undefined) {
      if (this._expanded.has(folder)) this._expanded.delete(folder);
      else this._expanded.add(folder);
      try {
        localStorage.setItem("notes-vault-expanded", JSON.stringify([...this._expanded]));
      } catch (err) {
        // Private mode: the tree just won't remember.
      }
      this._renderList();
    } else if (file) {
      this._open(file);
    }
  }

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
    const prefix = folder ? `${folder}/` : "";
    const folders = new Set();
    const files = [];
    for (const note of this._notes) {
      if (!note.path.startsWith(prefix)) continue;
      const rest = note.path.slice(prefix.length);
      const slash = rest.indexOf("/");
      if (slash === -1) files.push(note);
      else folders.add(rest.slice(0, slash));
    }
    const indent = `style="--mdc-list-side-padding-left: ${16 + depth * 20}px"`;
    const rows = [];
    for (const name of [...folders].sort((a, b) => a.localeCompare(b))) {
      const full = prefix + name;
      const open = this._expanded.has(full);
      rows.push(`
        <ha-list-item graphic="icon" data-folder="${escapeHtml(full)}" ${indent}>
          <ha-icon slot="graphic" icon="${open ? "mdi:folder-open-outline" : "mdi:folder-outline"}"></ha-icon>
          ${escapeHtml(name)}
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

const ensureNote = (container, before, target, variant) => {
  let note = container.querySelector(":scope > notes-vault-note");
  if (!note) {
    note = document.createElement("notes-vault-note");
    note.setAttribute("variant", variant);
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

let pageCache = { path: null, page: null };

const injectPage = (ha) => {
  const path = location.pathname;
  let tag;
  let target;
  let match = path.match(/^\/config\/devices\/device\/([^/]+)/);
  if (match) {
    tag = "ha-config-device-page";
    target = { device_id: match[1] };
  } else if ((match = path.match(/^\/config\/areas\/area\/([^/]+)/))) {
    tag = "ha-config-area-page";
    target = { area_id: decodeURIComponent(match[1]) };
  } else {
    pageCache = { path: null, page: null };
    return;
  }
  let page = pageCache.path === path && pageCache.page?.isConnected ? pageCache.page : null;
  if (!page) {
    page = deepFind(ha, tag);
    pageCache = { path, page };
  }
  const column = page?.shadowRoot?.querySelector(".column");
  if (!column) return;
  // Right below the device's own info card, or at the top of an area's first column.
  const anchor =
    tag === "ha-config-device-page"
      ? column.querySelector(":scope > ha-device-info-card")?.nextElementSibling
      : column.querySelector(":scope > ha-card");
  ensureNote(column, anchor || null, target, "card");
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
