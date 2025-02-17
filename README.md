# AI Hex Adventure Game

An AI-powered text adventure game that uses a hexagonal grid for movement and exploration. The game combines modern AI capabilities with classic text adventure mechanics.

## Features

- **Hex-based World**: Explore a world built on a hexagonal grid, offering six directions of movement
- **AI-Driven Narrative**: Uses Cohere's RAG-enabled AI for dynamic storytelling and world building
- **Persistent World**: Game state is stored in SQLite and ChromaDB for seamless continuation
- **Natural Language Interface**: Interact with the game using natural language commands
- **Rich World Lore**: Ask questions about the world and get AI-generated, contextually relevant answers

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up your Cohere API key:
```bash
export COHERE_API_KEY='your-api-key-here'
```

3. Choose how to run the game:

### Web Version (Recommended)
```bash
cd web
python3 server.py
```
Then open your browser and go to: `http://localhost:8000`

### CLI Version
```bash
python3 game_ui.py
```

## How to Play

### Web Version
1. Open your browser to `http://localhost:8000`
2. Use the text input field to enter commands
3. Click the "Submit" button or press Enter to execute commands
4. The game state and available actions will be shown on the page

### CLI Version
1. Run the game using `python3 game_ui.py`
2. Type commands directly into the terminal
3. Press Enter to execute commands

### Available Commands
1. **Basic Commands**:
   - `look around`: Examine your current location
   - `walk [direction]`: Move in any of six directions (north, northeast, southeast, south, southwest, northwest)
   - `examine [object]`: Look at something specific
   - `ask: [question]`: Ask about the world's lore

2. **Movement**:
   ```
      N
   NW ╱╲ NE
   SW ╲╱ SE
      S
   ```

3. **Special Commands**:
   - Start questions with "ask:" to query the game's lore system
   - Use natural language for actions

## Project Structure

- `game_engine.py`: Core game logic and AI integration
- `game_ui.py`: Streamlit-based user interface
- `test_game.py`: Test cases for game functionality
- `game.db`: SQLite database for game state (created automatically)

## Technical Details

- Uses Cohere's Command-R model for RAG-enabled AI responses
- Combines SQLite for game state with ChromaDB for vector storage
- Implements thread-safe database access
- Provides citation support for lore answers

## Troubleshooting

### Port Already in Use
If you see an error about port 8000 being in use, you have two options:

1. Kill the existing process and restart on the default port:
```bash
pkill -f "python3 server.py"
cd web
export COHERE_API_KEY='your-api-key-here'
python3 server.py
```

2. Use a different port (e.g., 8001):
```bash
# All in one command:
pkill -f "python3 server.py" && export COHERE_API_KEY='your-api-key-here' && python3 server.py --port 8001
```
Then access the game at `http://localhost:8001`

### Check Game State
To check if a player exists in the database:
```bash
sqlite3 game.db "SELECT * FROM player;"
```
If no player exists, the game will automatically create one when you start playing.

### Server Not Starting
1. Make sure you're in the correct directory (`web/`)
2. Verify your Cohere API key is exported
3. Check if the server is already running (use `pkill` command above if needed)

## License

MIT License
