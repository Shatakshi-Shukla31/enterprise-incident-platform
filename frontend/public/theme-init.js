// Runs before the first paint, so a dark page never flashes light. This is a file rather
// than an inline script because the production Content-Security-Policy forbids those.
(function () {
  var saved = null;
  try {
    saved = localStorage.getItem("theme");
  } catch (error) {
    // Storage can be blocked. The system setting still applies.
  }
  var dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
})();
