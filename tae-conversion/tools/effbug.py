#!/usr/bin/env python3
"""
effbug — create (or read) a Bugzilla bug on YOUR machine, so Claude can get a real bug number to put in
commit messages. Runs host-side via effwatch, exactly like effgit: it never runs in Claude's sandbox
(bugzilla.mozilla.org isn't reachable there) and Claude never sees your API key.

AUTH (never printed, never passed through the request file). The key is resolved in this order — the first
that's set wins, so you can set it once and forget it:
  1. env  BUGZILLA_API_KEY
  2. env  BUGZILLA_API_KEY_FILE   → a file whose entire contents are the key
  3. dotenv file, first found:  <tools>/.eff.env , ~/.config/eff/eff.env , ~/.eff.env
       (lines like  BUGZILLA_API_KEY=xxxx  — a leading `export ` and surrounding quotes are tolerated)
  BUGZILLA_URL       default https://bugzilla.mozilla.org
Keep whichever file you use chmod 600 and out of version control (a .gitignore for .eff.env is provided).

Request JSON (dropped by Claude into conversion-runs/_queue/<id>.request.json):
  { "bug": "read",   "id": "2057054" }
      → returns that bug's product/component/version (used to clone filing settings; no auth needed).

  { "bug": "update", "ids": [2057407, …], "self_assign": true }   # or "assigned_to","summary","status",…
      → assigns/edits existing bugs. self_assign (default on) sets the assignee to the API key's owner.
      `dupe_of` marks the bug(s) a duplicate: it fills in RESOLVED/DUPLICATE for you, and DUPLICATE
      without it is rejected rather than sent for Bugzilla to refuse.

  Assignee on create/update resolves as: explicit `assigned_to` → env BUGZILLA_ASSIGNEE → self (BMO whoami,
  the key owner) unless `self_assign` is false.

  { "bug": "create",
    "summary": "[efficiency] Convert <Test> to ui/efficiency",
    "comment": "Optional first-comment body.",
    "template_bug": "2057054",        # clone product/component/version from an existing bug (recommended)
    "product": "Fenix", "component": "...", "version": "unspecified",   # or set explicitly (override template)
    "type": "task",                   # defect|enhancement|task (default task)
    "keywords": [], "whiteboard": "",
    "depends_on": [], "blocks": [],
    "assigned_to": "you@mozilla.com",   # optional; omit to leave default (the API-key owner)
    "dry_run": true                   # true = build + validate payload, do NOT file
  }

Result: writes <report>.txt AND a sibling <id>.bug-result.json = {"bug_id": N, "url": "...", "dry_run": bool}.
effwatch points Claude at both. Exit 0 on success, non-zero on failure.
"""
import json, os, sys, urllib.request, urllib.error

BZ_URL = os.environ.get("BUGZILLA_URL", "https://bugzilla.mozilla.org").rstrip("/")

def _read_env_file(path):
    """Parse a tiny dotenv file into a dict; tolerate `export`, quotes, comments. Missing file → {}."""
    vals = {}
    p = os.path.expanduser(path)
    try:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k.startswith("export "):
                    k = k[len("export "):].strip()
                vals[k] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return vals

def resolve_api_key():
    """Return (key, source_label). Env wins, then a key-file, then dotenv files. Never logs the key."""
    if os.environ.get("BUGZILLA_API_KEY"):
        return os.environ["BUGZILLA_API_KEY"].strip(), "env BUGZILLA_API_KEY"
    kf = os.environ.get("BUGZILLA_API_KEY_FILE")
    if kf and os.path.isfile(os.path.expanduser(kf)):
        return open(os.path.expanduser(kf)).read().strip(), f"file {kf}"
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, ".eff.env"), "~/.config/eff/eff.env", "~/.eff.env"):
        v = _read_env_file(p).get("BUGZILLA_API_KEY")
        if v:
            return v.strip(), f"dotenv {p}"
    return "", "none"

API_KEY, API_KEY_SRC = resolve_api_key()

def _req(method, path, body=None):
    url = f"{BZ_URL}/rest/{path}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    r.add_header("Accept", "application/json")
    if API_KEY:
        r.add_header("X-BUGZILLA-API-KEY", API_KEY)   # header, so the key never lands in a URL/log
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("message", detail)
        except Exception:
            pass
        raise RuntimeError(f"BMO {method} {path} → HTTP {e.code}: {detail}")

# Tracking epic appended to the context footer. Set EFF_EPIC to your team's epic; unset = omitted.
_EPIC = os.environ.get("EFF_EPIC", "").strip()
_EPIC_NOTE = f" Epic {_EPIC}." if _EPIC else ""

_FOOTERS = {
    "conversion": (
        "Context: part of the ui/efficiency UI-test modernization. This is a faithful port of an existing "
        "legacy ui/ smoke test onto the ui/efficiency framework — same coverage and assertions, but far less "
        "per-test code via a shared page-object / selector / navigation layer, which bends the UI-test "
        "maintenance cost curve. Smoke-conversion campaign." + _EPIC_NOTE),
    "enablement": (
        "Context: part of the ui/efficiency UI-test modernization. This adds framework capability/enablement "
        "(page objects, selectors, navigation edges, or BasePage primitives) required to convert legacy ui/ "
        "smoke tests onto ui/efficiency. Tracked separately from strict conversion so conversion effort can be "
        "measured over time." + _EPIC_NOTE),
    "tooling": (
        "Context: part of the ui/efficiency UI-test modernization. This adds developer tooling / observability "
        "for the ui/efficiency harness (debugging, screen dumps, structured-log rendering) rather than test "
        "coverage itself." + _EPIC_NOTE),
}

def _compose_description(req):
    """Build a well-structured bug description: what → why → standard context → TestRail. Pass a full
    `comment` for the 'what'; `why` for a one-line rationale; `kind` (conversion|enablement|tooling) picks
    the context footer; `testrail` (id or list) is appended. Set `no_context_footer` to suppress the footer."""
    parts = []
    body = (req.get("comment") or "").strip()
    if body:
        parts.append(body)
    why = (req.get("why") or "").strip()
    if why:
        parts.append("Why: " + why)
    if not req.get("no_context_footer"):
        parts.append(_FOOTERS.get(req.get("kind", "conversion"), _FOOTERS["conversion"]))
    tr = req.get("testrail")
    if tr:
        tr = ", ".join(str(x) for x in tr) if isinstance(tr, list) else str(tr)
        parts.append("TestRail: " + tr)
    return "\n\n".join(parts)

def read_bug(bug_id):
    fields = "id,product,component,version,type,summary,status,assigned_to"
    d = _req("GET", f"bug/{bug_id}?include_fields={fields}")
    bugs = d.get("bugs") or []
    if not bugs:
        raise RuntimeError(f"bug {bug_id} not found / not visible")
    return bugs[0]

_WHOAMI = None
def whoami():
    """Login (email) that owns the API key, via BMO /rest/whoami. Cached. None if unavailable."""
    global _WHOAMI
    if _WHOAMI is None and API_KEY:
        try:
            _WHOAMI = _req("GET", "whoami").get("name") or ""
        except Exception:
            _WHOAMI = ""
    return _WHOAMI or None

def resolve_assignee(req):
    """Who to assign to: explicit `assigned_to` → env BUGZILLA_ASSIGNEE → self (whoami) unless self_assign=False."""
    if req.get("assigned_to"):
        return req["assigned_to"]
    if os.environ.get("BUGZILLA_ASSIGNEE"):
        return os.environ["BUGZILLA_ASSIGNEE"]
    if req.get("self_assign", True):
        return whoami()
    return None

def run(req):
    action = req.get("bug")
    lines = [f"# effbug: {action}", f"bugzilla: {BZ_URL}",
             f"auth: key {'loaded from ' + API_KEY_SRC if API_KEY else 'NOT FOUND'}", ""]
    result = {"dry_run": bool(req.get("dry_run"))}

    if action == "read":
        bug_id = str(req.get("id", "")).strip()
        if not bug_id.isdigit():
            raise RuntimeError(f"invalid id: {bug_id!r}")
        b = read_bug(bug_id)
        lines += [f"bug {b['id']}: {b.get('summary','')}",
                  f"product={b.get('product')} component={b.get('component')} "
                  f"version={b.get('version')} type={b.get('type')} status={b.get('status')}"]
        result.update({"bug_id": int(b["id"]), "product": b.get("product"),
                       "component": b.get("component"), "version": b.get("version"),
                       "type": b.get("type")})
        return "\n".join(lines) + "\n", result

    if action == "update":
        ids = req.get("ids") or ([req.get("id")] if req.get("id") else [])
        ids = [str(i).strip() for i in ids if str(i).strip().isdigit()]
        if not ids:
            raise RuntimeError("update requires `id` or `ids`")
        if not API_KEY:
            raise RuntimeError("no Bugzilla API key found — cannot update")
        fields = {}
        assignee = resolve_assignee(req)
        if assignee:
            fields["assigned_to"] = assignee
        for k in ("summary", "status", "resolution", "keywords", "whiteboard", "priority", "severity"):
            if req.get(k):
                fields[k] = req[k]
        # Marking a duplicate: Bugzilla rejects resolution=DUPLICATE without dupe_of, and setting dupe_of
        # implies RESOLVED/DUPLICATE, so fill in whichever half the caller left out.
        if req.get("dupe_of"):
            dupe = str(req["dupe_of"]).strip()
            if not dupe.isdigit():
                raise RuntimeError(f"update: dupe_of must be a bug number, got {req['dupe_of']!r}")
            fields["dupe_of"] = int(dupe)
            fields.setdefault("status", "RESOLVED")
            fields.setdefault("resolution", "DUPLICATE")
        elif str(req.get("resolution", "")).upper() == "DUPLICATE":
            raise RuntimeError("update: resolution=DUPLICATE also needs dupe_of=<bug number>")
        # Relations take an add/remove object on update (unlike create, which takes a plain list) —
        # a bare list would REPLACE the existing set, which on a meta bug would silently drop every
        # other bug it tracks. Accept a list for convenience and wrap it as {"add": [...]}.
        for k in ("depends_on", "blocks", "see_also"):
            v = req.get(k)
            if v:
                fields[k] = {"add": v} if isinstance(v, list) else v
        if not fields:
            raise RuntimeError("update: nothing to change (pass assigned_to/self_assign or a field)")
        updated, failed = [], []
        for i in ids:
            try:
                _req("PUT", f"bug/{i}", fields)
                updated.append(i)
            except Exception as e:
                failed.append((i, str(e)))
        lines.append(f"fields: {json.dumps(fields)}")
        lines.append(f"✅ updated {len(updated)} bug(s): {', '.join(updated) or '(none)'}")
        if failed:
            lines.append("⚠️ failed: " + "; ".join(f"{i}: {e}" for i, e in failed))
        result.update({"updated": updated, "failed": [i for i, _ in failed], "fields": fields})
        return "\n".join(lines) + "\n", result

    if action != "create":
        raise RuntimeError(f"unknown action {action!r} (allowed: create, read, update)")

    # ---- create ----
    summary = (req.get("summary") or "").strip()
    if not summary:
        raise RuntimeError("create requires a summary")
    product = req.get("product"); component = req.get("component"); version = req.get("version")

    # clone product/component/version from a template bug when asked (keeps filing consistent)
    tb = req.get("template_bug")
    if tb:
        t = read_bug(str(tb).strip())
        product = product or t.get("product")
        component = component or t.get("component")
        version = version or t.get("version")
        lines.append(f"cloned filing target from bug {tb}: {product} :: {component} ({version})")
    version = version or "unspecified"
    if not (product and component):
        raise RuntimeError("need product+component (set them, or pass template_bug to clone from)")

    payload = {
        "product": product, "component": component, "version": version,
        "summary": summary, "type": req.get("type", "task"),
        "op_sys": req.get("op_sys", "Unspecified"),
        "platform": req.get("platform", "Unspecified"),
        "description": _compose_description(req),
    }
    assignee = resolve_assignee(req)
    if assignee:
        payload["assigned_to"] = assignee
    for k in ("keywords", "whiteboard", "depends_on", "blocks", "priority", "severity"):
        if req.get(k):
            payload[k] = req[k]

    lines += ["payload:", json.dumps({k: v for k, v in payload.items() if k != "description"}, indent=2),
              f"assignee: {assignee or '(component default)'}"]

    if req.get("dry_run"):
        if not API_KEY:
            lines.append("\n(dry run — note: BUGZILLA_API_KEY not set, real create would fail)")
        lines.append("\n✅ DRY RUN — no bug filed.")
        result.update({"bug_id": None, "url": None})
        return "\n".join(lines) + "\n", result

    if not API_KEY:
        raise RuntimeError("no Bugzilla API key found — set BUGZILLA_API_KEY (env), or BUGZILLA_API_KEY_FILE, "
                           "or put BUGZILLA_API_KEY=… in tools/.eff.env or ~/.config/eff/eff.env")
    resp = _req("POST", "bug", payload)
    bug_id = resp.get("id")
    if not bug_id:
        raise RuntimeError(f"unexpected BMO response: {resp}")
    url = f"{BZ_URL}/show_bug.cgi?id={bug_id}"
    lines += ["", f"✅ FILED bug {bug_id}", url]
    result.update({"bug_id": int(bug_id), "url": url})

    # Prepend "Bug NNNNN - " to the title so the bug summary matches the commit subject exactly.
    final_summary = summary
    title_updated = False
    if req.get("prepend_bug_number", True) and not summary.lstrip().lower().startswith("bug "):
        final_summary = f"Bug {bug_id} - {summary}"
        try:
            _req("PUT", f"bug/{bug_id}", {"summary": final_summary})
            title_updated = True
            lines.append(f"✅ title updated → {final_summary}")
        except Exception as e:
            # bug is already filed; a title-update failure is non-fatal but must be surfaced
            lines.append(f"⚠️  bug {bug_id} FILED, but title update FAILED: {e}\n"
                         f"   fix manually: set summary to \"{final_summary}\"")
    result.update({"summary": final_summary, "title_updated": title_updated})
    lines.append(f"\ncommit subject to use:\n{final_summary}")
    return "\n".join(lines) + "\n", result

def _tae_version():
    """Version of the whole tae-conversion toolchain (tools + docs are stamped together).

    realpath, not __file__: these tools are commonly invoked through symlinks from another checkout's
    tools/ dir, and an unresolved path would look for VERSION in the wrong repo and report "unknown"
    exactly where a staleness check matters most.
    """
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "VERSION")
    try:
        return open(p).read().strip()
    except OSError:
        return "unknown"


def main():
    if "--version" in sys.argv[1:]:
        print(f"{os.path.basename(__file__)} \u2014 tae-conversion {_tae_version()}")
        sys.exit(0)
    req_path, out_path = sys.argv[1], sys.argv[2]
    req = json.load(open(req_path))
    result_path = out_path.replace("-report.txt", "-result.json")
    try:
        report, result = run(req)
        ok = True
    except Exception as e:
        report, result, ok = f"# effbug: {req.get('bug')}\n❌ FAILED: {e}\n", {"error": str(e)}, False
    open(out_path, "w").write(report)
    json.dump(result, open(result_path, "w"))
    sys.stdout.write(report)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
