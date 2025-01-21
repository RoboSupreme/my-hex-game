document.addEventListener("DOMContentLoaded", () => {
    const playerStatusDiv = document.getElementById("playerStatus");
    const actionsContainer = document.getElementById("actionsContainer");
    const askInput = document.getElementById("askInput");
    const askButton = document.getElementById("askButton");
    const outputLog = document.getElementById("outputLog");
    const toggleStats = document.getElementById("toggleStats");

    // Load stats visibility from localStorage or default to visible
    const statsVisible = localStorage.getItem("statsVisible") !== "false";
    playerStatusDiv.className = statsVisible ? "stats-visible" : "stats-hidden";

    // Toggle stats visibility
    toggleStats.addEventListener("click", () => {
        const isVisible = playerStatusDiv.classList.contains("stats-visible");
        playerStatusDiv.className = isVisible ? "stats-hidden" : "stats-visible";
        localStorage.setItem("statsVisible", !isVisible);
    });

    // Utility: append text to outputLog
    function appendLog(text) {
        const p = document.createElement("p");
        p.innerHTML = text;
        outputLog.appendChild(p);
        // Auto-scroll to bottom
        outputLog.scrollTop = outputLog.scrollHeight;
    }

    // 1) Load player state
    async function loadPlayerState() {
        try {
            const res = await fetch("/api/get_player_state");
            const data = await res.json();
            playerStatusDiv.innerHTML = `
                <div class="status-row location-info">
                    <div class="status-item">
                        <b>Location:</b> ${data.location_name} (${data.q}, ${data.r})
                    </div>
                    ${data.place_name ? `
                    <div class="status-item">
                        <b>Inside:</b> ${data.place_name}
                    </div>
                    ` : ''}
                </div>
                <div class="stats-grid">
                    <div class="stats-column primary-stats">
                        <div class="stat-item">
                            <b>Health:</b> ${data.health}
                        </div>
                        <div class="stat-item">
                            <b>Energy:</b> ${data.energy}
                        </div>
                        <div class="stat-item">
                            <b>Money:</b> ${data.money}
                        </div>
                    </div>
                    <div class="stats-column needs-stats">
                        <div class="stat-item">
                            <b>Hunger:</b> ${data.hunger}
                        </div>
                        <div class="stat-item">
                            <b>Thirst:</b> ${data.thirst}
                        </div>
                        <div class="stat-item">
                            <b>Alignment:</b> ${data.alignment}/100
                        </div>
                    </div>
                    <div class="stats-column combat-stats">
                        <div class="stat-item">
                            <b>Attack:</b> ${data.attack}
                        </div>
                        <div class="stat-item">
                            <b>Defense:</b> ${data.defense}
                        </div>
                        <div class="stat-item">
                            <b>Agility:</b> ${data.agility}
                        </div>
                    </div>
                </div>
            `;
        } catch (err) {
            console.error(err);
            playerStatusDiv.innerHTML = "Error loading player state.";
        }
    }

    // 2) Load possible actions
    async function loadActions() {
        try {
            const res = await fetch("/api/get_actions");
            const data = await res.json();
            const actions = data.actions;
            actionsContainer.innerHTML = ""; // clear old
            actions.forEach(action => {
                const btn = document.createElement("button");
                btn.textContent = action;
                btn.addEventListener("click", () => applyAction(action));
                actionsContainer.appendChild(btn);
            });
        } catch (err) {
            console.error(err);
            actionsContainer.innerHTML = "Error loading actions.";
        }
    }

    // 3) Apply an action by calling /api/apply_action
    async function applyAction(actionName) {
        try {
            const res = await fetch("/api/apply_action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: actionName })
            });
            const data = await res.json();
            appendLog(`<b>Action:</b> ${actionName}<br><b>Result:</b> ${data.result}`);
            // refresh UI
            await loadPlayerState();
            await loadActions();
        } catch (err) {
            console.error(err);
            appendLog("Error applying action: " + err);
        }
    }

    // 4) Ask a question
    askButton.addEventListener("click", async () => {
        const question = askInput.value.trim();
        if (!question) return;
        try {
            const res = await fetch("/api/ask_question", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question })
            });
            const data = await res.json();
            appendLog(`<b>Q:</b> ${question}<br><b>A:</b> ${data.answer}`);
        } catch (err) {
            console.error(err);
            appendLog("Error asking question: " + err);
        }
        askInput.value = "";
    });

    // On page load, fetch initial state + actions
    loadPlayerState();
    loadActions();
});