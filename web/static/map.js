// Map initialization and rendering
document.addEventListener("DOMContentLoaded", () => {
    // Constants
    const HEX_SIZE = 50;  // side length of each hex cell
    const sqrt3 = Math.sqrt(3);

    // State
    let mapData = [];
    let cameraOffset = { x: 400, y: 300 }; // Center of canvas
    let cameraZoom = 1.0;
    let isDragging = false;
    let lastMousePos = { x: 0, y: 0 };

    // Get DOM elements
    const mapContainer = document.getElementById("mapContainer");
    const toggleMap = document.getElementById("toggleMap");
    const canvas = document.getElementById("mapCanvas");
    const ctx = canvas.getContext("2d");

    // Load map visibility from localStorage
    const mapVisible = localStorage.getItem("mapVisible") !== "false";
    mapContainer.className = mapVisible ? "map-visible" : "map-hidden";

    // Toggle map visibility
    toggleMap.addEventListener("click", () => {
        const isVisible = mapContainer.classList.contains("map-visible");
        mapContainer.className = isVisible ? "map-hidden" : "map-visible";
        localStorage.setItem("mapVisible", !isVisible);
        if (!isVisible) {
            // Refresh map when showing
            refreshMap();
        }
    });

    // Convert axial coordinates (q,r) to pixel coordinates
    function hexToPixel(q, r) {
        const x = HEX_SIZE * sqrt3 * (q + r/2);
        const y = HEX_SIZE * 1.5 * r;
        return { x, y };
    }

    // Draw a single pointy-topped hex
    function drawHex(ctx, cx, cy, fill = "#eee", stroke = "#888") {
        ctx.beginPath();
        for (let i = 0; i < 6; i++) {
            const angleDeg = 60 * i - 30;
            const angleRad = Math.PI / 180 * angleDeg;
            const x = cx + HEX_SIZE * Math.cos(angleRad);
            const y = cy + HEX_SIZE * Math.sin(angleRad);
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.strokeStyle = stroke;
        ctx.fill();
        ctx.stroke();
    }

    // Get a stable offset for location placement within a hex
    function stableSubPosition(locName) {
        let hash = 0;
        for (let i = 0; i < locName.length; i++) {
            hash = (hash << 5) - hash + locName.charCodeAt(i);
            hash |= 0;
        }
        const dx = (hash % 60) - 30;
        const dy = ((hash / 60) % 60) - 30;
        return { dx, dy };
    }

    // Pick a shape based on location name
    function pickShape(locName) {
        const shapes = ["circle", "triangle", "square"];
        let index = 0;
        for (let i = 0; i < locName.length; i++) {
            index = (index + locName.charCodeAt(i)) % shapes.length;
        }
        return shapes[index];
    }

    // Draw location marker
    function drawLocation(ctx, shape, x, y, isCurrentLocation = false) {
        ctx.save();
        ctx.translate(x, y);
        
        // Draw highlight for current location
        if (isCurrentLocation) {
            ctx.beginPath();
            ctx.arc(0, 0, 12, 0, 2 * Math.PI);
            ctx.fillStyle = "rgba(74, 144, 226, 0.3)";
            ctx.fill();
        }

        ctx.fillStyle = isCurrentLocation ? "#4a90e2" : "#c33";
        
        if (shape === "circle") {
            ctx.beginPath();
            ctx.arc(0, 0, 8, 0, 2 * Math.PI);
            ctx.fill();
        } else if (shape === "square") {
            ctx.fillRect(-6, -6, 12, 12);
        } else { // triangle
            ctx.beginPath();
            ctx.moveTo(0, -8);
            ctx.lineTo(7, 6);
            ctx.lineTo(-7, 6);
            ctx.closePath();
            ctx.fill();
        }
        ctx.restore();
    }

    // Draw connection between locations
    function drawLine(ctx, x1, y1, x2, y2) {
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = "#444";
        ctx.stroke();
    }

    // Main map drawing function
    function drawMap() {
        console.log('Drawing map...');
        // Get current player location
        const coordsText = document.getElementById("coordinatesDisplay").textContent;
        console.log('Coordinates text:', coordsText);
        const qMatch = coordsText.match(/\((-?\d+)/);
        const rMatch = coordsText.match(/,\s*(-?\d+)/);
        
        if (!qMatch || !rMatch) {
            console.error('Could not parse coordinates from:', coordsText);
            return;
        }
        
        const playerQ = parseInt(qMatch[1]);
        const playerR = parseInt(rMatch[1]);
        console.log('Player location:', playerQ, playerR);
        
        ctx.save();
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // Apply camera transformations
        ctx.translate(cameraOffset.x, cameraOffset.y);
        ctx.scale(cameraZoom, cameraZoom);

        // Draw each chunk
        for (let chunk of mapData) {
            const q = chunk.q;
            const r = chunk.r;
            const { x: cx, y: cy } = hexToPixel(q, r);
            
            // Draw hex cell
            const isCurrentChunk = (q === playerQ && r === playerR);
            drawHex(ctx, cx, cy, isCurrentChunk ? "#e3f2fd" : "#eee");

            // Draw locations in chunk
            const locations = chunk.chunk_data.locations || {};
            for (let locName in locations) {
                const locObj = locations[locName];
                const { dx, dy } = stableSubPosition(locName);
                const lx = cx + dx;
                const ly = cy + dy;
                
                // Check if this is current location
                const isCurrentLoc = isCurrentChunk && 
                    document.getElementById("locationDisplay").textContent.includes(locName);
                
                // Draw location marker
                const shape = pickShape(locName);
                drawLocation(ctx, shape, lx, ly, isCurrentLoc);

                // Draw connections
                const conns = locObj.connections || [];
                for (let c of conns) {
                    if (c.startsWith("exit:")) {
                        // Draw partial line toward next chunk
                        let [qStr, rStr] = c.replace("exit:", "").split(",");
                        let dq = parseInt(qStr.slice(1), 10) * (qStr[0] === "-" ? -1 : 1);
                        let dr = parseInt(rStr.slice(1), 10) * (rStr[0] === "-" ? -1 : 1);
                        let edgeHex = {
                            x: cx + dq * HEX_SIZE * sqrt3 * 0.5,
                            y: cy + dr * HEX_SIZE * 1.5 * 0.5
                        };
                        drawLine(ctx, lx, ly, edgeHex.x, edgeHex.y);
                    } else if (locations[c]) {
                        // Connection to another location in same chunk
                        const { dx: tdx, dy: tdy } = stableSubPosition(c);
                        const tx = cx + tdx;
                        const ty = cy + tdy;
                        // Only draw if locName < c to avoid double lines
                        if (locName < c) {
                            drawLine(ctx, lx, ly, tx, ty);
                        }
                    }
                }
            }
        }
        ctx.restore();
    }

    // Pan/Zoom event handlers
    function initPanZoom() {
        canvas.addEventListener("mousedown", e => {
            isDragging = true;
            lastMousePos.x = e.clientX;
            lastMousePos.y = e.clientY;
        });

        canvas.addEventListener("mousemove", e => {
            if (isDragging) {
                const dx = e.clientX - lastMousePos.x;
                const dy = e.clientY - lastMousePos.y;
                cameraOffset.x += dx;
                cameraOffset.y += dy;
                lastMousePos.x = e.clientX;
                lastMousePos.y = e.clientY;
                drawMap();
            }
        });

        canvas.addEventListener("mouseup", () => isDragging = false);
        canvas.addEventListener("mouseleave", () => isDragging = false);

        canvas.addEventListener("wheel", e => {
            e.preventDefault();
            const zoomFactor = 1.05;
            const oldZoom = cameraZoom;
            
            // Get mouse position relative to canvas
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;
            
            // Get mouse position relative to camera
            const mouseXCanvas = (mouseX - cameraOffset.x) / oldZoom;
            const mouseYCanvas = (mouseY - cameraOffset.y) / oldZoom;
            
            // Apply zoom
            if (e.deltaY < 0) {
                cameraZoom *= zoomFactor;
            } else {
                cameraZoom /= zoomFactor;
            }
            
            // Adjust offset to keep mouse position fixed
            cameraOffset.x = mouseX - mouseXCanvas * cameraZoom;
            cameraOffset.y = mouseY - mouseYCanvas * cameraZoom;
            
            drawMap();
        });
    }

    // Make drawMap accessible outside
    window.drawMap = drawMap;

    // Fetch map data and refresh display
    async function doRefreshMap() {
        try {
            console.log('Fetching map data...');
            const resp = await fetch("/api/map_data");
            mapData = await resp.json();
            console.log('Map data received:', mapData);
            drawMap();
        } catch (err) {
            console.error("Error fetching map data:", err);
        }
    }

    // Make refreshMap globally available
    window.refreshMap = doRefreshMap;

    // Initialize
    initPanZoom();
    refreshMap();

    // Add map refresh to the global refreshUI function
    const originalRefreshUI = window.refreshUI;
    window.refreshUI = async function() {
        await originalRefreshUI();
        await refreshMap();
    };
});
