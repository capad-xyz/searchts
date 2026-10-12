"""The four states a logged-in read can be in, and who owns the copy.

The cookie work in ``session_cookies`` answers "how do I get this site's
cookies". This module answers the question above it: "which of the four things
happens now", and it answers the same way every time so the CLI, the MCP tool,
and a library caller cannot drift into four different behaviours.

    1. kept      searchts's own store holds this site's login. Use it. No
                 browser opens, nothing is copied, nothing is asked.
    2. copy      not kept, but a local browser has the login. One approval per
                 session covers copying, for the sites that session actually
                 reads. The copy is scratch and is deleted when the read ends.
                 Copying is never the same as keeping.
    3. signin    not kept and there is nothing to copy. The user signs in once
                 in a browser searchts owns. That sign-in is the approval, and
                 nothing is copied from the user's own browser.
    4. after     the read worked. Ask once whether to keep this site's login.
                 A yes writes that one site into the store. A no keeps nothing
                 and the next logged-in read asks again.

``kill`` is the other verb: it drops searchts's copy of one site and never
touches the cookies in the user's own Firefox or Chrome unless explicitly told
to. Scratch is deleted every time, kept or not.

Two invariants this module exists to hold, both of them easy to break by
accident and impossible to notice afterwards:

- **The scratch copy and the saved login are not the same file.** Scratch is
  ephemeral and is purged on every exit path. A kept login is a site somebody
  agreed to keep. A bug that wrote a kept login into scratch would look correct
  right up until the next run deleted it, and the loss would be silent.
- **Consent is per session and per site, not per machine.** One approval lets a
  session copy the sites it actually reads. It never grants the rest of the
  machine, and never a site the session did not open.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse

from searchts.session_cookies import (
    CookieReadError,
    CookieRecord,
    CookieSource,
    read_owned_site,
    save_owned_site,
)

# ── states ──────────────────────────────────────────────────────────────────

#: Kept. searchts's store already holds this site's login.
KEPT = "kept"
#: Not kept, but a local browser has the login. Copying needs session consent.
COPY = "copy"
#: Not kept and nothing to copy. The user signs in once in a browser we own.
SIGNIN = "signin"
#: Not a logged-in page. Nothing here applies.
NONE = "none"

_ALL_STATES = (KEPT, COPY, SIGNIN, NONE)


class SessionConsentNeeded(Exception):
    """Copying this site's cookies needs the user's yes, once per session.

    Deliberately not a :class:`CookieReadError`: callers catch that to mean "the
    read failed", and a refused consent has to stay distinguishable from a site
    that could not be read at all.
    """


# ── paths ───────────────────────────────────────────────────────────────────


def _home() -> str:
    return os.path.expanduser("~")


def store_dir() -> str:
    """The directory holding everything searchts owns for logged-in reads."""
    return os.path.join(_home(), ".searchts", "cookies")


def session_grant_path() -> str:
    """Where the per-session copy approval is recorded.

    Scoped to the running process rather than the user, because "once per
    session" is the promise: a new terminal, a new agent run, or a new day is a
    new session and asks again. A file-wide grant would silently outlive the
    thing the user actually agreed to.
    """
    return os.path.join(store_dir(), "session-grant.json")


def scratch_root() -> str:
    """Where ephemeral per-read copies live. Nothing here is ever kept."""
    return os.path.join(store_dir(), "scratch")


def _ensure_dir(path: str, mode: int) -> str:
    os.makedirs(path, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, mode)
        except OSError:
            pass
    return path


def _write_json(path: str, data: object, mode: int) -> None:
    """Write `data` to `path` atomically, owner-only on POSIX."""
    _ensure_dir(os.path.dirname(path), 0o700)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    if os.name != "nt":
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
    os.replace(tmp, path)
    if os.name != "nt":
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def _read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def host_of(site: str) -> str:
    """The host a site is filed under. Everything keys on this, never the URL.

    ``urlparse`` is happy to call ``"not a url"`` a hostname, because a space is
    a legal character in the grammar it checks and it is not the one validating
    this. Left alone, a malformed argument reached a sign-in prompt naming a
    host that cannot exist, and any future consumer that put this string in a
    message, a path, or a header inherited the problem. So the host is validated
    here, once, and a caller that passed nonsense gets nothing.
    """
    host = (urlparse(site if "://" in site else "https://" + site).hostname or "").lower()
    host = host.rstrip(".")
    if not host or len(host) > 253:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-.")
    if not set(host) <= allowed:
        return ""
    # A label cannot start or end with a hyphen, and cannot be empty.
    labels = host.split(".")
    if any(
        not lab or lab.startswith("-") or lab.endswith("-") or len(lab) > 63
        for lab in labels
    ):
        return ""
    if host.startswith("."):
        return ""
    return host


# ── session consent ─────────────────────────────────────────────────────────


def _current_pid() -> int:
    return os.getpid()


def session_granted() -> bool:
    """True when *this* process already has the one approval it needs.

    A grant recorded by a different process is treated as absent on purpose. It
    is not a shared pool of trust: it is one answer to one question, asked of one
    running session.
    """
    grant = _read_json(session_grant_path())
    return bool(grant.get("copy")) and int(grant.get("pid", -1)) == _current_pid()


def grant_session_copy() -> None:
    """Record this session's approval to copy cookies for sites it reads."""
    _write_json(
        session_grant_path(),
        {"copy": True, "pid": _current_pid(), "at": int(time.time())},
        0o600,
    )


def revoke_session_copy() -> None:
    """Forget this session's approval. Asks again on the next copy."""
    try:
        os.remove(session_grant_path())
    except OSError:
        pass


def session_copied_sites() -> List[str]:
    """Which sites this session has actually copied.

    Reported so the user can see the blast radius of what they approved: the
    sites they read, and not the rest of the machine. Empty unless a grant
    exists.
    """
    grant = _read_json(session_grant_path())
    if not grant.get("copy") or int(grant.get("pid", -1)) != _current_pid():
        return []
    sites = grant.get("sites")
    return sorted(sites) if isinstance(sites, list) else []


def _note_copied_site(host: str) -> None:
    """Record that this session copied `host`, keeping any prior note.

    Best effort by design. Losing the note means the next copy re-asks nothing
    and the store is unaffected; failing a successful read because a note could
    not be written would be the worse trade.
    """
    grant = _read_json(session_grant_path())
    if not grant.get("copy") or int(grant.get("pid", -1)) != _current_pid():
        return
    sites = grant.get("sites")
    sites = list(sites) if isinstance(sites, list) else []
    if host in sites:
        return
    sites.append(host)
    try:
        _write_json(session_grant_path(), {**grant, "sites": sorted(sites)}, 0o600)
    except OSError:
        pass


# ── the decision ────────────────────────────────────────────────────────────


@dataclass
class Decision:
    """What happens next for one site, and why, in words the user can act on."""

    site: str
    state: str
    why: str
    #: Populated for KEPT only: the store's cookies, already host-scoped.
    source: Optional[CookieSource] = None
    #: What the caller should do, spelled out. ``None`` means "just read it".
    action: Optional[str] = None

    @property
    def needs_consent(self) -> bool:
        return self.state == COPY and not session_granted()

    @property
    def needs_signin(self) -> bool:
        return self.state == SIGNIN


def kept(site: str) -> bool:
    """True when searchts's store holds a login for `site`."""
    try:
        return bool(read_owned_site(site).count)
    except CookieReadError:
        return False


def decide(site: str, *, browser: str = "") -> Decision:
    """Which of the four states `site` is in, without performing any of them.

    Read-only by construction: it opens no browser, reads no cookie database,
    and copies nothing. The order is the spec's order, and the order matters --
    a kept login is used even when a browser is named, because the whole point
    of keeping is that Chrome does not open.
    """
    host = host_of(site)
    if not host:
        return Decision(site, NONE, f"{site!r} is not a URL searchts can file a login under.")

    # 1. Already kept.
    try:
        source = read_owned_site(site)
        if source.count:
            return Decision(
                site, KEPT,
                f"{host} is already kept in the searchts store "
                f"({source.count} cookies). No browser opens and nothing is copied.",
                source=source,
            )
    except CookieReadError:
        pass

    # 2. Not kept. Is there anything to copy?
    if browser:
        try:
            from searchts.session_cookies import family_of

            family = family_of(browser)
        except ValueError as e:
            return Decision(site, NONE, str(e))
        if family == "firefox":
            return Decision(
                site, COPY,
                f"{host} is not kept, and {browser} has its cookie file readable "
                f"on disk. One approval for this session covers copying the "
                f"sites this session reads. The copy is scratch and is deleted "
                f"when the read finishes.",
                action="copy",
            )
        # Chromium: the file is locked, so a copy means a side-by-side window.
        return Decision(
            site, COPY,
            f"{host} is not kept, and {browser}'s cookie file is locked. "
            f"Copying it means opening {browser} side by side on a scratch "
            f"profile, once you approve. One approval for this session covers "
            f"the sites this session reads. The scratch profile is deleted "
            f"when the read finishes.",
            action="copy",
        )

    # 3. Not kept, and nothing named to copy from.
    return Decision(
        site, SIGNIN,
        f"{host} is not kept and there is nothing to copy. Sign in once in a "
        f"browser searchts opens for you; that sign-in is the approval, and "
        f"nothing is copied from your own browser.",
        action="signin",
    )


def require_copy_consent(site: str) -> None:
    """Raise unless this session may copy `site`'s cookies."""
    if session_granted():
        return
    raise SessionConsentNeeded(
        f"{host_of(site)} is not kept, and copying its cookies needs your "
        f"approval once per session. Approve it and this session may copy the "
        f"sites it reads -- not the rest of your machine, and not a site this "
        f"session never opens."
    )


def note_copied(site: str) -> None:
    """Record a copy against this session's grant."""
    _note_copied_site(host_of(site))


# ── keep ────────────────────────────────────────────────────────────────────


@dataclass
class Kept:
    """The outcome of the once-per-read question: keep this site's login?"""

    site: str
    kept: bool
    count: int = 0
    why: str = ""
    #: Set when the user also asked to remove the browser's own copy.
    also_kill_browser: bool = False


def keep(site: str, records: List[CookieRecord], *, browser: str = "") -> Kept:
    """Save exactly one site's login into the store. A yes to the keep question.

    Only the requested site is written. The scratch copy the read just used is
    not promoted and not referenced: keeping copies the values out of the
    records in hand, so the two files can never be the same file.
    """
    count = save_owned_site(site, records, browser=browser)
    return Kept(
        site=site,
        kept=True,
        count=count,
        why=f"kept {host_of(site)} in the searchts store ({count} cookies). "
            f"The next read of that site uses the store and opens no browser.",
    )


def keep_question(site: str) -> str:
    """The once-per-read question, in full. Neither answer is skippable."""
    host = host_of(site)
    return (
        f"keep {host}'s login for next time? A yes writes only {host} into the "
        f"searchts store, the same place as a login searchts owns. The next "
        f"read of {host} uses that store and does not open a browser again. "
        f"A no keeps nothing, and the next logged-in read of {host} asks again."
    )


# ── kill ────────────────────────────────────────────────────────────────────


@dataclass
class Killed:
    """What a kill actually removed, so the answer can be exact."""

    site: str
    removed_from_store: bool = False
    #: Sites whose scratch copies went with it.
    scratch_removed: List[str] = field(default_factory=list)
    why: str = ""


def kill(site: str, *, browser_copies: bool = False) -> Killed:
    """Drop searchts's copy of one site.

    Deletes the site's entry in the owned store and purges any scratch left for
    it. It does **not** touch the cookies in the user's own Firefox or Chrome;
    that is a different machine-owned thing, and deleting a login the user did
    not ask about is not searchts' call. Pass ``browser_copies`` to mean it.
    """
    host = host_of(site)
    out = Killed(site=site)

    from searchts.session_cookies import owned_store_path, read_owned_store

    store = read_owned_store()
    if host in store:
        _ensure_dir(store_dir(), 0o700)
        del store[host]
        _write_json(owned_store_path(), store, 0o600)
        out.removed_from_store = True

    out.scratch_removed = purge_scratch()

    if not browser_copies:
        out.why = (
            f"{host} is gone from the searchts store."
            if out.removed_from_store
            else f"there was no saved login for {host} to remove."
        )
        if out.scratch_removed:
            out.why += f" Deleted {len(out.scratch_removed)} scratch copy/copies."
        out.why += (
            f" Your browser's own cookies for {host} were left alone; say so "
            f"explicitly if you want those deleted too."
        )
    else:
        removed = kill_browser_copies(host)
        out.why = (
            f"{host} is gone from the searchts store and {removed} browser "
            f"cookie entries were deleted."
        )
    return out


def kill_browser_copies(host: str) -> int:
    """Delete `host`'s cookies from the user's own browsers. Explicit opt-in.

    Separate from :func:`kill` on purpose: the store is searchts's to remove,
    a browser profile is the user's. Returns how many entries went.
    """
    import sqlite3

    from searchts.session_cookies import (
        CHROMIUM_FAMILY,
        _firefox_profile_roots,
    )

    host = (host or "").lower().lstrip(".")
    if not host:
        return 0
    removed = 0
    # Firefox-derived: the cookie DB is a plain SQLite file we already know how
    # to open read-only. Opening it read-write here is the whole point.
    for browser in ("firefox", "zen", "librewolf", "waterfox", "floorp", "mullvad"):
        for root in _firefox_profile_roots(browser):
            if not os.path.isdir(root):
                continue
            for profile in os.listdir(root):
                db = os.path.join(root, profile, "cookies.sqlite")
                if not os.path.isfile(db):
                    continue
                try:
                    conn = sqlite3.connect(db)
                    cur = conn.execute(
                        "DELETE FROM moz_cookies WHERE host LIKE ?",
                        ("%" + host,),
                    )
                    removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                    conn.commit()
                    conn.close()
                except sqlite3.Error:
                    continue
    # Chromium values are encrypted and its DB is locked while the browser
    # runs, so this is the honest answer rather than a silent no-op.
    for browser in CHROMIUM_FAMILY:
        for profile in _chromium_profiles(browser):
            db = os.path.join(profile, "Network", "Cookies")
            if not os.path.isfile(db):
                continue
            try:
                conn = sqlite3.connect(db)
                cur = conn.execute(
                    "DELETE FROM cookies WHERE host_key LIKE ?", ("%" + host,)
                )
                removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                conn.commit()
                conn.close()
            except sqlite3.Error:
                continue
    return removed


def _chromium_profiles(browser: str) -> List[str]:
    """Candidate ``User Data`` profile dirs for a Chromium browser."""
    local = os.environ.get("LOCALAPPDATA", "")
    roots = {
        "chrome": os.path.join(local, "Google", "Chrome", "User Data"),
        "edge": os.path.join(local, "Microsoft", "Edge", "User Data"),
        "brave": os.path.join(local, "BraveSoftware", "Brave-Browser", "User Data"),
        "vivaldi": os.path.join(local, "Vivaldi", "User Data"),
        "opera": os.path.join(local, "Opera Software", "Opera Stable"),
    }
    root = roots.get((browser or "").lower(), "")
    if not root or not os.path.isdir(root):
        return []
    out = []
    for name in os.listdir(root):
        candidate = os.path.join(root, name)
        if os.path.isdir(candidate) and (
            name == "Default" or name.startswith("Profile")
        ):
            out.append(candidate)
    return out


# ── scratch ─────────────────────────────────────────────────────────────────


def new_scratch(label: str) -> str:
    """Create a scratch directory for one read. Its owner always deletes it.

    Named under :func:`scratch_root` and never under the store, so a bug that
    keeps the wrong file is visible in the path rather than silent.
    """
    safe = "".join(c for c in (label or "read") if c.isalnum() or c in "-_")[:48]
    root = _ensure_dir(scratch_root(), 0o700)
    path = os.path.join(root, f"{safe}-{int(time.time() * 1000)}-{os.getpid()}")
    os.makedirs(path, exist_ok=True)
    return path


def scratch_paths() -> List[str]:
    """Every scratch directory that exists right now."""
    root = scratch_root()
    if not os.path.isdir(root):
        return []
    return [
        os.path.join(root, name)
        for name in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, name))
    ]


def purge_scratch() -> List[str]:
    """Delete every scratch directory. Returns what went.

    Called on every exit path, kept or not. Scratch is not a cache: a copy left
    behind is a login sitting on disk that nobody agreed to keep.
    """
    import shutil

    gone = []
    for path in scratch_paths():
        try:
            shutil.rmtree(path, ignore_errors=False)
            gone.append(path)
        except (OSError, shutil.Error):
            continue
    return gone


# ── listing ─────────────────────────────────────────────────────────────────


def list_kept() -> Dict[str, dict]:
    """Which sites are kept, so a user can see what they have agreed to keep."""
    from searchts.session_cookies import read_owned_store

    store = read_owned_store()
    return {
        host: {
            "cookies": len(entry.get("cookies", []))
            if isinstance(entry, dict)
            else 0,
            "browser": entry.get("browser", "") if isinstance(entry, dict) else "",
        }
        for host, entry in sorted(store.items())
    }


@dataclass
class Audit:
    """The whole picture, typed so a caller does not have to guess.

    A plain dict would have to be annotated at every use, and the two fields
    that get printed (``scratch``, ``session_copied_sites``) are exactly the ones
    a mistyped read turns into a crash at the worst moment. Naming them once
    here is cheaper than casting them at each call site.
    """

    kept: Dict[str, dict]
    scratch: List[str]
    session_copy_granted: bool
    session_copied_sites: List[str]
    store_dir: str
    scratch_dir: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "kept": self.kept,
            "scratch": self.scratch,
            "session_copy_granted": self.session_copy_granted,
            "session_copied_sites": self.session_copied_sites,
            "store_dir": self.store_dir,
            "scratch_dir": self.scratch_dir,
        }


def audit() -> Audit:
    """What is kept, what is scratch, what consent is live, in one call.

    So an agent can answer "what do you have from me" without guessing, and
    without any cookie value ever appearing in the answer.
    """
    return Audit(
        kept=list_kept(),
        scratch=[os.path.basename(p) for p in scratch_paths()],
        session_copy_granted=session_granted(),
        session_copied_sites=session_copied_sites(),
        store_dir=store_dir(),
        scratch_dir=scratch_root(),
    )


# ── the state machine, run ──────────────────────────────────────────────────


def prepare(site: str, *, browser: str = "", allow_signin: bool = False) -> CookieSource:
    """Take one site from its current state to "cookies in hand", or explain why not.

    This is the order, and it is the only place the order lives:

    kept    the store's cookies, returned as they are. No browser, no copy.
    copy    the session's approval, then a scratch copy that the caller must
            purge. Never written to the store; keeping is a separate yes.
    signin  refused unless the caller can actually put a browser in front of the
            user, because otherwise the instruction "sign in" has nothing to sign
            into and the read hangs on a question it cannot ask.

    Raises :class:`SessionConsentNeeded` for an unapproved copy and
    :class:`CookieReadError` for everything else.
    """
    decision = decide(site, browser=browser)

    if decision.state == KEPT and decision.source is not None:
        return decision.source

    if decision.state == COPY:
        # Settle "can this browser be read at all" before asking for consent.
        # A Chromium cookie file is locked, and a user asked to approve a copy
        # that cannot happen has been asked a question whose answer does not
        # matter -- and has spent the session's one approval on it. The refusal
        # from for_site carries the real reason and the working alternative.
        from searchts.session_cookies import (
            chromium_locked_message,
            family_of,
            for_site,
        )

        if family_of(browser) == "chromium":
            raise CookieReadError(chromium_locked_message(browser))
        require_copy_consent(site)
        source = for_site(site, browser)
        note_copied(site)
        return source

    if decision.state == SIGNIN:
        if not allow_signin:
            raise CookieReadError(
                f"{host_of(site)} is not kept and there is nothing to copy. "
                f"Sign in once in a browser searchts opens, or pass "
                f"--cookies-from-browser to copy from a browser you already "
                f"signed into."
            )
        from searchts.signin_browser import signin

        source = signin(site)
        note_copied(site)
        return source

    raise CookieReadError(decision.why)
