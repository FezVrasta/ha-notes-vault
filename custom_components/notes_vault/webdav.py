"""A small WebDAV server over the vault, for remotely-save and any other DAV client.

It lives on Home Assistant's own HTTP server, so it inherits its TLS, its IP bans and
its reverse proxy setup. Clients authenticate with a long-lived access token, either as
a Bearer header or as the password of HTTP Basic auth (the user name is ignored), which
is what remotely-save and most desktop clients can send.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from datetime import UTC, datetime
from email.utils import format_datetime
from urllib.parse import quote, unquote, urlsplit
from xml.sax.saxutils import escape

from aiohttp import BasicAuth, hdrs, web
from homeassistant.auth.models import User
from homeassistant.components.http import KEY_AUTHENTICATED, KEY_HASS_USER
from homeassistant.components.http.ban import process_wrong_login
from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView

from .const import CONF_WEBDAV, DAV_COLLECTION, DAV_URL
from .manager import NotesVault, loaded_manager
from .vault import (
    ConflictError,
    FileInfo,
    InvalidPathError,
    NotFoundError,
    Vault,
    VaultError,
)

_LOGGER = logging.getLogger(__name__)

#: Upper bound for one uploaded file. Attachments are the only thing that gets close.
MAX_UPLOAD = 256 * 1024 * 1024

ALLOW = "OPTIONS, GET, HEAD, PUT, DELETE, PROPFIND, PROPPATCH, MKCOL, COPY, MOVE, LOCK, UNLOCK"
_UNAUTHORIZED_HEADERS = {
    "WWW-Authenticate": 'Basic realm="Notes Vault", charset="UTF-8"'
}


def _http_date(ts: float) -> str:
    return format_datetime(datetime.fromtimestamp(ts, UTC), usegmt=True)


def _etag(info: FileInfo) -> str:
    raw = f"{info.path}:{info.size}:{info.mtime}".encode()
    return '"' + hashlib.sha1(raw, usedforsecurity=False).hexdigest() + '"'


def _precondition_failed(request: web.Request, info: FileInfo | None) -> bool:
    """Return whether `If-Match` or `If-None-Match` rule out this write.

    A client that sends the ETag it last saw gets a 412 instead of overwriting a
    change made since, by Home Assistant or an assistant.
    """
    current = _etag(info) if info else None
    if (if_match := request.headers.get(hdrs.IF_MATCH)) is not None:
        tags = {t.strip() for t in if_match.split(",")}
        if current is None or ("*" not in tags and current not in tags):
            return True
    if (if_none_match := request.headers.get(hdrs.IF_NONE_MATCH)) is not None:
        tags = {t.strip() for t in if_none_match.split(",")}
        if current is not None and ("*" in tags or current in tags):
            return True
    return False


def _href(vault_path: str | None, is_dir: bool) -> str:
    if vault_path is None:
        return f"{DAV_URL}/"
    parts = [DAV_COLLECTION, *(p for p in vault_path.split("/") if p)]
    href = DAV_URL + "/" + "/".join(quote(p) for p in parts)
    return href + "/" if is_dir else href


def _response_xml(href: str, name: str, info: FileInfo | None, is_dir: bool) -> str:
    props = [f"<d:displayname>{escape(name)}</d:displayname>"]
    if is_dir:
        props.append("<d:resourcetype><d:collection/></d:resourcetype>")
    else:
        props.append("<d:resourcetype/>")
    if info is not None:
        props.append(f"<d:getlastmodified>{_http_date(info.mtime)}</d:getlastmodified>")
        created = datetime.fromtimestamp(info.mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        props.append(f"<d:creationdate>{created}</d:creationdate>")
        if not is_dir:
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if name.endswith(".md"):
                ctype = "text/markdown"
            props.append(f"<d:getcontentlength>{info.size}</d:getcontentlength>")
            props.append(f"<d:getcontenttype>{escape(ctype)}</d:getcontenttype>")
            props.append(f"<d:getetag>{escape(_etag(info))}</d:getetag>")
    props.append(
        "<d:supportedlock><d:lockentry><d:lockscope><d:exclusive/></d:lockscope>"
        "<d:locktype><d:write/></d:locktype></d:lockentry></d:supportedlock>"
    )
    return (
        f"<d:response><d:href>{escape(href)}</d:href><d:propstat><d:prop>"
        + "".join(props)
        + "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    )


def _walk_all(vault: Vault, path: str) -> list[FileInfo]:
    """List everything below a folder, for PROPFIND with Depth: infinity."""
    out: list[FileInfo] = []
    stack = [path]
    while stack:
        for entry in vault.list_dir(stack.pop()):
            out.append(entry)
            if entry.is_dir:
                stack.append(entry.path)
    return out


def _multistatus(responses: list[str]) -> web.Response:
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n<d:multistatus xmlns:d="DAV:">'
        + "".join(responses)
        + "</d:multistatus>"
    )
    return web.Response(
        status=207, body=body.encode(), content_type="application/xml", charset="utf-8"
    )


def active_manager(hass: HomeAssistant) -> NotesVault | None:
    """Return the vault of the loaded entry, if WebDAV is enabled on it."""
    manager = loaded_manager(hass)
    return manager if manager and manager.options[CONF_WEBDAV] else None


class NotesVaultDavView(HomeAssistantView):
    """Serve the vault over WebDAV."""

    url = DAV_URL
    extra_urls = [DAV_URL + "/{path:.*}"]
    name = "api:notes_vault:dav"
    # Authentication happens in the handler: Home Assistant's middleware only knows
    # Bearer tokens, and WebDAV clients mostly speak Basic.
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Serve the vault of whichever config entry is loaded.

        Routes cannot be removed from a running server, so the view is registered once
        and looks the vault up per request. That keeps it right across reloads, and
        answers 404 while the entry is unloaded or WebDAV is switched off.
        """
        self.hass = hass

    def register(
        self, hass: HomeAssistant, app: web.Application, router: web.UrlDispatcher
    ) -> None:
        """Route every method to one handler.

        `HomeAssistantView.register` only wires the standard HTTP verbs, and WebDAV
        needs PROPFIND, MKCOL, MOVE and friends.
        """
        for url in (self.url, *self.extra_urls):
            router.add_route(hdrs.METH_ANY, url, self._handle)

    # -- Plumbing ------------------------------------------------------------------

    async def _authenticate(self, request: web.Request) -> User | None:
        hass = self.hass
        if request.get(KEY_AUTHENTICATED):
            return request[KEY_HASS_USER]
        header = request.headers.get(hdrs.AUTHORIZATION)
        if not header:
            return None
        token: str | None = None
        try:
            token = BasicAuth.decode(header).password
        except ValueError:
            scheme, _, value = header.partition(" ")
            if scheme.lower() == "bearer":
                token = value.strip()
        if not token:
            await process_wrong_login(request)
            return None
        refresh_token = hass.auth.async_validate_access_token(token)
        if refresh_token is None or not refresh_token.user.is_active:
            await process_wrong_login(request)
            return None
        return refresh_token.user

    @staticmethod
    def _vault_path(raw: str) -> str | None:
        """Map a URL path below the DAV root to a vault path. None is the DAV root."""
        parts = [p for p in raw.split("/") if p]
        if not parts:
            return None
        if parts[0] != DAV_COLLECTION:
            raise NotFoundError(raw)
        return "/".join(parts[1:])

    def _destination(self, request: web.Request) -> str:
        dest = request.headers.get("Destination")
        if not dest:
            raise InvalidPathError("missing Destination")
        path = unquote(urlsplit(dest).path)
        if not path.startswith(DAV_URL + "/"):
            raise InvalidPathError(dest)
        vault_path = self._vault_path(path[len(DAV_URL) :])
        if not vault_path:
            raise InvalidPathError(dest)
        return vault_path

    async def _run(self, func, *args, **kwargs):
        return await self.hass.async_add_executor_job(lambda: func(*args, **kwargs))

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        response = await self._handle_inner(request)
        _LOGGER.debug(
            "%s /%s (Depth %s) -> %s",
            request.method,
            request.match_info.get("path", ""),
            request.headers.get("Depth", "-"),
            response.status,
        )
        return response

    async def _handle_inner(self, request: web.Request) -> web.StreamResponse:
        manager = active_manager(self.hass)
        if manager is None:
            return web.Response(status=404)
        method = request.method.upper()
        if method == "OPTIONS" and not request.headers.get(hdrs.AUTHORIZATION):
            return self._options()
        user = await self._authenticate(request)
        if user is None:
            return web.Response(status=401, headers=_UNAUTHORIZED_HEADERS)
        if not user.is_admin:
            return web.Response(
                status=403, text="Notes Vault needs an administrator token"
            )

        handler = getattr(self, f"_do_{method.lower()}", None)
        if handler is None:
            return web.Response(status=405, headers={"Allow": ALLOW})
        try:
            path = self._vault_path(request.match_info.get("path", ""))
            return await handler(request, manager, path)
        except NotFoundError:
            return web.Response(status=404)
        except InvalidPathError:
            return web.Response(status=400)
        except ConflictError:
            return web.Response(status=409)
        except VaultError:
            _LOGGER.exception("WebDAV %s failed", method)
            return web.Response(status=500)

    # -- Methods -------------------------------------------------------------------

    @staticmethod
    def _options() -> web.Response:
        return web.Response(
            status=200,
            headers={"DAV": "1, 2", "Allow": ALLOW, "MS-Author-Via": "DAV"},
        )

    async def _do_options(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        return self._options()

    async def _do_propfind(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        vault = manager.vault
        depth = request.headers.get("Depth", "infinity").lower()
        await request.read()  # The requested property list is ignored: we send allprop.

        if path is None:
            responses = [_response_xml(_href(None, True), "", None, True)]
            if depth != "0":
                info = await self._run(vault.stat, "")
                responses.append(
                    _response_xml(_href("", True), DAV_COLLECTION, info, True)
                )
            return _multistatus(responses)

        info = await self._run(vault.stat, path)
        name = path.rsplit("/", 1)[-1] if path else DAV_COLLECTION
        responses = [_response_xml(_href(path, info.is_dir), name, info, info.is_dir)]
        if info.is_dir and depth != "0":
            if depth == "1":
                children = await self._run(vault.list_dir, path)
            else:
                children = await self._run(_walk_all, vault, path)
            responses.extend(
                _response_xml(
                    _href(c.path, c.is_dir), c.path.rsplit("/", 1)[-1], c, c.is_dir
                )
                for c in children
            )
        return _multistatus(responses)

    async def _do_proppatch(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        # Clients (Finder, Windows) set cosmetic properties. Accept and forget them.
        await request.read()
        if path is None:
            return web.Response(status=403)
        info = await self._run(manager.vault.stat, path)
        return _multistatus(
            [
                f"<d:response><d:href>{escape(_href(path, info.is_dir))}</d:href>"
                "<d:propstat><d:prop/><d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
                "</d:response>"
            ]
        )

    async def _do_get(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.StreamResponse:
        return await self._get(manager, path, head=False)

    async def _do_head(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.StreamResponse:
        return await self._get(manager, path, head=True)

    async def _get(
        self, manager: NotesVault, path: str | None, *, head: bool
    ) -> web.Response:
        if path is None:
            return web.Response(status=200, text=f"{DAV_COLLECTION}/\n")
        vault = manager.vault
        info = await self._run(vault.stat, path)
        if info.is_dir:
            children = await self._run(vault.list_dir, path)
            listing = "\n".join(
                c.path.rsplit("/", 1)[-1] + ("/" if c.is_dir else "") for c in children
            )
            return web.Response(status=200, text=listing + "\n")
        name = path.rsplit("/", 1)[-1]
        ctype = (
            "text/markdown"
            if name.endswith(".md")
            else (mimetypes.guess_type(name)[0] or "application/octet-stream")
        )
        headers = {
            hdrs.LAST_MODIFIED: _http_date(info.mtime),
            hdrs.ETAG: _etag(info),
            hdrs.CONTENT_TYPE: ctype,
        }
        if head:
            headers[hdrs.CONTENT_LENGTH] = str(info.size)
            return web.Response(status=200, headers=headers)
        body = await self._run(vault.read_bytes, path)
        return web.Response(status=200, body=body, headers=headers)

    async def _do_put(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        if not path:
            return web.Response(status=405)
        chunks = bytearray()
        async for chunk in request.content.iter_chunked(64 * 1024):
            chunks.extend(chunk)
            if len(chunks) > MAX_UPLOAD:
                return web.Response(status=413)
        async with manager.lock:
            try:
                current = await self._run(manager.vault.stat, path)
            except NotFoundError:
                current = None
            if _precondition_failed(request, current):
                return web.Response(status=412)
            created = await self._run(
                manager.vault.write_bytes, path, chunks, make_parents=False
            )
            if created:
                await self._run(manager.index_file, path)
        manager.file_changed(path, "webdav")
        info = await self._run(manager.vault.stat, path)
        return web.Response(
            status=201 if created else 204, headers={hdrs.ETAG: _etag(info)}
        )

    async def _do_mkcol(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        if not path:
            return web.Response(status=405)
        if await request.read():
            return web.Response(status=415)
        try:
            await self._run(manager.vault.mkdir, path)
        except ConflictError:
            if await self._run(manager.vault.exists, path):
                return web.Response(status=405)
            raise
        return web.Response(status=201)

    async def _do_delete(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        if not path:
            return web.Response(status=403)
        async with manager.lock:
            # A sync client deleting a note is the easiest way to lose one, so it goes
            # to the trash like a delete from Home Assistant does.
            await self._run(manager.vault.trash, path)
        manager.file_removed(path)
        return web.Response(status=204)

    async def _do_move(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        return await self._move(request, manager, path, copy=False)

    async def _do_copy(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        return await self._move(request, manager, path, copy=True)

    async def _move(
        self,
        request: web.Request,
        manager: NotesVault,
        path: str | None,
        *,
        copy: bool,
    ) -> web.Response:
        if not path:
            return web.Response(status=403)
        dest = self._destination(request)
        overwrite = request.headers.get("Overwrite", "T").upper() != "F"
        try:
            async with manager.lock:
                created = await self._run(
                    manager.vault.move, path, dest, overwrite=overwrite, copy=copy
                )
                if copy:
                    await self._run(manager.index_file, dest)
        except ConflictError:
            if not overwrite and await self._run(manager.vault.exists, dest):
                return web.Response(status=412)
            raise
        if copy:
            manager.file_changed(dest, "webdav")
        else:
            manager.file_moved(path, dest)
        return web.Response(status=201 if created else 204)

    async def _do_lock(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        # Locks are advisory and never enforced: they exist so that clients which
        # refuse to write without one (Finder mounts read-only otherwise) work.
        await request.read()
        token = f"opaquelocktoken:{uuid.uuid4()}"
        href = _href(path, False)
        body = (
            '<?xml version="1.0" encoding="utf-8"?>\n<d:prop xmlns:d="DAV:">'
            "<d:lockdiscovery><d:activelock><d:locktype><d:write/></d:locktype>"
            "<d:lockscope><d:exclusive/></d:lockscope><d:depth>0</d:depth>"
            "<d:timeout>Second-3600</d:timeout>"
            f"<d:locktoken><d:href>{token}</d:href></d:locktoken>"
            f"<d:lockroot><d:href>{escape(href)}</d:href></d:lockroot>"
            "</d:activelock></d:lockdiscovery></d:prop>"
        )
        return web.Response(
            status=200,
            body=body.encode(),
            content_type="application/xml",
            charset="utf-8",
            headers={"Lock-Token": f"<{token}>"},
        )

    async def _do_unlock(
        self, request: web.Request, manager: NotesVault, path: str | None
    ) -> web.Response:
        return web.Response(status=204)
