// Shared across all pages.
// 1. Runs lucide.createIcons() so sidebar icons always render.
// 2. Handles the collapsible sidebar and remembers the user's choice
//    (in localStorage) so it stays consistent as you move between pages.
(function () {
    const STORAGE_KEY = "sidebarCollapsed";

    // Always initialise icons -- sidebar.js loads before app.js on every
    // page, so this guarantees the brand logo and toggle icon render even
    // on pages that don't call lucide.createIcons() themselves.
    if (window.lucide) lucide.createIcons();

    function applyState(collapsed) {
        const sidebar = document.getElementById("sidebar");
        const toggleBtn = document.getElementById("sidebarToggle");
        if (!sidebar) return;

        sidebar.classList.toggle("sidebar--collapsed", collapsed);
        if (toggleBtn) {
            toggleBtn.setAttribute("title", collapsed ? "Expand sidebar" : "Collapse sidebar");
            toggleBtn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        // Re-run after DOM is ready in case some icons were added late.
        if (window.lucide) lucide.createIcons();

        applyState(localStorage.getItem(STORAGE_KEY) === "true");

        const toggleBtn = document.getElementById("sidebarToggle");
        if (toggleBtn) {
            toggleBtn.addEventListener("click", function () {
                const sidebar = document.getElementById("sidebar");
                const next = !sidebar.classList.contains("sidebar--collapsed");
                localStorage.setItem(STORAGE_KEY, String(next));
                applyState(next);
            });
        }
    });
})();
