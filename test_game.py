"""
test_game.py

Runs a minimal test on the engine. 
Useful if you want to see debug info without running the full CLI.
"""

from hex_game_engine import HexGameEngine

def test_game():
    engine = HexGameEngine(db_path="game.db")

    print("=== Checking possible actions at start ===")
    actions = engine.get_possible_actions()
    print("Actions =>", actions)

    if actions:
        # pick the first action and apply
        print("Applying action:", actions[0])
        outcome = engine.apply_action(actions[0])
        print("Outcome =>", outcome)

    # test question
    ans = engine.answer_question("What is the legend of the Eastern mountains?")
    print("Question =>", ans)


if __name__ == "__main__":
    test_game()
