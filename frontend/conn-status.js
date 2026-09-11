// Shared across every page.
// Keeps the topbar "Connected / Reconnecting…" pill in sync with the
// backend, independent of whatever page-specific WebSocket (app.js,
// case-number.js, chat.js) may also be open for search/chat progress.
(function () {
  function $(id) { return document.getElementById(id); }

  function setConnected(connected) {
    var dot = $("connDot");
    var label = $("connLabel");
    if (dot) dot.classList.toggle("connected", connected);
    if (label) label.textContent = connected ? "Connected" : "Reconnecting…";
  }

  function connect() {
    // Nothing to update on pages without the status pill.
    if (!$("connStatus")) return;

    var proto = location.protocol === "https:" ? "wss" : "ws";
    var ws = new WebSocket(proto + "://" + location.host + "/ws/logs");

    ws.onopen = function () { setConnected(true); };
    ws.onclose = function () {
      setConnected(false);
      setTimeout(connect, 2000);
    };
    ws.onerror = function () { ws.close(); };
  }

  document.addEventListener("DOMContentLoaded", connect);
})();
