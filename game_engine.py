# game_engine.py

import sqlite3
import cohere
from typing import Dict, Any, List, Optional
from cohere_secrets import COHERE_API_KEY
from lore_rag import LoreRAG

from chunk_manager import ChunkManager
from location_manager import LocationManager
from site_manager import SiteManager
from npc_manager import NPCManager

class GameEngine:
    """
    This class ties the entire game together:
    - DB setup
    - Player stats
    - RAG-based Q&A
    - Access to chunk/location/site/npc managers
    """

    def __init__(self, db_path="game.db"):
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row

        # Cohere + RAG
        self.ai = cohere.ClientV2(api_key=COHERE_API_KEY)
        self.rag = LoreRAG(cohere_api_key=COHERE_API_KEY, collection_name="hex_game_lore")

        # Setup DB tables
        self.setup_tables()
        self.ensure_stats_columns()
        self.ensure_npc_team_column()

        # Instantiate managers
        self.chunk_manager = ChunkManager(self.db, self.ai)
        self.location_manager = LocationManager(self.db, self.chunk_manager)
        self.npc_manager = NPCManager(self.db, self.ai)
        self.site_manager = SiteManager(self.db, self.ai, self.rag, self.npc_manager)

    def setup_tables(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS player (
            player_id INTEGER PRIMARY KEY,
            health INTEGER DEFAULT 100,
            inventory TEXT,
            q INTEGER DEFAULT 0,
            r INTEGER DEFAULT 0,
            location_name TEXT,
            place_name TEXT,
            npc_team TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
            q INTEGER,
            r INTEGER,
            data_json TEXT
        );

        -- New NPC table
        CREATE TABLE IF NOT EXISTS npc (
            npc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            personality TEXT,
            memory TEXT,
            home_q INTEGER,
            home_r INTEGER,
            current_q INTEGER,
            current_r INTEGER,
            location_name TEXT,
            site_name TEXT,
            status TEXT,
            last_interaction TIMESTAMP
        );

        -- Conversation history table
        CREATE TABLE IF NOT EXISTS conversation_history (
            conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            npc_id INTEGER,
            player_id INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dialogue TEXT,
            FOREIGN KEY (npc_id) REFERENCES npc(npc_id),
            FOREIGN KEY (player_id) REFERENCES player(player_id)
        );
        """)

        # Ensure a default player row
        cur = self.db.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO player (player_id, inventory, location_name, place_name)
            VALUES (1, 'Nothing', 'village', NULL)
        """)
        self.db.commit()

    def ensure_stats_columns(self):
        new_columns = {
            "attack": 5,
            "defense": 5,
            "agility": 5,
            "money": 50,
            "hunger": 100,
            "energy": 100,
            "thirst": 100,
            "alignment": 50,
            "current_npc_id": None,  # Currently talking to this NPC

            ### TIME FEATURE ADDED ###
            "time_year": 0,
            "time_month": 1,   # 1 => Jan, 2 => Feb, etc.
            "time_day": 1,
            "time_hour": 0
        }

        cur = self.db.cursor()
        for col, default in new_columns.items():
            try:
                cur.execute(f"ALTER TABLE player ADD COLUMN {col} INTEGER DEFAULT {default}")
            except:
                pass
        self.db.commit()

    def ensure_npc_team_column(self):
        """Add npc_team column to player table if it doesn't exist."""
        cur = self.db.cursor()
        cur.execute("PRAGMA table_info(player)")
        columns = [row["name"] for row in cur.fetchall()]
        if "npc_team" not in columns:
            try:
                cur.execute("ALTER TABLE player ADD COLUMN npc_team TEXT DEFAULT '[]'")
            except Exception as e:
                print("Error adding npc_team column:", e)
        self.db.commit()

    # ---------------------------------------------------------------------
    # GET and SET player
    # ---------------------------------------------------------------------
    def get_player_state(self) -> Dict[str, Any]:
        c = self.db.cursor()
        row = c.execute("SELECT * FROM player WHERE player_id=1").fetchone()
        if not row:
            # create default
            self.create_default_player()
            row = c.execute("SELECT * FROM player WHERE player_id=1").fetchone()

        d = dict(row)
        # fill missing
        defaults = {
            "attack": 5, "defense": 5, "agility": 5, "money": 50,
            "hunger": 100, "energy": 100, "thirst": 100, "alignment": 50,
            ### TIME FEATURE ADDED ###
            "time_year": 0, "time_month": 1, "time_day": 1, "time_hour": 0
        }
        for k, v in defaults.items():
            if k not in d:
                d[k] = v
        return d

    def create_default_player(self):
        c = self.db.cursor()
        c.execute("""
            INSERT OR IGNORE INTO player (player_id, health, inventory, q, r, location_name)
            VALUES (1, 100, 'Nothing', 0, 0, 'village')
        """)
        self.db.commit()

    # ---------------------------------------------------------------------
    # CORE ACTIONS & UI
    # ---------------------------------------------------------------------
    def get_possible_actions(self) -> dict:
        """
        Return a dictionary with four categories of possible actions:
        1) location_movement: moving between locations (including exits to other chunks)
        2) site_movement: entering/exiting sites
        3) site_actions: site-specific or general actions
        4) follow_up_actions: contextual actions based on current state (e.g. NPC interactions)
        """
        p = self.get_player_state()
        chunk_data = self.chunk_manager.get_or_create_chunk_data(p["q"], p["r"])
        loc_obj = chunk_data["locations"].get(p["location_name"], {})

        location_movement = []
        site_movement = []
        site_actions = []

        # --- 1) Location-to-location movement ---
        # These are the "connections" for the current location, which may include "exit:q±1,r±1"
        for connection in loc_obj.get("connections", []):
            location_movement.append(connection)

        # --- 2) Site entrance/exit ---
        sites = loc_obj.get("sites", {})
        if p["place_name"]:
            # If we're inside a site, we can leave it (or search inside it)
            site_movement.append("leave site")
            site_movement.append("search site")
        else:
            # Show all discovered sites
            for sname, site_data in sites.items():
                if site_data.get("discovered", False):
                    site_movement.append(f"enter {sname}")

        # --- 3) Site-specific actions ---
        # If we are inside a site, load possible site actions
        if p["place_name"]:
            possible_site_actions = self.site_manager.get_possible_site_actions(
                chunk_data,
                p["location_name"],
                p["place_name"]
            )
            site_actions.extend(possible_site_actions)
        else:
            # If not in a site, you can still allow location-level searches
            site_actions.append("search location")

        # NPC interactions are added to site_actions
        npcs = self.npc_manager.get_npcs_in_location(
            p["q"],
            p["r"],
            p["location_name"],
            p["place_name"]
        )
        
        for npc in npcs:
            site_actions.append(f"talk to {npc['name']}")
            if npc['status'] == 'active':
                site_actions.append(f"recruit {npc['name']}")
            elif npc['status'] == 'in_team':
                site_actions.append(f"dismiss {npc['name']}")

        # Add general actions to the front of site_actions
        site_actions.insert(0, "check inventory")
        site_actions.insert(0, "rest")

        # Add follow-up actions based on current state
        follow_up_actions = []
        
        # If we're talking to an NPC, add conversation options
        if p.get("current_npc_id"):
            npc = self.npc_manager.get_npc_by_id(p["current_npc_id"])
            if npc:
                follow_up_actions.extend([
                    "ask about quests",
                    "ask about rumors",
                    "trade items",
                    "end conversation"
                ])
                if npc["status"] == "active":
                    follow_up_actions.append(f"recruit {npc['name']}")
                elif npc["status"] == "in_team":
                    follow_up_actions.append(f"dismiss {npc['name']}")

        return {
            "location_movement": location_movement,
            "site_movement": site_movement,
            "site_actions": site_actions,
            "follow_up_actions": follow_up_actions
        }

    def apply_action(self, chosen_action: str) -> str:
        p = self.get_player_state()

        # Periodic stat changes
        self.apply_periodic_changes()
        ### TIME FEATURE ADDED: increment time on every action
        self.advance_time(hours=1)  # e.g. each action costs 1 hour
        self.db.commit()  # Ensure all state changes are committed

        if chosen_action == "rest":
            return self.do_rest()
        if chosen_action == "check inventory":
            return self.do_check_inventory()

        # site or location
        if p["place_name"]:
            if chosen_action == "leave site":
                return self.site_manager.do_leave_site(p)
            elif chosen_action == "search site":
                chunk_data = self.chunk_manager.get_or_create_chunk_data(p["q"], p["r"])
                return self.site_manager.do_search_site(p, chunk_data)
            else:
                chunk_data = self.chunk_manager.get_or_create_chunk_data(p["q"], p["r"])
                return self.site_manager.handle_site_action(p, chunk_data, p["place_name"], chosen_action)
        else:
            if chosen_action == "search location":
                chunk_data = self.chunk_manager.get_or_create_chunk_data(p["q"], p["r"])
                return self.site_manager.do_search_location_for_new_site(p, chunk_data)
            if chosen_action.startswith("exit:"):
                return self.location_manager.do_exit_chunk(p, chosen_action)
            if chosen_action.startswith("enter "):
                site_name = chosen_action.replace("enter ", "").strip()
                chunk_data = self.chunk_manager.get_or_create_chunk_data(p["q"], p["r"])
                return self.site_manager.do_enter_site(p, chunk_data, site_name)
            elif chosen_action.startswith("talk to "):
                npc_name = chosen_action[8:]  # Remove "talk to " prefix
                # Get NPC and start conversation
                npc = self.npc_manager.get_npc_by_name(npc_name, p["q"], p["r"], p["location_name"])
                if npc:
                    # Set current_npc_id to enable follow-up actions
                    c = self.db.cursor()
                    c.execute("UPDATE player SET current_npc_id=? WHERE player_id=1", (npc["npc_id"],))
                    self.db.commit()
                    return f"You begin talking to {npc_name}. What would you like to discuss?"
                return f"Cannot find {npc_name} here."
            # Handle follow-up actions for NPC conversations
            elif chosen_action == "end conversation":
                c = self.db.cursor()
                c.execute("UPDATE player SET current_npc_id=NULL WHERE player_id=1")
                self.db.commit()
                return "You end the conversation."
            elif chosen_action == "ask about quests":
                if p.get("current_npc_id"):
                    npc = self.npc_manager.get_npc_by_id(p["current_npc_id"])
                    if npc:
                        return self.npc_manager.handle_quest_inquiry(npc["npc_id"])
                return "You need to be in a conversation to ask about quests."
            elif chosen_action == "ask about rumors":
                if p.get("current_npc_id"):
                    npc = self.npc_manager.get_npc_by_id(p["current_npc_id"])
                    if npc:
                        return self.npc_manager.handle_rumor_inquiry(npc["npc_id"])
                return "You need to be in a conversation to ask about rumors."
            elif chosen_action == "trade items":
                if p.get("current_npc_id"):
                    npc = self.npc_manager.get_npc_by_id(p["current_npc_id"])
                    if npc:
                        return self.npc_manager.handle_trade(npc["npc_id"])
                return "You need to be in a conversation to trade items."
            elif chosen_action.startswith("recruit "):
                npc_name = chosen_action[8:]  # Remove "recruit " prefix
                return self.recruit_npc(npc_name)
            elif chosen_action.startswith("dismiss "):
                npc_name = chosen_action[8:]  # Remove "dismiss " prefix
                return self.dismiss_npc(npc_name)
            else:
                return self.location_manager.do_move_to_location(p, chosen_action)

    # ---------------------------------------------------------------------
    # Additional
    # ---------------------------------------------------------------------
    def do_rest(self) -> str:
        c = self.db.cursor()
        c.execute("UPDATE player SET health=MIN(health+5, 100) WHERE player_id=1")
        self.db.commit()
        ### TIME FEATURE ADDED: resting more hours, e.g. 8 hours
        self.advance_time(hours=8)
        return "You take a moment to rest and regain some health."

    def do_check_inventory(self) -> str:
        p = self.get_player_state()
        return f"You have: {p['inventory']}"

    # ---------------------------------------------------------------------
    # Stats Management
    # ---------------------------------------------------------------------
    def apply_periodic_changes(self):
        c = self.db.cursor()
        p = self.get_player_state()

        # Calculate new stats
        new_hunger = max(0, min(100, p["hunger"] - 2))
        new_energy = max(0, min(100, p["energy"] - 1))
        new_thirst = max(0, min(100, p["thirst"] - 3))

        health_change = 0
        if p["hunger"] <= 10 or p["energy"] <= 10 or p["thirst"] <= 10:
            health_change = -5

        new_health = max(0, min(100, p["health"] + health_change))

        # Update all stats in a single transaction
        self.db.execute('BEGIN TRANSACTION')
        try:
            c.execute("""
                UPDATE player
                SET hunger=?, energy=?, thirst=?, health=?
                WHERE player_id=1
            """, (new_hunger, new_energy, new_thirst, new_health))
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise e

    # ---------------------------------------------------------------------
    # Q&A with RAG
    # ---------------------------------------------------------------------
    def answer_question(self, question: str) -> str:
        """
        Enhanced question answering that proactively provides actionable information
        along with answers to player questions. Uses specialized helper functions
        to retrieve detailed data based on the question type.
        """
        # Get basic player state first
        p = self.get_player_state()
        
        # Analyze the question to determine what kind of information we need
        lower_q = question.lower()
        
        # Define question categories and their keywords
        question_categories = {
            "stats": ["stats", "health", "hunger", "thirst", "energy", "attack", "defense", "agility", "money", "alignment", "inventory", "how am i", "my character"],
            "location": ["where", "location", "place", "here", "around", "surroundings", "nearby", "area", "environment"],
            "map": ["map", "world", "region", "chunks", "hex", "territory", "kingdom", "layout"],
            "quest": ["quest", "mission", "task", "goal", "objective", "adventure"],
            "survival": ["food", "water", "survive", "survival", "rest", "heal", "recover", "shelter", "danger"],
            "time": ["time", "day", "night", "month", "year", "hour", "calendar", "date", "season"],
            "npcs": ["people", "person", "npc", "character", "citizen", "villager", "friend", "enemy"]
        }
        
        # Determine the primary question category
        question_type = "general"  # Default category
        matched_keywords = []
        
        for category, keywords in question_categories.items():
            if any(keyword in lower_q for keyword in keywords):
                question_type = category
                matched_keywords = [kw for kw in keywords if kw in lower_q]
                break
                
        # Retrieve specialized information based on question type
        specialized_info = {}
        
        # Always get detailed player stats for context
        detailed_stats = self.get_detailed_player_stats()
        
        # Get detailed location information
        location_info = self.get_detailed_location_info(p["q"], p["r"], p["location_name"])
        
        # Get available actions
        available_actions = self.get_possible_actions()
        
        # Based on question type, add additional specialized information
        if question_type == "map":
            # For map questions, get a larger surrounding area
            specialized_info["map_data"] = self.get_surroundings_map(p["q"], p["r"], radius=2)
            
        # Track which specialized functions were called for debugging
        function_calls = [question_type]
        
        # Get relevant lore documents after we know the question type
        # This makes the search more contextual
        enhanced_query = question
        if matched_keywords:
            enhanced_query = f"{question} in context of {', '.join(matched_keywords)}"
        lore_docs = self.rag.query_lore(enhanced_query)
        
        # Gather all context information for the AI response
        context_bits = []
        
        # Add question type classification for better answer targeting
        context_bits.append(f"Question categorized as: {question_type.upper()}")
        if matched_keywords:
            context_bits.append(f"Matched keywords: {', '.join(matched_keywords)}")
        
        # Add appropriate lore information
        for doc in lore_docs:
            context_bits.append(f"From the game lore: {doc['data']['content']}")
        
        # Add critical alerts first (if any)
        critical_conditions = []
        if detailed_stats["health"]["status"] == "Critical":
            critical_conditions.append("Health critical")
        if detailed_stats["hunger"]["status"] == "Starving":
            critical_conditions.append("Starving")
        if detailed_stats["energy"]["status"] == "Exhausted":
            critical_conditions.append("Exhausted")
        if detailed_stats["thirst"]["status"] == "Dehydrated":
            critical_conditions.append("Dehydrated")
            
        if critical_conditions:
            context_bits.append("\nURGENT PLAYER CONDITION: " + ", ".join(critical_conditions))
        
        # Add detailed player state information
        context_bits.append("\nDetailed Player State:")
        context_bits.append(f" - Health: {detailed_stats['health']['value']}/100 ({detailed_stats['health']['status']})")
        context_bits.append(f" - Hunger: {detailed_stats['hunger']['value']}/100 ({detailed_stats['hunger']['status']})")
        context_bits.append(f" - Energy: {detailed_stats['energy']['value']}/100 ({detailed_stats['energy']['status']})")
        context_bits.append(f" - Thirst: {detailed_stats['thirst']['value']}/100 ({detailed_stats['thirst']['status']})")
        context_bits.append(f" - Combat: Attack {detailed_stats['attack']['value']} ({detailed_stats['attack']['rating']}), Defense {detailed_stats['defense']['value']} ({detailed_stats['defense']['rating']})")
        context_bits.append(f" - Money: {detailed_stats['money']} coins")
        context_bits.append(f" - Alignment: {detailed_stats['alignment']['value']}/100 ({detailed_stats['alignment']['rating']})")
        
        # Add time information
        month_names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        month_num = detailed_stats["time"]["month"]
        month_name = month_names[(month_num-1) % 12]
        time_text = f"{detailed_stats['time']['hour']}:00, {month_name} {detailed_stats['time']['day']}, Year {detailed_stats['time']['year']} AC"
        context_bits.append(f" - Current Time: {time_text}")
        
        # Add location information based on retrieved details
        context_bits.append(f"\nCurrent Location: {location_info['name']} at coordinates ({location_info['coordinates']['q']},{location_info['coordinates']['r']})")
        context_bits.append(f"Description: {location_info['description']}")
        
        if detailed_stats["location"]["place"]:
            context_bits.append(f"Currently inside: {detailed_stats['location']['place']}")
            
        # Add connection information
        if location_info["connections"]:
            locations_list = [conn["name"] for conn in location_info["connections"]]
            context_bits.append(f"Connected locations: {', '.join(locations_list)}")
            
        if location_info["exits"]:
            exits_list = [f"{exit['direction']} (to next chunk)" for exit in location_info["exits"]]
            context_bits.append(f"Available exits: {', '.join(exits_list)}")
            
        # Add discovered sites
        if location_info["sites"]:
            sites_list = [f"{site['name']}" for site in location_info["sites"]]
            context_bits.append(f"Discovered sites here: {', '.join(sites_list)}")
            
        # Add map information if requested
        if "map_data" in specialized_info:
            map_data = specialized_info["map_data"]
            context_bits.append(f"\nMap Information (radius {map_data['radius']} around current position):")
            context_bits.append(f"Total chunks mapped: {len(map_data['chunks'])}")
            # Add some general area description
            known_locations = sum(chunk["location_count"] for chunk in map_data["chunks"])
            context_bits.append(f"Known locations in area: {known_locations}")
        
        # Add recent events at current location
        if location_info["events"]:
            context_bits.append("\nRecent events at this location:")
            for ev in location_info["events"][:2]:  # Just show the 2 most recent
                context_bits.append(f" - {ev}")
                
        # Add available actions based on question type
        context_bits.append("\nAvailable Actions:")
        
        # Prioritize different action types based on question category
        if question_type == "location" or question_type == "map":
            # For location questions, emphasize movement options
            if available_actions["location_movement"]:
                context_bits.append(f"Movement options: {', '.join(available_actions['location_movement'])}")
            if available_actions["site_movement"]:
                context_bits.append(f"Site options: {', '.join(available_actions['site_movement'])}")
        elif question_type == "survival":
            # For survival questions, prioritize rest and relevant site actions
            survival_actions = [action for action in available_actions["site_actions"] 
                               if any(term in action.lower() for term in ["rest", "eat", "drink", "sleep", "heal"])]
            if survival_actions:
                context_bits.append(f"Survival actions: {', '.join(survival_actions)}")
        elif question_type == "quest" or question_type == "npcs":
            # For quest or NPC questions, show follow-up actions like talking to NPCs
            if available_actions["follow_up_actions"]:
                context_bits.append(f"Special actions: {', '.join(available_actions['follow_up_actions'])}")
        
        # Always include general site actions
        if available_actions["site_actions"] and question_type != "survival":  # Avoid duplicating for survival questions
            context_bits.append(f"General actions: {', '.join(available_actions['site_actions'][:5])}" + 
                               (" (and more)" if len(available_actions["site_actions"]) > 5 else ""))
                
        # Create the full context
        full_context = "\n".join(context_bits)
        
        # Create a system prompt tailored to the question type
        system_prompts = {
            "stats": "You are an insightful spirit guide. Focus on analyzing the player's current abilities and status. Provide practical advice on improving weaknesses.",
            "location": "You are a wise navigator spirit. Describe the current location vividly but briefly. Highlight key features and tactical considerations for movement.",
            "map": "You are an ancient cartographer spirit. Describe the surrounding region, noting distinctive landmarks and spatial relationships between areas.",
            "quest": "You are a prophetic spirit of destiny. Suggest possible adventures or quests based on the player's current location and abilities.",
            "survival": "You are a survival expert spirit. Prioritize immediate survival advice concerning health, hunger, thirst, and energy management.",
            "time": "You are a temporal spirit. Explain how time affects the world and what opportunities or challenges the current time period brings.",
            "npcs": "You are a spirit of connection. Discuss people in the area, their relationships, and how the player might interact with them.",
            "general": "You are the spirit guide of this fantasy hex world. Answer the player's question with wisdom and practicality."
        }
        
        # Choose the appropriate system prompt based on question type
        persona = system_prompts.get(question_type, system_prompts["general"])
        
        # Build the final system prompt
        system_prompt = f"""
{persona}

IMPORTANT GUIDELINES:
1. Be concise but informative - keep responses under 75 words
2. Prioritize actionable advice that directly helps the player
3. If the player is in critical condition, emphasize this first
4. Include one specific recommendation related to their question
5. Format key information in bold using ** for emphasis
6. If multiple answers are possible, choose the most immediately helpful one

---
Context:
{full_context}
---
"""

        try:
            # Call the AI with the enhanced prompt
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                temperature=0.7,  # Slightly higher temperature for more varied responses
                max_tokens=150    # Allow slightly longer responses for more helpful answers
            )
            return resp.message.content[0].text.strip()
        except Exception as e:
            return f"The spirits are gathering information... (Function calls: {', '.join(function_calls)})"

    # ---------------------------------------------------------------------
    # Helper methods for detailed information retrieval
    # ---------------------------------------------------------------------
    def get_detailed_player_stats(self) -> Dict[str, Any]:
        """
        Returns detailed player statistics including derived information
        and contextual stats such as status effects and attribute ratings.
        """
        p = self.get_player_state()
        
        # Create a more detailed player stats dictionary
        detailed_stats = {
            "health": {
                "value": p["health"],
                "max": 100,
                "status": "Critical" if p["health"] < 30 else ("Low" if p["health"] < 50 else "Good")
            },
            "hunger": {
                "value": p["hunger"],
                "max": 100,
                "status": "Starving" if p["hunger"] < 20 else ("Hungry" if p["hunger"] < 40 else "Satisfied")
            },
            "energy": {
                "value": p["energy"],
                "max": 100,
                "status": "Exhausted" if p["energy"] < 20 else ("Tired" if p["energy"] < 40 else "Energetic")
            },
            "thirst": {
                "value": p["thirst"],
                "max": 100,
                "status": "Dehydrated" if p["thirst"] < 20 else ("Thirsty" if p["thirst"] < 40 else "Hydrated")
            },
            "attack": {
                "value": p["attack"],
                "rating": "Weak" if p["attack"] < 10 else ("Average" if p["attack"] < 20 else "Strong")
            },
            "defense": {
                "value": p["defense"],
                "rating": "Vulnerable" if p["defense"] < 10 else ("Average" if p["defense"] < 20 else "Resilient")
            },
            "agility": {
                "value": p["agility"],
                "rating": "Slow" if p["agility"] < 10 else ("Average" if p["agility"] < 20 else "Quick")
            },
            "money": p["money"],
            "alignment": {
                "value": p["alignment"],
                "rating": "Evil" if p["alignment"] < 30 else ("Neutral" if p["alignment"] < 70 else "Good")
            },
            "location": {
                "q": p["q"],
                "r": p["r"],
                "name": p["location_name"],
                "place": p["place_name"]
            },
            "time": {
                "year": p["time_year"],
                "month": p["time_month"],
                "day": p["time_day"],
                "hour": p["time_hour"]
            }
        }
        
        return detailed_stats
    
    def get_detailed_location_info(self, q: int, r: int, location_name: str) -> Dict[str, Any]:
        """
        Returns detailed information about the current location including
        description, connections, sites, and recent events.
        """
        chunk_data = self.chunk_manager.get_or_create_chunk_data(q, r)
        loc_obj = chunk_data["locations"].get(location_name, {})
        
        if not loc_obj:
            return {"error": f"Location {location_name} not found in chunk({q},{r})"}
            
        # Extract connections and categorize them
        local_connections = []
        exits = []
        for conn in loc_obj.get("connections", []):
            if conn.startswith("exit:"):
                exits.append({
                    "direction": conn.replace("exit:", ""),
                    "type": "exit"
                })
            else:
                local_connections.append({
                    "name": conn,
                    "type": "location"
                })
                
        # Get site information
        sites = []
        for site_name, site_data in loc_obj.get("sites", {}).items():
            if site_data.get("discovered", False):
                sites.append({
                    "name": site_name,
                    "description": site_data.get("description", "No description available"),
                    "type": site_data.get("type", "unknown")
                })
                
        # Compile detailed location info
        detailed_info = {
            "name": location_name,
            "description": loc_obj.get("description", "No description available"),
            "coordinates": {"q": q, "r": r},
            "connections": local_connections,
            "exits": exits,
            "sites": sites,
            "events": loc_obj.get("history_of_events", [])
        }
        
        return detailed_info
        
    def get_surroundings_map(self, center_q: int, center_r: int, radius: int = 1) -> Dict[str, Any]:
        """
        Returns map data for chunks surrounding the specified coordinates.
        Radius determines how many chunks in each direction to include.
        """
        map_data = []
        cursor = self.db.cursor()
        
        # Calculate the range of coordinates to query
        min_q = center_q - radius
        max_q = center_q + radius
        min_r = center_r - radius
        max_r = center_r + radius
        
        # Query for chunks within the range
        rows = cursor.execute(
            "SELECT q, r, data_json FROM chunks WHERE q >= ? AND q <= ? AND r >= ? AND r <= ?",
            (min_q, max_q, min_r, max_r)
        ).fetchall()
        
        for row in rows:
            try:
                q = row[0]
                r = row[1]
                chunk_data = json.loads(row[2])
                
                # Simplify the chunk data to include only essential information
                locations = []
                for loc_name, loc_data in chunk_data.get("locations", {}).items():
                    loc_info = {
                        "name": loc_name,
                        "visible": loc_data.get("visible", True),
                        "site_count": len(loc_data.get("sites", {}))
                    }
                    locations.append(loc_info)
                
                map_data.append({
                    "q": q,
                    "r": r,
                    "distance_from_center": abs(q - center_q) + abs(r - center_r),
                    "location_count": len(locations),
                    "locations": locations
                })
            except Exception as e:
                print(f"Error processing chunk data at ({row[0]}, {row[1]}): {e}")
        
        return {
            "center": {"q": center_q, "r": center_r},
            "radius": radius,
            "chunks": map_data
        }
    
    ### TIME FEATURE ADDED: helper function to advance time
    def advance_time(self, hours: int):
        """
        Add 'hours' to the player's current time, handling day/month/year rollover.
        """
        # fetch current time
        p = self.get_player_state()
        cur_hour = p["time_hour"]
        cur_day = p["time_day"]
        cur_month = p["time_month"]
        cur_year = p["time_year"]

        # simple approach: add hours
        new_hour = cur_hour + hours

        # handle day rollover (24 hour)
        while new_hour >= 24:
            new_hour -= 24
            cur_day += 1

            # days in a month, let's do a simple 30-day months
            # or you can get fancier
            if cur_day > 30:
                cur_day = 1
                cur_month += 1
                if cur_month > 12:
                    cur_month = 1
                    cur_year += 1

        # update DB
        c = self.db.cursor()
        c.execute("""
            UPDATE player
            SET time_hour=?, time_day=?, time_month=?, time_year=?
            WHERE player_id=1
        """, (new_hour, cur_day, cur_month, cur_year))
        self.db.commit()

    def talk_to_npc(self, npc_name: str) -> str:
        """Talk to an NPC in the current location."""
        player_state = self.get_player_state()
        npcs = self.npc_manager.get_npcs_in_location(
            player_state["q"],
            player_state["r"],
            player_state["location_name"],
            player_state["place_name"]
        )
        
        for npc in npcs:
            if npc["name"] == npc_name:
                response = self.npc_manager.interact_with_npc(
                    npc["npc_id"],
                    player_state["player_id"],
                    "Hello!"
                )
                return f"{npc_name} says: {response}"
        
        return f"You don't see {npc_name} here."

    def recruit_npc(self, npc_name: str) -> str:
        """Try to recruit an NPC to your team."""
        player_state = self.get_player_state()
        npcs = self.npc_manager.get_npcs_in_location(
            player_state["q"],
            player_state["r"],
            player_state["location_name"],
            player_state["place_name"]
        )
        
        for npc in npcs:
            if npc["name"] == npc_name and npc["status"] == "active":
                if self.npc_manager.add_npc_to_team(player_state["player_id"], npc["npc_id"]):
                    return f"{npc_name} has joined your team!"
        
        return f"You cannot recruit {npc_name} right now."

    def dismiss_npc(self, npc_name: str) -> str:
        """Remove an NPC from your team."""
        player_state = self.get_player_state()
        npcs = self.npc_manager.get_npcs_in_location(
            player_state["q"],
            player_state["r"],
            player_state["location_name"],
            player_state["place_name"]
        )
        
        for npc in npcs:
            if npc["name"] == npc_name and npc["status"] == "in_team":
                if self.npc_manager.remove_npc_from_team(player_state["player_id"], npc["npc_id"]):
                    return f"{npc_name} has left your team."
        
        return f"You cannot dismiss {npc_name} right now."
