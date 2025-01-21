#!/usr/bin/env python3
"""
lore_rag.py

Simple RAG (Retrieval Augmented Generation) implementation using ChromaDB and Cohere embeddings.
"""

import cohere
import chromadb
import numpy as np
from chromadb.utils import embedding_functions
from cohere_secrets import COHERE_API_KEY

# Create a custom embedding function that returns numpy arrays
class CustomCohereEmbedder:
    def __init__(self, api_key):
        self.client = cohere.Client(api_key)
    
    def __call__(self, input):
        if not input:
            return []
        response = self.client.embed(
            texts=input,
            model="embed-english-v3.0",
            input_type="search_document"
        )
        # Convert to numpy arrays
        return [np.array(embedding, dtype=np.float32) for embedding in response.embeddings]

class LoreRAG:
    """
    A class to store lore text chunks in ChromaDB and retrieve them by semantic similarity
    and retrieve them by semantic similarity for RAG.
    """

    def __init__(self, cohere_api_key: str, collection_name="hex_game_lore"):
        """
        cohere_api_key: your Cohere API key
        collection_name: the name of your Chroma collection (like a "database table" for your lore)
        """
        self.cohere_api_key = cohere_api_key

        # Create an embedding function using Cohere
        self.embedder = CustomCohereEmbedder(api_key=self.cohere_api_key)

        # Initialize the Chroma client (uses local .chromadb directory)
        self.chroma_client = chromadb.Client()

        # Get or create a Chroma collection
        self.collection = self.chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embedder
        )

    def add_lore_text(self, text: str, lore_id: str):
        """
        Splits a big text into multiple overlapping chunks, and adds them
        to the Chroma collection (with doc IDs like `lore_id_chunk0`, etc.).
        """
        print(f"\nStarting to process text of length: {len(text)}")
        
        # Smaller chunks for testing
        chunk_size = 400  # Reduced from 800
        overlap = 50

        # Split by lines first
        print("Splitting text into lines...")
        lines = text.splitlines()
        print(f"Got {len(lines)} lines")
        
        # Group lines into chunks
        chunks = []
        current_chunk = []
        current_size = 0
        
        print("Creating chunks...")
        for line in lines:
            line = line.strip()
            if not line:  # Skip empty lines
                continue
            
            # If adding this line would exceed chunk_size, save current chunk and start new one
            if current_size + len(line) > chunk_size and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            
            current_chunk.append(line)
            current_size += len(line)
        
        # Add the last chunk if it exists
        if current_chunk:
            chunks.append("\n".join(current_chunk))

        print(f"Created {len(chunks)} chunks")

        # Insert chunks with progress tracking
        for i, chunk in enumerate(chunks):
            try:
                print(f"\nProcessing chunk {i+1}/{len(chunks)}")
                print(f"Chunk size: {len(chunk)} characters")
                print(f"First 100 chars: {chunk[:100]}...")
                
                doc_id = f"{lore_id}_chunk{i}"
                self.collection.add(
                    documents=[chunk],
                    metadatas=[{"title": lore_id}],
                    ids=[doc_id]
                )
                print(f"Successfully added chunk {i+1}")
            except Exception as e:
                print(f"Error processing chunk {i+1}: {str(e)}")
                raise

    def query_lore(self, query: str, top_k: int = 3):
        """
        Given a user query, retrieve the top_k most relevant chunks from the collection.
        Returns a list of documents, each in a format suitable for co.chat(documents=...).
        """
        # Do the search
        results = self.collection.query(
            query_texts=[query],
            n_results=top_k
        )

        docs_to_return = []
        # We'll iterate over the top hits for the first (and only) query
        for i, doc_text in enumerate(results["documents"][0]):
            snippet_text = doc_text.strip()
            meta = results["metadatas"][0][i]  # e.g. {"title": "some_lore_id"}
            doc_id = results["ids"][0][i]

            # We'll pass them to co.chat in the "data" field
            # We can also store e.g. snippet=snippet_text, title, ...
            docs_to_return.append({
                "id": doc_id,
                "data": {
                    "content": snippet_text,
                    "title": meta.get("title", "")
                }
            })
        return docs_to_return

if __name__ == "__main__":
    """
    Example usage:
    1) Put your big "lore text" inside `big_lore_text`.
    2) This script will chunk it up and store it in Chroma.
    3) Then you can run `python lore_rag.py` once to build the DB.
    """
    from cohere_secrets import COHERE_API_KEY
    import time
    
    # Let's start with a small test text
    test_lore = """
    # Core Game Mechanics
    The Hex World is divided into hexagonal chunks. Players can:
    - Move between connected locations
    - Search for hidden sites
    - Rest to recover health
    """

    print("Initializing RAG system...")
    rag = LoreRAG(COHERE_API_KEY, collection_name="hex_game_lore")

    # Clear the collection for a fresh start
    print("Clearing existing collection...")
    try:
        rag.chroma_client.delete_collection(name="hex_game_lore")
        rag.collection = rag.chroma_client.get_or_create_collection(
            name="hex_game_lore",
            embedding_function=rag.embedder
        )
        print("Collection cleared successfully")
    except Exception as e:
        print(f"Note: No existing collection to clear ({e})")

    # First try with test text
    print("\nTesting with small text sample...")
    start_time = time.time()
    rag.add_lore_text(test_lore, "test_lore")
    print(f"Small test completed in {time.time() - start_time:.2f} seconds")
    
    # Test a query
    print("\nTesting query...")
    results = rag.query_lore("What can players do in the game?")
    print("Query results:", results)

    print("\nTest successful! Now adding full lore...")
    
    # Now add the full lore
    big_lore_text = r"""
    # World Overview
    The Hex World is a vast, mysterious realm where each hexagonal region tells its own story. The world operates on ancient magic that responds to those who take time to understand its secrets.

    # Core Mechanics
    - Movement: The world is divided into hexagonal chunks, allowing travel in six directions
    - Discovery: Each location contains hidden sites that can be uncovered through careful exploration
    - Interaction: Players can rest to recover health, search locations, and interact with various sites

    # Starting Area (0,0)
    The central village serves as the heart of this world. Known for its:
    - Town Square: A bustling center where travelers gather
    - Local Inn: Offers rest and tales from fellow adventurers
    - Hidden passages: Rumors speak of secret tunnels beneath the village

    # Location Types
    1. Common Locations:
       - Villages: Safe havens with various services and information
       - Forests: Dense woodlands hiding ancient secrets
       - Mountains: Treacherous peaks with valuable resources
       - Caves: Natural formations that may lead to underground networks
       - Ruins: Remnants of ancient civilizations

    2. Special Sites:
       - Inns: Places to rest and gather information
       - Shops: Trading posts for supplies and equipment
       - Temples: Sacred places with unique powers
       - Libraries: Sources of knowledge and history
       - Workshops: Places where items can be crafted

    # Game Rules
    - Health: Players must maintain their health through rest
    - Exploration: Each location can be searched for hidden sites
    - Navigation: Players can move between connected locations
    - Discovery: Sites start hidden and must be discovered through exploration

    # World Lore
    The Hex World was created by ancient beings who left behind powerful artifacts and knowledge. They designed the world's hexagonal structure to maintain magical balance. Each chunk of land holds its own mysteries:
    - Some locations remain hidden until discovered
    - Each site has its own history and significance
    - The world remembers player actions through the history_of_events system
    - Magical forces guide travelers through connected paths

    # Special Features
    - Dynamic Discovery: New sites can be found through exploration
    - Connected Paths: Locations link naturally to their neighbors
    - Hidden Secrets: Many locations contain undiscovered sites
    - Living History: The world records and remembers significant events
    """

    start_time = time.time()
    rag.add_lore_text(big_lore_text, "hex_game_lore")
    print(f"Full lore added in {time.time() - start_time:.2f} seconds")

    print("Successfully added all lore to ChromaDB!")
