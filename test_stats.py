#!/usr/bin/env python3
"""
Test script for the new player stats and site actions.
"""

from hex_game_engine import HexGameEngine

def test_stats_and_actions():
    # Initialize game engine
    game = HexGameEngine()
    
    # Helper function to display player stats
    def show_stats():
        p = game.get_player_state()
        print("\nCurrent Stats:")
        print(f"Combat: Attack {p['attack']}, Defense {p['defense']}, Agility {p['agility']}")
        print(f"Resources: Money {p['money']}, Health {p['health']}")
        print(f"Needs: Hunger {p['hunger']}, Energy {p['energy']}, Thirst {p['thirst']}")
        print(f"Alignment: {p['alignment']}/100")
        print(f"Location: {p['location_name']} at ({p['q']}, {p['r']})")
        if p['place_name']:
            print(f"Inside: {p['place_name']}")
    
    # Test sequence
    print("Starting test sequence...")
    show_stats()
    
    # 1. Search for an inn
    print("\n1. Searching for inn...")
    result = game.do_search_location()
    print(result)
    
    # 2. Enter the inn if found
    print("\n2. Available actions:")
    actions = game.get_possible_actions()
    print(actions)
    
    # Try to enter inn if it exists
    inn_action = next((a for a in actions if a.startswith("enter") and "inn" in a), None)
    if inn_action:
        print("\nEntering inn...")
        result = game.apply_action(inn_action)
        print(result)
        
        # 3. Show inn actions
        print("\n3. Available inn actions:")
        inn_actions = game.get_possible_actions()
        print(inn_actions)
        
        # 4. Try some inn actions
        print("\n4. Testing inn actions...")
        
        # Buy a meal
        print("\nBuying a meal...")
        result = game.apply_action("buy meal")
        print(result)
        show_stats()
        
        # Rent a room
        print("\nRenting a room...")
        result = game.apply_action("rent room")
        print(result)
        show_stats()
        
        # Leave inn
        print("\nLeaving inn...")
        result = game.apply_action("leave site")
        print(result)
    else:
        print("No inn found. Try running the test again!")
    
    # 5. Ask about our current state
    print("\n5. Asking about our state...")
    answer = game.answer_question("How am I doing? Tell me about my current state.")
    print("\nSpirit's Answer:", answer)

if __name__ == "__main__":
    test_stats_and_actions()
