/** Runs before first paint (inlined in the root layout), so the page never flashes. */
const STORAGE_KEY = "wfe-theme";

export const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("${STORAGE_KEY}");if(t==="dark"||(!t&&matchMedia("(prefers-color-scheme: dark)").matches)){document.documentElement.classList.add("dark")}}catch(e){}})();`;

export { STORAGE_KEY };
