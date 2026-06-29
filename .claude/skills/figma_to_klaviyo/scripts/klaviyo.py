#!/usr/bin/env python3
"""Klaviyo template + image client for the figma_to_klaviyo skill.

Subcommands:
  upload <file> [--name NAME] [--manifest PATH]      upload image (multipart) -> prints "name id url"
  create <payload.json>                              create template -> prints id
  patch  <id> <payload.json>                         patch template definition
  render <id> [--context k=v ...] [--out PATH]       render saved template -> saves HTML (default render.html)
  get    <id> [--out PATH]                           fetch full template (saves JSON)
  list   [--filter SUBSTR]                           list templates (id | name | editor | HAS-BUTTON)
  checkenv                                           offline: confirm the .env key resolves (no API call)

Auth: KLAVIYO_API_KEY + KLAVIYO_API_REVISION from env vars first; else a .env found by
walking up from BOTH this script's folder and the cwd (so it resolves from any directory);
else --env <path>. The .env parser tolerates a BOM, CRLF, surrounding quotes, and `export `.
No third-party deps (urllib only).
"""
import sys, os, json, time, argparse, uuid, hashlib, mimetypes, urllib.request, urllib.error

BASE = "https://a.klaviyo.com"

def _loads(raw):
    # Klaviyo errors usually return JSON, but a gateway/WAF 5xx can return HTML.
    try:
        return json.loads(raw or b"{}")
    except Exception:
        return {"_raw": (raw[:800].decode("utf-8", "replace") if raw else "")}

def _sha8(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]

def _load_json(path):
    if not os.path.exists(path): sys.exit("ERROR: file not found: %s" % path)
    try:
        return json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit("ERROR: bad JSON in %s: %s" % (path, e))

def _scrub_ids(o):
    # Remove read-only ids recursively (keep asset_id, which image blocks require).
    # Klaviyo 400s a create/patch that carries id/data_id/template_id.
    if isinstance(o, list): return [_scrub_ids(x) for x in o]
    if isinstance(o, dict): return {k: _scrub_ids(v) for k, v in o.items() if k not in ("id", "data_id", "template_id")}
    return o
def _env_candidates():
    # Portable: walk UP from BOTH this script's folder and the cwd, collecting every
    # .env on the way to the filesystem root. Anchoring on __file__ matters because the
    # script lives at <repo>/.claude/skills/figma_to_klaviyo/scripts/, so it finds the
    # repo-root .env no matter which directory Claude happens to run it from (the cwd
    # walk-up alone misses it when the cwd is outside/above the repo). Env vars still
    # take priority in load_auth; this is only the file fallback.
    starts = []
    try:
        starts.append(os.path.dirname(os.path.abspath(__file__)))  # script dir FIRST so the repo's own .env wins over an unrelated .env in/above the cwd
    except NameError:
        pass
    starts.append(os.getcwd())
    seen, out = set(), []
    for start in starts:
        d = start
        for _ in range(12):
            p = os.path.join(d, ".env")
            if p not in seen:
                seen.add(p); out.append(p)
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return out

def _read_env_file(path):
    # Parse KEY=VALUE pairs, tolerant of a UTF-8 BOM (Windows editors add one),
    # CRLF, surrounding quotes, leading whitespace, and an `export ` prefix.
    vals = {}
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line[:7].lower() == "export ":
                    line = line[7:].lstrip()
                k, v = line.split("=", 1)
                v = v.strip()
                if v[:1] not in ("'", '"'):
                    v = v.split(" #", 1)[0].split("\t#", 1)[0].rstrip()  # drop an inline comment on an unquoted value
                vals[k.strip()] = v.strip("\"'")
    except OSError:
        return {}
    return vals

DEFAULT_ENVS = _env_candidates()

def load_auth(env_path=None):
    key = os.environ.get("KLAVIYO_API_KEY")
    rev = os.environ.get("KLAVIYO_API_REVISION", "2026-04-15")
    searched = [env_path] if env_path else DEFAULT_ENVS
    if not key:
        for p in searched:
            if p and os.path.exists(p):
                vals = _read_env_file(p)
                if vals.get("KLAVIYO_API_KEY"):
                    key = vals["KLAVIYO_API_KEY"]
                    if vals.get("KLAVIYO_API_REVISION"):
                        rev = vals["KLAVIYO_API_REVISION"]
                    break
    if not key:
        looked = "\n  ".join(p for p in searched if p)
        sys.exit("ERROR: no KLAVIYO_API_KEY found.\n"
                 "Fix: put the .env you were given at the repo root (next to README.md), or\n"
                 "set KLAVIYO_API_KEY as an env var, or pass --env <path to .env>.\n"
                 "The key lives in the .env FILE - the scripts read it automatically; it is\n"
                 "NOT a shell environment variable. Looked for a .env in:\n  " + looked)
    return key, rev

def call(method, path, key, rev, body=None, files=None, fields=None):
    headers = {"Authorization": "Klaviyo-API-Key " + key, "revision": rev,
               "Accept": "application/vnd.api+json"}
    data = None
    if files is not None or fields is not None:
        boundary = "----ftk" + uuid.uuid4().hex
        buf = []
        for k, v in (fields or {}).items():
            buf.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode())
        for k, fp in (files or {}).items():
            fn = os.path.basename(fp); ct = mimetypes.guess_type(fn)[0] or "application/octet-stream"
            buf.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                        % (boundary, k, fn, ct)).encode())
            buf.append(open(fp, "rb").read()); buf.append(b"\r\n")
        buf.append(("--%s--\r\n" % boundary).encode())
        data = b"".join(buf)
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    elif body is not None:
        data = json.dumps(body).encode(); headers["Content-Type"] = "application/vnd.api+json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    for attempt in range(5):  # retry on rate-limit / transient (parallel uploads hit 3/s)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, _loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                ra = None
                try:
                    ra = float(e.headers.get("Retry-After")) if (e.headers and e.headers.get("Retry-After")) else None
                except (ValueError, TypeError):
                    ra = None
                if ra is not None: ra = max(0.0, ra)   # a negative Retry-After must never reach time.sleep
                if e.code == 429 and ra is not None and ra > 30:
                    return e.code, _loads(e.read())   # daily/long cap (hours away): don't burn retries, surface it
                time.sleep(ra if (ra is not None and ra <= 30) else 1.5 * (attempt + 1)); continue
            return e.code, _loads(e.read())
        except OSError as e:   # URLError + socket timeout + connection reset are all OSError subclasses
            if attempt < 4:
                time.sleep(1.5 * (attempt + 1)); continue
            sys.exit("ERROR: network failure after retries (%s)" % e)

def die(status, payload):
    hint = ("  [rate / daily-cap: reuse already-uploaded CDN urls from the manifest; the "
            "per-endpoint daily image cap resets after hours]") if status == 429 else ""
    sys.exit("ERROR HTTP %s: %s%s" % (status, json.dumps(payload)[:800], hint))

def main():
    ap = argparse.ArgumentParser(description="Klaviyo client for figma_to_klaviyo")
    ap.add_argument("--env")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("upload"); u.add_argument("file"); u.add_argument("--name"); u.add_argument("--manifest")
    c = sub.add_parser("create"); c.add_argument("payload")
    p = sub.add_parser("patch"); p.add_argument("id"); p.add_argument("payload")
    r = sub.add_parser("render"); r.add_argument("id"); r.add_argument("--context", nargs="*", default=[]); r.add_argument("--out", default="render.html")
    g = sub.add_parser("get"); g.add_argument("id"); g.add_argument("--out")
    l = sub.add_parser("list"); l.add_argument("--filter", default="")
    sub.add_parser("checkenv")   # offline: prove the .env key resolves, no API call
    a = ap.parse_args()
    key, rev = load_auth(a.env)

    if a.cmd == "checkenv":
        if os.environ.get("KLAVIYO_API_KEY"):
            src = "env var KLAVIYO_API_KEY"
        elif a.env and os.path.exists(a.env):
            src = a.env
        else:
            src = next((p for p in DEFAULT_ENVS if os.path.exists(p) and _read_env_file(p).get("KLAVIYO_API_KEY")), "(.env not found)")
        print("OK: Klaviyo key resolved (...%s), revision %s" % (key[-4:], rev))
        print("source: %s" % src)
        print("offline check only - run 'list' to confirm the key works against the API")
        return

    if a.cmd == "upload":
        if not os.path.exists(a.file): sys.exit("ERROR: file not found: %s" % a.file)
        name = (a.name or os.path.splitext(os.path.basename(a.file))[0]).replace("\t", " ").replace("\n", " ")
        sz = os.path.getsize(a.file)
        if sz > 5 * 1024 * 1024:
            sys.exit("ERROR: %s is %.1fMB; Klaviyo caps uploads at 5MB. Compress or split it." % (a.file, sz / 1048576.0))
        h8 = _sha8(a.file)
        if a.manifest and os.path.exists(a.manifest):   # reuse: identical CONTENT already uploaded -> no new upload (saves the daily cap)
            for line in open(a.manifest, encoding="utf-8"):
                p = line.rstrip("\r\n").split("\t")
                if len(p) >= 4 and p[3] == h8:   # match on content-hash (a drifted name must not miss the cache)
                    sys.stderr.write("cached: %s already uploaded (%s); not re-uploaded\n" % (a.file, p[1]))
                    print("%s %s %s" % (p[0], p[1], p[2])); return
        if sz > 1024 * 1024:
            sys.stderr.write("warning: %s is %.1fMB (did you forget to compress?)\n" % (a.file, sz / 1048576.0))
        st, d = call("POST", "/api/image-upload", key, rev, files={"file": a.file}, fields={"name": name})
        if st != 201: die(st, d)
        aid = d["data"]["id"]; url = d["data"]["attributes"]["image_url"]
        rname = d["data"]["attributes"].get("name", name)   # Klaviyo appends a numeric suffix on a dup name
        print("%s %s %s" % (rname, aid, url))
        if a.manifest:
            with open(a.manifest, "a", encoding="utf-8") as f: f.write("%s\t%s\t%s\t%s\n" % (rname, aid, url, h8))

    elif a.cmd == "create":
        body = _load_json(a.payload)
        sys.stderr.write("klaviyo: create with key ...%s\n" % key[-4:])  # which account am I writing to
        st, d = call("POST", "/api/templates/", key, rev, body=body)
        if st != 201: die(st, d)
        print(d["data"]["id"])

    elif a.cmd == "patch":
        body = _load_json(a.payload)
        body.setdefault("data", {})["id"] = a.id; body["data"]["type"] = "template"
        defn = body["data"].get("attributes", {}).get("definition")
        if defn is not None:   # scrub read-only ids so a GET -> edit -> PATCH round-trip does not 400 (keeps asset_id)
            body["data"]["attributes"]["definition"] = _scrub_ids(defn)
        sys.stderr.write("klaviyo: patch %s with key ...%s\n" % (a.id, key[-4:]))
        st, d = call("PATCH", "/api/templates/%s/" % a.id, key, rev, body=body)
        if st != 200: die(st, d)
        print("patched", a.id)

    elif a.cmd == "render":
        ctx = {}
        for kv in a.context:
            if "=" in kv: k, v = kv.split("=", 1); ctx[k] = v
        body = {"data": {"type": "template", "attributes": {"id": a.id, "context": ctx}}}
        st, d = call("POST", "/api/template-render/", key, rev, body=body)
        if st != 200: die(st, d)
        html = d["data"]["attributes"].get("html", "")
        open(a.out, "w", encoding="utf-8").write(html)
        print("rendered %s -> %s (%d bytes)" % (a.id, a.out, len(html)))

    elif a.cmd == "get":
        st, d = call("GET", "/api/templates/%s/" % a.id, key, rev)
        if st != 200: die(st, d)
        out = a.out or ("tpl_%s.json" % a.id)
        open(out, "w", encoding="utf-8").write(json.dumps(d, indent=2))
        print("saved", out)

    elif a.cmd == "list":
        st, d = call("GET", "/api/templates/?page%5Bsize%5D=10", key, rev)
        if st != 200: die(st, d)
        for t in d.get("data", []):
            at = t.get("attributes", {}); defn = at.get("definition")
            if a.filter and a.filter.lower() not in (at.get("name", "") or "").lower(): continue
            hb = "HAS-BUTTON" if defn and '"type":"button"' in json.dumps(defn, separators=(",", ":")) else "-"
            print("%s | %s | %s | %s" % (t["id"], at.get("name"), at.get("editor_type"), hb))

if __name__ == "__main__":
    main()
