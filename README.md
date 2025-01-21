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

3. Run the game:
```bash
streamlit run game_ui.py
```

## How to Play

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

## License

MIT License
