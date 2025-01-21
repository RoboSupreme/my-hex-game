# site_manager.py

import json
import cohere
import sqlite3
from typing import Dict, Any, Optional, List

from lore_rag import LoreRAG

class SiteManager:
    """
    Manages sub-locations (sites) in a location. Searching for new sites,
    entering a site, searching inside a site, and site-specific actions.
    """

    def __init__(self, db: sqlite3.Connection, cohere_client: cohere.ClientV2, rag: LoreRAG):
        self.db = db
        self.ai = cohere_client
        self.rag = rag

    def get_possible_site_actions(self, chunk_data: Dict[str, Any], location_name: str, site_name: str) -> List[str]:
        """
        Generate a list of possible site actions with AI, plus "search site", "leave site".
        Called only if player is inside a site.
        """
        loc_obj = chunk_data["locations"].get(location_name, {})
        site_data = loc_obj.get("sites", {}).get(site_name, {})

        site_description = site_data.get("description", "")
        # fallback: check location history if no direct description
        if not site_description and "history_of_events" in loc_obj:
            for event in loc_obj["history_of_events"]:
                if site_name in event.lower():
                    site_description = event
                    break

        # Query RAG for lore about this site type
        lore_docs = self.rag.query_lore(f"What are common activities and interactions in a {site_name}?")
        lore_context = "\n".join(d["data"]["content"] for d in lore_docs)

        system_prompt = f"""Based on this site description and game lore, generate 2-4 logical actions the player could take.
Each action should be a short verb phrase like "buy bread" or "pet cat" that is plausible in this site.
Keep them short and relevant.

Site Description: {site_description}

Relevant Game Lore:
{lore_context}
"""

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "What actions are possible here?"}
                ],
                temperature=0.7
            )

            raw_lines = response.message.content[0].text.strip().split('\n')
            actions = []
            for line in raw_lines:
                line = line.strip("- ").strip()
                if line:
                    # keep short lines
                    if len(line.split()) <= 4:
                        actions.append(line.lower())
            if not actions:
                actions = ["look around"]
            return actions

        except Exception as e:
            print(f"Error generating site actions: {e}")
            return ["look around"]

    def do_enter_site(self, p: Dict[str, Any], chunk_data: Dict[str, Any], site_name: str) -> str:
        """
        Enter a site in the current location, if discovered.
        """
        loc_obj = chunk_data["locations"].get(p["location_name"], {})
        sites = loc_obj.get("sites", {})
        if site_name not in sites or not sites[site_name].get("discovered", False):
            return f"There is no {site_name} here that you can enter."

        # Generate a rich site description
        site_data = sites[site_name]
        base_desc = site_data.get("description", "")
        new_desc = self._generate_site_description(site_name, base_desc)

        # Update site desc if the new one is more detailed
        if len(new_desc) > len(base_desc):
            sites[site_name]["description"] = new_desc
            chunk_data["locations"][p["location_name"]]["sites"] = sites
            self._update_chunk(p["q"], p["r"], chunk_data)

        self._set_player_place(p["player_id"], site_name)
        return f"You enter the {site_name}. {new_desc}"

    def do_leave_site(self, p: Dict[str, Any]) -> str:
        self._set_player_place(p["player_id"], None)
        return "You step out of the site, back to the main location."

    def do_search_location_for_new_site(self, p: Dict[str, Any], chunk_data: Dict[str, Any]) -> str:
        """
        Searching a location might reveal up to 1 new site. We'll call Cohere to see if we find anything new.
        """
        loc_name = p["location_name"]
        loc_obj = chunk_data["locations"].get(loc_name, {})
        sites = loc_obj.get("sites", {})

        if len(sites) >= 20:
            return "You've discovered everything here. No more new discoveries."

        # build system prompt
        system_prompt = f"""
We are searching the location '{loc_name}'.
We have these existing sites (some discovered, some not):
{json.dumps(sites, indent=2)}

We can reveal up to 1 new site. Return JSON in the form:
{{
  "discovery_text": "...",
  "new_site_name": "something" or null,
  "new_site_data": {{
     "description": "...",
     "entities": [],
     "history_of_events": [],
     "discovered": true
  }}
}}
If no new site, set new_site_name=null.
No commentary, only JSON.
"""
        user_prompt = "The player searches around to see if they find a new site."

        try:
            response = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            raw = response.message.content[0].text.strip()
            data = json.loads(raw)
        except:
            data = {
                "discovery_text": "You find nothing special.",
                "new_site_name": None,
                "new_site_data": {}
            }

        disc_text = data.get("discovery_text", "Nothing found.")
        new_name = data.get("new_site_name")
        new_data = data.get("new_site_data", {})

        if new_name:
            sites[new_name] = new_data
            loc_obj["sites"] = sites
            loc_obj.setdefault("history_of_events", [])
            loc_obj["history_of_events"].append(f"Found new site: {new_name}")

            chunk_data["locations"][loc_name] = loc_obj
            self._update_chunk(p["q"], p["r"], chunk_data)
            return f"You search the {loc_name}... {disc_text}"
        else:
            return f"You search around but: {disc_text}"

    def do_search_site(self, p: Dict[str, Any], chunk_data: Dict[str, Any]) -> str:
        """
        Searching inside a site might reveal up to 1 new entity.
        """
        loc_name = p["location_name"]
        site_name = p["place_name"]
        loc_obj = chunk_data["locations"].get(loc_name, {})
        sites = loc_obj.get("sites", {})
        site_data = sites.get(site_name, {})
        if not site_data:
            return f"Something's off; there's no {site_name} here."

        existing_ents = site_data.get("entities", [])
        if len(existing_ents) >= 100:
            return "This site is already crowded. No more new discoveries."

        system_prompt = f"""
We are searching inside site '{site_name}' at location '{loc_name}'.
We have these existing entities:
{json.dumps(existing_ents, indent=2)}

We can discover up to 1 new entity. Return JSON:
{{
  "discovery_text": "...",
  "new_entity": {{
    "name": "...",
    "description": "...",
    "history_of_events": []
  }} or null
}}
No commentary.
"""
        user_prompt = "The player inspects the site thoroughly for items or NPCs."

        try:
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            raw = resp.message.content[0].text.strip()
            data = json.loads(raw)
        except:
            data = {
                "discovery_text": "Nothing new to find.",
                "new_entity": None
            }

        disc_text = data.get("discovery_text", "Nothing discovered.")
        new_ent = data.get("new_entity")

        if new_ent:
            existing_ents.append(new_ent)
            site_data["entities"] = existing_ents
            site_data.setdefault("history_of_events", [])
            site_data["history_of_events"].append(f"New entity discovered: {new_ent['name']}")

            sites[site_name] = site_data
            loc_obj["sites"] = sites
            chunk_data["locations"][loc_name] = loc_obj

            self._update_chunk(p["q"], p["r"], chunk_data)
            return f"You search {site_name}: {disc_text}"
        else:
            return f"You search {site_name}... {disc_text}"

    def handle_site_action(self, p: Dict[str, Any], chunk_data: Dict[str, Any], site_name: str, chosen_action: str) -> str:
        """
        Perform a site-specific custom action. Use RAG + AI to generate a result and
        apply stat changes (money, alignment, hunger, etc.)
        """
        loc_obj = chunk_data["locations"].get(p["location_name"], {})
        site_data = loc_obj.get("sites", {}).get(site_name, {})
        site_description = site_data.get("description", "")

        # Query lore about this specific action
        lore_query = f"What happens when someone {chosen_action} in a {site_name}? Effects?"
        lore_docs = self.rag.query_lore(lore_query)
        lore_context = "\n".join(d["data"]["content"] for d in lore_docs)

        system_prompt = f"""Given the site description, game lore, and chosen action, generate a short result describing what happens.
Mention how it affects the player's stats (like hunger, energy, money, alignment) in the narrative.
Site Description: {site_description}

Relevant Game Lore:
{lore_context}

Chosen Action: {chosen_action}
Current Stats: (We will parse changes ourselves)
"""

        try:
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Describe the outcome of this action in a short story form."}
                ],
                temperature=0.7
            )
            result_text = resp.message.content[0].text.strip()

            # Very simple heuristic
            stat_changes = {
                "money": -2 if "buy" in chosen_action else 0,
                "energy": -5 if "work" in chosen_action or "clean" in chosen_action else 5,
                "hunger": -10 if "eat" in chosen_action or "meal" in chosen_action else 0,
                "alignment": 2 if "help" in chosen_action or "clean" in chosen_action else 0
            }
            self._apply_stat_changes(p["player_id"], stat_changes)
            return result_text
        except Exception as e:
            print(f"Error in handle_site_action: {e}")
            return f"You {chosen_action}, but nothing special seems to happen."

    # ------------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------------
    def _generate_site_description(self, site_name: str, base_description: str) -> str:
        """
        Ask AI to produce an atmospheric site description based on the base description and lore.
        """
        lore_docs = self.rag.query_lore(f"Tell me about {site_name}s in this world. ")
        lore_context = "\n".join(d["data"]["content"] for d in lore_docs)

        system_prompt = f"""Generate a descriptive text (2-3 sentences) about this site.
Base it on the existing site description below and the lore. 
Existing Description: {base_description}

Relevant Lore:
{lore_context}
"""

        try:
            resp = self.ai.chat(
                model="command-r-08-2024",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Please describe this site vividly."}
                ],
                temperature=0.7
            )
            return resp.message.content[0].text.strip()
        except Exception as e:
            print(f"Error generating site desc: {e}")
            return base_description

    def _update_chunk(self, q: int, r: int, new_data: Dict[str, Any]):
        c = self.db.cursor()
        c.execute("UPDATE chunks SET data_json=? WHERE q=? AND r=?", (json.dumps(new_data), q, r))
        self.db.commit()

    def _set_player_place(self, player_id: int, place_name: Optional[str]):
        c = self.db.cursor()
        c.execute("UPDATE player SET place_name=? WHERE player_id=?", (place_name, player_id))
        self.db.commit()

    def _apply_stat_changes(self, player_id: int, changes: Dict[str, int]):
        c = self.db.cursor()
        row = c.execute("SELECT money, energy, hunger, alignment FROM player WHERE player_id=?", (player_id,)).fetchone()
        if row:
            money = max(row["money"] + changes.get("money", 0), 0)
            energy = row["energy"] + changes.get("energy", 0)
            energy = max(min(energy, 100), 0)
            hunger = row["hunger"] + changes.get("hunger", 0)
            hunger = max(min(hunger, 100), 0)
            alignment = row["alignment"] + changes.get("alignment", 0)
            alignment = max(min(alignment, 100), 0)

            c.execute("""
                UPDATE player
                SET money=?, energy=?, hunger=?, alignment=?
                WHERE player_id=?
            """, (money, energy, hunger, alignment, player_id))
            self.db.commit()
