// Shared across all pages.
// 1. Runs lucide.createIcons() so sidebar icons always render.
// 2. Sidebar is always collapsed on load — hover-to-expand is handled
//    purely by CSS (.sidebar--collapsed:hover rules in styles.css).
//    No persistent state, no toggle button needed.
(function () {

    // Initialise icons immediately so the brand logo renders.
    if (window.lucide) lucide.createIcons();

    document.addEventListener("DOMContentLoaded", function () {
        // Re-run after DOM is ready in case icons were added late.
        if (window.lucide) lucide.createIcons();

        // Always start collapsed so the CSS hover-expand kicks in.
        var sidebar = document.getElementById("sidebar");
        if (sidebar) {
            sidebar.classList.add("sidebar--collapsed");
        }
    });

})();
