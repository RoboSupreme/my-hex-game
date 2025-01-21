#!/usr/bin/env python3
import sqlite3
import json

def view_database():
    # Connect to the database
    conn = sqlite3.connect("game.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # View player table
    print("\n=== Player Table ===")
    cursor.execute("SELECT * FROM player")
    for row in cursor.fetchall():
        print(dict(row))
    
    # View chunks table
    print("\n=== Chunks Table ===")
    cursor.execute("SELECT * FROM chunks")
    for row in cursor.fetchall():
        chunk = dict(row)
        # Pretty print the JSON data
        chunk['data_json'] = json.loads(chunk['data_json'])
        print(f"\nChunk at (q={chunk['q']}, r={chunk['r']}):")
        print(json.dumps(chunk['data_json'], indent=2))
    
    conn.close()

if __name__ == "__main__":
    view_database()
