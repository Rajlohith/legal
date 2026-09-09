// Shared across index.html, search.html and case-number.html.
// Handles the collapsible sidebar and remembers the user's choice
// (in localStorage) so it stays consistent as you move between pages.
(function () {
    const STORAGE_KEY = "sidebarCollapsed";

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