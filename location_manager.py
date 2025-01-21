# location_manager.py

from typing import Dict, Any, List
import sqlite3

class LocationManager:
    """
    Manages logic for moving the player between locations within a chunk,
    as well as handling 'exit:q±1,r±1' transitions to new chunks.
    """

    def __init__(self, db: sqlite3.Connection, chunk_manager):
        self.db = db
        self.chunk_manager = chunk_manager  # an instance of ChunkManager

    def get_possible_location_actions(self, chunk_data: Dict[str, Any], location_name: str) -> List[str]:
        """
        Returns possible location-level actions: the location's 'connections'
        plus "search location".
        """
        loc_obj = chunk_data["locations"].get(location_name)
        if not loc_obj:
            return []

        actions = []
        # connections
        for c in loc_obj["connections"]:
            actions.append(c)
        # searching
        actions.append("search location")
        return actions

    def do_move_to_location(self, p: Dict[str, Any], loc_name: str) -> str:
        """
        Attempt to move from player's current location to 'loc_name' if in connections.
        """
        q, r = p["q"], p["r"]
        chunk_data = self.chunk_manager.get_or_create_chunk_data(q, r)
        current_loc_obj = chunk_data["locations"].get(p["location_name"], {})
        conns = current_loc_obj.get("connections", [])
        if loc_name not in conns:
            # might be secret or not in connections
            return f"You can't go to {loc_name} from here."

        # set player's location to loc_name
        self._set_player_location(p["player_id"], loc_name)
        self._set_player_place(p["player_id"], None)
        return f"You travel to {loc_name}."

    def do_exit_chunk(self, p: Dict[str, Any], action: str) -> str:
        """
        e.g. action like 'exit:q+1,r-1' => parse, set new chunk,
        pick default location in the new chunk.
        """
        data = action.replace("exit:", "")  # "q+1,r-1"
        part = data.split(",")  # ["q+1", "r-1"]
        old_q, old_r = p["q"], p["r"]
        dq = int(part[0][1:])  # +1 => 1
        dr = int(part[1][1:])  # -1 => -1
        new_q = old_q + dq
        new_r = old_r + dr

        self._set_player_chunk(p["player_id"], new_q, new_r)

        # load chunk, pick default location
        chunk_data = self.chunk_manager.get_or_create_chunk_data(new_q, new_r)
        possible_locs = list(chunk_data["locations"].keys())

        if "village" in possible_locs:
            new_loc = "village"
        else:
            new_loc = possible_locs[0]

        self._set_player_location(p["player_id"], new_loc)
        self._set_player_place(p["player_id"], None)
        return f"You exit to chunk({new_q},{new_r}), arriving at {new_loc}."

    # ----------------------------------------------------------------------
    # DB helpers to set player's location or chunk
    # ----------------------------------------------------------------------
    def _set_player_chunk(self, player_id: int, new_q: int, new_r: int):
        c = self.db.cursor()
        c.execute(
            "UPDATE player SET q=?, r=? WHERE player_id=?",
            (new_q, new_r, player_id)
        )
        self.db.commit()

    def _set_player_location(self, player_id: int, loc_name: str):
        c = self.db.cursor()
        c.execute(
            "UPDATE player SET location_name=?, place_name=NULL WHERE player_id=?",
            (loc_name, player_id)
        )
        self.db.commit()

    def _set_player_place(self, player_id: int, place_name: str):
        c = self.db.cursor()
        c.execute(
            "UPDATE player SET place_name=? WHERE player_id=?",
            (place_name, player_id)
        )
        self.db.commit()
