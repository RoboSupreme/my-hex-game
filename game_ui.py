"""
game_ui.py

A CLI interface to the HexGameEngine. 
We either pick an action from the enumerated list or type "ask: question".
"""
import sys
from hex_game_engine import HexGameEngine

def main():
    engine = HexGameEngine(db_path="game.db")  # or your path

    print("Welcome to the Hex Adventure World!")
    while True:
        # get possible actions
        actions = engine.get_possible_actions()
        p = engine.get_player_state()
        
        print("\nYou are", end=" ")
        if p["place_name"]:
            print(f"inside the {p['place_name']} in {p['location_name']}")
        else:
            print(f"in {p['location_name']}")
            
        print("\nPossible Actions:")
        
        # Separate actions into categories
        basic_actions = []
        movement_actions = []
        site_actions = []
        
        for action in actions:
            if action in ["rest", "check inventory", "search location"]:
                basic_actions.append(action)
            elif action.startswith("enter "):
                site_actions.append(action)
            elif action.startswith("exit:") or (not action.startswith("enter ") and not action in ["rest", "check inventory", "search location", "leave site", "search site"]):
                movement_actions.append(action)
            else:
                basic_actions.append(action)
        
        # Display actions with categories
        action_number = 1
        displayed_actions = []
        
        if basic_actions:
            print("\nBasic Actions:")
            for action in basic_actions:
                print(f"{action_number}. {action}")
                displayed_actions.append(action)
                action_number += 1
                
        if movement_actions:
            print("\nMovement Options:")
            for action in movement_actions:
                print(f"{action_number}. {action}")
                displayed_actions.append(action)
                action_number += 1
                
        if site_actions:
            print("\nAvailable Sites:")
            for action in site_actions:
                site_name = action.replace("enter ", "")
                print(f"{action_number}. enter {site_name}")
                displayed_actions.append(action)
                action_number += 1
                
        print("\n(Or type ask: <question> to ask the AI about the world)")
        print("(Or 'quit'/'exit' to stop)")

        cmd = input("> ").strip()
        if cmd.lower() in ["quit", "exit"]:
            print("Goodbye!")
            sys.exit(0)

        if cmd.lower().startswith("ask:"):
            question = cmd[4:].strip()
            ans = engine.answer_question(question)
            print("\n[AI Answer]:\n", ans)
        else:
            # parse numeric choice
            try:
                idx = int(cmd)
                if 1 <= idx <= len(displayed_actions):
                    chosen = displayed_actions[idx - 1]
                    result = engine.apply_action(chosen)
                    print("\n[Result]:\n", result)
                else:
                    print("Invalid choice, try again.")
            except ValueError:
                print("Unknown command, please pick a number or 'ask: ...' or 'quit'.")

if __name__ == "__main__":
    main()
