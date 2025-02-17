#!/usr/bin/env python3
"""
reset_game.py

This script resets the game world by:
1. Deleting the existing database
2. Creating a new database with fresh tables
3. Initializing a new player and starting chunk
"""

import os
import sqlite3
import json
from datetime import datetime

def create_tables(cur):
    # Create player table with all required columns
    cur.execute("""
    CREATE TABLE player (
        player_id INTEGER PRIMARY KEY AUTOINCREMENT,
        health INTEGER DEFAULT 100,
        inventory TEXT DEFAULT 'Nothing',
        money INTEGER DEFAULT 50,
        hunger INTEGER DEFAULT 0,
        thirst INTEGER DEFAULT 0,
        energy INTEGER DEFAULT 100,
        alignment INTEGER DEFAULT 50,
        attack INTEGER DEFAULT 10,
        defense INTEGER DEFAULT 10,
        agility INTEGER DEFAULT 10,
        location_name TEXT DEFAULT 'village',
        q INTEGER DEFAULT 0,
        r INTEGER DEFAULT 0,
        place_name TEXT DEFAULT NULL,
        time_year INTEGER DEFAULT 1,
        time_month INTEGER DEFAULT 1,
        time_day INTEGER DEFAULT 1,
        time_hour INTEGER DEFAULT 8,
        npc_team TEXT DEFAULT '[]',
        current_npc_id INTEGER DEFAULT NULL
    )
    """)

    # Create chunks table
    cur.execute("""
    CREATE TABLE chunks (
        chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
        q INTEGER,
        r INTEGER,
        data_json TEXT,
        UNIQUE(q, r)
    )
    """)

    # Create NPC table
    cur.execute("""
    CREATE TABLE npc (
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
        status TEXT DEFAULT 'active',
        last_interaction TIMESTAMP,
        npc_type TEXT DEFAULT 'wanderer'
    )
    """)

    # Create conversation history table
    cur.execute("""
    CREATE TABLE conversation_history (
        conversation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        npc_id INTEGER,
        player_id INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        dialogue TEXT,
        FOREIGN KEY (npc_id) REFERENCES npc(npc_id),
        FOREIGN KEY (player_id) REFERENCES player(player_id)
    )
    """)

def create_starting_chunk():
    """Create the initial chunk at (0,0) with a village and surrounding areas"""
    return {
        "locations": {
            "village": {
                "description": "A quaint village nestled among rolling hills, with cobblestone streets and timber-framed houses. The village square is a hub of activity, where locals gather to trade stories and goods.",
                "visible": True,
                "connections": ["forest", "exit:q+1,r+0"],
                "sites": {
                    "inn": {
                        "description": "The Golden Plough Inn, a warm and welcoming establishment, offers travelers a cozy respite with its crackling fireplace and hearty meals.",
                        "discovered": False,
                        "entities": [],
                        "history_of_events": []
                    },
                    "smithy": {
                        "description": "A small forge where the village's blacksmith crafts tools and weapons, the air filled with the scent of burning coal and the sound of hammer on anvil.",
                        "discovered": False,
                        "entities": [],
                        "history_of_events": []
                    },
                    "bakery": {
                        "description": "A cozy bakery with a warm and inviting atmosphere, the air filled with the mouthwatering scent of freshly baked goods.",
                        "discovered": False,
                        "entities": [],
                        "history_of_events": []
                    }
                },
                "history_of_events": []
            },
            "forest": {
                "description": "A dense forest with towering trees and a canopy of lush greenery. The forest floor is blanketed with soft moss and an abundance of wildlife calls this place home.",
                "visible": True,
                "connections": ["village", "exit:q+0,r-1"],
                "sites": {
                    "hidden_clearing": {
                        "description": "A secret clearing deep within the forest, where a mystical stone circle stands, its purpose unknown to all but a few.",
                        "discovered": False,
                        "entities": [],
                        "history_of_events": []
                    }
                },
                "history_of_events": []
            },
            "mystic_grove": {
                "description": "A sacred grove, where ancient trees whisper secrets to those who dare to listen. The air is thick with the scent of incense and the sound of distant chanting.",
                "visible": False,
                "connections": ["exit:q+1,r+0"],
                "sites": {
                    "altar": {
                        "description": "A stone altar, surrounded by flickering torches, where rituals and offerings are made to the unknown gods.",
                        "discovered": False,
                        "entities": [],
                        "history_of_events": []
                    }
                },
                "history_of_events": []
            },
            "mountain_pass": {
                "description": "A treacherous mountain pass, with steep cliffs and narrow pathways. The air is thin and cold, and the sound of rushing water echoes from a nearby waterfall.",
                "visible": True,
                "connections": ["exit:q-1,r+0"],
                "sites": {
                    "abandoned_watchtower": {
                        "description": "An ancient watchtower, now in ruins, offers a breathtaking view of the surrounding landscape. Its walls still bear the marks of long-forgotten battles.",
                        "discovered": False,
                        "entities": [],
                        "history_of_events": []
                    }
                },
                "history_of_events": []
            },
            "ruined_castle": {
                "description": "The remnants of a once-grand castle, now overgrown with ivy and shrouded in mystery. Its crumbling walls hide dark secrets and forgotten treasures.",
                "visible": False,
                "connections": ["exit:q+0,r+1"],
                "sites": {
                    "crypt": {
                        "description": "A subterranean crypt, its stone steps leading to ancient tombs and forgotten relics.",
                        "discovered": False,
                        "entities": [],
                        "history_of_events": []
                    }
                },
                "history_of_events": []
            }
        }
    }

def reset_game(db_path="web/game.db"):
    """Reset the game by creating a new database with initial data"""
    # Delete existing database if it exists
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Deleted existing database: {db_path}")

    # Create new database
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # Create tables
    create_tables(cur)
    print("Created new tables")

    # Insert starting player
    cur.execute("""
    INSERT INTO player DEFAULT VALUES
    """)
    print("Created new player")

    # Insert starting chunk
    starting_chunk = create_starting_chunk()
    cur.execute("""
    INSERT INTO chunks (q, r, data_json)
    VALUES (0, 0, ?)
    """, (json.dumps(starting_chunk),))
    print("Created starting chunk at (0,0)")

    # Commit changes and close
    db.commit()
    db.close()
    print("Game reset complete!")

if __name__ == "__main__":
    reset_game()
