# Onboarding a teammate

Hand-off guide for setting up a new person on the Figma to Klaviyo tool. The install is
clone-and-run: Claude does all the technical work; the person only clicks prompts and drops in
one file.

## Send them three things
1. The **shared Mach33 Claude account** login.
2. The **`.env`** file (it lives at `mach33/.env`) — the Klaviyo key; it is never in the repo.
3. **The prompt below** — they paste it into Claude Code.

## The prompt to share (they paste this into Claude Code)

```
Set me up for the Figma-to-Klaviyo tool. Ask me my first name, then (installing git first if it's missing) clone https://github.com/AIforOperations/mach33 with a plain public git clone (no login) into a new folder named "<my first name>-Figma-to-Klaviyo", and follow the SETUP.md inside it. I have a .env file to add, so pause and tell me when to drop it into that folder.
```

## What the person does (Claude does everything else)
1. Install **Claude Code Desktop**; sign in with the **shared Mach33 Claude account** (not a
   personal one, that is what connects Figma).
2. Save the **`.env`** somewhere easy to find (the Desktop is fine).
3. Open any empty folder in Claude Code and paste the prompt above.
4. Follow Claude's prompts:
   - when it pauses, **drag the `.env` into the folder it names**, then tell it to continue;
   - **approve** any password / install pop-ups;
   - **Windows:** when asked, **quit and reopen Claude Code once**, then type "continue setup".
5. When it finishes, **open the new `<name>-Figma-to-Klaviyo` folder** in Claude Code. Build a
   template with `/figma_to_klaviyo <paste a Figma email link>`.

First run is ~10-15 min (it downloads a browser). After that it is instant.

## Before you roll this out
- Do **one real install yourself first, ideally on Windows**, to validate.
- Confirm the **Figma Connector** is on the shared Claude account (claude.ai -> Settings -> Connectors); everyone inherits it from there.
- Make sure the **`.env`** has the key you intend (rotate the dummy key first if needed).
