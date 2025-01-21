# chunk_manager.py

import json
import cohere
import sqlite3
from typing import Dict, Any, Optional

class ChunkManager:
    """
    Responsible for retrieving or creating chunk data (top-level locations),
    storing it in the DB, and calling Cohere to generate chunk JSON if missing.
    """

    def __init__(self, db: sqlite3.Connection, cohere_client: cohere.ClientV2):
        self.db = db
        self.ai = cohere_client

    def get_or_create_chunk_data(self, q: int, r: int) -> Dict[str, Any]:
        """
        Try to load chunk data from the DB. If missing, generate via Cohere AI.
        Returns the JSON dict for the chunk structure.
        """
        c = self.db.cursor()
        row = c.execute(
            "SELECT data_json FROM chunks WHERE q=? AND r=?",
            (q, r)
        ).fetchone()
        if row:
            return json.loads(row["data_json"])

        # If not found, generate new chunk data
        new_chunk = self.generate_chunk_via_ai(q, r)
        c.execute(
            "INSERT INTO chunks (q, r, data_json) VALUES (?,?,?)",
            (q, r, json.dumps(new_chunk))
        )
        self.db.commit()
        return new_chunk

    def generate_chunk_via_ai(self, q: int, r: int) -> Dict[str, Any]:
        """
        Calls Cohere to produce JSON describing multiple named locations in this chunk.
        Each location must have 'visible', 'connections', 'description',
        'history_of_events', and 'sites'.
        If (q,r)==(0,0), one location must be 'village'.
        """
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
       * AT MOST ONE "exit:q±1,r±1" reference
   - "description": short but vivid text
   - "history_of_events": empty array
   - "sites": dict of 1-3 discoverable sub-locations

3. If (q,r) == (0,0), one location MUST be named "village"

Example structure:
{example_json}

Return ONLY the JSON, no commentary.
"""

        try:
            user_prompt = "Generate the chunk with 3-6 named top-level locations, some possibly secret."
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

            # Validate
            if "locations" not in chunk_data:
                raise ValueError("No 'locations' field in JSON")

            # If (q,r) == (0,0), ensure 'village'
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
        c.execute(
            "UPDATE chunks SET data_json=? WHERE q=? AND r=?",
            (json.dumps(new_data), q, r)
        )
        self.db.commit()
