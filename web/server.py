# server.py
import sys, os
from flask import Flask, request, jsonify, send_from_directory

# Update Python path if needed to ensure your new modules are importable:
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.insert(0, parent_dir)

# Import your game engine
from hex_game_engine import HexGameEngine  # Updated import statement

app = Flask(__name__, static_folder="static", static_url_path="/static")
engine = HexGameEngine(db_path="game.db")  # Updated class name

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/get_player_state", methods=["GET"])
def get_player_state():
    p = engine.get_player_state()
    return jsonify({
        "health": p["health"],
        "money": p["money"],
        "hunger": p["hunger"],
        "energy": p["energy"],
        "thirst": p["thirst"],
        "alignment": p["alignment"],
        "attack": p["attack"],
        "defense": p["defense"],
        "agility": p["agility"],
        "location_name": p["location_name"],
        "q": p["q"],
        "r": p["r"],
        "place_name": p["place_name"]
    })

@app.route("/api/get_actions", methods=["GET"])
def get_actions():
    actions = engine.get_possible_actions()
    return jsonify({"actions": actions})

@app.route("/api/apply_action", methods=["POST"])
def apply_action():
    data = request.json
    chosen_action = data.get("action", "")
    result = engine.apply_action(chosen_action)
    return jsonify({"result": result})

@app.route("/api/ask_question", methods=["POST"])
def ask_question():
    data = request.json
    question = data.get("question", "")
    answer = engine.answer_question(question)
    return jsonify({"answer": answer})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8000)
