#!/usr/bin/env python3
"""
hex_game_engine.py

Implements a hex-based chunk exploration system plus sub-locations (sites).
We store all data in SQLite. We also call Cohere's API to generate new chunk data
when a chunk doesn't already exist in the DB.
"""

import sqlite3
import json
from typing import Dict, Any, List, Optional
import cohere

from cohere_secrets import COHERE_API_KEY
from lore_rag import LoreRAG  # Import the new RAG helper

class HexGameEngine:
    def __init__(self, db_path="game.db"):
        """
        db_path: path to the SQLite database.
        """
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

        # Create a Cohere client with your key
        self.ai = cohere.ClientV2(api_key=COHERE_API_KEY)

        # Initialize RAG for lore-based question answering
        self.rag = LoreRAG(
            cohere_api_key=COHERE_API_KEY,
            collection_name="hex_game_lore"
        )

        self.setup_tables()
        self.ensure_stats_columns()  # Add new stats columns if they don't exist

    def setup_tables(self):
        """
        Create DB tables for 'player' and 'chunks' if not exist.
        """
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS player (
            player_id INTEGER PRIMARY KEY,
            health INTEGER DEFAULT 100,
            inventory TEXT,
            q INTEGER DEFAULT 0,
            r INTEGER DEFAULT 0,
            location_name TEXT,
            place_name TEXT
        );

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            q INTEGER,
            r INTEGER,
            data_json TEXT  -- stores the entire chunk definition as JSON
        );
        """)

        # Ensure a default player row exists
        cur = self.db.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO player (player_id, inventory, location_name, place_name)
            VALUES (1, 'Nothing', 'village', NULL)
            """
        )
        self.db.commit()

    def ensure_stats_columns(self):
        """
        Add columns for player stats if they don't exist yet.
        """
        cur = self.db.cursor()
        # Define new columns with their default values
        new_columns = {
            "attack": 5,
            "defense": 5,
            "agility": 5,
            "money": 50,
            "hunger": 100,
            "energy": 100,
            "thirst": 100,
            "alignment": 50  # 0=Evil, 100=Very Good
        }

        for col, default_val in new_columns.items():
            try:
                cur.execute(f"ALTER TABLE player ADD COLUMN {col} INTEGER DEFAULT {default_val}")
                print(f"Added new column: {col}")
            except:
                # Column likely exists already
                pass

        self.db.commit()

    # ------------------------------------------------------------------------
    # 1) LOADING / CREATING CHUNK DATA
    # ------------------------------------------------------------------------
    def get_or_create_chunk_data(self, q: int, r: int) -> Dict[str, Any]:
        """
        Try to load chunk data from the DB. If missing, generate via Cohere AI.
        Returns the JSON dict for the chunk structure.
        """
        c = self.db.cursor()
        row = c.execute("SELECT data_json FROM chunks WHERE q=? AND r=?", (q, r)).fetchone()
        if row:
            return json.loads(row["data_json"])

        # else we generate
        new_chunk = self.generate_chunk_via_ai(q, r)
        c.execute("INSERT INTO chunks (q, r, data_json) VALUES (?,?,?)",
                  (q, r, json.dumps(new_chunk)))
        self.db.commit()
        return new_chunk

    def generate_chunk_via_ai(self, q: int, r: int) -> Dict[str, Any]:
        """
        Calls Cohere to produce JSON describing multiple named locations in this chunk,
        including "village" if (q,r)==(0,0). Some locations might be secret (visible=false).
        Must return valid JSON with structure:
            {
              "locations": {
                "village": {
                  "visible": true,
                  "connections": [...],
                  "description": "...",
                  "history_of_events": [],
                  "sites": { ... }  <-- or any sub-locations
                },
                "forest": {...},
                "secretcave": {...}  # with visible=false, etc.
              }
            }
        """
        # Note: We'll instruct the AI to produce 3-6 named locations total,
        # with 2 possibly secret, each referencing each other plus an exit reference.
        # We'll also instruct it to produce sub-locations (sites) inside each location.
        # The user specifically wants 2 secret ones named X and Y if it can be done,
        # but we’ll just rely on the AI for variety. We will handle the secrets by
        # "visible": false.

        example_json = '''
{
  "locations": {
    "village": {
      "visible": true,
      "connections": ["forest", "exit:q+1,r0"],
      "description": "...",
      "history_of_events": [],
      "sites": {
        "inn": {
          "description": "...",
          "entities": [],
          "history_of_events": [],
          "discovered": false
        }
      }
    }
  }
}'''

        system_prompt = f"""
You are generating a new area in our fantasy exploration game at chunk coordinates (q={q}, r={r}).
Return ONLY valid JSON describing this chunk's locations, following these STRICT rules:

1. Generate EXACTLY 4-7 locations within this chunk
2. Each location MUST have:
   - "visible": boolean (false for secret locations)
   - "connections": array of strings listing ONLY:
     * Names of OTHER locations in this chunk
     * AT MOST ONE "exit:q±1,r±1" reference (0 or 1 exits per location)
   - "description": vivid but concise text
   - "history_of_events": empty array
   - "sites": dict of 1-3 discoverable sub-locations

3. If (q,r) is (0,0), one location MUST be named "village"

Example structure:
{example_json}

Return ONLY the JSON, no commentary.
"""

        # We'll do a small user prompt
        user_prompt = "Generate a chunk with 3-6 named top-level locations. Some might be secret."

        # We'll attempt the generation
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
            chunk_data = json.loads(raw_text)

            # Validate we have something
            if "locations" not in chunk_data:
                raise ValueError("No 'locations' field in JSON")

            # If (q,r) == (0,0), ensure we have 'village'
            if q == 0 and r == 0:
                locs = chunk_data["locations"]
                if "village" not in locs:
                    raise ValueError("No 'village' in chunk(0,0) data")

            return chunk_data

        except Exception as e:
            # fallback if anything fails
            return {
                "locations": {
                    "village": {
                        "visible": True,
                        "connections": ["exit:q+1,r-1", "forest"],
                        "description": f"A default village at chunk({q},{r})",
                        "history_of_events": [],
                        "sites": {
                            "town_hall": {
                                "description": "A small town hall building.",
                                "entities": [],
                                "history_of_events": [],
                                "discovered": False
                            }
                        }
                    },
                    "forest": {
                        "visible": True,
                        "connections": ["village", "exit:q,r+1"],
                        "description": "A fallback forest area.",
                        "history_of_events": [],
                        "sites": {
                            "hidden_grove": {
                                "description": "A serene grove of trees",
                                "entities": [],
                                "history_of_events": [],
                                "discovered": False
                            }
                        }
                    }
                }
            }

    def update_chunk(self, q: int, r: int, new_data: Dict[str, Any]):
        """
        Overwrites chunk data in DB.
        """
        c = self.db.cursor()
        c.execute("UPDATE chunks SET data_json=? WHERE q=? AND r=?",
                  (json.dumps(new_data), q, r))
        self.db.commit()

    # ------------------------------------------------------------------------
    # 2) POSSIBLE ACTIONS (UI logic)
    # ------------------------------------------------------------------------
    def get_possible_actions(self) -> List[str]:
        """
        Return the valid actions for the player's current situation.
        - "rest"
        - "check inventory"
        - if inside a site -> "leave site", "search site"
        - else -> location connections, "enter <someSite>", "search location", etc.
        """
        p = self.get_player_state()
        q, r = p["q"], p["r"]
        loc_name = p["location_name"]
        place_name = p["place_name"]

        chunk_data = self.get_or_create_chunk_data(q, r)
        loc_obj = chunk_data["locations"].get(loc_name)
        if not loc_obj:
            return ["rest", "check inventory"]

        actions = ["rest", "check inventory"]

        if place_name:
            # We are inside a site
            actions.append("leave site")
            actions.append("search site")

            # Add site-specific custom actions
            site_actions = self.get_site_actions(p["location_name"], p["place_name"])
            actions.extend(site_actions)

        else:
            # location-level
            for c in loc_obj["connections"]:
                actions.append(c)

            # discovered sites
            sites = loc_obj.get("sites", {})
            discovered_site_names = []
            for sname, sdata in sites.items():
                if sdata.get("discovered", False):
                    discovered_site_names.append(sname)
            for ds in discovered_site_names:
                actions.append(f"enter {ds}")

            actions.append("search location")

        return actions

    def get_site_actions(self, location_name: str, site_name: str) -> List[str]:
        """
        Generate a list of possible actions based on the site's description and game lore.
        """
        # Get the current chunk and location data
        p = self.get_player_state()
        chunk_data = self.get_or_create_chunk_data(p["q"], p["r"])
        loc_obj = chunk_data["locations"].get(location_name, {})
        
        # Get site description from the discovered sites
        sites = loc_obj.get("sites", {})
        site_data = sites.get(site_name, {})
        site_description = site_data.get("description", "")
        
        # If no description available, use search result
        if not site_description and "history_of_events" in loc_obj:
            for event in loc_obj["history_of_events"]:
                if site_name in event.lower():
                    site_description = event
                    break

        # Get relevant lore for this type of site
        lore_docs = self.rag.query_lore(f"What are common activities and interactions in a {site_name}?")
        lore_context = "\n".join(doc["data"]["content"] for doc in lore_docs)

        # Generate context-aware actions using AI with lore
        system_prompt = f"""Based on this site description and game lore, generate 2-4 logical actions the player could take. 
        Each action should make sense given the description and should affect player stats like hunger, energy, money, or alignment.
        
        Site Description: {site_description}
        
        Relevant Game Lore:
        {lore_context}
        
        Format each action as a simple verb phrase like "buy bread" or "pet cat".
        Actions should be natural interactions with described elements of the site.
        """

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "What actions are possible here?"}
                ],
                temperature=0.7
            )
            
            # Parse the response into a list of actions
            actions = []
            for line in response.message.content[0].text.strip().split('\n'):
                action = line.strip().strip('- ').lower()
                if action and len(action.split()) <= 3:  # Keep actions short
                    actions.append(action)
            
            return actions if actions else ["look around"]
            
        except Exception as e:
            print(f"Error generating actions: {e}")
            return ["look around"]  # Fallback action

    def apply_action(self, chosen_action: str) -> str:
        p = self.get_player_state()
        place_name = p["place_name"]

        if chosen_action == "rest":
            return self.do_rest()
        if chosen_action == "check inventory":
            return self.do_check_inventory()

        if place_name:
            # We are inside a site
            if chosen_action == "leave site":
                self.set_player_place(None)
                return "You step out of the site, back to the main location."
            if chosen_action == "search site":
                return self.do_search_site()

            # Handle site-specific custom actions
            return self.handle_site_action(place_name, chosen_action)

        # If not inside a site
        if chosen_action == "search location":
            return self.do_search_location()

        if chosen_action.startswith("exit:"):
            return self.do_exit(chosen_action)

        if chosen_action.startswith("enter "):
            site_name = chosen_action.replace("enter ", "").strip()
            return self.do_enter_site(site_name)

        # else it might be a local location name
        return self.do_move_to_location(chosen_action)

    def handle_site_action(self, site_name: str, chosen_action: str) -> str:
        """
        Handle site-specific actions and generate a detailed description of the result using game lore.
        """
        # Get current site description and player state
        p = self.get_player_state()
        chunk_data = self.get_or_create_chunk_data(p["q"], p["r"])
        loc_obj = chunk_data["locations"].get(p["location_name"], {})
        sites = loc_obj.get("sites", {})
        site_data = sites.get(site_name, {})
        site_description = site_data.get("description", "")

        # Get relevant lore for this action and site type
        lore_query = f"What happens when someone {chosen_action} in a {site_name}? What are the effects and consequences?"
        lore_docs = self.rag.query_lore(lore_query)
        lore_context = "\n".join(doc["data"]["content"] for doc in lore_docs)

        # Generate action result using AI with lore
        system_prompt = f"""Given the site description, game lore, and chosen action, generate a detailed result describing what happens.
        Include how it affects the player's stats in a structured way.
        Make the description atmospheric and engaging, incorporating elements from the game lore.
        
        Site Description: {site_description}
        
        Relevant Game Lore:
        {lore_context}
        
        Chosen Action: {chosen_action}
        Current Stats:
        - Money: {p['money']}
        - Energy: {p['energy']}
        - Hunger: {p['hunger']}
        - Alignment: {p['alignment']}/100 (0=Evil, 100=Very Good)

        Return your response in this format:
        DESCRIPTION: [Your atmospheric description here]
        STATS:
        money: [change in money, e.g. -5 for spending or +10 for earning]
        energy: [change in energy, -10 to +10]
        hunger: [change in hunger, -10 to +10]
        alignment: [change in alignment, -5 to +5]
        """

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "What happens when I take this action?"}
                ],
                temperature=0.7
            )
            
            result_text = response.message.content[0].text.strip()
            
            # Parse the response to extract description and stat changes
            description = ""
            stat_changes = {
                "money": 0,
                "energy": 0,
                "hunger": 0,
                "alignment": 0
            }
            
            # Split into sections
            sections = result_text.split("\n")
            for section in sections:
                if section.startswith("DESCRIPTION:"):
                    description = section.replace("DESCRIPTION:", "").strip()
                elif section.startswith("STATS:"):
                    continue  # Skip the STATS header
                elif ":" in section:
                    stat, value = section.split(":")
                    stat = stat.strip().lower()
                    if stat in stat_changes:
                        try:
                            stat_changes[stat] = int(value.strip())
                        except ValueError:
                            pass  # Skip if value isn't a valid integer
            
            # Apply the stat changes with bounds checking
            c = self.db.cursor()
            new_money = max(p["money"] + stat_changes["money"], 0)
            new_energy = max(min(p["energy"] + stat_changes["energy"], 100), 0)
            new_hunger = max(min(p["hunger"] + stat_changes["hunger"], 100), 0)
            new_alignment = max(min(p["alignment"] + stat_changes["alignment"], 100), 0)
            
            c.execute(
                """
                UPDATE player
                SET money=?, energy=?, hunger=?, alignment=?
                WHERE player_id=1
                """,
                (new_money, new_energy, new_hunger, new_alignment)
            )
            self.db.commit()
            
            # Add stat change summary to description
            changes_desc = []
            if stat_changes["money"] != 0:
                changes_desc.append(f"Money {'increased' if stat_changes['money'] > 0 else 'decreased'} by {abs(stat_changes['money'])}")
            if stat_changes["energy"] != 0:
                changes_desc.append(f"Energy {'increased' if stat_changes['energy'] > 0 else 'decreased'} by {abs(stat_changes['energy'])}")
            if stat_changes["hunger"] != 0:
                changes_desc.append(f"Hunger {'increased' if stat_changes['hunger'] > 0 else 'decreased'} by {abs(stat_changes['hunger'])}")
            if stat_changes["alignment"] != 0:
                changes_desc.append(f"Alignment {'improved' if stat_changes['alignment'] > 0 else 'worsened'} by {abs(stat_changes['alignment'])}")
            
            if changes_desc:
                description += "\n\n" + ". ".join(changes_desc) + "."
            
            return description
            
        except Exception as e:
            print(f"Error handling action: {e}")
            return f"You {chosen_action}, but nothing special happens."

    def generate_site_description(self, site_name: str, base_description: str) -> str:
        """
        Generate a rich, detailed description of a site using RAG and existing description.
        """
        # Get relevant lore about this type of site
        lore_docs = self.rag.query_lore(f"Tell me about {site_name}s in this world. What are they like?")
        lore_context = "\n".join(doc["data"]["content"] for doc in lore_docs)

        # Get time of day and weather if available
        current_time = "day" # TODO: Add time system
        
        system_prompt = f"""Generate a rich, atmospheric description of this {site_name} that the player has entered.
        Base your description on the existing description and game lore, but add more sensory details and atmosphere.
        Include sights, sounds, smells, and the general mood of the place.
        
        Existing Description: {base_description}
        
        Relevant Game Lore:
        {lore_context}
        
        Time of Day: {current_time}
        
        Make the description vivid and engaging, but keep it concise (2-3 sentences).
        Focus on details that might be relevant for player interactions.
        """

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Describe what I see as I enter."}
                ],
                temperature=0.7
            )
            
            return response.message.content[0].text.strip()
            
        except Exception as e:
            print(f"Error generating description: {e}")
            return base_description

    def do_enter_site(self, site_name: str) -> str:
        """
        Enter a site in the current location.
        """
        p = self.get_player_state()
        chunk_data = self.get_or_create_chunk_data(p["q"], p["r"])
        loc_obj = chunk_data["locations"].get(p["location_name"], {})
        
        # Check if site exists and is discovered
        sites = loc_obj.get("sites", {})
        if site_name not in sites or not sites[site_name].get("discovered", False):
            return f"There is no {site_name} here that you can enter."
            
        # Get or generate site description
        site_data = sites[site_name]
        base_description = site_data.get("description", "")
        
        # Generate rich description
        rich_description = self.generate_site_description(site_name, base_description)
        
        # Update site description if it's more detailed
        if len(rich_description) > len(base_description):
            sites[site_name]["description"] = rich_description
            self.update_chunk(p["q"], p["r"], chunk_data)
        
        # Set player location
        self.set_player_place(site_name)
        
        return f"You enter the {site_name}. {rich_description}"

    def do_look_around(self) -> str:
        """
        Look around the current site to get a detailed description.
        """
        p = self.get_player_state()
        if not p["place_name"]:
            return "You're not inside any site to look around."
            
        chunk_data = self.get_or_create_chunk_data(p["q"], p["r"])
        loc_obj = chunk_data["locations"].get(p["location_name"], {})
        sites = loc_obj.get("sites", {})
        site_data = sites.get(p["place_name"], {})
        site_description = site_data.get("description", "")
        
        # Get current description and generate a new perspective
        current_desc = site_data.get("description", "")
        new_desc = self.generate_site_description(p["place_name"], current_desc)
        
        # Sometimes update the stored description if the new one is more detailed
        if len(new_desc) > len(current_desc):
            sites[p["place_name"]]["description"] = new_desc
            self.update_chunk(p["q"], p["r"], chunk_data)
        
        return new_desc

    def do_rest(self) -> str:
        """
        +5 health up to 100
        """
        c = self.db.cursor()
        c.execute("UPDATE player SET health=MIN(health+5, 100) WHERE player_id=1")
        self.db.commit()
        return "You take a rest and regain some health."

    def do_check_inventory(self) -> str:
        """
        Show inventory as a string
        """
        p = self.get_player_state()
        return f"You have: {p['inventory']}"

    def do_exit(self, action: str) -> str:
        """
        action like "exit:q+1,r-1"
        parse it, switch chunk, set location to either 'village' if found, or first location.
        """
        p = self.get_player_state()
        old_q, old_r = p["q"], p["r"]
        data = action.replace("exit:", "")  # "q+1,r-1"
        part = data.split(",")  # ["q+1", "r-1"]
        dq = int(part[0][1:])  # +1 => 1
        dr = int(part[1][1:])  # -1 => -1
        new_q = old_q + dq
        new_r = old_r + dr

        self.set_player_chunk(new_q, new_r)
        # load chunk, pick default location
        chunk_data = self.get_or_create_chunk_data(new_q, new_r)
        # pick "village" if it exists, else first location
        possible_locs = list(chunk_data["locations"].keys())
        if "village" in possible_locs:
            new_loc = "village"
        else:
            new_loc = possible_locs[0]
        self.set_player_location(new_loc)
        self.set_player_place(None)
        return f"You exit to chunk({new_q},{new_r}), arriving at {new_loc}."

    def do_move_to_location(self, loc_name: str) -> str:
        """
        e.g. if we are in 'village' and loc_name='forest', check if it's in 'connections' of 'village'
        """
        p = self.get_player_state()
        q, r = p["q"], p["r"]
        chunk = self.get_or_create_chunk_data(q, r)
        current_loc_obj = chunk["locations"].get(p["location_name"], {})
        conns = current_loc_obj.get("connections", [])
        if loc_name not in conns:
            # might be secret or not in connections
            # if the location actually exists but is visible=false, we hide it from user anyway
            return f"You can't go to {loc_name} from here."

        # ok we can move
        self.set_player_location(loc_name)
        self.set_player_place(None)
        return f"You travel to {loc_name}."

    def do_enter_site(self, site_name: str) -> str:
        """
        We are in a location. site_name is a discovered site in 'sites'.
        We'll move the player into that site (place_name=site_name).
        """
        p = self.get_player_state()
        q, r = p["q"], p["r"]
        chunk_data = self.get_or_create_chunk_data(q, r)
        loc_obj = chunk_data["locations"].get(p["location_name"], {})
        
        # Check if site exists and is discovered
        sites = loc_obj.get("sites", {})
        if site_name not in sites or not sites[site_name].get("discovered", False):
            return f"There is no {site_name} here that you can enter."
            
        # Get or generate site description
        site_data = sites[site_name]
        base_description = site_data.get("description", "")
        
        # Generate rich description
        rich_description = self.generate_site_description(site_name, base_description)
        
        # Update site description if it's more detailed
        if len(rich_description) > len(base_description):
            sites[site_name]["description"] = rich_description
            self.update_chunk(q, r, chunk_data)
        
        # Set player location
        self.set_player_place(site_name)
        
        return f"You enter the {site_name}. {rich_description}"

    # ------------------------------------------------------------------------
    # 4) SEARCHING
    # ------------------------------------------------------------------------
    def do_search_location(self) -> str:
        """
        Searching a location might reveal a new site (set discovered=true) or do nothing.
        We'll call Cohere to see if we find anything new.
        """
        p = self.get_player_state()
        q, r = p["q"], p["r"]
        loc_name = p["location_name"]

        chunk_data = self.get_or_create_chunk_data(q, r)
        loc_obj = chunk_data["locations"].get(loc_name, {})
        sites = loc_obj.get("sites", {})

        # if we already have many sites, no new ones
        if len(sites) >= 20:
            return "You've discovered everything here. No more new discoveries."

        # system prompt
        system_prompt = """
We are searching the location '%s'.
We have these existing sites (some discovered, some not):
%s
We can reveal up to 1 new site. Return JSON in the form:
{
  "discovery_text": "...",
  "new_site_name": "something" or null,
  "new_site_data": {
     "description": "...",
     "entities": [],
     "history_of_events": [],
     "discovered": true
  }
}
If no new site, set new_site_name=null.
No commentary.
""" % (loc_name, json.dumps(sites, indent=2))

        user_prompt = "The player searches around to see if they find a new site."

        try:
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            raw = resp.message.content[0].text.strip()
            data = json.loads(raw)
        except:
            data = {
                "discovery_text": "You find nothing special.",
                "new_site_name": None,
                "new_site_data": {}
            }

        disc_text = data.get("discovery_text", "Nothing found.")
        new_name = data.get("new_site_name")
        new_data = data.get("new_site_data", {})

        if new_name:
            # add the site
            sites[new_name] = new_data
            loc_obj["sites"] = sites
            # record event
            loc_obj.setdefault("history_of_events", [])
            loc_obj["history_of_events"].append(f"Found new site: {new_name}")

            self.update_chunk(q, r, chunk_data)
            return f"You search the {loc_name}... {disc_text}"
        else:
            return f"You search around but: {disc_text}"

    def do_search_site(self) -> str:
        """
        Searching inside a site might reveal new 'entities' or nothing.
        We'll store them in site_data["entities"].
        """
        p = self.get_player_state()
        q, r = p["q"], p["r"]
        loc_name = p["location_name"]
        site_name = p["place_name"]

        chunk_data = self.get_or_create_chunk_data(q, r)
        loc_obj = chunk_data["locations"].get(loc_name, {})
        sites = loc_obj.get("sites", {})
        site_data = sites.get(site_name, {})
        if not site_data:
            return "Something's off; there's no such site here."

        # check how many entities we have
        existing_ents = site_data.get("entities", [])
        if len(existing_ents) >= 100:
            return "This site is already crowded. No more new discoveries."

        system_prompt = """
We are searching inside site '%s' at location '%s'.
We have these existing entities:
%s

We can discover up to 1 new entity. Return JSON:
{
  "discovery_text": "...",
  "new_entity": {
    "name": "...",
    "description": "...",
    "history_of_events": []
  } or null
}
No commentary.
""" % (site_name, loc_name, json.dumps(existing_ents, indent=2))

        user_prompt = "The player inspects the site thoroughly for items or NPCs."

        try:
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            raw = resp.message.content[0].text.strip()
            data = json.loads(raw)
        except:
            data = {
                "discovery_text": "Nothing new to find.",
                "new_entity": None
            }

        disc_text = data.get("discovery_text", "Nothing discovered.")
        new_ent = data.get("new_entity")

        if new_ent:
            existing_ents.append(new_ent)
            site_data["entities"] = existing_ents
            site_data.setdefault("history_of_events", [])
            site_data["history_of_events"].append(f"New entity discovered: {new_ent['name']}")
            sites[site_name] = site_data
            loc_obj["sites"] = sites

            self.update_chunk(q, r, chunk_data)
            return f"You search {site_name}: {disc_text}"
        else:
            return f"You search {site_name}... {disc_text}"

    # ------------------------------------------------------------------------
    # 5) BASIC Q/A (placeholder)
    # ------------------------------------------------------------------------
    def answer_question(self, question: str) -> str:
        """
        Enhanced question answering that uses RAG to combine game lore with current context.
        """
        # Get relevant lore snippets
        lore_docs = self.rag.query_lore(question)
        
        # Get current player context
        p = self.get_player_state()
        chunk_data = self.get_or_create_chunk_data(p["q"], p["r"])
        current_loc = chunk_data["locations"].get(p["location_name"], {})
        
        # Build context from both lore and current game state
        context = []
        
        # Add lore context
        for doc in lore_docs:
            context.append(f"From the game lore: {doc['data']['content']}")
            
        # Add player context with stats
        context.append(f"\nCurrent player state:")
        context.append(f"- Combat Stats: Attack {p['attack']}, Defense {p['defense']}, Agility {p['agility']}")
        context.append(f"- Resources: Money {p['money']}, Health {p['health']}")
        context.append(f"- Needs: Hunger {p['hunger']}, Energy {p['energy']}, Thirst {p['thirst']}")
        context.append(f"- Alignment: {p['alignment']}/100 (0=Evil, 100=Very Good)")
        context.append(f"- Location: {p['location_name']} at coordinates ({p['q']}, {p['r']})")
        if p["place_name"]:
            context.append(f"- Inside: {p['place_name']}")
            
        # Add location context
        if current_loc:
            context.append(f"\nCurrent location description: {current_loc.get('description', 'No description available')}")
            if "history_of_events" in current_loc:
                events = current_loc["history_of_events"]
                if events:
                    context.append("Notable events here:")
                    for event in events[:2]:  # Just the most recent events
                        context.append(f"- {event}")

        # Combine all context
        full_context = "\n".join(context)

        # Create the system prompt
        system_prompt = f"""You are the spirit of the Hex World, a mysterious realm of magic and adventure.
Answer the player's question using the following context about the game world and their current situation:

{full_context}

Answer in a mystical, atmospheric way that fits the game world. If you don't have enough information to answer accurately,
you can say so while staying in character (e.g. "The mists of time obscure that knowledge..." or "That secret remains hidden for now...").
When discussing player stats, be descriptive rather than just giving numbers (e.g. "Your spirit alignment leans towards the light" rather than "alignment is 75").
"""

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                temperature=0.7
            )
            return response.message.content[0].text.strip()
        except Exception as e:
            return f"(The spirits of this land are quiet for now. Try asking something else.)"

    # ------------------------------------------------------------------------
    # 6) GET/SET Player in DB
    # ------------------------------------------------------------------------
    def get_player_state(self) -> Dict[str, Any]:
        c = self.db.cursor()
        row = c.execute("SELECT * FROM player WHERE player_id=1").fetchone()
        if not row:
            # Default values for a new player
            return {
                "player_id": 1,
                "health": 100,
                "inventory": "Nothing",
                "q": 0,
                "r": 0,
                "location_name": "village",
                "place_name": None,
                "attack": 5,
                "defense": 5,
                "agility": 5,
                "money": 50,
                "hunger": 100,
                "energy": 100,
                "thirst": 100,
                "alignment": 50
            }

        # Convert row to dict and ensure all stats exist
        d = dict(row)
        default_stats = {
            "attack": 5,
            "defense": 5,
            "agility": 5,
            "money": 50,
            "hunger": 100,
            "energy": 100,
            "thirst": 100,
            "alignment": 50
        }
        
        # Add any missing stats with default values
        for stat, default in default_stats.items():
            if stat not in d:
                d[stat] = default

        return d

    def set_player_chunk(self, new_q: int, new_r: int):
        c = self.db.cursor()
        c.execute("UPDATE player SET q=?, r=? WHERE player_id=1", (new_q, new_r))
        self.db.commit()

    def set_player_location(self, loc_name: str):
        """
        Also resets place_name to NULL
        """
        c = self.db.cursor()
        c.execute("UPDATE player SET location_name=?, place_name=NULL WHERE player_id=1",
                  (loc_name,))
        self.db.commit()

    def set_player_place(self, place_name: Optional[str]):
        c = self.db.cursor()
        c.execute("UPDATE player SET place_name=? WHERE player_id=1", (place_name,))
        self.db.commit()
