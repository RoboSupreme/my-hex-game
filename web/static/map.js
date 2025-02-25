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

    // Precompute midpoints for the 6 neighboring directions in axial coords.
    // For a "pointy-top" hex, the directions can be mapped as:
    //   +q,   0  =>  0 degrees
    //   +q,  -1  => -60 degrees
    //    0,  -1  => -120
    //   -q,   0  => 180
    //   -q,  +1  => 120
    //    0,  +1  => 60
    // The distance from center to an edge midpoint is exactly HEX_SIZE.
    const sideVectors = {
        "1,0":   { x:  HEX_SIZE,          y: 0 },
        "1,-1":  { x:  HEX_SIZE * 0.5,    y: -HEX_SIZE * (sqrt3/2) },
        "0,-1":  { x: -HEX_SIZE * 0.5,    y: -HEX_SIZE * (sqrt3/2) },
        "-1,0":  { x: -HEX_SIZE,          y: 0 },
        "-1,1":  { x: -HEX_SIZE * 0.5,    y:  HEX_SIZE * (sqrt3/2) },
        "0,1":   { x:  HEX_SIZE * 0.5,    y:  HEX_SIZE * (sqrt3/2) },
    };

    // Helper to get the hex corner points for intersection testing
    function getHexCorners(cx, cy) {
        const corners = [];
        for (let i = 0; i < 6; i++) {
            const angleDeg = 60 * i - 30;  // pointy top offset
            const angleRad = (Math.PI / 180) * angleDeg;
            corners.push({
                x: cx + HEX_SIZE * Math.cos(angleRad),
                y: cy + HEX_SIZE * Math.sin(angleRad)
            });
        }
        return corners;
    }

    // Find the intersection with the correct hex edge
    function findHexEdgeIntersection(x1, y1, x2, y2, cx, cy, dq, dr) {
        // First, determine which edge we want based on direction
        let startAngle;
        if (dq === 1 && dr === 0) startAngle = -30;        // right edge
        else if (dq === 1 && dr === -1) startAngle = -90;  // upper right edge
        else if (dq === 0 && dr === -1) startAngle = -150; // upper left edge
        else if (dq === -1 && dr === 0) startAngle = 150;  // left edge
        else if (dq === -1 && dr === 1) startAngle = 90;   // lower left edge
        else if (dq === 0 && dr === 1) startAngle = 30;    // lower right edge
        else return null;

        // Get the two corners of this edge
        const angleRad1 = (Math.PI / 180) * startAngle;
        const angleRad2 = (Math.PI / 180) * (startAngle + 60);
        const x3 = cx + HEX_SIZE * Math.cos(angleRad1);
        const y3 = cy + HEX_SIZE * Math.sin(angleRad1);
        const x4 = cx + HEX_SIZE * Math.cos(angleRad2);
        const y4 = cy + HEX_SIZE * Math.sin(angleRad2);

        // Calculate the midpoint of this edge
        const mx = (x3 + x4) / 2;
        const my = (y3 + y4) / 2;

        // Find intersection with this edge segment
        const denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
        if (denominator === 0) return { x: mx, y: my }; // fallback to midpoint if parallel

        const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denominator;
        const u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denominator;

        // If intersection is on the edge segment, use it
        if (t >= 0 && t <= 1 && u >= 0 && u <= 1) {
            const ix = x1 + t * (x2 - x1);
            const iy = y1 + t * (y2 - y1);
            return { x: ix, y: iy };
        }

        // Otherwise use the midpoint
        return { x: mx, y: my };
    };

    // Helper to get the “midpoint of the edge” for an exit in direction dq,dr
    function getEdgeMidpoint(cx, cy, dq, dr) {
        const key = `${dq},${dr}`;
        const v = sideVectors[key];
        if (!v) {
            // If code tries to parse something like q+2 or an invalid direction, fallback
            return { x: cx, y: cy };
        }
        return { x: cx + v.x, y: cy + v.y };
    }

    // DOM elements
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

    // Convert axial (q,r) to pixel center of the chunk
    function hexToPixel(q, r) {
        const x = HEX_SIZE * sqrt3 * (q + r/2);
        const y = HEX_SIZE * 1.5 * r;
        return { x, y };
    }

    // Draw a single pointy-topped hex
    function drawHex(ctx, cx, cy, fill = "#eee", stroke = "#888") {
        ctx.beginPath();
        for (let i = 0; i < 6; i++) {
            const angleDeg = 60 * i - 30;  // pointy top offset
            const angleRad = (Math.PI / 180) * angleDeg;
            const x = cx + HEX_SIZE * Math.cos(angleRad);
            const y = cy + HEX_SIZE * Math.sin(angleRad);
            (i === 0) ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fillStyle = fill;
        ctx.strokeStyle = stroke;
        ctx.fill();
        ctx.stroke();
    }

    /**
     * stableSubPosition(locName)
     * Gives a stable offset (dx, dy) for a given location name,
     * but keeps it well within the hex boundary.
     */
    function stableSubPosition(locName) {
        // A simple hash
        let hash = 0;
        for (let i = 0; i < locName.length; i++) {
            hash = (hash << 5) - hash + locName.charCodeAt(i);
            hash |= 0; // convert to 32-bit
        }
        // Convert that into some offset in range ~[-30, +30]
        // but random enough per location name
        let dx = (hash % 60) - 30;
        let dy = (((hash / 60) | 0) % 60) - 30;

        // Now scale that so that the final (dx, dy) fits well inside the hex.
        // The hex’s “incircle” radius is (sqrt(3)/2)*HEX_SIZE ≈ 0.866 * HEX_SIZE
        // We’ll go ~ 60% of that radius to stay well inside.
        let maxRadius = 0.6 * HEX_SIZE * sqrt3/2;
        const dist = Math.sqrt(dx*dx + dy*dy);
        if (dist > 0) {
            const scale = maxRadius / dist;
            dx *= scale;
            dy *= scale;
        }
        return { dx, dy };
    }

    // Draw location marker (circle/square/triangle)
    function drawLocation(ctx, shape, x, y, isCurrentLocation = false) {
        ctx.save();
        ctx.translate(x, y);
        
        // If it’s the current location, add a highlight
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
        } else {
            // triangle
            ctx.beginPath();
            ctx.moveTo(0, -8);
            ctx.lineTo(7, 6);
            ctx.lineTo(-7, 6);
            ctx.closePath();
            ctx.fill();
        }
        ctx.restore();
    }

    // Draw a simple line
    function drawLine(ctx, x1, y1, x2, y2, color="#444") {
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = color;
        ctx.stroke();
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

    // Main map drawing function
    function drawMap() {
        console.log('Drawing map...');
        // We attempt to parse the player's current location (q,r)
        const coordsText = document.getElementById("coordinatesDisplay").textContent;
        const qMatch = coordsText.match(/\((-?\d+)/);
        const rMatch = coordsText.match(/,\s*(-?\d+)/);
        
        let playerQ = 0, playerR = 0;
        if (qMatch && rMatch) {
            playerQ = parseInt(qMatch[1]);
            playerR = parseInt(rMatch[1]);
            console.log('Player location:', playerQ, playerR);
        }

        ctx.save();
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        
        // Camera transform
        ctx.translate(cameraOffset.x, cameraOffset.y);
        ctx.scale(cameraZoom, cameraZoom);

        // Create a set of generated chunk coordinates for quick lookup
        const generatedChunks = new Set(mapData.map(chunk => `${chunk.q},${chunk.r}`));

        // Draw each chunk in mapData
        for (let chunk of mapData) {
            const { q, r, chunk_data } = chunk;
            const { x: cx, y: cy } = hexToPixel(q, r);

            // draw the hex background
            const isCurrentChunk = (q === playerQ && r === playerR);
            drawHex(ctx, cx, cy, isCurrentChunk ? "#e3f2fd" : "#eee");

            // Now draw each location in this chunk
            const locations = chunk_data.locations || {};
            for (let locName in locations) {
                const locObj = locations[locName];
                // Only draw visible locations
                if (!locObj.visible) continue;

                // Count how many visible locations we have and what number this one is
                const visibleLocations = Object.entries(locations)
                    .filter(([_, loc]) => loc.visible)
                    .map(([name]) => name);
                const index = visibleLocations.indexOf(locName);
                const total = visibleLocations.length;

                // Calculate position in a circular pattern
                const angle = (2 * Math.PI * index) / total;
                const radius = 0.6 * HEX_SIZE * sqrt3/2; // 60% of hex incircle
                const dx = Math.cos(angle) * radius;
                const dy = Math.sin(angle) * radius;
                const lx = cx + dx;
                const ly = cy + dy;

                // Is this the player's actual location?
                const locationDisplayText = document.getElementById("locationDisplay").textContent;
                const isCurrentLoc = (isCurrentChunk && locationDisplayText.includes(locName));

                // draw the marker
                const shape = pickShape(locName);
                drawLocation(ctx, shape, lx, ly, isCurrentLoc);

                // draw connections
                const conns = locObj.connections || [];
                for (let c of conns) {
                    if (c.startsWith("exit:")) {
                        // Parse the exit direction
                        let [qStr, rStr] = c.replace("exit:", "").split(",");
                        // Remove 'q' and 'r' prefixes
                        qStr = qStr.slice(1);
                        rStr = rStr.slice(1);
                        console.log('Exit string parts:', qStr, rStr);
                        
                        // Now strings should be like '+1' or '-1'
                        const dq = parseInt(qStr, 10);
                        const dr = parseInt(rStr, 10);
                        console.log('Parsed exit deltas:', dq, dr);

                        // Calculate target point well outside the hex
                        const targetX = cx + dq * HEX_SIZE * 2;
                        const targetY = cy + dr * HEX_SIZE * 2;
                        
                        // Find intersection with the correct edge
                        let intersection = findHexEdgeIntersection(lx, ly, targetX, targetY, cx, cy, dq, dr);
                        if (intersection) {
                            drawLine(ctx, lx, ly, intersection.x, intersection.y);
                        }
                    } else if (locations[c] && locations[c].visible) {
                        // Connect to another visible location in same chunk
                        if (locName < c) {
                            // Use same circular pattern for connected location
                            const index = visibleLocations.indexOf(c);
                            const angle = (2 * Math.PI * index) / total;
                            const tdx = Math.cos(angle) * radius;
                            const tdy = Math.sin(angle) * radius;
                            const tx = cx + tdx;
                            const ty = cy + tdy;
                            drawLine(ctx, lx, ly, tx, ty);
                        }
                    }
                }
            }
        }

        ctx.restore();
    }

    // Initialize panning/zooming
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

        // stop dragging
        canvas.addEventListener("mouseup", () => isDragging = false);
        canvas.addEventListener("mouseleave", () => isDragging = false);

        // zoom
        canvas.addEventListener("wheel", e => {
            e.preventDefault();
            const zoomFactor = 1.05;
            const oldZoom = cameraZoom;

            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            // transform to camera space
            const mouseXCanvas = (mouseX - cameraOffset.x) / oldZoom;
            const mouseYCanvas = (mouseY - cameraOffset.y) / oldZoom;

            // adjust zoom
            if (e.deltaY < 0) {
                cameraZoom *= zoomFactor;
            } else {
                cameraZoom /= zoomFactor;
            }
            // keep center under mouse
            cameraOffset.x = mouseX - mouseXCanvas * cameraZoom;
            cameraOffset.y = mouseY - mouseYCanvas * cameraZoom;

            drawMap();
        });
    }

    // Make drawMap accessible outside
    window.drawMap = drawMap;

    // Fetch map data and draw
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
    window.refreshMap = doRefreshMap;

    // Initialize
    initPanZoom();
    refreshMap();

    // Optionally, if you want to re-hook the global refreshUI to also refresh the map:
    /*
    const originalRefreshUI = window.refreshUI;
    window.refreshUI = async function() {
        await originalRefreshUI();
        await refreshMap();
    };
    */
});
