# npc_manager.py

import sqlite3
import json
import datetime
import cohere
import logging
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format="%(asctime)s [%(levelname)s] %(message)s",
                   datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)

class NPCManager:
    """
    The NPCManager handles the creation, retrieval, memory updates, conversation handling,
    and location management for interactive NPCs in the Hex Adventure Game.
    
    It uses a SQLite database connection to persist NPC data and a Cohere AI client to generate
    in-character responses based on each NPC's personality, memory, and context.
    """
    def __init__(self, db: sqlite3.Connection, ai_client: cohere.Client):
        """
        Initialize the NPC Manager.
        
        :param db: SQLite database connection.
        :param ai_client: Cohere client for AI interactions.
        """
        self.db = db
        self.ai = ai_client

    # ============================================================
    # NPC Creation and Retrieval
    # ============================================================
    def create_npc(self, name: str, personality: str, home_q: int, home_r: int, initial_memory=None) -> int:
        """
        Create a new NPC with the provided details.
        
        The new NPC will be initialized with:
          - home coordinates equal to its initial current coordinates,
          - a null location (it will be updated later),
          - a status of "wandering", and
          - an empty memory (unless initial_memory is provided).
        
        :param name: The name of the NPC (e.g., "Noah").
        :param personality: A description of the NPC's traits and style.
        :param home_q: Home chunk q-coordinate.
        :param home_r: Home chunk r-coordinate.
        :param initial_memory: Optional list of memory entries.
        :return: The NPC ID of the newly created NPC.
        """
        if initial_memory is None:
            initial_memory = []
        memory_json = json.dumps(initial_memory)
        now = datetime.datetime.now().isoformat()
        cur = self.db.cursor()
        cur.execute("""
            INSERT INTO npc 
            (name, personality, memory, home_q, home_r, current_q, current_r, location_name, site_name, status, last_interaction)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, personality, memory_json, home_q, home_r, home_q, home_r, None, None, "wandering", now))
        self.db.commit()
        return cur.lastrowid

    def spawn_npc(self, current_q: int, current_r: int, location_name: str, site_name: str = None) -> Optional[Dict[str, Any]]:
        """
        Check if there is an NPC at the given chunk and location (and optionally, site).
        If one exists, return it. Otherwise, with a certain probability, create a new NPC.
        Returns None if no NPC is present and none is spawned.
        """
        try:
            cur = self.db.cursor()
            if site_name:
                cur.execute(
                    "SELECT * FROM npc WHERE current_q=? AND current_r=? AND location_name=? AND site_name=?",
                    (current_q, current_r, location_name, site_name)
                )
            else:
                cur.execute(
                    "SELECT * FROM npc WHERE current_q=? AND current_r=? AND location_name=?",
                    (current_q, current_r, location_name)
                )
            row = cur.fetchone()
            if row:
                return dict(row)
            
            # No NPC is present; decide whether to spawn one (50% chance)
            import random
            if random.random() < 0.5:
                # Generate a new NPC with default details
                default_personality = "A friendly wanderer who loves to share stories and values honesty."
                new_name = "Noah"  # This could be randomized or generated via AI
                npc_id = self.create_npc(new_name, default_personality, current_q, current_r)
                # Update NPC location with site name if provided
                self.update_npc_location(npc_id, current_q, current_r, location_name, site_name)
                npc = self.get_npc_by_id(npc_id)
                if npc:
                    return npc
            # No NPC spawns this time or creation failed
            return None
        except Exception as e:
            logger.error(f"Error in spawn_npc: {e}", exc_info=True)
            return None

    def get_npc_by_id(self, npc_id: int) -> Optional[dict]:
        """
        Retrieve an NPC by its ID.
        
        :param npc_id: The ID of the NPC to retrieve.
        :return: The NPC record as a dictionary, or None if not found.
        """
        try:
            cur = self.db.cursor()
            cur.execute("SELECT * FROM npc WHERE npc_id = ?", (npc_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.Error as e:
            logger.error(f"Database error while getting NPC by ID: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error while getting NPC by ID: {e}", exc_info=True)
            return None

    def get_npc_by_name(self, name: str, current_q: int = None, current_r: int = None, location_name: str = None):
        """
        Retrieve an NPC by name. Optionally, filter the search by the current chunk coordinates
        and location name. This helps ensure you get the NPC that is present in the player's area.
        
        :param name: The name of the NPC.
        :param current_q: (Optional) Current chunk q coordinate.
        :param current_r: (Optional) Current chunk r coordinate.
        :param location_name: (Optional) The current location name.
        :return: The NPC record as a dictionary, or None if not found.
        """
        try:
            cur = self.db.cursor()
            query = "SELECT * FROM npc WHERE name = ?"
            params = [name]
            if current_q is not None and current_r is not None:
                query += " AND current_q = ? AND current_r = ?"
                params.extend([current_q, current_r])
            if location_name is not None:
                query += " AND location_name = ?"
                params.append(location_name)
            cur.execute(query, params)
            row = cur.fetchone()
            if row:
                return dict(row)
            return None
        except sqlite3.Error as e:
            logger.error(f"Database error while getting NPC by name: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Unexpected error while getting NPC by name: {e}", exc_info=True)
            return None

    # ============================================================
    # Memory Management
    # ============================================================
    def update_npc_memory(self, npc_id: int, new_memory_entry: dict):
        """
        Append a new memory entry to the NPC's persistent memory.
        
        The memory is stored as JSON (a list of memory entries) in the database.
        Each new entry is appended to this list, and the last_interaction timestamp is updated.
        
        :param npc_id: The ID of the NPC.
        :param new_memory_entry: A dictionary representing the new memory entry.
        """
        try:
            cur = self.db.cursor()
            cur.execute("SELECT memory FROM npc WHERE npc_id = ?", (npc_id,))
            row = cur.fetchone()
            if row:
                try:
                    current_memory = json.loads(row["memory"]) if row["memory"] else []
                except Exception:
                    current_memory = []
                current_memory.append(new_memory_entry)
                updated_memory = json.dumps(current_memory)
                cur.execute("UPDATE npc SET memory = ?, last_interaction = ? WHERE npc_id = ?",
                            (updated_memory, datetime.datetime.now().isoformat(), npc_id))
                self.db.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error while updating NPC memory: {e}", exc_info=True)
            self.db.rollback()
        except Exception as e:
            logger.error(f"Unexpected error while updating NPC memory: {e}", exc_info=True)
            self.db.rollback()

    # ============================================================
    # Conversation Handling
    # ============================================================
    def handle_quest_inquiry(self, npc_id: int) -> str:
        """Handle when player asks NPC about available quests."""
        npc = self.get_npc_by_id(npc_id)
        if not npc:
            return "That NPC is not available."

        # Get NPC's personality and memory for context
        personality = npc["personality"]
        memory = json.loads(npc["memory"]) if npc["memory"] else []

        system_prompt = f"""
        You are {npc['name']}, with this personality: {personality}.
        Generate a response about what quests or tasks you might have for the player.
        Keep it brief (1-2 sentences) and in character.
        """

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "What quests do you have available?"}
                ],
                temperature=0.7
            )
            return response.message.content[0].text.strip()
        except Exception as e:
            logger.error(f"Error generating quest response: {e}")
            return f"{npc['name']} seems distracted and doesn't respond."

    def handle_rumor_inquiry(self, npc_id: int) -> str:
        """Handle when player asks NPC about local rumors."""
        npc = self.get_npc_by_id(npc_id)
        if not npc:
            return "That NPC is not available."

        personality = npc["personality"]
        memory = json.loads(npc["memory"]) if npc["memory"] else []

        system_prompt = f"""
        You are {npc['name']}, with this personality: {personality}.
        Share an interesting rumor or piece of gossip about the local area.
        Keep it brief (1-2 sentences) and in character.
        """

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Have you heard any interesting rumors lately?"}
                ],
                temperature=0.7
            )
            return response.message.content[0].text.strip()
        except Exception as e:
            logger.error(f"Error generating rumor response: {e}")
            return f"{npc['name']} glances around nervously but says nothing."

    def handle_trade(self, npc_id: int) -> str:
        """Handle when player wants to trade with an NPC."""
        npc = self.get_npc_by_id(npc_id)
        if not npc:
            return "That NPC is not available."

        personality = npc["personality"]
        
        system_prompt = f"""
        You are {npc['name']}, with this personality: {personality}.
        Respond to a player's request to trade.
        Keep it brief (1-2 sentences) and in character.
        """

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "I'd like to trade with you."}
                ],
                temperature=0.7
            )
            return response.message.content[0].text.strip()
        except Exception as e:
            logger.error(f"Error generating trade response: {e}")
            return f"{npc['name']} seems uninterested in trading right now."

    def get_npc_memory(self, npc_id: int):
        """
        Retrieve the NPC's memory from the database.
        
        :param npc_id: The ID of the NPC.
        :return: A list of memory entries.
        """
        try:
            cur = self.db.cursor()
            cur.execute("SELECT memory FROM npc WHERE npc_id = ?", (npc_id,))
            row = cur.fetchone()
            if row:
                try:
                    return json.loads(row["memory"]) if row["memory"] else []
                except Exception:
                    return []
            return []
        except sqlite3.Error as e:
            logger.error(f"Database error while getting NPC memory: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error while getting NPC memory: {e}", exc_info=True)
            return []

    # ============================================================
    # Conversation and Interaction
    # ============================================================
    def interact_with_npc(self, npc: dict, player_input: str, context: dict) -> str:
        """
        Handle a conversation between the player and an NPC.
        
        This method builds an AI prompt that incorporates:
          - The NPC's personality.
          - A summary of recent memory entries.
          - Context about the current location and any relevant player history.
          - The player's input.
          
        It then calls the AI client to generate a natural, in-character response.
        Finally, it updates the NPC's memory with a summary of the exchange and records
        the conversation in the conversation_history table.
        
        :param npc: The NPC record as a dictionary.
        :param player_input: The player's message.
        :param context: A dictionary containing additional context (e.g., location and player history).
        :return: The NPC's response as a string.
        """
        try:
            # Retrieve and summarize recent memory entries.
            memory_entries = self.get_npc_memory(npc["npc_id"])
            memory_summary = ""
            if memory_entries:
                # For brevity, summarize the last three interactions.
                memory_summary = "\n".join(
                    [f"- {entry.get('summary', 'No summary provided')}" for entry in memory_entries[-3:]]
                )
            
            # Build context strings.
            location_context = f"Location: {context.get('location_name', 'Unknown')} in chunk ({context.get('q', '?')}, {context.get('r', '?')})"
            player_history = context.get("player_history", "No significant history.")
            
            # Build the system prompt for the AI.
            prompt = f"""
You are {npc['name']}, an NPC with the following personality:
{npc['personality']}

Your recent memories:
{memory_summary if memory_summary else 'No recent memories.'}

Current context:
{location_context}
Player history: {player_history}

The player says: "{player_input}"
Respond in character with a short, natural dialogue. If relevant, recall past interactions.
"""
            try:
                response = self.ai.chat(
                    model="command-r-08-2024",
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": player_input}
                    ],
                    temperature=0.7
                )
                # Assuming the response structure: response.message.content[0].text
                npc_response = response.message.content[0].text.strip()
            except Exception as e:
                npc_response = "(The NPC seems confused and says nothing...)"
            
            # Update NPC memory with a summary of this interaction.
            new_memory = {
                "timestamp": datetime.datetime.now().isoformat(),
                "player_input": player_input,
                "npc_response": npc_response,
                "summary": f"Talked about '{player_input[:30]}...'"
            }
            self.update_npc_memory(npc["npc_id"], new_memory)
            
            # Optionally record the conversation in the conversation_history table.
            self.record_conversation(npc["npc_id"], 1, f"Player: {player_input}\n{npc['name']}: {npc_response}")
            
            return npc_response
        except sqlite3.Error as e:
            logger.error(f"Database error while interacting with NPC: {e}", exc_info=True)
            return "(The NPC seems confused and says nothing...)"
        except Exception as e:
            logger.error(f"Unexpected error while interacting with NPC: {e}", exc_info=True)
            return "(The NPC seems confused and says nothing...)"

    def record_conversation(self, npc_id: int, player_id: int, dialogue: str):
        """
        Record the conversation exchange in the conversation_history table.
        
        :param npc_id: The ID of the NPC.
        :param player_id: The player's ID.
        :param dialogue: A string containing both sides of the conversation.
        """
        try:
            cur = self.db.cursor()
            cur.execute("""
                INSERT INTO conversation_history (npc_id, player_id, dialogue)
                VALUES (?, ?, ?)
            """, (npc_id, player_id, dialogue))
            self.db.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error while recording conversation: {e}", exc_info=True)
            self.db.rollback()
        except Exception as e:
            logger.error(f"Unexpected error while recording conversation: {e}", exc_info=True)
            self.db.rollback()

    # ============================================================
    # Location and Spawning Management
    # ============================================================
    def update_npc_location(self, npc_id: int, current_q: int, current_r: int, location_name: str, site_name: str = None):
        """
        Update the current location details of an NPC.
        
        :param npc_id: The ID of the NPC.
        :param current_q: The new chunk q-coordinate.
        :param current_r: The new chunk r-coordinate.
        :param location_name: The new location name.
        :param site_name: (Optional) The site name within the location.
        """
        try:
            cur = self.db.cursor()
            cur.execute("""
                UPDATE npc 
                SET current_q = ?, current_r = ?, location_name = ?, site_name = ?, last_interaction = ?
                WHERE npc_id = ?
            """, (current_q, current_r, location_name, site_name, datetime.datetime.now().isoformat(), npc_id))
            self.db.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error while updating NPC location: {e}", exc_info=True)
            self.db.rollback()
        except Exception as e:
            logger.error(f"Unexpected error while updating NPC location: {e}", exc_info=True)
            self.db.rollback()



    # ============================================================
    # Public Interface for Player–NPC Conversation
    # ============================================================
    def talk_to_npc(self, npc_name: str, player_input: str, context: dict, player_id: int = 1) -> str:
        """
        Public method to handle a conversation with an NPC.
        
        It first retrieves the NPC based on the name and current location (extracted from the context),
        then passes the player's input and context to the conversation handler (npc_interact).
        
        :param npc_name: The name of the NPC to talk to.
        :param player_input: The player's dialogue input.
        :param context: A dictionary containing context such as current chunk (q, r), location_name,
                        and optionally player history.
        :param player_id: The player's ID (default: 1).
        :return: The NPC's response as a string.
        """
        try:
            # Retrieve the NPC record from the database.
            npc = self.get_npc_by_name(npc_name, context.get("q"), context.get("r"), context.get("location_name"))
            if not npc:
                return f"There is no {npc_name} here to talk to."
            # Engage in conversation.
            return self.interact_with_npc(npc, player_input, context)
        except sqlite3.Error as e:
            logger.error(f"Database error while talking to NPC: {e}", exc_info=True)
            return "(The NPC seems confused and says nothing...)"
        except Exception as e:
            logger.error(f"Unexpected error while talking to NPC: {e}", exc_info=True)
            return "(The NPC seems confused and says nothing...)"

    def get_npcs_in_location(self, q: int, r: int, location_name: str, site_name: str = None) -> list:
        """
        Return all NPCs located in the given chunk and location.
        
        Args:
            q (int): The q coordinate of the chunk.
            r (int): The r coordinate of the chunk.
            location_name (str): The name of the location.
            site_name (str, optional): The name of the site within the location. Defaults to None.
            
        Returns:
            list: A list of dictionaries containing NPC data.
        """
        try:
            cur = self.db.cursor()
            if site_name:
                cur.execute(
                    "SELECT * FROM npc WHERE current_q=? AND current_r=? AND location_name=? AND site_name=?",
                    (q, r, location_name, site_name)
                )
            else:
                cur.execute(
                    "SELECT * FROM npc WHERE current_q=? AND current_r=? AND location_name=?",
                    (q, r, location_name)
                )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Database error while getting NPCs in location: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Unexpected error while getting NPCs in location: {e}", exc_info=True)
            return []

    # ============================================================
    # Team Management
    # ============================================================
    def add_npc_to_team(self, player_id: int, npc_id: int) -> bool:
        """
        Add the NPC (npc_id) to the player's team if there is space.
        
        Args:
            player_id (int): The ID of the player.
            npc_id (int): The ID of the NPC to add to the team.
            
        Returns:
            bool: True if successful, False if the team is already full or other error.
        """
        try:
            cur = self.db.cursor()
            cur.execute("SELECT npc_team FROM player WHERE player_id=?", (player_id,))
            row = cur.fetchone()
            if not row:
                logger.error(f"Player {player_id} not found")
                return False
                
            try:
                team = json.loads(row["npc_team"]) if row["npc_team"] else []
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing team JSON for player {player_id}: {e}", exc_info=True)
                team = []
                
            if len(team) >= 4:
                logger.info(f"Team is full for player {player_id}")
                return False
                
            team.append(npc_id)
            cur.execute("UPDATE player SET npc_team=? WHERE player_id=?", (json.dumps(team), player_id))
            cur.execute("UPDATE npc SET status=? WHERE npc_id=?", ("in_team", npc_id))
            self.db.commit()
            logger.info(f"Added NPC {npc_id} to player {player_id}'s team")
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Database error while adding NPC {npc_id} to team: {e}", exc_info=True)
            self.db.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error while adding NPC {npc_id} to team: {e}", exc_info=True)
            self.db.rollback()
            return False

    def remove_npc_from_team(self, player_id: int, npc_id: int) -> bool:
        """
        Remove the NPC (npc_id) from the player's team.
        
        Args:
            player_id (int): The ID of the player.
            npc_id (int): The ID of the NPC to remove from the team.
            
        Returns:
            bool: True if successful, False if the NPC was not in the team or other error.
        """
        try:
            cur = self.db.cursor()
            cur.execute("SELECT npc_team FROM player WHERE player_id=?", (player_id,))
            row = cur.fetchone()
            if not row:
                logger.error(f"Player {player_id} not found")
                return False
                
            try:
                team = json.loads(row["npc_team"]) if row["npc_team"] else []
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing team JSON for player {player_id}: {e}", exc_info=True)
                team = []
                
            if npc_id not in team:
                logger.info(f"NPC {npc_id} not in player {player_id}'s team")
                return False
                
            team.remove(npc_id)
            cur.execute("UPDATE player SET npc_team=? WHERE player_id=?", (json.dumps(team), player_id))
            cur.execute("UPDATE npc SET status=? WHERE npc_id=?", ("active", npc_id))
            self.db.commit()
            logger.info(f"Removed NPC {npc_id} from player {player_id}'s team")
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Database error while removing NPC {npc_id} from team: {e}", exc_info=True)
            self.db.rollback()
            return False
        except Exception as e:
            logger.error(f"Unexpected error while removing NPC {npc_id} from team: {e}", exc_info=True)
            self.db.rollback()
            return False
