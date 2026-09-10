// Homepage chatbot. Keeps the conversation in memory (per page load)
// and posts it to the backend, which forwards it to the configured LLM.
(function () {
    const messagesEl = document.getElementById("chatMessages");
    const formEl = document.getElementById("chatForm");
    const inputEl = document.getElementById("chatInput");
    const sendBtn = document.getElementById("chatSendBtn");

    if (!formEl) return; // not on the homepage

    const history = []; // [{role: "user"|"assistant", content: "..."}]

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // Simple markdown → safe HTML renderer (no external deps)
    function renderMarkdown(text) {
        var html = text
            // Escape HTML entities first
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            // Bold **text** or __text__
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/__(.+?)__/g, '<strong>$1</strong>')
            // Italic *text* or _text_ (not at start of line — preserve list bullets)
            .replace(/(?<!\n)\*(?!\*|[ \t])(.+?)(?<!\s)\*/g, '<em>$1</em>')
            // Inline code `code`
            .replace(/`([^`]+)`/g, '<code style="font-family:monospace;font-size:0.9em;background:#EDF0F7;padding:1px 4px;">$1</code>')
            // Convert bullet lines: lines starting with * or - or •
            .replace(/^[ \t]*[\*\-•][ \t]+(.+)$/gm, '<li>$1</li>')
            // Wrap consecutive <li> blocks in <ul>
            .replace(/(<li>[\s\S]*?<\/li>)(\n(?!<li>)|$)/g, function(m) {
                return '<ul style="margin:6px 0 6px 18px;padding:0;">' + m.replace(/\n/g, '') + '</ul>';
            })
            // Numbered lists: lines starting with 1. 2. etc.
            .replace(/^[ \t]*\d+\.[ \t]+(.+)$/gm, '<li>$1</li>')
            // Paragraphs: blank lines → paragraph breaks
            .replace(/\n{2,}/g, '</p><p>')
            // Single newlines → line break
            .replace(/\n/g, '<br>');

        // Wrap in paragraph if not already
        if (!html.startsWith('<')) {
            html = '<p>' + html + '</p>';
        }
        return html;
    }

    function addMessage(role, text) {
        const wrap = document.createElement("div");
        wrap.className = "chat-msg " + (role === "user" ? "chat-msg--user" : "chat-msg--bot");
        const bubble = document.createElement("div");
        bubble.className = "chat-msg__bubble";
        if (role === "user") {
            bubble.textContent = text;
        } else {
            // Render markdown for assistant messages
            bubble.innerHTML = renderMarkdown(text);
        }
        wrap.appendChild(bubble);
        messagesEl.appendChild(wrap);
        scrollToBottom();
        return wrap;
    }

    function addTypingIndicator() {
        const wrap = document.createElement("div");
        wrap.className = "chat-msg chat-msg--bot chat-msg--typing";
        wrap.id = "chatTyping";
        const bubble = document.createElement("div");
        bubble.className = "chat-msg__bubble";
        bubble.textContent = "Thinking…";
        wrap.appendChild(bubble);
        messagesEl.appendChild(wrap);
        scrollToBottom();
    }

    function removeTypingIndicator() {
        const el = document.getElementById("chatTyping");
        if (el) el.remove();
    }

    async function sendMessage(text) {
        history.push({ role: "user", content: text });
        addMessage("user", text);
        addTypingIndicator();
        sendBtn.disabled = true;

        try {
            const resp = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ messages: history }),
            });
            const data = await resp.json();
            removeTypingIndicator();

            const reply = data.reply || "Sorry, I didn't get a response.";
            history.push({ role: "assistant", content: reply });
            addMessage("bot", reply);
        } catch (err) {
            removeTypingIndicator();
            addMessage("bot", "Sorry, I couldn't reach the assistant right now.");
            console.error(err);
        } finally {
            sendBtn.disabled = false;
            inputEl.focus();
        }
    }

    // Auto-grow the textarea a little as the user types.
    inputEl.addEventListener("input", function () {
        inputEl.style.height = "auto";
        inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
    });

    // Enter to send, Shift+Enter for a new line.
    inputEl.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            formEl.requestSubmit();
        }
    });

    formEl.addEventListener("submit", function (e) {
        e.preventDefault();
        const text = inputEl.value.trim();
        if (!text) return;
        inputEl.value = "";
        inputEl.style.height = "auto";
        sendMessage(text);
    });
})();
