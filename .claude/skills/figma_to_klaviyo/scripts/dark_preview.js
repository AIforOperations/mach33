// Standardized dark-mode preview for the figma_to_klaviyo verify step.
// Read this file's contents and pass it verbatim as the `function` arg to
// mcp__playwright__browser_evaluate (after navigating to the served render).
// It simulates an inbox dark engine deterministically: darken every near-white
// block background (the dark-opt block_background_color lever) and lighten
// near-black live text, then return counts. Take a screenshot + ONE visual read
// after: transparent cutouts + live text must re-theme uniformly with the base;
// baked own-bg slices (cards, photos) stay as light islands (correct). The
// fixed transform removes the hand-written-eval variance that could falsely pass.
() => {
  const DARK = 'rgb(11, 31, 43)';
  const rgb = (s) => { const m = (s || '').match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/); return m ? [+m[1], +m[2], +m[3]] : null; };
  let bg = 0, txt = 0;
  document.querySelectorAll('*').forEach(e => {
    const c = rgb(getComputedStyle(e).backgroundColor);
    if (c && c[0] > 200 && c[1] > 200 && c[2] > 200) { e.style.backgroundColor = DARK; bg++; }
  });
  document.querySelectorAll('h1,h2,h3,h4,h5,p,span,a,td,div,li').forEach(e => {
    const c = rgb(getComputedStyle(e).color);
    if (c && c[0] < 60 && c[1] < 60 && c[2] < 60) { e.style.color = '#eef3f7'; txt++; }
  });
  document.body.style.backgroundColor = DARK;
  return { recoloredBackgrounds: bg, lightenedText: txt };
}
