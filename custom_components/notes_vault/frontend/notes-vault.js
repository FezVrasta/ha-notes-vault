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

const ENTITY_HREF = "#notes-vault-entity=";

/** Where a resolved link goes in Home Assistant. */
const linkHref = (link) => {
  if (link.type === "entity") return `${ENTITY_HREF}${link.id}`;
  if (link.type === "device") return `/config/devices/device/${encodeURIComponent(link.id)}`;
  if (link.type === "area") return `/config/areas/area/${encodeURIComponent(link.id)}`;
  return null;
};

/**
 * Obsidian wikilinks mean nothing to Home Assistant's Markdown renderer. The server
 * resolves each target to the entity, device or area behind it: entities open their
 * more-info dialog, devices and areas their page. Links to the user's own notes have
 * no page in Home Assistant, so they show as bold text.
 */
const renderWikilinks = (text, links = {}) =>
  text
    .replace(/!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/g, (_m, target, label) => `*${label || target.split("/").pop()}*`)
    .replace(/\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|([^\]]*))?\]\]/g, (_m, target, label) => {
      const shown = label || target.split("/").pop();
      const link = links[target.trim()];
      const href = link && linkHref(link);
      return href ? `[${shown}](${href})` : `**${shown}**`;
    });

/*
 * Everything visible is a stock Home Assistant element: ha-card and ha-expansion-panel
 * for the frame, ha-markdown for the note, ha-form with a text selector for editing,
 * ha-button, ha-spinner and ha-alert. The CSS here is spacing only, so the notes look
 * like the rest of the UI and follow its theme.
 */
const STYLE = `
  :host { display: block; }
  ha-expansion-panel { margin-top: 16px; }
  .body { display: flex; flex-direction: column; gap: 8px; }
  .panel-body { padding: 0 16px 16px; }
  .path, .empty { color: var(--secondary-text-color); font-size: var(--ha-font-size-s, 12px); }
  .empty { font-size: inherit; }
  .path { word-break: break-all; }
  ha-markdown { overflow-wrap: anywhere; }
  .actions { display: flex; justify-content: flex-end; gap: 8px; }
  .card-actions { display: flex; justify-content: flex-end; gap: 8px; }
  ha-spinner { align-self: center; }
`;

const escapeHtml = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const NOTE_SCHEMA = [{ name: "note", selector: { text: { multiline: true } } }];

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
  }

  set hass(hass) {
    this._hass = hass;
    const form = this.shadowRoot.querySelector("ha-form");
    if (form) form.hass = hass;
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
        setTimeout(() => this.isConnected && target === this._target && this._load(), 10000);
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
    const note = this._state.draft ?? "";
    this._state = { ...this._state, saving: true, error: undefined };
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
    // ha-form loads the text selector lazily; focus once it has rendered.
    setTimeout(() => this.shadowRoot.querySelector("ha-form")?.focus?.(), 200);
  }

  _cancel() {
    this._state = { ...this._state, editing: false, draft: undefined, error: undefined };
    this._render();
  }

  _button(action, label, { appearance = "plain", disabled = false } = {}) {
    return `<ha-button size="s" appearance="${appearance}" data-action="${action}" ${disabled ? "disabled" : ""}>${escapeHtml(label)}</ha-button>`;
  }

  _render() {
    const s = this._state;
    if (s.unavailable) {
      this.shadowRoot.innerHTML = "";
      return;
    }
    const card = this.getAttribute("variant") === "card";
    const title = this.getAttribute("heading") || "Notes";

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
    const path = s.path && (s.editing || s.note) ? `<span class="path">${escapeHtml(s.path)}</span>` : "";

    let actions = "";
    if (s.editing) {
      actions =
        this._button("cancel", "Cancel", { disabled: s.saving }) +
        this._button("save", s.saving ? "Saving…" : "Save", { appearance: "filled", disabled: s.saving });
    } else if (!s.loading && !s.error && s.canEdit) {
      actions = this._button("edit", s.note ? "Edit" : "Add note");
    }

    const content = `<div class="body">${path}${body}</div>`;
    this.shadowRoot.innerHTML = card
      ? `<style>${STYLE}</style>
         <ha-card header="${escapeHtml(title)}">
           <div class="card-content">${content}</div>
           ${actions ? `<div class="card-actions">${actions}</div>` : ""}
         </ha-card>`
      : `<style>${STYLE}</style>
         <ha-expansion-panel outlined expanded header="${escapeHtml(title)}">
           <div class="panel-body">${content}${actions ? `<div class="actions">${actions}</div>` : ""}</div>
         </ha-expansion-panel>`;

    const md = this.shadowRoot.querySelector("ha-markdown");
    if (md) {
      md.hass = this.hass;
      md.content = renderWikilinks(s.note, s.links);
    }

    const form = this.shadowRoot.querySelector("ha-form");
    if (form) {
      form.hass = this.hass;
      form.schema = NOTE_SCHEMA;
      form.data = { note: s.draft ?? "" };
      form.disabled = !!s.saving;
      form.computeLabel = () => "";
      form.computeHelper = () => "Markdown. Link with [[light.kitchen]] or [[Device name]].";
      form.addEventListener("value-changed", (ev) => {
        this._state.draft = ev.detail.value.note ?? "";
        form.data = { note: this._state.draft };
      });
    }

    this.shadowRoot.addEventListener("click", this._onLinkClick ||= (ev) => {
      const anchor = ev.composedPath().find((el) => el.tagName === "A");
      const href = anchor?.getAttribute("href") || "";
      if (href.startsWith(ENTITY_HREF)) {
        ev.preventDefault();
        ev.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            detail: { entityId: href.slice(ENTITY_HREF.length) },
            bubbles: true,
            composed: true,
          }),
        );
      } else if (href.startsWith("/config/")) {
        // Navigate inside the app, the way Home Assistant's own links do, and close
        // the more-info dialog if the note is in one.
        ev.preventDefault();
        ev.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("hass-more-info", { detail: { entityId: null }, bubbles: true, composed: true }),
        );
        history.pushState(null, "", href);
        window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
      }
    });
    this.shadowRoot.querySelectorAll("ha-button[data-action]").forEach((button) => {
      button.addEventListener("click", () => this[`_${button.dataset.action}`]());
    });
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
