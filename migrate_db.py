#!/usr/bin/env python3
"""
migrate_db.py

This script updates the existing game database to support interactive NPCs.
It adds a new column 'npc_team' to the player table (if missing) and creates
new tables for npc and conversation_history.
"""

import sqlite3

def migrate_db(db_path="game.db"):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # --- Ensure 'npc_team' column exists in player table ---
    cur.execute("PRAGMA table_info(player)")
    columns = [row["name"] for row in cur.fetchall()]
    if "npc_team" not in columns:
        try:
            cur.execute("ALTER TABLE player ADD COLUMN npc_team TEXT DEFAULT '[]'")
            print("Added npc_team column to player table.")
        except Exception as e:
            print("Error adding npc_team column:", e)
    else:
        print("npc_team column already exists in player table.")

    # --- Create npc table if it does not exist ---
    cur.execute("""
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
    """)
    print("Ensured npc table exists.")

    # --- Add new columns to NPC table ---
    cur.executescript("""
        -- Add npc_type column if it doesn't exist
        ALTER TABLE npc ADD COLUMN IF NOT EXISTS npc_type TEXT DEFAULT 'wanderer';

        -- Ensure memory column exists and has correct default
        ALTER TABLE npc ADD COLUMN IF NOT EXISTS memory TEXT DEFAULT '{
            "player_opinion": 50,
            "interactions": [],
            "knowledge": {
                "visited_locations": [],
                "known_npcs": [],
                "stories": []
            },
            "inventory": {
                "gold": 50,
                "items": []
            },
            "abilities": {
                "can_trade": false,
                "can_heal": false,
                "can_guide": true,
                "combat_skill": 5
            },
            "daily_routine": {
                "morning": null,
                "afternoon": null,
                "evening": null
            },
            "relationships": {},
            "quests": []
        }';

        -- Update status values for existing NPCs
        UPDATE npc SET status = 'active' WHERE status = 'wandering';
    """)
    print("Updated NPC table schema.")

    # --- Create conversation_history table if it does not exist ---
    cur.execute("""
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
    print("Ensured conversation_history table exists.")

    db.commit()
    db.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate_db()
