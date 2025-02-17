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
        lore_docs = self.rag.query_lore(question)
        p = self.get_player_state()
        chunk_data = self.chunk_manager.get_or_create_chunk_data(p["q"], p["r"])
        loc_obj = chunk_data["locations"].get(p["location_name"], {})

        context_bits = []
        for doc in lore_docs:
            context_bits.append(f"From the game lore: {doc['data']['content']}")
        context_bits.append("\nCurrent Player State:")
        context_bits.append(f" - Health={p['health']}, Money={p['money']}, Attack={p['attack']}")
        context_bits.append(f" - Hunger={p['hunger']}, Energy={p['energy']}, Thirst={p['thirst']}")
        context_bits.append(f" - Alignment={p['alignment']}/100")

        ### TIME FEATURE ADDED: mention time
        # e.g. Year 0 AC, month 1 => "Jan"
        month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        cur_month_str = month_names[(p["time_month"]-1) % 12]
        time_text = f"{p['time_hour']}:00, {cur_month_str} {p['time_day']}th, Year {p['time_year']} AC"
        context_bits.append(f" - Time: {time_text}")

        context_bits.append(f" - Location={p['location_name']} at chunk({p['q']},{p['r']})")
        if p["place_name"]:
            context_bits.append(f"   inside {p['place_name']}")

        if loc_obj:
            context_bits.append(f"\nCurrent location desc: {loc_obj.get('description','No desc')}")
            events = loc_obj.get("history_of_events", [])
            if events:
                context_bits.append("Recent events:")
                for ev in events[:2]:
                    context_bits.append(f" - {ev}")

        full_context = "\n".join(context_bits)
        system_prompt = f"""
You are the spirit of this fantasy hex world. Answer the player's question with the context below.
Be mystical but CONCISE - keep responses under 50 words. If you lack data, simply say "The mists obscure..."
---
Context:
{full_context}
---
"""

        try:
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ],
                temperature=0.5,
                max_tokens=100
            )
            return resp.message.content[0].text.strip()
        except Exception as e:
            return "(The spirits are silent...)"

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
