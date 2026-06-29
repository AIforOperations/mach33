# Figma to Klaviyo

Turn an approved Figma email design into a verified, mobile-first Klaviyo template, from
Claude Code. Runs on **macOS and Windows**.

## One-time setup (per machine)

1. Install **Claude Code Desktop** and sign in with the **shared Mach33 Claude account**.
   That is what makes Figma work. There is **no per-machine Figma login and no GitHub login**,
   the repo is public, so cloning needs no sign-in.
2. Save the **`.env` file** you were given somewhere easy to find (your Desktop is fine).
3. Open any empty folder in Claude Code and paste this one message:

   > Set me up for the Figma-to-Klaviyo tool. Ask me my first name, then (installing git first if it's missing) clone https://github.com/AIforOperations/mach33 with a plain public git clone (no login) into a new folder named "<my first name>-Figma-to-Klaviyo", and follow the SETUP.md inside it. I have a .env file to add, so pause and tell me when to drop it into that folder.

   Claude installs everything it needs (Git, Node, Python, Playwright, the image library),
   adapting to your operating system, and pauses to let you copy in the `.env`. Just complete
   any password / permission prompts when they pop up.
4. When it finishes, open the new **`<your name>-Figma-to-Klaviyo`** folder (the one that
   contains a `.claude` folder) in Claude Code.

That is it. You never touch the command line yourself; Claude runs the steps.

## To build a template

In the open project, type:

```
/figma_to_klaviyo <paste the Figma email node link>
```

Claude reads the design, builds the Klaviyo template (live text + sliced images + buttons,
with dark-mode handling), verifies the render on mobile + desktop + dark mode, and gives you
the Klaviyo template id and editor link. For other languages, ask it to build the replica in
that language.

## Good to know

- Always sign in to Claude Code with the **shared Claude account** (the Figma connection
  rides on it; a personal API-key login will not see Figma).
- The **`.env`** holds the Klaviyo keys (the shared dummy account, plus one key per client store
  once it is set up). It is given to you separately, lives only on your machine, and is never in
  the repo. Drop it into your `<your name>-Figma-to-Klaviyo` folder during setup. The dummy key can
  be rotated; the **real store keys cannot, so never commit or share the `.env`** (a safety hook
  blocks committing it).
- The skill never deletes anything in Figma; a safety guard blocks that, and setup verifies
  the guard works on your machine.
- Full detail for Claude lives in `CLAUDE.md`, `SETUP.md`, and `.claude/skills/figma_to_klaviyo/`.
