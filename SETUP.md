# SETUP, one-time machine setup (Claude runs this)

A ONE-TIME setup per machine. **Claude executes these steps**; the human only copies in the
`.env` file, restarts the app once, and completes any password / UAC prompt during installs. It
is idempotent: safe to re-run, it skips whatever is already done. Works on **macOS and Windows**.
There is **no GitHub login**, the repo is public.

Trigger: the teammate says "set me up" / "run setup", or the skill's step 0 reports the
machine is not ready. Follow the steps IN ORDER, run every CHECK before installing, install
only what is missing, and print a clear PASS/FAIL checklist at the end.

> Cross-platform rule: detect the OS first and use the matching column. Do not assume macOS.

## 0. Detect the OS
- **macOS** if `uname` returns `Darwin`. Package manager: Homebrew. Python command: `python3`.
- **Windows** if `uname` is absent or returns `MINGW*`/`MSYS*`, or `$env:OS` is `Windows_NT`.
  Package manager: `winget` (ships with Windows 10/11). Python command: `python` (plus a
  `python3` shim, step 6).

## 1. Package manager
- macOS: `brew --version` ; if missing, install Homebrew (`/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`, prompts for the Mac password).
- Windows: `winget --version` ; if missing, install "App Installer" from the Microsoft Store.

## 2. git (no GitHub login needed)
- `git --version` ; if missing, macOS `xcode-select --install` ; Windows `winget install --id Git.Git -e`.
- The repo is **public**, so cloning needs NO GitHub account and NO `gh`. Plain `git clone`
  over HTTPS is all that is required. (If a clone ever prompts for GitHub credentials, the repo
  was flipped back to private; ask the owner to make it public again, or run `gh auth login` once.)

## 3. Clone into a per-person folder (NOT "mach33")
- If you are ALREADY inside the repo (the current folder contains `.claude/`), just `git pull` and go to step 4.
- Otherwise ask the person their **first name**, then clone into a folder named for them:
  `git clone https://github.com/AIforOperations/mach33.git "<FirstName>-Figma-to-Klaviyo"`,
  then `cd` into it. Sanitize the name to letters/digits/hyphens (e.g. "Jo Ann" becomes "JoAnn-Figma-to-Klaviyo").
  If that folder already exists from a previous attempt, `cd` into it and `git pull` instead of cloning.
  Do NOT leave it as the default "mach33" folder.
- The repo root (the folder you just entered, holding `README.md` + `.claude/`) is "the repo root" referenced below.

## 4. Drop in the .env (the Klaviyo key you were given)
- Check for `.env` at the repo root. If it is missing, **PAUSE and ask the human** to copy the
  `.env` file they were given into this exact folder (give them the absolute path of the
  `<FirstName>-Figma-to-Klaviyo` folder you just cloned), then continue once they confirm.
- Re-check that `.env` exists at the repo root and has a line starting `KLAVIYO_API_KEY=`. The
  scripts read the key from this FILE automatically (env vars win if set); it is NOT a shell
  variable, so do not try to `echo $KLAVIYO_API_KEY`. Step 10 proves it actually resolves.
- A real sending key is NEVER committed; this is a DUMMY key, rotate before any real send.

## 5. Node.js (Playwright verify step needs it)
- `node --version` ; if missing, macOS `brew install node` ; Windows `winget install --id OpenJS.NodeJS.LTS -e`. Want Node 20+.

## 6. Python 3 and the `python3` command
- Python 3 present? macOS `python3 --version` ; Windows `python --version`. If missing,
  macOS `brew install python` (or `xcode-select --install`) ; Windows `winget install --id Python.Python.3.12 -e`.
- Ensure Pillow: `python3 -m pip install --user Pillow` (Windows: `python -m pip install --user Pillow`).
- **WINDOWS ONLY, make `python3` resolve.** The scripts AND the safety-guard hook call
  `python3`, but stock Windows only has `python`/`py`. Create a shim so `python3` works:
  1. Pick a folder on PATH (or create `%USERPROFILE%\bin` and add it to PATH with
     `setx PATH "%USERPROFILE%\bin;%PATH%"`, then reopen the shell).
  2. In it, write `python3.cmd` whose body runs whichever of these starts Python 3 on this
     machine (test first): `@py -3 %*` (py launcher) or `@python %*`.
  3. Confirm `python3 --version` now prints Python 3.x.

## 7. Playwright browser binary
- `npx --yes playwright install chromium` (one-time ~400MB download; the verify step fails without it).

## 8. RESTART Claude Code (mandatory on Windows if anything was installed)
Anything installed in steps 2-7, ESPECIALLY the Windows `python3` shim, was added to PATH AFTER
Claude Code launched. The running app cannot see it: that includes the safety-guard hook the app
spawns AND this terminal. If you do not restart, the guard hook can silently fail to find
`python3` and **fall open** (a destructive Figma call would go through), and the step-9 self-test
below would not reflect the real hook.
- If you installed ANYTHING this run (or you are on Windows and created the shim), tell the human:
  **"Quit and fully reopen Claude Code Desktop, then tell me to continue setup."** When they
  resume, re-run this routine: every install CHECK now passes (already installed), so you fall
  through to steps 9-11, which now run with the correct PATH.
- If nothing was installed this run (everything was already present), no restart is needed; continue.

## 9. SELF-TEST THE SAFETY GUARD (CRITICAL, never skip; run AFTER the step-8 restart)
A failed guard hook is **fail-OPEN** (the destructive call would proceed), so PROVE the guard
blocks on THIS machine before trusting it for Figma writes:
```
echo '{"tool_name":"mcp__claude_ai_Figma__use_figma","tool_input":{"code":"node.remove()"}}' | python3 .claude/hooks/figma_guard.py
```
Must return JSON containing `"permissionDecision":"deny"`. Then confirm a reversible write passes:
```
echo '{"tool_name":"mcp__claude_ai_Figma__use_figma","tool_input":{"code":"node.fills=orig"}}' | python3 .claude/hooks/figma_guard.py
```
Must return `"allow"`. (The guard fires on any tool ending in `use_figma`, so this is the same
code path as the real Figma connector.) If the first does NOT return `deny` (usually `python3`
not found), **STOP**: the machine is NOT safe for Figma writes. Fix `python3` (step 6), restart
(step 8), and re-test.

## 10. Smoke-test the scripts
- `python3 .claude/skills/figma_to_klaviyo/scripts/build_def.py -h` (prints usage).
- `python3 .claude/skills/figma_to_klaviyo/scripts/imaging.py dims t.png` (prints "W H"). A fresh
  clone has no PNG; make a throwaway one first: `python3 -c "from PIL import Image; Image.new('RGB',(2,2),'white').save('t.png')"` (delete `t.png` after).
- `python3 .claude/skills/figma_to_klaviyo/scripts/klaviyo.py checkenv` (OFFLINE; prints "OK: Klaviyo
  key resolved ..." and which `.env` it used). If it instead prints "no KLAVIYO_API_KEY found", the
  `.env` is missing or in the wrong folder, fix step 4.
- `python3 .claude/skills/figma_to_klaviyo/scripts/klaviyo.py list` (ONLINE; lists templates, confirms
  the key is valid). An HTTP/auth error here (not a "no key found" error) means the key resolved but
  the dummy account or network has an issue, note it, it is not a setup blocker.

## 11. Claude Code wiring
- The human must be signed into Claude Code with the SHARED Claude account, so the **Figma
  account Connector** loads. NOTE: an account Connector may NOT appear in `claude mcp list`
  (that lists project `.mcp.json` servers like `playwright`, not account Connectors). Confirm
  Figma instead by asking Claude to do a small Figma READ (e.g. `get_metadata` on any node), or
  by checking claude.ai -> Settings -> Connectors. If a Figma read works, Figma is wired. If not,
  they are not on the shared account, or the Connector is not added.
- The skill pre-approves Figma under both names (`mcp__figma__*` and the connector's
  `mcp__claude_ai_Figma__*`), so either setup works without repeated prompts.
- On first open of the project, approve the hook + the Playwright MCP server if prompted.

## Report
Print PASS/FAIL for: OS, git, clone (per-person folder name), **`.env` present + key resolves
(`checkenv`)**, node, python3 (+ Windows shim), Pillow, Playwright browser, **restart done if
needed**, **GUARD SELF-TEST (must PASS)**, scripts smoke, Figma read works. For anything not PASS,
tell the human the exact next action. Then: "Open the `<FirstName>-Figma-to-Klaviyo` folder in
Claude Code and type `/figma_to_klaviyo <figma link>`."
