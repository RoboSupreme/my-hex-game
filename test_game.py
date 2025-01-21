#!/usr/bin/env python3
"""
test_game.py

Runs a minimal test on the engine. 
Useful if you want to see debug info without running the full CLI.
"""

from hex_game_engine import HexGameEngine

def test_game():
    engine = HexGameEngine(db_path="game.db")

    def show_stats():
        p = engine.get_player_state()
        print("\nCurrent Stats:")
        print(f"Combat: Attack {p['attack']}, Defense {p['defense']}, Agility {p['agility']}")
        print(f"Resources: Money {p['money']}, Health {p['health']}")
        print(f"Needs: Hunger {p['hunger']}, Energy {p['energy']}, Thirst {p['thirst']}")
        print(f"Alignment: {p['alignment']}/100")
        ### TIME FEATURE ADDED ###
        # Convert month to string if you like, or just show numeric
        month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        month_str = month_names[(p['time_month']-1) % 12]
        print(f"Time: Year {p['time_year']} AC, {month_str} {p['time_day']}th, {p['time_hour']}:00")
        print(f"Location: {p['location_name']} at ({p['q']}, {p['r']})")
        if p['place_name']:
            print(f"Inside: {p['place_name']}")

    print("Starting test...")
    show_stats()

    print("\nApplying action: rest")
    outcome = engine.apply_action("rest")
    print("Outcome =>", outcome)
    show_stats()

    print("\nApplying action: check inventory")
    outcome = engine.apply_action("check inventory")
    print("Outcome =>", outcome)
    show_stats()

if __name__ == "__main__":
    test_game()
