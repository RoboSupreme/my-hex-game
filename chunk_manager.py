# chunk_manager.py

import random
import json
import sqlite3
from typing import Dict, Any
import cohere

# The 6 axial neighbor directions (pointy-top hex)
HEX_NEIGHBORS = [
    ("q+1,r+0", 1, 0),
    ("q+1,r-1", 1, -1),
    ("q+0,r-1", 0, -1),
    ("q-1,r+0", -1, 0),
    ("q-1,r+1", -1, 1),
    ("q+0,r+1", 0, 1),
]

class ChunkManager:
    """
    Creates new chunks with your 6-step procedure:

    1) Decide how many normal locations (2..3).
    2) Decide how many secret locations (0..2) by rolling 10% up to 10 times.
    3) For each neighbor chunk that references this chunk via 'exit:...', unify them with exactly
       one local location in this chunk. One edge cannot connect to multiple local locations.
    4) Add additional outward edges (to ungenerated neighbors) with your multi-step probabilities:
         - If we have only 1 neighbor connected => 80% chance to add another, then 40%, then 20%, then 10%, then 10%.
         - If we have 2 neighbors => start from 40%, etc.
         - If we have >=6 neighbors => no more edges.
    5) Ensure all local locations in this chunk are mutually reachable (no isolated spots).
    6) Pass final structure to AI to fill in "description", "sites", etc.
    """

    def __init__(self, db: sqlite3.Connection, cohere_client: cohere.Client):
        self.db = db
        self.ai = cohere_client
        
    def _flip_direction(self, dir_str: str) -> str:
        """Convert a direction to its opposite, e.g. 'q+1,r+0' -> 'q-1,r+0'"""
        parts = dir_str.split(',')
        def flip(s):
            if '+' in s:
                return s.replace('+','-')
            return s.replace('-','+')
        return flip(parts[0]) + ',' + flip(parts[1])

    def get_or_create_chunk_data(self, q: int, r: int, from_dir: str = None) -> Dict[str, Any]:
        print(f"\n[DEBUG] get_or_create_chunk_data called for ({q},{r}) from direction {from_dir}")
        """
        Main entry point: If a chunk (q,r) already exists in DB, return it.
        Otherwise generate it using the 6-step logic, store in DB, and return.
        
        from_dir: If provided (e.g. 'q+1,r+0'), indicates we're generating this chunk
                 because the player is moving here from that direction. We MUST ensure
                 there's a location that points back in that direction.
        """
        c = self.db.cursor()
        row = c.execute("SELECT data_json FROM chunks WHERE q=? AND r=?", (q, r)).fetchone()
        if row:
            chunk_data = json.loads(row["data_json"])
            print(f"[DEBUG] Found existing chunk at ({q},{r}) with {len(chunk_data.get('locations', {}))} locations")
            print(f"[DEBUG] Locations: {list(chunk_data.get('locations', {}).keys())}")
            print(f"[DEBUG] Connections: {[(loc, data.get('connections', [])) for loc, data in chunk_data.get('locations', {}).items()]}")
            return chunk_data

        print(f"[ChunkManager] Generating new chunk at ({q},{r})...")
        if from_dir:
            print(f"[DEBUG] Player is coming from direction {from_dir}")

        # STEP 1 & 2: Decide how many normal & secret locations
        print(f"\n[DEBUG] Starting new chunk generation for ({q},{r})")
        normal_count = 3  # Always generate 3 normal locations
        secret_count = self._roll_secret_count() # up to 2
        print(f"[DEBUG] Generating chunk({q},{r}) with {normal_count} normal + {secret_count} secret locations")

        # Build placeholders
        loc_names = []
        for i in range(normal_count):
            loc_names.append(f"Location{chr(ord('A') + i)}")
        for s in range(secret_count):
            loc_names.append(f"Secret{s+1}")
        print(f"[DEBUG] Location names: {loc_names}")

        chunk_data = {"locations": {}}
        for ln in loc_names:
            chunk_data["locations"][ln] = {
                "connections": [],
                "visible": True,
                "description": f"A default location named {ln}",
                "history_of_events": [],
                "sites": {}
            }

        # If we're coming from a direction, ensure we have a location pointing back
        if from_dir:
            # Pick first normal location to be the entry point
            entry_loc = loc_names[0]
            back_dir = self._flip_direction(from_dir)
            chunk_data["locations"][entry_loc]["connections"].append(f"exit:{back_dir}")
            print(f"[DEBUG] Set {entry_loc} as entry point with back link {back_dir}")

        # STEP 3: Link to neighbors that reference this chunk
        print(f"\n[DEBUG] Step 3: Getting neighbor data for ({q},{r})")
        neighbors = self.get_neighbor_data(q, r)
        print(f"[DEBUG] Got {len(neighbors)} neighbors with data")
        for dir_str, data in neighbors.items():
            print(f"[DEBUG] Neighbor {dir_str} has {len(data.get('locations', {}))} locations")
            for loc, loc_data in data.get('locations', {}).items():
                print(f"[DEBUG] Location {loc} has connections: {loc_data.get('connections', [])}")
        self._apply_neighbor_backlinks(q, r, chunk_data, neighbors)

        # STEP 4: Additional outward edges
        print(f"[DEBUG] Adding additional exits...")
        self._add_additional_exits(q, r, chunk_data, neighbors)

        # STEP 5: Ensure local connectivity
        self._connect_local_locations(chunk_data)

        # NEW STEP: Generate unique names and backstories
        chunk_data = self._generate_location_names_and_stories(q, r, chunk_data)

        # STEP 6: Ask AI for descriptions, sites, etc.
        final_chunk = self._generate_ai_descriptions(q, r, chunk_data)

        # Store in DB
        c.execute(
            "INSERT INTO chunks (q, r, data_json) VALUES (?,?,?)",
            (q, r, json.dumps(final_chunk))
        )
        self.db.commit()

        return final_chunk

    # ----------------------------------------------------------------------
    #  Step 2: roll for secret locations, up to 2
    # ----------------------------------------------------------------------
    def _roll_secret_count(self) -> int:
        """
        We do 10 rolls, each 10% chance. We can get up to 2 successes total.
        """
        count = 0
        for _ in range(10):
            if random.random() < 0.10:
                count += 1
                if count == 2:
                    break
        return count

    # ----------------------------------------------------------------------
    # Get neighbor chunk data if exists, else treat as empty
    # ----------------------------------------------------------------------
    def get_neighbor_data(self, q: int, r: int) -> Dict[str, Dict[str, Any]]:
        print(f"\n[DEBUG] Getting neighbors for chunk ({q},{r})")
        neighbors = {}
        c = self.db.cursor()
        for dir_str, dq, dr in HEX_NEIGHBORS:
            nq = q + dq
            nr = r + dr
            print(f"[DEBUG] Checking neighbor {dir_str} at ({nq},{nr})")
            row = c.execute("SELECT data_json FROM chunks WHERE q=? AND r=?", (nq, nr)).fetchone()
            if row:
                try:
                    # row is a tuple, get first element
                    chunk_data = json.loads(row[0])
                    neighbors[dir_str] = chunk_data
                    print(f"[DEBUG] Successfully loaded neighbor from DB with {len(chunk_data.get('locations', {}))} locations")
                    # Print any locations that point to us
                    back_dir = self._flip_direction(dir_str)
                    back_exit = f"exit:{back_dir}"
                    pointing_locs = [loc for loc, data in chunk_data.get('locations', {}).items() 
                                   if back_exit in data.get('connections', [])]
                    if pointing_locs:
                        print(f"[DEBUG] Found {len(pointing_locs)} locations pointing to us: {pointing_locs}")
                except Exception as e:
                    print(f"[WARNING] Error loading neighbor at {dir_str} ({nq},{nr}): {e}")
                    neighbors[dir_str] = {"locations": {}}
            else:
                neighbors[dir_str] = {"locations": {}}
                print(f"[DEBUG] No neighbor at {dir_str} ({nq},{nr})")
        return neighbors

    # ----------------------------------------------------------------------
    #  Step 3: For each neighbor chunk referencing this chunk, unify
    # ----------------------------------------------------------------------
    def _apply_neighbor_backlinks(self, q: int, r: int, chunk_data: Dict[str,Any], neighbors: Dict[str,Any]):
        """
        For each of the 6 neighbors around us:
        1. Check if it exists and has locations pointing to us
        2. If yes, create a connection back to each location
        3. One edge can connect to only one location, but one location can connect to multiple edges
        """
        # Track which edges are used (can't have multiple locations connecting to same edge)
        edge_to_loc = {}  # Maps edge -> location name that connects to it
        
        # First gather all locations from each direction that point to us
        connecting_by_dir = {}  # Maps direction -> list of locations pointing to us
        
        # Get all possible neighbors, even if not in neighbors dict
        all_directions = [
            "q+1,r+0", "q+1,r-1", "q+0,r-1",  # Top half
            "q-1,r+0", "q-1,r+1", "q+0,r+1"   # Bottom half
        ]
        
        # For each of the 6 possible neighbors
        for dir_str in all_directions:
            # Get neighbor data, either from neighbors dict or by loading it
            print(f"\n[DEBUG] Checking direction {dir_str}")
            neighbor_data = neighbors.get(dir_str)
            if not neighbor_data:
                # Parse direction to get neighbor coordinates
                dq = int(dir_str.split(',')[0][1:])  # Extract number after q+ or q-
                dr = int(dir_str.split(',')[1][1:])  # Extract number after r+ or r-
                nbr_q, nbr_r = q + dq, r + dr
                
                print(f"[DEBUG] No data in neighbors dict, trying to load from DB for ({nbr_q},{nbr_r})")
                # Try to load this neighbor's data
                try:
                    c = self.db.cursor()
                    row = c.execute("SELECT data_json FROM chunks WHERE q=? AND r=?", 
                                  (nbr_q, nbr_r)).fetchone()
                    if row:
                        neighbor_data = json.loads(row[0])
                        print(f"[DEBUG] Successfully loaded neighbor from DB with {len(neighbor_data.get('locations', {}))} locations")
                    else:
                        print(f"[DEBUG] No neighbor found in DB at ({nbr_q},{nbr_r})")
                except Exception as e:
                    print(f"[WARNING] Error loading neighbor at ({nbr_q},{nbr_r}): {e}")
                    continue
            
            # Skip if neighbor doesn't exist
            if not neighbor_data:
                print(f"[DEBUG] No neighbor data found for {dir_str}, skipping")
                continue
                
            # Get the direction they would use to point to us
            # e.g. if we're at (0,0) and looking at neighbor at (1,0)
            # dir_str is "q+1,r+0" and back_dir is "q-1,r+0"
            back_dir = self._flip_direction(dir_str)
            back_exit = f"exit:{back_dir}"
            
            print(f"[DEBUG] Checking neighbor {dir_str} for locations using {back_exit}")
            print(f"[DEBUG] Neighbor has locations: {list(neighbor_data.get('locations', {}).keys())}")
            
            # Find all locations in this neighbor that point to us
            connecting_locs = []
            for nbr_loc, nbr_info in neighbor_data.get("locations", {}).items():
                conns = nbr_info.get("connections", [])
                print(f"[DEBUG] Location {nbr_loc} has connections: {conns}")
                if back_exit in conns:
                    print(f"[DEBUG] Found connection {back_exit} in {nbr_loc}")
                    connecting_locs.append(nbr_loc)
            
            if connecting_locs:
                connecting_by_dir[dir_str] = connecting_locs
                print(f"[DEBUG] Found {len(connecting_locs)} locations in {dir_str} pointing to us: {connecting_locs}")
        
        # Now process each direction and create ONE connection per direction
        print(f"\n[DEBUG] Processing connections for chunk ({q},{r})")
        for dir_str, connecting_locs in connecting_by_dir.items():
            print(f"\n[DEBUG] Processing direction {dir_str} with locations: {connecting_locs}")
            # Try to connect one location for this direction
            connected = False
            
            # First try to find a matching location name that isn't already connected
            for nbr_loc in connecting_locs:
                print(f"[DEBUG] Checking if we can connect {nbr_loc} to {dir_str}")
                if nbr_loc in chunk_data["locations"]:
                    current_conns = chunk_data["locations"][nbr_loc].get("connections", [])
                    print(f"[DEBUG] Location {nbr_loc} exists and has connections: {current_conns}")
                    if f"exit:{dir_str}" not in current_conns:
                        # Perfect - matching name and not already connected to this direction
                        chunk_data["locations"][nbr_loc]["connections"].append(f"exit:{dir_str}")
                        edge_to_loc[dir_str] = nbr_loc
                        print(f"[DEBUG] Connected matching location {nbr_loc} to {dir_str}")
                        connected = True
                        break
                    else:
                        print(f"[DEBUG] Location {nbr_loc} already connected to {dir_str}")
                else:
                    print(f"[DEBUG] Location {nbr_loc} does not exist in our chunk")
            
            # If we couldn't match any names, find any available location
            if not connected:
                print(f"[DEBUG] No matching locations found, looking for any available location")
                print(f"[DEBUG] Current chunk locations: {list(chunk_data['locations'].keys())}")
                print(f"[DEBUG] Current connections: {[(loc, data.get('connections', [])) for loc, data in chunk_data['locations'].items()]}")
                available_locs = [ln for ln in chunk_data["locations"].keys() 
                                if f"exit:{dir_str}" not in chunk_data["locations"][ln].get("connections", [])]
                print(f"[DEBUG] Available locations (no {dir_str} connection): {available_locs}")
                if available_locs:
                    loc_name = random.choice(available_locs)
                    chunk_data["locations"][loc_name]["connections"].append(f"exit:{dir_str}")
                    edge_to_loc[dir_str] = loc_name
                    print(f"[DEBUG] Connected random location {loc_name} to {dir_str} for {connecting_locs}")
                    print(f"[DEBUG] Location {loc_name} now has connections: {chunk_data['locations'][loc_name]['connections']}")
                else:
                    print(f"[WARNING] No available locations to connect to {dir_str} for {connecting_locs}")
            
            # Debug output for this direction
            print(f"[DEBUG] Finished processing connections for direction {dir_str}")
            print(f"[DEBUG] Current edge_to_loc map: {edge_to_loc}")

    # ----------------------------------------------------------------------
    #  Step 4: Additional outward edges with multi-step probability
    # ----------------------------------------------------------------------
    def _add_additional_exits(self, q: int, r: int, chunk_data: Dict[str,Any], neighbors: Dict[str,Any]):
        # Track which edges and locations are used
        used_edges = set()  # Which edges have a connection
        edge_to_loc = {}    # Map edge -> location that connects to it
        
        # Get currently used edges and their locations
        for loc_name, loc_data in chunk_data["locations"].items():
            for c in loc_data["connections"]:
                if c.startswith("exit:"):
                    edge = c.replace("exit:", "")
                    used_edges.add(edge)
                    edge_to_loc[edge] = loc_name
        print(f"[DEBUG] Currently used edges: {used_edges}")

        # Get available directions and split into unexplored vs explored
        unexplored_dirs = []
        explored_dirs = []
        for dir_str, dq, dr in HEX_NEIGHBORS:
            if dir_str in used_edges:
                continue
                
            # Check if this neighbor exists in DB
            c = self.db.cursor()
            nq, nr = q + dq, r + dr
            exists = c.execute("SELECT 1 FROM chunks WHERE q=? AND r=?", (nq, nr)).fetchone()
            
            if exists:
                explored_dirs.append(dir_str)
            else:
                unexplored_dirs.append(dir_str)
                
        print(f"[DEBUG] Unexplored directions: {unexplored_dirs}")
        print(f"[DEBUG] Explored directions: {explored_dirs}")

        # Probability sequence based on current connections
        connected_count = len(used_edges)
        prob_map = {
            1: [1.0, 0.50, 0.25, 0.125, 0.125],
            2: [0.50, 0.25, 0.125, 0.125],
            3: [0.25, 0.125, 0.125],
            4: [0.125, 0.125],
            5: [0.125]
        }
        
        if connected_count >= 6:
            return
            
        probs = prob_map[connected_count]
        print(f"[DEBUG] Using probability sequence: {probs}")
        
        # Try to make connections
        for prob in probs:
            if random.random() >= (1.0 - prob):  # Now prob is chance to SUCCEED
                print(f"[DEBUG] Passed probability check {prob}")
                
                # First try unexplored directions
                if unexplored_dirs:
                    chosen_dir = random.choice(unexplored_dirs)
                    unexplored_dirs.remove(chosen_dir)
                    
                    # Pick a random location that doesn't already have an outgoing connection
                    available_locs = [ln for ln in chunk_data["locations"].keys()
                                    if ln not in edge_to_loc.values()]
                    if available_locs:
                        loc_name = random.choice(available_locs)
                        chunk_data["locations"][loc_name]["connections"].append(f"exit:{chosen_dir}")
                        used_edges.add(chosen_dir)
                        edge_to_loc[chosen_dir] = loc_name
                        print(f"[DEBUG] Added connection to unexplored: {loc_name} -> exit:{chosen_dir}")
                        continue
                    else:
                        print(f"[DEBUG] No available locations for unexplored direction {chosen_dir}")
            else:
                print(f"[DEBUG] Failed probability check {prob}, stopping")
                break
            
            # If no unexplored dirs, try explored ones
            if explored_dirs:
                chosen_dir = random.choice(explored_dirs)
                explored_dirs.remove(chosen_dir)
                
                # Get the neighbor's data
                dq = int(chosen_dir.split(',')[0][1:]) if '+' in chosen_dir.split(',')[0] else -int(chosen_dir.split(',')[0][1:])
                dr = int(chosen_dir.split(',')[1][1:]) if '+' in chosen_dir.split(',')[1] else -int(chosen_dir.split(',')[1][1:])
                nq, nr = q + dq, r + dr
                
                neighbor_data = json.loads(c.execute(
                    "SELECT data_json FROM chunks WHERE q=? AND r=?", 
                    (nq, nr)
                ).fetchone()["data_json"])
                
                # Check if any location in neighbor points to us
                back_dir = self._flip_direction(chosen_dir)
                back_exit = f"exit:{back_dir}"
                
                # First find ALL locations in neighbor that point to us
                connecting_locs = []
                for nbr_loc, nbr_data in neighbor_data["locations"].items():
                    if back_exit in nbr_data.get("connections", []):
                        connecting_locs.append(nbr_loc)
                
                print(f"[DEBUG] Found {len(connecting_locs)} locations in {chosen_dir} pointing to us: {connecting_locs}")
                
                # Try each location in order
                connecting_loc = None
                
                # Try to connect each location that points to us
                for nbr_loc in connecting_locs:
                    connecting_loc = None
                    
                    # First try to match name if it exists and isn't already connected
                    if nbr_loc in chunk_data["locations"] and \
                       f"exit:{chosen_dir}" not in chunk_data["locations"][nbr_loc].get("connections", []):
                        connecting_loc = nbr_loc
                        print(f"[DEBUG] Found matching location name {connecting_loc} from {nbr_loc}")
                    
                    # If no matching name works, pick a random available location
                    if not connecting_loc:
                        available_locs = [ln for ln in chunk_data["locations"].keys()
                                        if f"exit:{chosen_dir}" not in chunk_data["locations"][ln].get("connections", [])]
                        if available_locs:
                            connecting_loc = random.choice(available_locs)
                            print(f"[DEBUG] Using random location {connecting_loc} for connection to match {nbr_loc}")
                    
                    if connecting_loc:
                        chunk_data["locations"][connecting_loc]["connections"].append(f"exit:{chosen_dir}")
                        used_edges.add(chosen_dir)
                        edge_to_loc[chosen_dir] = connecting_loc
                        print(f"[DEBUG] Added connection to explored: {connecting_loc} -> exit:{chosen_dir} to match {nbr_loc}")
                    else:
                        print(f"[DEBUG] Could not find an available location for connection to {chosen_dir} to match {nbr_loc}")
            
            # If we get here, we couldn't make any more connections
            break

    # ----------------------------------------------------------------------
    #  Step 5: ensure local connectivity (no location is isolated)
    # ----------------------------------------------------------------------
    def _connect_local_locations(self, chunk_data: Dict[str,Any]):
        loc_names = list(chunk_data["locations"].keys())
        adjacency = {ln: set() for ln in loc_names}

        # gather adjacency ignoring 'exit:' references
        for ln in loc_names:
            conns = chunk_data["locations"][ln]["connections"]
            for c in conns:
                if c in loc_names:
                    adjacency[ln].add(c)

        # BFS to find connected components
        def bfs(start, visited):
            from collections import deque
            Q = deque([start])
            visited.add(start)
            while Q:
                node = Q.popleft()
                for nxt in adjacency[node]:
                    if nxt not in visited:
                        Q.append(nxt)
                        visited.add(nxt)
                        Q.append(nxt)
                        visited.add(nxt)

        visited_global = set()
        components = []
        for ln in loc_names:
            if ln not in visited_global:
                comp = set()
                bfs(ln, comp)
                components.append(comp)
                visited_global |= comp

        # If more than 1 connected component, unify them with minimal edges
        while len(components) > 1:
            c1 = components.pop()
            c2 = components.pop()
            # pick a location from each
            l1 = next(iter(c1))
            l2 = next(iter(c2))
            adjacency[l1].add(l2)
            adjacency[l2].add(l1)
            cnew = c1 | c2
            components.append(cnew)

        # Now update connections back
        for ln in loc_names:
            local_conns = sorted(list(adjacency[ln]))
            old_exits = [
                x for x in chunk_data["locations"][ln]["connections"]
                if x.startswith("exit:")
            ]
            new_conns = sorted(set(local_conns + old_exits))
            chunk_data["locations"][ln]["connections"] = new_conns

    # ----------------------------------------------------------------------
    #  Step 6: Pass final structure to AI to fill in descriptions, sites, etc.
    # ----------------------------------------------------------------------
    def _generate_ai_descriptions(self, q: int, r: int, chunk_data: Dict[str,Any]) -> Dict[str,Any]:
        """
        Asks AI to fill in:
          - "description"
          - "visible": true
          - "history_of_events": []
          - "sites": up to 2 discovered sub-sites
        Keep "connections" the same!
        """
        loc_names = list(chunk_data["locations"].keys())
        placeholders = []
        for ln in loc_names:
            conns = chunk_data["locations"][ln]["connections"]
            placeholders.append(f'  "{ln}": {{ "connections": {conns} }}')
        base_str = "{\n" + ",\n".join(placeholders) + "\n}"

        system_prompt = f"""
We have a new chunk at (q={q}, r={r}) with these location placeholders:

{base_str}

For each location, fill in:
  "description": short text
  "visible": true
  "history_of_events": []
  "sites": dictionary with 0-2 sites, each site must have "discovered": true
Keep connections exactly the same. Return valid JSON of form:
{{
  "locations": {{
    "LocName": {{
      "visible": true,
      "description": "...",
      "history_of_events": [],
      "sites": {{
        "site1": {{
          "discovered": true,
          "description": "..."
        }},
        "site2": {{
          "discovered": true,
          "description": "..."
        }}
      }},
      "connections": [...]
    }},
    ...
  }}
}}
No extra commentary, just JSON.
"""
        user_prompt = "Please fill in those fields for each location."

        try:
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=1000
            )
            raw_json = resp.message.content[0].text.strip()
            new_chunk = json.loads(raw_json)
            
            # Ensure each location has proper structure
            for ln, loc_data in new_chunk["locations"].items():
                # Keep original connections
                loc_data["connections"] = chunk_data["locations"][ln]["connections"]
                # Ensure sites is a dict with proper structure
                sites = loc_data.get("sites", {})
                if not isinstance(sites, dict):
                    sites = {}
                
                # Ensure each site has required fields
                for site_name, site_data in list(sites.items()):
                    if not isinstance(site_data, dict):
                        del sites[site_name]
                        continue
                        
                    if "discovered" not in site_data:
                        site_data["discovered"] = True
                    if "description" not in site_data:
                        site_data["description"] = f"A site called {site_name}"
                        
                loc_data["sites"] = sites
                # Ensure other required fields
                loc_data["visible"] = True
                if "description" not in loc_data:
                    loc_data["description"] = f"A default location named {ln}"
                if "history_of_events" not in loc_data:
                    loc_data["history_of_events"] = []
                    
            return new_chunk
        except Exception as e:
            print(f"[WARN] AI chunk gen failed: {e}")
            # fallback: fill with defaults
            for ln in loc_names:
                chunk_data["locations"][ln].update({
                    "visible": True,
                    "description": f"A default location named {ln}",
                    "history_of_events": [],
                    "sites": {}
                })
            return chunk_data

    def _generate_location_names_and_stories(self, q: int, r: int, chunk_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate unique names and rich backstories for each location in the chunk.
        This is called after all locations and connections are established.
        """
        # Create a list of current locations and their connections
        locations = []
        for loc_name, loc_data in chunk_data["locations"].items():
            locations.append({
                "current_name": loc_name,
                "is_secret": loc_name.startswith("Secret"),
                "connections": loc_data["connections"]
            })

        system_prompt = """You are generating unique names and rich backstories for locations in a fantasy game world.
IMPORTANT: You must respond with ONLY valid JSON, no other text.

For each location in this list, generate:
1. A unique and thematic name (e.g. "Whispering Woods", "Thornhaven Village")
2. A rich backstory explaining its history
3. Current state description
4. Notable features

Example response format:
{
  "LocationA": {
    "new_name": "Whispering Woods",
    "backstory": "Long ago, these woods were home to an ancient order of druids...",
    "current_state": "Now, the whispers of the past still echo...",
    "notable_features": ["The Speaking Stones", "The Elder Grove", "The Moonlit Pool"]
  }
}

Current locations to rename:"""

        user_prompt = json.dumps(locations, indent=2)

        try:
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.8
            )
            
            raw_text = resp.message.content[0].text.strip()
            print(f"[DEBUG] AI Response: {raw_text}")  # Debug line
            
            # Try to find JSON in the response
            json_start = raw_text.find('{')
            json_end = raw_text.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = raw_text[json_start:json_end]
                new_details = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
            
            # First, create a mapping of old names to new names
            name_mapping = {old_name: details["new_name"] 
                          for old_name, details in new_details.items()}
            
            # Create new locations dictionary
            new_locations = {}
            
            # Update each location with new details and update connections
            for old_name, details in new_details.items():
                if old_name in chunk_data["locations"]:
                    new_name = details["new_name"]
                    loc_data = chunk_data["locations"][old_name].copy()
                    
                    # Update the location with new details
                    loc_data.update({
                        "description": details["current_state"],
                        "backstory": details["backstory"],
                        "notable_features": details["notable_features"],
                        "history_of_events": []  # Will be filled later
                    })
                    
                    # Update connections to use new names
                    new_connections = []
                    for conn in loc_data["connections"]:
                        if conn.startswith("exit:"):
                            new_connections.append(conn)  # Keep exit connections as is
                        else:
                            # Update connection to use new name if it exists in our mapping
                            new_connections.append(name_mapping.get(conn, conn))
                    loc_data["connections"] = new_connections
                    
                    # Store under the new name
                    new_locations[new_name] = loc_data
            
            # Replace the locations with the updated ones
            chunk_data["locations"] = new_locations
            
            return chunk_data
            
        except Exception as e:
            print(f"[WARN] Failed to generate names and stories: {e}")
            print(f"[DEBUG] Raw response: {resp.message.content[0].text if 'resp' in locals() else 'No response'}")  # More debug info
            return chunk_data
