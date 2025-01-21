# game_engine.py

import sqlite3
import cohere
from typing import Dict, Any, List, Optional
from cohere_secrets import COHERE_API_KEY
from lore_rag import LoreRAG

from chunk_manager import ChunkManager
from location_manager import LocationManager
from site_manager import SiteManager

class GameEngine:
    """
    This class ties the entire game together:
    - DB setup
    - Player stats
    - RAG-based Q&A
    - Access to chunk/location/site managers
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

        # Instantiate managers
        self.chunk_manager = ChunkManager(self.db, self.ai)
        self.location_manager = LocationManager(self.db, self.chunk_manager)
        self.site_manager = SiteManager(self.db, self.ai, self.rag)

    def setup_tables(self):
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
            data_json TEXT
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
    def get_possible_actions(self) -> List[str]:
        p = self.get_player_state()
        actions = ["rest", "check inventory"]

        chunk_data = self.chunk_manager.get_or_create_chunk_data(p["q"], p["r"])
        loc_obj = chunk_data["locations"].get(p["location_name"], {})

        if p["place_name"]:
            # We are inside a site
            actions.append("leave site")
            actions.append("search site")
            site_actions = self.site_manager.get_possible_site_actions(
                chunk_data, p["location_name"], p["place_name"]
            )
            actions.extend(site_actions)
        else:
            # location-level
            for c in loc_obj.get("connections", []):
                actions.append(c)
            # discovered sites
            sites = loc_obj.get("sites", {})
            for sname, sdata in sites.items():
                if sdata.get("discovered", False):
                    actions.append(f"enter {sname}")
            actions.append("search location")

        return actions

    def apply_action(self, chosen_action: str) -> str:
        p = self.get_player_state()

        # Periodic stat changes
        self.apply_periodic_changes()
        ### TIME FEATURE ADDED: increment time on every action
        self.advance_time(hours=1)  # e.g. each action costs 1 hour

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

        new_hunger = max(0, min(100, p["hunger"] - 2))
        new_energy = max(0, min(100, p["energy"] - 1))
        new_thirst = max(0, min(100, p["thirst"] - 3))

        health_change = 0
        if p["hunger"] <= 10 or p["energy"] <= 10 or p["thirst"] <= 10:
            health_change = -5

        new_health = max(0, min(100, p["health"] + health_change))

        c.execute("""
            UPDATE player
            SET hunger=?, energy=?, thirst=?, health=?
            WHERE player_id=1
        """, (new_hunger, new_energy, new_thirst, new_health))
        self.db.commit()

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
Stay in character and be mystical. If you lack enough data, respond with a lore-friendly "unknown" or "The mists obscure..."
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
                temperature=0.7
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
