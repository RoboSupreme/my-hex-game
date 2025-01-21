#!/usr/bin/env python3
"""
Test script for the RAG-enhanced question answering system.
"""

from hex_game_engine import HexGameEngine

def test_questions():
    # Initialize game engine
    game = HexGameEngine()
    
    # Test questions about game mechanics and lore
    test_questions = [
        "What is the Hex World?",
        "What can I do in this game?",
        "Tell me about the special sites I might find.",
        "How does health work in this game?",
        "What's the significance of the starting village?",
    ]
    
    print("Testing RAG-enhanced question answering...\n")
    for question in test_questions:
        print(f"Q: {question}")
        answer = game.answer_question(question)
        print(f"A: {answer}\n")

if __name__ == "__main__":
    test_questions()
