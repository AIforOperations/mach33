#!/usr/bin/env python3
"""Figma MCP guard (PreToolUse hook).

Policy (set by the file owner, 2026-06): Figma WRITES are ALLOWED — including
`use_figma` — EXCEPT operations that DELETE or destroy existing design content
(node removal, child wiping, deleteCharacters). `use_figma` runs arbitrary JS via
the Figma Plugin API; this guard inspects that code and DENIES it only when it
contains a deletion/destructive call. Reversible writes (fills, export settings,
text edits incl. `.characters = ...`, layout, clones) and all reads pass.

BEST-EFFORT, NOT A SANDBOX. A regex over arbitrary JS cannot catch every
obfuscation (`eval("node.rem"+"ove()")`, `node[String.fromCharCode(...)]()`),
so this guard catches the plain dotted / bracket / aliased forms only. The real
guarantee is the agent's standing no-deletion rule (SKILL.md, figma_and_env.md);
the guard is a backstop against an ACCIDENTAL destructive call, not a security
boundary. It deliberately does NOT block `.characters = "..."` text edits, which
the translation retext flow needs (reversible: capture + restore).

Wired for any `*use_figma` tool (either Figma MCP server) via the PreToolUse
matcher in settings.json. Fail-safe: on a parse error, DENY.
"""
import sys, json, re

# Destructive Figma Plugin API operations to block. `remove` is also an English
# word that appears in marketing copy, so it is matched ONLY as a call (`.remove(`)
# or a bracket key; the API-specific tokens are matched as a bare reference too
# (so an aliased `const d = node.deleteCharacters; d()` is still caught).
_DOTTED_CALL = re.compile(r"\.\s*remove\s*\(", re.IGNORECASE)                                   # node.remove(...)
_DOTTED_API  = re.compile(r"\.\s*(?:removeChild(?:ren)?|removeRange|deleteCharacters)\b", re.IGNORECASE)
_CHILDREN    = re.compile(r"\.\s*children\s*=\s*\[\s*\]")                                       # node.children = []
_BRACKET     = re.compile(r"""\[\s*[\x27\x22\x60](?:remove|removeChild(?:ren)?|removeRange|deleteCharacters)[\x27\x22\x60]\s*\]""", re.IGNORECASE)  # node["remove"]() / node[`remove`]()


def _strip_comments(code):
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.DOTALL)   # block comments
    code = re.sub(r"//[^\n]*", " ", code)                     # line comments
    return code


def _blank_string_contents(code):
    # Blank the CONTENTS of '...' and "..." (keep the quotes) so a destructive word
    # inside a DATA string (marketing copy, a retext value) does not false-match.
    # Backticks are intentionally NOT blanked: a template literal can carry a real
    # `${ node.remove() }` call, which must still be caught.
    return re.sub(r"""(['"])(?:\\.|(?!\1).)*?\1""", r"\1\1", code)


def is_destructive(code):
    nocomments = _strip_comments(code)
    # Bracket access is checked WITH strings intact (the destructive name IS the
    # string-literal key, e.g. node["remove"]()).
    m = _BRACKET.search(nocomments)
    if m:
        return m.group(0)
    # Dotted / children checks run with string CONTENTS blanked, so `.remove` etc.
    # appearing inside copy strings do not trip them.
    blanked = _blank_string_contents(nocomments)
    for rx in (_DOTTED_CALL, _DOTTED_API, _CHILDREN):
        m = rx.search(blanked)
        if m:
            return m.group(0)
    return None


def emit(decision, reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason}}))
    sys.exit(0)


try:
    data = json.load(sys.stdin)
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}

    # Only police the code-runner. Other Figma tools (reads, creates) are not the
    # deletion path; this guard has no opinion on them.
    if not tool.endswith("use_figma"):
        sys.exit(0)

    code = tool_input.get("code") or ""
    hit = is_destructive(code)
    if hit:
        emit("deny",
             "BLOCKED: a Figma DELETION/destructive call was detected in the "
             f"use_figma code ({hit!r}). Reversible writes are allowed; deleting "
             "or removing design content is not. Change this only by editing the "
             "guard hook file.")
    emit("allow",
         "use_figma: no deletion/destructive call detected; reversible write allowed.")

except Exception as e:
    emit("deny", f"BLOCKED (figma guard fail-safe): could not evaluate the request ({e}).")
