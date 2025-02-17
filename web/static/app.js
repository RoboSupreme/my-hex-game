document.addEventListener("DOMContentLoaded", () => {
    // Get DOM elements
    const playerStatusDiv = document.getElementById("playerStatus");
    const actionButtons = document.getElementById("actionButtons");
    const questionInput = document.getElementById("questionInput");
    const askButton = document.getElementById("askButton");
    const gameOutput = document.getElementById("gameOutput");
    const toggleStats = document.getElementById("toggleStats");
    const spiritAnswer = document.getElementById("spiritAnswer");
    const locationDisplay = document.getElementById("locationDisplay");
    const coordinatesDisplay = document.getElementById("coordinatesDisplay");
    const timeDisplay = document.getElementById("timeDisplay");
    const healthStats = document.getElementById("healthStats");
    const resourceStats = document.getElementById("resourceStats");
    const needsStats = document.getElementById("needsStats");
    const timeStats = document.getElementById("timeStats");

    // Load stats visibility from localStorage or default to visible
    const statsVisible = localStorage.getItem("statsVisible") !== "false";
    playerStatusDiv.className = statsVisible ? "stats-visible" : "stats-hidden";

    // Toggle stats visibility
    toggleStats.addEventListener("click", () => {
        const isVisible = playerStatusDiv.classList.contains("stats-visible");
        playerStatusDiv.className = isVisible ? "stats-hidden" : "stats-visible";
        localStorage.setItem("statsVisible", !isVisible);
    });

    // Utility: append text to gameOutput
    function appendOutput(text) {
        const p = document.createElement("p");
        p.innerHTML = text;
        gameOutput.appendChild(p);
        // Auto-scroll to bottom
        gameOutput.scrollTop = gameOutput.scrollHeight;
    }

    // Format time string
    function formatTime(hour) {
        return `${hour.toString().padStart(2, '0')}:00`;
    }

    // Format day with suffix
    function formatDay(day) {
        const suffixes = {
            1: 'st', 21: 'st', 31: 'st',
            2: 'nd', 22: 'nd',
            3: 'rd', 23: 'rd',
            default: 'th'
        };
        return `${day}${suffixes[day] || suffixes.default}`;
    }

    // 1) Load player state
    async function loadPlayerState() {
        try {
            const res = await fetch("/api/get_player_state");
            const data = await res.json();
            
            // Update location and time info
            locationDisplay.textContent = `Location: ${data.location_name}`;
            coordinatesDisplay.textContent = `Coordinates: (${data.q},${data.r})`; // Removed space after comma to match regex
            timeDisplay.textContent = `Time: Year ${data.time_year} AC, ${data.time_month_str} ${formatDay(data.time_day)}, ${formatTime(data.time_hour)}`;
            
            // Update health & combat stats
            healthStats.innerHTML = `
                <div class="stat-item"><b>Health:</b> ${data.health}</div>
                <div class="stat-item"><b>Attack:</b> ${data.attack}</div>
                <div class="stat-item"><b>Defense:</b> ${data.defense}</div>
                <div class="stat-item"><b>Agility:</b> ${data.agility}</div>
            `;
            
            // Update resource stats
            resourceStats.innerHTML = `
                <div class="stat-item"><b>Money:</b> ${data.money}</div>
                <div class="stat-item"><b>Energy:</b> ${data.energy}</div>
                <div class="stat-item"><b>Alignment:</b> ${data.alignment}/100</div>
            `;
            
            // Update needs stats
            needsStats.innerHTML = `
                <div class="stat-item"><b>Hunger:</b> ${data.hunger}</div>
                <div class="stat-item"><b>Thirst:</b> ${data.thirst}</div>
            `;

            // Update time stats
            timeStats.innerHTML = `
                <div class="stat-item"><b>Year:</b> ${data.time_year} AC</div>
                <div class="stat-item"><b>Month:</b> ${data.time_month_str}</div>
                <div class="stat-item"><b>Day:</b> ${formatDay(data.time_day)}</div>
                <div class="stat-item"><b>Hour:</b> ${formatTime(data.time_hour)}</div>
            `;
        } catch (err) {
            console.error(err);
            appendOutput("Error loading player state: " + err.message);
        }
    }

    // Helper function to add a group of actions
    function addActionGroup(heading, actionList) {
        if (!actionList || actionList.length === 0) return;

        const section = document.createElement("div");
        section.className = "action-group";

        const label = document.createElement("h3");
        label.textContent = heading;
        section.appendChild(label);

        const buttonContainer = document.createElement("div");
        buttonContainer.className = "action-buttons";

        actionList.forEach(action => {
            const btn = document.createElement("button");
            btn.textContent = action;
            btn.addEventListener("click", () => applyAction(action));
            buttonContainer.appendChild(btn);
        });

        section.appendChild(buttonContainer);
        actionButtons.appendChild(section);
    }

    // 2) Load possible actions
    async function loadActions() {
        try {
            const res = await fetch("/api/get_actions");
            const data = await res.json();
            const { location_movement, site_movement, site_actions, follow_up_actions } = data;

            // Clear old buttons
            actionButtons.innerHTML = "";

            // Add each category
            if (follow_up_actions && follow_up_actions.length > 0) {
                // If we have follow-up actions, show them prominently
                addActionGroup("Available Actions", follow_up_actions);
            } else {
                // Otherwise show the standard movement and site actions
                addActionGroup("Location Movement", location_movement);
                addActionGroup("Site Actions", site_movement);
                addActionGroup("Other Actions", site_actions);
            }
        } catch (err) {
            console.error(err);
            appendOutput("Error loading actions: " + err.message);
        }
    }

    // 3) Apply an action
    async function applyAction(actionName) {
        try {
            const res = await fetch("/api/apply_action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ action: actionName })
            });
            const data = await res.json();
            appendOutput(`<b>Action:</b> ${actionName}<br><b>Result:</b> ${data.result}`);
            // refresh UI after action
            await refreshUI();
        } catch (err) {
            console.error(err);
            appendOutput("Error applying action: " + err.message);
        }
    }

    // 4) Ask a question to the spirit
    askButton.addEventListener("click", async () => {
        const question = questionInput.value.trim();
        if (!question) return;
        
        try {
            spiritAnswer.innerHTML = "Asking the spirit...";
            const res = await fetch("/api/ask_question", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question })
            });
            const data = await res.json();
            spiritAnswer.innerHTML = data.answer;
            appendOutput(`<b>You asked:</b> ${question}<br><b>Spirit answers:</b> ${data.answer}`);
            // Refresh UI after spirit interaction
            await refreshUI();
        } catch (err) {
            console.error(err);
            spiritAnswer.innerHTML = "The spirit is silent...";
            appendOutput("Error asking the spirit: " + err.message);
        }
        questionInput.value = "";
    });

    // Also allow pressing Enter to ask a question
    questionInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            askButton.click();
        }
    });

    // Utility: refresh all UI elements
    async function refreshUI() {
        try {
            await loadPlayerState();
            await loadActions();
            // Refresh map if it's visible
            if (document.getElementById('mapContainer').classList.contains('map-visible')) {
                if (typeof refreshMap === 'function') {
                    await refreshMap();
                }
            }
        } catch (err) {
            console.error('Error refreshing UI:', err);
            appendOutput('Error refreshing game state: ' + err.message);
        }
    }

    // On page load, refresh UI
    refreshUI();
});