/**
 * Copilot Chat - WebSocket with REST fallback.
 * D3: Inline data cards for request references
 * D7: Proactive suggestions on page load
 * D8: Session persistence via sessionStorage
 * D9: WebSocket streaming with tool-use step feedback
 */
(function () {
    const messagesEl = document.getElementById("copilot-messages");
    const form = document.getElementById("copilot-form");
    const input = document.getElementById("copilot-input");

    // D8: Restore chat history from sessionStorage
    let chatHistory = [];
    try {
        const saved = sessionStorage.getItem("copilot_history");
        if (saved) {
            chatHistory = JSON.parse(saved);
            // Re-render saved messages
            chatHistory.forEach(msg => addMessage(msg.role, msg.content, true));
        }
    } catch (e) { /* ignore parse errors */ }

    function saveHistory() {
        try {
            // Keep last 20 messages to avoid storage limits
            const toSave = chatHistory.slice(-20);
            sessionStorage.setItem("copilot_history", JSON.stringify(toSave));
        } catch (e) { /* ignore quota errors */ }
    }

    // Get current page context
    function getContext() {
        const ctx = { page: document.title };
        const match = window.location.pathname.match(/\/request\/([a-f0-9-]+)/i);
        if (match) ctx.request_id = match[1];
        return ctx;
    }

    // D3: Replace [REQUEST:uuid] markers with clickable data cards
    function renderInlineCards(html) {
        return html.replace(
            /\b([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\b/gi,
            function(match) {
                return '<a href="/dashboard/request/' + match + '" ' +
                    'class="inline-block bg-blue-50 border border-blue-200 rounded px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 cursor-pointer" ' +
                    'title="Antrag anzeigen">' + match.substring(0, 8) + '...</a>';
            }
        );
    }

    // D3: Replace SP-XXXX-XXXX patterns with clickable links
    function renderDisplayIds(html) {
        return html.replace(
            /\b(SP-\d{4}-\d{4})\b/g,
            '<span class="inline-block bg-blue-50 border border-blue-200 rounded px-2 py-0.5 text-xs text-blue-700 font-mono">$1</span>'
        );
    }

    function addMessage(role, text, isRestore) {
        const div = document.createElement("div");
        div.className = role === "user" ? "copilot-msg-user" :
                        role === "suggestion" ? "copilot-msg-suggestion" :
                        "copilot-msg-assistant";
        if (role === "assistant" || role === "suggestion") {
            if (typeof marked !== "undefined") {
                let html = marked.parse(text);
                html = renderInlineCards(html);
                html = renderDisplayIds(html);
                div.innerHTML = html;
                div.querySelectorAll("table").forEach(t => {
                    t.classList.add("text-xs", "border-collapse", "w-full", "mt-2", "mb-2");
                    t.querySelectorAll("th,td").forEach(c => c.classList.add("border", "border-gray-300", "px-2", "py-1"));
                });
            } else {
                let html = text
                    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
                    .replace(/```([\s\S]*?)```/g, "<pre class='bg-gray-100 p-2 rounded text-xs overflow-x-auto my-1'>$1</pre>")
                    .replace(/`([^`]+)`/g, "<code class='bg-gray-200 px-1 rounded text-xs'>$1</code>")
                    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
                    .replace(/\n/g, "<br>");
                html = renderInlineCards(html);
                html = renderDisplayIds(html);
                div.innerHTML = html;
            }
        } else {
            div.textContent = text;
        }
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // D9: Show tool-use step indicator
    function showToolStep(toolName) {
        let el = document.getElementById("copilot-tool-step");
        if (!el) {
            el = document.createElement("div");
            el.id = "copilot-tool-step";
            el.className = "copilot-msg-assistant flex items-center gap-2 text-xs text-gray-500 italic";
            messagesEl.appendChild(el);
        }
        const toolLabels = {
            search_requests: "Suche Anfragen...",
            get_request_detail: "Lade Anfragedetails...",
            get_budget_status: "Pruefe Budget...",
            get_statistics: "Berechne Statistiken...",
            search_historical: "Durchsuche Historie...",
            get_org_profile: "Lade Organisationsprofil...",
            get_audit_trail: "Lese Verlaufsprotokoll...",
            run_analytics_query: "Fuehre Analyse aus...",
            approve_request: "Genehmige Antrag...",
            reject_request: "Lehne Antrag ab...",
            defer_request: "Stelle Antrag zurueck...",
            compare_requests: "Vergleiche Anfragen...",
            draft_email: "Erstelle E-Mail-Entwurf...",
            run_pipeline: "Starte Pipeline...",
            get_config: "Lese Konfiguration...",
            update_config: "Aktualisiere Konfiguration...",
        };
        const label = toolLabels[toolName] || `Tool: ${toolName}...`;
        el.innerHTML = '<svg class="animate-spin h-3 w-3 text-primary-500" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>' +
            '<span>' + label + '</span>';
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function removeToolStep() {
        const el = document.getElementById("copilot-tool-step");
        if (el) el.remove();
    }

    function showTyping() {
        const div = document.createElement("div");
        div.id = "copilot-typing";
        div.className = "copilot-msg-assistant flex items-center gap-1";
        div.innerHTML = '<span class="animate-pulse">Thinking</span><span class="animate-bounce inline-block">...</span>';
        messagesEl.appendChild(div);
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function removeTyping() {
        const el = document.getElementById("copilot-typing");
        if (el) el.remove();
    }

    // ----------------------------------------------------------------
    // D9: WebSocket connection with auto-reconnect
    // ----------------------------------------------------------------
    let ws = null;
    let wsReady = false;
    let wsReconnectTimer = null;
    let pendingResolve = null;

    function connectWs() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const url = proto + "//" + location.host + "/ws/copilot";

        try {
            ws = new WebSocket(url);
        } catch (e) {
            wsReady = false;
            return;
        }

        ws.onopen = () => {
            wsReady = true;
            if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // D9: Handle streaming tool-use steps
                if (data.type === "tool_start") {
                    showToolStep(data.tool_name);
                    return;
                }
                if (data.type === "tool_result") {
                    // Tool completed, keep showing for next step
                    return;
                }

                // Final reply
                removeToolStep();
                removeTyping();
                const reply = data.reply || "No response.";
                addMessage("assistant", reply);
                chatHistory.push({ role: "assistant", content: reply });
                saveHistory();

                if (pendingResolve) { pendingResolve(); pendingResolve = null; }
            } catch (e) { /* ignore parse errors */ }
        };

        ws.onclose = () => {
            wsReady = false;
            // Auto-reconnect after 3 seconds
            if (!wsReconnectTimer) {
                wsReconnectTimer = setTimeout(connectWs, 3000);
            }
        };

        ws.onerror = () => {
            wsReady = false;
        };
    }

    // Try to connect WebSocket on load
    connectWs();

    // ----------------------------------------------------------------
    // Send message: prefer WebSocket, fallback to REST
    // ----------------------------------------------------------------
    async function sendMessage(text) {
        if (!text.trim()) return;
        addMessage("user", text);
        chatHistory.push({ role: "user", content: text });
        saveHistory();
        input.value = "";
        showTyping();

        // Try WebSocket first
        if (wsReady && ws && ws.readyState === WebSocket.OPEN) {
            try {
                ws.send(JSON.stringify({
                    messages: chatHistory,
                    context: getContext(),
                }));
                // Wait for response via onmessage handler
                await new Promise((resolve) => {
                    pendingResolve = resolve;
                    // Timeout fallback after 60 seconds
                    setTimeout(() => {
                        if (pendingResolve) { pendingResolve(); pendingResolve = null; }
                    }, 60000);
                });
                return;
            } catch (e) {
                // Fall through to REST
            }
        }

        // REST fallback
        try {
            const resp = await fetch("/api/copilot/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    messages: chatHistory,
                    context: getContext(),
                }),
            });
            const data = await resp.json();
            removeTyping();
            const reply = data.reply || "No response.";
            addMessage("assistant", reply);
            chatHistory.push({ role: "assistant", content: reply });
            saveHistory();
        } catch (err) {
            removeTyping();
            addMessage("assistant", "Verbindungsfehler. Bitte erneut versuchen.");
        }
    }

    form.addEventListener("submit", (e) => {
        e.preventDefault();
        sendMessage(input.value);
    });

    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage(input.value);
        }
    });

    // D8: Clear Chat button
    const clearBtn = document.getElementById("copilot-clear");
    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            chatHistory = [];
            sessionStorage.removeItem("copilot_history");
            messagesEl.innerHTML = "";
        });
    }

    // D7: Load proactive suggestion on page load
    async function loadSuggestion() {
        try {
            const ctx = getContext();
            const params = new URLSearchParams({ page: ctx.page || "" });
            if (ctx.request_id) params.append("request_id", ctx.request_id);
            const resp = await fetch("/api/copilot/suggestion?" + params.toString());
            const data = await resp.json();
            if (data.suggestion) {
                addMessage("suggestion", data.suggestion);
            }
        } catch (e) { /* silently fail */ }
    }
    // Load suggestion after a short delay (let page render first)
    setTimeout(loadSuggestion, 1500);

    // --- Voice input (Web Speech API) ---
    const micBtn = document.getElementById("copilot-mic");
    if (micBtn && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window)) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.lang = "de-DE";
        recognition.continuous = false;
        recognition.interimResults = false;
        let listening = false;

        micBtn.addEventListener("click", () => {
            if (listening) {
                recognition.stop();
                return;
            }
            recognition.start();
            listening = true;
            micBtn.classList.add("bg-red-500", "animate-pulse");
            micBtn.classList.remove("bg-gray-200");
        });

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            input.value = transcript;
            sendMessage(transcript);
        };

        recognition.onend = () => {
            listening = false;
            micBtn.classList.remove("bg-red-500", "animate-pulse");
            micBtn.classList.add("bg-gray-200");
        };

        recognition.onerror = () => {
            listening = false;
            micBtn.classList.remove("bg-red-500", "animate-pulse");
            micBtn.classList.add("bg-gray-200");
        };
    }
})();
