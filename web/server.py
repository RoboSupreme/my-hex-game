# server.py
import sys, os, json
from flask import Flask, request, jsonify, send_from_directory, current_app

# Update Python path if needed...
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
sys.path.insert(0, parent_dir)

from game_engine import GameEngine

app = Flask(__name__, static_folder="static", static_url_path="/static")
engine = GameEngine(db_path="game.db")

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/get_player_state", methods=["GET"])
def get_player_state():
    try:
        p = engine.get_player_state()

        # Convert month numeric -> string if you wish
        month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        month_str = month_names[(p['time_month']-1) % 12]

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
            "place_name": p["place_name"],

            ### TIME FEATURE ADDED ###
            "time_year": p["time_year"],
            "time_month_str": month_str,
            "time_day": p["time_day"],
            "time_hour": p["time_hour"]
        })
    except Exception as e:
        current_app.logger.exception("Error in get_player_state")
        return jsonify({"error": str(e)}), 500

@app.route("/api/get_actions", methods=["GET"])
def get_actions():
    try:
        # Now returns a dictionary of 3 lists directly
        actions_dict = engine.get_possible_actions()
        return jsonify(actions_dict)
    except Exception as e:
        current_app.logger.exception("Error in get_actions")
        return jsonify({"error": str(e)}), 500

@app.route("/api/apply_action", methods=["POST"])
def apply_action():
    try:
        data = request.json
        chosen_action = data.get("action", "")
        result = engine.apply_action(chosen_action)
        return jsonify({"result": result})
    except Exception as e:
        current_app.logger.exception("Error in apply_action")
        return jsonify({"error": str(e)}), 500

@app.route("/api/ask_question", methods=["POST"])
def ask_question():
    try:
        data = request.json
        question = data.get("question", "")
        answer = engine.answer_question(question)
        return jsonify({"answer": answer})
    except Exception as e:
        current_app.logger.exception("Error in ask_question")
        return jsonify({"error": str(e)}), 500

@app.route("/api/map_data", methods=["GET"])
def map_data():
    try:
        cursor = engine.db.cursor()
        rows = cursor.execute("SELECT q, r, data_json FROM chunks").fetchall()
        results = []
        for row in rows:
            try:
                q = row[0]  # Using index instead of key
                r = row[1]
                chunk_json = json.loads(row[2])
                results.append({
                    "q": q,
                    "r": r,
                    "chunk_data": chunk_json
                })
            except Exception as e:
                current_app.logger.error(f"Error processing row {row}: {e}")
        return jsonify(results)
    except Exception as e:
        current_app.logger.error(f"Error in map_data: {e}")
        return jsonify([]), 500

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000, help='Port to run the server on')
    args = parser.parse_args()
    app.run(debug=True, host="0.0.0.0", port=args.port)
