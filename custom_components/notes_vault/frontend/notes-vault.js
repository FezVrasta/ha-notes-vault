/*
 * Notes Vault frontend.
 *
 * Adds a note section to the more-info dialog of every entity, and a notes card to
 * the device and area pages. Also defines `custom:notes-vault-card` for dashboards.
 *
 * Home Assistant has no extension point for any of these places, so the section is
 * appended to the frontend's own DOM. Every lookup is defensive: if a frontend update
 * moves things around, the notes simply stop showing up there, nothing breaks.
 */

const VERSION = "0.1.0";
const POLL_MS = 700;

const getHass = () => document.querySelector("home-assistant")?.hass;

let infoPromise;
const getInfo = (hass) => {
  if (!infoPromise) {
    infoPromise = hass.callWS({ type: "notes_vault/info" }).catch(() => {
      infoPromise = undefined;
      return { loaded: false };
    });
  }
  return infoPromise;
};

const ENTITY_ID = /^[a-z0-9_]+\.[a-z0-9_]+$/;
const ENTITY_HREF = "#notes-vault-entity=";

/**
 * Obsidian wikilinks mean nothing to Home Assistant's Markdown renderer. Links to
 * entities become links that open their more-info dialog; anything else is shown
 * as bold text.
 */
const renderWikilinks = (text, hass) =>
  text
    .replace(/!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/g, (_m, target, label) => `*${label || target.split("/").pop()}*`)
    .replace(/\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|([^\]]*))?\]\]/g, (_m, target, label) => {
      const name = target.split("/").pop();
      const shown = label || name;
      if (ENTITY_ID.test(name) && hass?.states?.[name]) return `[${shown}](${ENTITY_HREF}${name})`;
      return `**${shown}**`;
    });

const STYLE = `
  :host { display: block; }
  .section { padding: 16px 0 0; }
  :host([variant="inline"]) .section {
    margin-top: 16px;
    border-top: 1px solid var(--divider-color);
  }
  :host([variant="card"]) .section { padding: 0 16px 16px; }
  .header {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 40px;
  }
  .title {
    flex: 1;
    font-weight: 500;
    font-size: var(--ha-font-size-l, 16px);
    color: var(--primary-text-color);
  }
  :host([variant="card"]) .title {
    font-size: var(--ha-card-header-font-size, var(--ha-font-size-2xl, 24px));
    font-weight: var(--ha-font-weight-normal, 400);
    line-height: var(--ha-line-height-condensed, 32px);
    padding-top: 16px;
  }
  .path {
    font-size: var(--ha-font-size-s, 12px);
    color: var(--secondary-text-color);
    word-break: break-all;
    margin: -4px 0 8px;
  }
  .empty { color: var(--secondary-text-color); font-style: italic; margin: 4px 0 8px; }
  ha-markdown { display: block; overflow-wrap: anywhere; }
  textarea {
    box-sizing: border-box;
    width: 100%;
    min-height: 140px;
    resize: vertical;
    padding: 12px;
    border-radius: var(--ha-border-radius-md, 8px);
    border: 1px solid var(--outline-color, var(--divider-color));
    background: var(--secondary-background-color, transparent);
    color: var(--primary-text-color);
    font: var(--ha-font-size-m, 14px) / 1.5 var(--ha-font-family-code, ui-monospace, monospace);
  }
  textarea:focus { outline: 2px solid var(--primary-color); outline-offset: -1px; }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
  .hint { flex: 1; align-self: center; font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); }
  .error { color: var(--error-color); margin: 8px 0; }
  button.link {
    border: none;
    background: none;
    color: var(--primary-color);
    cursor: pointer;
    font: inherit;
    font-weight: 500;
    padding: 6px 8px;
    border-radius: 6px;
  }
  button.link:hover { background: var(--secondary-background-color); }
  button.link[disabled] { opacity: .5; cursor: default; }
  button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  button.primary:hover { background: var(--primary-color); filter: brightness(1.1); }
`;

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

class NotesVaultNote extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._target = null;
    this._state = { loading: true };
    this._unsub = null;
  }

  set hass(hass) {
    this._hass = hass;
  }

  get hass() {
    return this._hass || getHass();
  }

  /** The object the note belongs to: {entity_id}, {device_id} or {area_id}. */
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
      } else {
        const result = await hass.callWS({ type: "notes_vault/get", ...target });
        if (target !== this._target) return;
        this._state = { ...result, canEdit: info.can_edit };
      }
    } catch (err) {
      this._state = { error: err.message || String(err) };
    }
    this._render();
  }

  async _save() {
    const textarea = this.shadowRoot.querySelector("textarea");
    const note = textarea.value;
    this._state = { ...this._state, saving: true, draft: note, error: undefined };
    this._render();
    try {
      const result = await this.hass.callWS({ type: "notes_vault/set", note, ...this._target });
      this._state = { ...result, canEdit: this._state.canEdit };
    } catch (err) {
      this._state = { ...this._state, saving: false, error: err.message || String(err) };
    }
    this._render();
  }

  _edit() {
    this._state = { ...this._state, editing: true, draft: this._state.note || "" };
    this._render();
    const textarea = this.shadowRoot.querySelector("textarea");
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);
  }

  _cancel() {
    this._state = { ...this._state, editing: false, draft: undefined, error: undefined };
    this._render();
  }

  _render() {
    const s = this._state;
    if (s.unavailable) {
      this.shadowRoot.innerHTML = "";
      return;
    }
    const title = this.getAttribute("heading") || "Notes";
    let body = "";
    if (s.loading) {
      body = `<div class="empty">Loading…</div>`;
    } else if (s.editing) {
      const mac = navigator.platform.includes("Mac");
      body = `
        <textarea placeholder="Write in Markdown. Link with [[light.kitchen]] or [[Device name]].">${escapeHtml(s.draft ?? "")}</textarea>
        ${s.error ? `<div class="error">${escapeHtml(s.error)}</div>` : ""}
        <div class="actions">
          <span class="hint">${mac ? "⌘" : "Ctrl"}+Enter to save</span>
          <button class="link" data-action="cancel" ${s.saving ? "disabled" : ""}>Cancel</button>
          <button class="link primary" data-action="save" ${s.saving ? "disabled" : ""}>${s.saving ? "Saving…" : "Save"}</button>
        </div>`;
    } else if (s.error) {
      body = `<div class="error">${escapeHtml(s.error)}</div>`;
    } else if (s.note) {
      body = `<ha-markdown breaks></ha-markdown>`;
    } else {
      body = `<div class="empty">No notes yet.</div>`;
    }
    const editButton =
      !s.loading && !s.editing && s.canEdit && !s.error
        ? `<button class="link" data-action="edit">${s.note ? "Edit" : "Add note"}</button>`
        : "";
    const path = s.path && !s.loading && (s.editing || s.note) ? `<div class="path">${escapeHtml(s.path)}</div>` : "";
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <div class="section">
        <div class="header"><span class="title">${escapeHtml(title)}</span>${editButton}</div>
        ${path}
        ${body}
      </div>`;
    const md = this.shadowRoot.querySelector("ha-markdown");
    if (md) {
      md.hass = this.hass;
      md.content = renderWikilinks(s.note, this.hass);
    }
    this.shadowRoot.querySelector(".section")?.addEventListener("click", (ev) => {
      const anchor = ev.composedPath().find((el) => el.tagName === "A");
      const href = anchor?.getAttribute("href") || "";
      if (!href.startsWith(ENTITY_HREF)) return;
      ev.preventDefault();
      ev.stopPropagation();
      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          detail: { entityId: href.slice(ENTITY_HREF.length) },
          bubbles: true,
          composed: true,
        }),
      );
    });
    this.shadowRoot.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", () => this[`_${button.dataset.action}`]());
    });
    const textarea = this.shadowRoot.querySelector("textarea");
    if (textarea) {
      textarea.addEventListener("keydown", (ev) => {
        // Keep the dialog from treating Escape or Enter as its own shortcuts.
        ev.stopPropagation();
        if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
          ev.preventDefault();
          this._save();
        } else if (ev.key === "Escape") {
          ev.preventDefault();
          this._cancel();
        }
      });
    }
  }
}

if (!customElements.get("notes-vault-note")) {
  customElements.define("notes-vault-note", NotesVaultNote);
}

/* -- Dashboard card ------------------------------------------------------------- */

class NotesVaultCard extends HTMLElement {
  setConfig(config) {
    const keys = ["entity", "device_id", "area_id"].filter((k) => config[k]);
    if (keys.length !== 1) {
      throw new Error("Set exactly one of entity, device_id or area_id");
    }
    this._config = config;
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this._note = document.createElement("notes-vault-note");
      this._note.setAttribute("variant", "card");
      this._card.appendChild(this._note);
      this.appendChild(this._card);
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

const ensureNote = (container, before, target, variant, wrapInCard) => {
  let host = container.querySelector(":scope > .notes-vault-host");
  if (!host) {
    host = document.createElement(wrapInCard ? "ha-card" : "div");
    host.className = "notes-vault-host";
    const note = document.createElement("notes-vault-note");
    note.setAttribute("variant", variant);
    host.appendChild(note);
    if (before) container.insertBefore(host, before);
    else container.appendChild(host);
  }
  const note = host.querySelector("notes-vault-note");
  note.hass = getHass();
  note.setTarget(target);
};

const injectMoreInfo = (ha) => {
  const dialog = ha.shadowRoot?.querySelector("ha-more-info-dialog");
  const info = dialog?.shadowRoot?.querySelector("ha-more-info-info");
  const content = info?.shadowRoot?.querySelector("div.content");
  if (!content || !info.entityId) return;
  ensureNote(content, null, { entity_id: info.entityId }, "inline", false);
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
  ensureNote(column, anchor || null, target, "card", true);
};

const tick = () => {
  const ha = document.querySelector("home-assistant");
  if (!ha?.hass) return;
  try {
    injectMoreInfo(ha);
    injectPage(ha);
  } catch (err) {
    // Never let a frontend change turn into a stream of errors.
  }
};

if (!window.__notesVaultStarted) {
  window.__notesVaultStarted = true;
  setInterval(tick, POLL_MS);
  console.info(`%c NOTES-VAULT %c ${VERSION} `, "background:#7c3aed;color:#fff;border-radius:3px 0 0 3px", "background:#ddd;color:#333;border-radius:0 3px 3px 0");
}
