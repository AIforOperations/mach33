#!/usr/bin/env python3
"""Klaviyo template + image client for the figma_to_klaviyo skill.

Subcommands:
  upload <file> [--name NAME] [--manifest PATH]      upload image (multipart) -> prints "name id url"
  create <payload.json>                              create template -> prints id
  patch  <id> <payload.json>                         patch template definition
  render <id> [--context k=v ...] [--out PATH]       render saved template -> saves HTML (default render.html)
  get    <id> [--out PATH]                           fetch full template (saves JSON)
  list   [--filter SUBSTR]                           list templates (id | name | editor | HAS-BUTTON)
  checkenv                                           offline: confirm the key (default or --store) resolves
  stores                                             offline: list wired stores from .env (keys MASKED)
  wire   <export.csv> [--only s1,s2] [--write-env P] verify each store's key via /accounts, write .env block
  whichstore [--brand NAME] [--figma-file-key KEY]   resolve a design to ONE store slug (or fail; never guess)
  learnfigma --figma-file-key KEY  (with --store)    remember that a Figma file belongs to a store

Auth (single, default account): KLAVIYO_API_KEY + KLAVIYO_API_REVISION from env vars first; else a
.env found by walking up from BOTH this script's folder and the cwd; else --env <path>.

Auth (multi-store): a single .env can also hold many accounts as namespaced vars
  KLAVIYO_STORE_<SLUG>_KEY=pk_...      (the secret)
  KLAVIYO_STORE_<SLUG>_PUBLIC=AbC123   (6-char public/company id; NOT secret)
  KLAVIYO_STORE_<SLUG>_NAME=Acme       (verified Klaviyo org name)
  KLAVIYO_STORE_<SLUG>_FIGMA=fileKey   (optional; learned Figma file key(s), space-separated)
Select one with `--store <slug>` (or the KLAVIYO_STORE env). An explicit --store that does not
resolve HARD-FAILS; it never silently falls back to the default key. The .env parser tolerates a
BOM, CRLF, surrounding quotes, and `export `. No third-party deps (urllib + csv, stdlib only).

Secret hygiene: no full `pk_` key is ever printed. Key-bearing output is masked (pk_...wxyz) AND
run through _redact() as a backstop; the only key material ever shown is that prefix+last4 mask.
"""
import sys, os, json, time, argparse, uuid, hashlib, mimetypes, csv, re, urllib.request, urllib.error

BASE = "https://a.klaviyo.com"

_PK_RE = re.compile(r"pk_[A-Za-z0-9_-]{6,}")                     # a real Klaviyo private key (alnum/_/- tolerant)
_STORE_RE = re.compile(r"^KLAVIYO_STORE_(.+)_(KEY|PUBLIC|NAME|FIGMA|REVISION)$")

def _redact(s):
    # Last line of defense: scrub any full pk_ key from anything we print. A deliberate mask
    # (pk_...wxyz, produced by _mask) survives this because "..." is not [A-Za-z0-9].
    return _PK_RE.sub("pk_<redacted>", str(s))

def _mask(k):
    return ("%s...%s" % (k[:3], k[-4:])) if (k and len(k) > 11) else "pk_...????"

def _err(msg):   sys.exit(_redact(msg))
def _log(msg):   sys.stderr.write(_redact(msg))
def _out(msg):   sys.stdout.write(_redact(str(msg)) + "\n")   # stdout backstop; the pk_...wxyz mask survives _redact

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

def _all_env_values(env_path=None):
    # Merged view for store parsing: the first existing .env (repo .env wins via DEFAULT_ENVS
    # ordering), overlaid by real KLAVIYO_* env vars (env wins, so cloud env vars work later).
    vals = {}
    for p in ([env_path] if env_path else DEFAULT_ENVS):
        if p and os.path.exists(p):
            fv = _read_env_file(p)
            if fv:
                vals.update(fv); break
    for k, v in os.environ.items():
        if k.startswith("KLAVIYO_"):
            vals[k] = v
    return vals

def _parse_stores(vals):
    # {slug: {key, public, name, figma, revision}} from KLAVIYO_STORE_<SLUG>_<FIELD> pairs.
    stores = {}
    for k, v in vals.items():
        m = _STORE_RE.match(k)
        if not m:
            continue
        stores.setdefault(m.group(1).lower(), {})[m.group(2).lower()] = v
    return stores

def _env_source(env_path=None):
    return next((p for p in ([env_path] if env_path else DEFAULT_ENVS) if p and os.path.exists(p)), None)

def load_auth(env_path=None, store=None):
    """Returns (key, rev, store_meta_or_None).
       --store / KLAVIYO_STORE selects a namespaced account and is AUTHORITATIVE: it overrides the
       default key and HARD-FAILS if unresolved (never falls back to the dummy). No store => today's
       single-key path (env var KLAVIYO_API_KEY, else the .env walk-up), unchanged."""
    store = store or os.environ.get("KLAVIYO_STORE")
    if store:
        slug = store.lower()
        stores = _parse_stores(_all_env_values(env_path))
        s = stores.get(slug)
        if not s or not s.get("key"):
            known = ", ".join(sorted(stores)) or "(none)"
            _err("ERROR: --store %r not found in .env (need KLAVIYO_STORE_%s_KEY). Known stores: %s\n"
                 "Wire stores with: klaviyo.py wire <export.csv> ; list them with: klaviyo.py stores"
                 % (slug, slug.upper(), known))
        if not s["key"].startswith("pk_"):
            _err("ERROR: store %r has a malformed key (must start with pk_)." % slug)
        rev = s.get("revision") or os.environ.get("KLAVIYO_API_REVISION", "2026-04-15")
        return s["key"], rev, {"slug": slug, "public": s.get("public", ""),
                               "name": s.get("name", ""), "figma": s.get("figma", "")}
    # ---- single-key (default account) path, unchanged ----
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
    return key, rev, None

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
            _err("ERROR: network failure after retries (%s)" % e)

def die(status, payload):
    hint = ("  [rate / daily-cap: reuse already-uploaded CDN urls from the manifest; the "
            "per-endpoint daily image cap resets after hours]") if status == 429 else ""
    _err("ERROR HTTP %s: %s%s" % (status, json.dumps(payload)[:800], hint))

# ---------------------------------------------------------------------------
# multi-store helpers
# ---------------------------------------------------------------------------
def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "store"

def _target_desc(store):
    if store:
        return "store '%s' / %s (public %s)" % (store["slug"], store.get("name") or "?", store.get("public") or "?")
    return "DEFAULT account (.env KLAVIYO_API_KEY)"

def _repo_root():
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        for _ in range(4):                       # scripts/ -> figma_to_klaviyo -> skills -> .claude -> repo root
            d = os.path.dirname(d)
        return d
    except NameError:
        return os.getcwd()

def _assert_safe_keyfile(path, what):
    # Refuse to write raw keys into a repo file git would NOT ignore. Inside the repo only a
    # `.env`-prefixed name is ignored (.gitignore `.env*`); any other in-repo name could be committed.
    ap = os.path.abspath(path); root = os.path.abspath(_repo_root())
    inside = ap == root or ap.startswith(root + os.sep)
    if inside and not os.path.basename(ap).startswith(".env"):
        _err("ERROR: refusing to write keys to %r (%s): it is inside the repo but not a .env* name,\n"
             "so git could commit it. Use a .env-prefixed name, or a path outside the repo." % (path, what))

def _default_env_path(env_path=None):
    # write target for wire/learnfigma: the explicit --env if given, else the .env the skill reads,
    # else the repo-root .env. Respecting --env keeps the read and write on the SAME file.
    if env_path:
        return env_path
    p = _env_source()
    if p:
        return p
    try:
        d = os.path.dirname(os.path.abspath(__file__))
        for _ in range(4):
            d = os.path.dirname(d)
        return os.path.join(d, ".env")
    except NameError:
        return os.path.join(os.getcwd(), ".env")

def _set_env_var(path, name, value):
    lines, found, existing = [], False, ""
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            existing = f.read()
        for line in existing.splitlines():
            if "=" in line and line.split("=", 1)[0].strip() == name:
                lines.append("%s=%s" % (name, value)); found = True
            else:
                lines.append(line)
    if not found:
        lines.append("%s=%s" % (name, value))
    if existing:
        with open(path + ".bak", "w", encoding="utf-8") as f:   # never lose an unrotatable key on a mid-write crash
            f.write(existing)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    os.replace(tmp, path)                                       # atomic swap

def _read_import_csv(path):
    # Tolerant: detect the store-name + key columns from the header, else assume col0=name col1=key.
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = [r for r in csv.reader(f) if any((c or "").strip() for c in r)]
    if not rows:
        _err("ERROR: %s is empty." % path)
    header = [(c or "").strip().lower() for c in rows[0]]
    ki = next((i for i, h in enumerate(header) if any(t in h for t in ("api", "key", "token"))), None)
    ni = next((i for i, h in enumerate(header) if any(t in h for t in ("store", "name", "brand", "account", "client"))), None)
    start = 1
    if ki is None:                                   # no recognizable header row
        ni, ki = 0, 1
        start = 0 if any((c or "").strip().startswith("pk_") for c in rows[0]) else 1
    if ni is None:
        ni = 0 if ki != 0 else 1
    out = []
    for r in rows[start:]:
        if len(r) <= max(ki, ni):
            continue
        name, key = (r[ni] or "").strip(), (r[ki] or "").strip()
        if name or key:
            out.append((name, key))
    return out

def _merge_stores_into_env(path, good):
    # Idempotent: drop any existing lines (and our comment) for the slugs we are (re)writing,
    # keep everything else (esp. KLAVIYO_API_KEY), append fresh blocks. Backs up to .env.bak.
    existing = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            existing = f.read()
    slugs = {r[0] for r in good}
    prior = _parse_stores(_read_env_file(path)) if os.path.exists(path) else {}   # keep learned _FIGMA/_REVISION across a re-wire
    keep = []
    for line in existing.splitlines():
        drop = False
        if "=" in line:
            m = _STORE_RE.match(line.split("=", 1)[0].strip())
            if m and m.group(1).lower() in slugs:
                drop = True
        st = line.strip()
        if st.startswith("# store "):
            parts = st.split()
            if len(parts) >= 3 and parts[2].lower() in slugs:
                drop = True
        if not drop:
            keep.append(line)
    block = []
    for slug, name, live, public, key, status in good:
        U = slug.upper()
        block += ["",
                  "# store %s  ->  %s  (klaviyo org: %s, public %s)" % (slug, name, live or "?", public or "?"),
                  "KLAVIYO_STORE_%s_KEY=%s" % (U, key),
                  "KLAVIYO_STORE_%s_PUBLIC=%s" % (U, public),
                  "KLAVIYO_STORE_%s_NAME=%s" % (U, live or name)]
        figma = (prior.get(slug) or {}).get("figma", "")
        if figma:                                            # preserve a learned Figma->store binding across re-wire
            block.append("KLAVIYO_STORE_%s_FIGMA=%s" % (U, figma))
        rev0 = (prior.get(slug) or {}).get("revision", "")
        if rev0:
            block.append("KLAVIYO_STORE_%s_REVISION=%s" % (U, rev0))
    if existing:
        with open(path + ".bak", "w", encoding="utf-8") as f:
            f.write(existing)
    with open(path, "w", encoding="utf-8") as f:
        f.write(("\n".join(keep).rstrip() + "\n" + "\n".join(block).strip() + "\n").lstrip("\n"))

def _cmd_stores(a):
    stores = _parse_stores(_all_env_values(a.env))
    src = _env_source(a.env) or "(no .env found)"
    if not stores:
        _out("No stores wired in %s." % src)
        _out("Add them with:  klaviyo.py wire <stores_import.csv>")
        return
    _out(".env: %s" % src)
    bad = 0
    for slug in sorted(stores):
        s = stores[slug]; k = s.get("key", ""); ok = k.startswith("pk_"); bad += 0 if ok else 1
        _out("%-16s | %-26s | public %-8s | figma %-22s | %s%s"
             % (slug, (s.get("name") or "-")[:26], s.get("public") or "-",
                (s.get("figma") or "-")[:22], _mask(k), "" if ok else "  <-- MALFORMED KEY"))
    _out("%d store(s); offline only. Run 'list --store <slug>' to prove one key is live." % len(stores))
    if bad:
        sys.exit(2)

def _print_store(stores, slug, tier):
    s = stores[slug]
    # machine-readable for the skill: slug \t name \t public \t maskedkey \t tier
    _out("%s\t%s\t%s\t%s\t%s" % (slug, s.get("name", ""), s.get("public", ""), _mask(s.get("key", "")), tier))

def _cmd_whichstore(a):
    stores = _parse_stores(_all_env_values(a.env))
    if not stores:
        _err("ERROR: no stores wired; run 'klaviyo.py wire <stores_import.csv>'.")
    fk = (a.figma_file_key or "").strip()
    if fk:                                            # Tier 1: learned Figma file key (deterministic)
        hits = [sl for sl, s in stores.items() if s.get("key") and fk in re.split(r"[ ,;]+", s.get("figma", ""))]
        if len(hits) == 1:
            return _print_store(stores, hits[0], "EXACT (figma file key)")
        if len(hits) > 1:
            _err("ERROR: figma file key %s maps to >1 store: %s (dedupe .env)." % (fk, ", ".join(sorted(hits))))
    b = _norm(a.brand)
    if b:                                             # Tier 2/3: normalized exact match on slug or org name (must have a key)
        hits = [sl for sl, s in stores.items() if s.get("key") and (_norm(sl) == b or _norm(s.get("name", "")) == b)]
        if len(hits) == 1:
            return _print_store(stores, hits[0], "MATCH (brand name)")
        if len(hits) > 1:
            _err("ERROR: brand %r matches >1 store: %s; pass an explicit --store." % (a.brand, ", ".join(sorted(hits))))
    _err("NO MATCH for brand=%r figma=%r. Known stores: %s.\n"
         "Pass an explicit --store <slug>, or wire the store first. (Will NOT guess or use the dummy.)"
         % (a.brand, fk, ", ".join(sorted(stores))))

def _cmd_learnfigma(a):
    if not a.store:
        _err("ERROR: learnfigma needs --store <slug> (the store the Figma file belongs to).")
    slug = a.store.lower()
    stores = _parse_stores(_all_env_values(a.env))
    if slug not in stores:
        _err("ERROR: store %r is not wired; run 'wire' first." % slug)
    fk = a.figma_file_key.strip()
    cur = [x for x in re.split(r"[ ,;]+", stores[slug].get("figma", "")) if x]
    if fk in cur:
        print("already learned: %s -> %s" % (fk, slug)); return
    cur.append(fk)
    _set_env_var(_default_env_path(a.env), "KLAVIYO_STORE_%s_FIGMA" % slug.upper(), " ".join(cur))
    print("learned: figma file key %s -> store %s" % (fk, slug))

def _cmd_wire(a):
    if not os.path.exists(a.csv):
        _err("ERROR: import csv not found: %s" % a.csv)
    rows = _read_import_csv(a.csv)
    if not rows:
        _err("ERROR: no (store name, key) rows parsed from %s." % a.csv)
    only = set(x.strip().lower() for x in a.only.split(",") if x.strip()) if a.only else None
    rev = os.environ.get("KLAVIYO_API_REVISION", "2026-04-15")
    results, used = [], set()
    for name, key in rows:
        base = _slugify(name); slug = base; n = 1
        while slug in used:                          # bump until unique so "Acme"/"Acme 2"/"Acme" can't collide on acme_2
            n += 1; slug = "%s_%d" % (base, n)
        used.add(slug)
        if only and slug not in only:
            continue
        if not key.startswith("pk_"):
            results.append((slug, name, "(skipped: not a pk_ key)", "", key, "BAD")); continue
        st, d = call("GET", "/api/accounts/", key, rev)
        if st != 200:
            results.append((slug, name, "(HTTP %s: key rejected)" % st, "", key, "FAIL")); continue
        data = (d.get("data") or [{}])[0]
        attrs = data.get("attributes", {}) or {}
        public = data.get("id", "")
        live = (attrs.get("contact_information", {}) or {}).get("organization_name", "") or ""
        status = "OK" if _norm(live) == _norm(name) else "CHECK"
        results.append((slug, name, live, public, key, status))
    print("Verified %d row(s) via GET /api/accounts/  (keys MASKED):\n" % len(results))
    print("%-16s | %-22s | %-24s | %-8s | %-9s | status" % ("slug", "sheet name", "klaviyo org name", "public", "key"))
    print("-" * 96)
    for slug, name, live, public, key, status in results:
        _out("%-16s | %-22s | %-24s | %-8s | %-9s | %s"
             % (slug, name[:22], (live or "-")[:24], public or "-", _mask(key), status))
    good = [r for r in results if r[5] in ("OK", "CHECK")]
    if not good:
        print("\nNo valid stores to write (every key was rejected or malformed)."); sys.exit(2)
    target = a.write_env or _default_env_path(a.env)
    _assert_safe_keyfile(target, "wire --write-env")
    _merge_stores_into_env(target, good)
    print("\nWrote %d store(s) into %s  (backup: %s.bak)." % (len(good), target, target))
    print("DELETE the import CSV now: %s" % a.csv)
    chk = [r[0] for r in results if r[5] == "CHECK"]
    if chk:
        print("REVIEW (%d): sheet name != Klaviyo org name, eyeball these once: %s" % (len(chk), ", ".join(chk)))
    bad = [r[0] for r in results if r[5] in ("BAD", "FAIL")]
    if bad:
        print("SKIPPED (%d, bad/rejected key, NOT written): %s" % (len(bad), ", ".join(bad)))

def main():
    ap = argparse.ArgumentParser(description="Klaviyo client for figma_to_klaviyo")
    ap.add_argument("--env")
    ap.add_argument("--store", help="account from .env KLAVIYO_STORE_<SLUG>_* (overrides default key; hard-fails if unknown)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("upload"); u.add_argument("file"); u.add_argument("--name"); u.add_argument("--manifest")
    c = sub.add_parser("create"); c.add_argument("payload")
    p = sub.add_parser("patch"); p.add_argument("id"); p.add_argument("payload")
    r = sub.add_parser("render"); r.add_argument("id"); r.add_argument("--context", nargs="*", default=[]); r.add_argument("--out", default="render.html")
    g = sub.add_parser("get"); g.add_argument("id"); g.add_argument("--out")
    l = sub.add_parser("list"); l.add_argument("--filter", default="")
    sub.add_parser("checkenv")   # offline: prove a key resolves, no API call
    sub.add_parser("stores")     # offline: list wired stores, keys masked
    wp = sub.add_parser("wire"); wp.add_argument("csv"); wp.add_argument("--only", default=""); wp.add_argument("--write-env", default="", dest="write_env")
    ws = sub.add_parser("whichstore"); ws.add_argument("--brand", default=""); ws.add_argument("--figma-file-key", default="", dest="figma_file_key")
    lf = sub.add_parser("learnfigma"); lf.add_argument("--figma-file-key", required=True, dest="figma_file_key")
    a = ap.parse_args()

    # commands that read per-row / per-store keys (or none) — do NOT resolve a single default key
    if a.cmd == "stores":     return _cmd_stores(a)
    if a.cmd == "wire":       return _cmd_wire(a)
    if a.cmd == "whichstore": return _cmd_whichstore(a)
    if a.cmd == "learnfigma": return _cmd_learnfigma(a)

    key, rev, store = load_auth(a.env, a.store)

    if a.cmd == "checkenv":
        if store:
            _out("OK: store '%s' resolved (%s), public %s, key %s, revision %s"
                 % (store["slug"], store.get("name") or "?", store.get("public") or "?", _mask(key), rev))
            print("source: %s" % (_env_source(a.env) or "env vars"))
        else:
            if os.environ.get("KLAVIYO_API_KEY"):
                src = "env var KLAVIYO_API_KEY"
            elif a.env and os.path.exists(a.env):
                src = a.env
            else:
                src = next((p for p in DEFAULT_ENVS if os.path.exists(p) and _read_env_file(p).get("KLAVIYO_API_KEY")), "(.env not found)")
            _out("OK: default Klaviyo key resolved (%s), revision %s" % (_mask(key), rev))
            print("source: %s" % src)
        print("offline check only - run 'list' (optionally --store <slug>) to confirm the key works against the API")
        return

    if a.cmd == "upload":
        if not os.path.exists(a.file): sys.exit("ERROR: file not found: %s" % a.file)
        name = (a.name or os.path.splitext(os.path.basename(a.file))[0]).replace("\t", " ").replace("\n", " ")
        sz = os.path.getsize(a.file)
        if sz > 5 * 1024 * 1024:
            sys.exit("ERROR: %s is %.1fMB; Klaviyo caps uploads at 5MB. Compress or split it." % (a.file, sz / 1048576.0))
        h8 = _sha8(a.file)
        pub = store["public"] if store else ""
        if a.manifest and os.path.exists(a.manifest):   # reuse: identical CONTENT already uploaded -> no new upload (saves the daily cap)
            for line in open(a.manifest, encoding="utf-8"):
                pcols = line.rstrip("\r\n").split("\t")
                if len(pcols) >= 4 and pcols[3] == h8:   # match on content-hash (a drifted name must not miss the cache)
                    cached_pub = pcols[4] if len(pcols) >= 5 else ""
                    if store and cached_pub and cached_pub != pub:
                        _err("ERROR: %s is cached in %s under account %r, but --store %s is account %r. "
                             "Image asset_ids/urls are PER-ACCOUNT and not portable; point --manifest at this "
                             "store's own builds/<slug>/ manifest." % (a.file, a.manifest, cached_pub, store["slug"], pub or "?"))
                    if store and not cached_pub:        # untagged legacy line in store mode: re-upload to tag it, don't reuse blindly
                        _log("warning: %s line for %s is untagged; re-uploading to bind it to %s\n" % (a.manifest, a.file, store["slug"]))
                        continue
                    _log("cached: %s already uploaded (%s); not re-uploaded\n" % (a.file, pcols[1]))
                    print("%s %s %s" % (pcols[0], pcols[1], pcols[2])); return
        if sz > 1024 * 1024:
            sys.stderr.write("warning: %s is %.1fMB (did you forget to compress?)\n" % (a.file, sz / 1048576.0))
        _log("klaviyo: upload %s -> %s  key %s\n" % (os.path.basename(a.file), _target_desc(store), _mask(key)))
        st, d = call("POST", "/api/image-upload", key, rev, files={"file": a.file}, fields={"name": name})
        if st != 201: die(st, d)
        aid = d["data"]["id"]; url = d["data"]["attributes"]["image_url"]
        rname = d["data"]["attributes"].get("name", name)   # Klaviyo appends a numeric suffix on a dup name
        print("%s %s %s" % (rname, aid, url))
        if a.manifest:
            with open(a.manifest, "a", encoding="utf-8") as f:
                f.write("%s\t%s\t%s\t%s%s\n" % (rname, aid, url, h8, ("\t" + pub) if (store and pub) else ""))

    elif a.cmd == "create":
        body = _load_json(a.payload)
        _log("klaviyo: create template -> %s  key %s\n" % (_target_desc(store), _mask(key)))  # which account am I writing to
        st, d = call("POST", "/api/templates/", key, rev, body=body)
        if st != 201: die(st, d)
        print(d["data"]["id"])

    elif a.cmd == "patch":
        body = _load_json(a.payload)
        body.setdefault("data", {})["id"] = a.id; body["data"]["type"] = "template"
        defn = body["data"].get("attributes", {}).get("definition")
        if defn is not None:   # scrub read-only ids so a GET -> edit -> PATCH round-trip does not 400 (keeps asset_id)
            body["data"]["attributes"]["definition"] = _scrub_ids(defn)
        _log("klaviyo: patch %s -> %s  key %s\n" % (a.id, _target_desc(store), _mask(key)))
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
