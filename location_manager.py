# location_manager.py

from typing import Dict, Any
import sqlite3

class LocationManager:
    """
    Manages local movement (location -> location) and cross-chunk exits.
    Ensures the correct corresponding location is used when crossing chunks.
    """

    def __init__(self, db: sqlite3.Connection, chunk_manager):
        self.db = db
        self.chunk_manager = chunk_manager

    def do_move_to_location(self, p: Dict[str, Any], loc_name: str) -> str:
        """
        Move the player from their current location (within the same chunk) to another
        local location, if it exists in connections.
        """
        q, r = p["q"], p["r"]
        chunk_data = self.chunk_manager.get_or_create_chunk_data(q, r)
        current_loc_obj = chunk_data["locations"].get(p["location_name"], {})
        conns = current_loc_obj.get("connections", [])

        if loc_name not in conns:
            return f"You cannot go to {loc_name} from here."

        self._set_player_location(p["player_id"], loc_name)
        self._set_player_place(p["player_id"], None)
        return f"You travel to {loc_name}."

    def do_exit_chunk(self, p: Dict[str, Any], action: str) -> str:
        """
        Handle an action like 'exit:q+1,r-1'. We parse the direction, load or create
        the new chunk, and find which location in the new chunk references back.
        """
        # action = "exit:q+1,r-1"
        data = action.replace("exit:", "")
        qpart, rpart = data.split(',')
        old_q, old_r = p["q"], p["r"]
        dq = int(qpart[1:])  # +1 => 1, -1 => -1
        dr = int(rpart[1:])
        new_q = old_q + dq
        new_r = old_r + dr

        # Tell chunk manager which direction we're coming from
        # e.g. if we're going "q+1,r+0", we're coming from "q+1,r+0" relative to old chunk
        from_dir = data  # use the same direction string

        # Get or create the new chunk, telling it which direction we're coming from
        new_chunk = self.chunk_manager.get_or_create_chunk_data(new_q, new_r, from_dir=from_dir)

        # The back edge we need to find
        back_edge = f"exit:{self._flip_direction(data)}"
        print(f"[DEBUG] Looking for location with {back_edge}")

        # Find the location that points back to us
        # This MUST exist because we passed from_dir to chunk generation
        new_loc = None
        for loc_name, loc_data in new_chunk["locations"].items():
            if back_edge in loc_data.get("connections", []):
                new_loc = loc_name
                print(f"[DEBUG] Found matching location {new_loc}")
                break

        if not new_loc:
            # This should never happen now
            print(f"[ERROR] No location found with {back_edge} - this should be impossible!")
            new_loc = list(new_chunk["locations"].keys())[0]

        # update player's chunk & location
        self._set_player_chunk(p["player_id"], new_q, new_r)
        self._set_player_location(p["player_id"], new_loc)
        self._set_player_place(p["player_id"], None)

        return f"You exit to chunk({new_q},{new_r}) and arrive at {new_loc}."

    def _flip_direction(self, dir_str: str) -> str:
        # e.g. "q+1,r+0" => "q-1,r+0"
        # e.g. "q-1,r+1" => "q+1,r-1"
        parts = dir_str.split(',')
        def flip(s: str):
            if '+' in s:
                return s.replace('+','-')
            return s.replace('-','+')
        return flip(parts[0]) + ',' + flip(parts[1])

    def _set_player_chunk(self, player_id: int, q: int, r: int):
        c = self.db.cursor()
        c.execute("UPDATE player SET q=?, r=? WHERE player_id=?", (q, r, player_id))
        self.db.commit()

    def _set_player_location(self, player_id: int, loc_name: str):
        c = self.db.cursor()
        c.execute("UPDATE player SET location_name=?, place_name=NULL WHERE player_id=?",
                  (loc_name, player_id))
        self.db.commit()

    def _set_player_place(self, player_id: int, place_name: str):
        c = self.db.cursor()
        c.execute("UPDATE player SET place_name=? WHERE player_id=?", (place_name, player_id))
        self.db.commit()
