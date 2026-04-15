#!/bin/bash

echo " Starting Risk Monitor..."

# 1. Attendre Ollama
echo " Waiting for Ollama..."
until curl -s http://ollama:11434 > /dev/null; do
  sleep 2
done

echo " Ollama is ready"

# 2. Télécharger modèle si besoin
echo " Pulling Mistral model..."
ollama pull mistral || true

# 3. Générer dataset risk scoring
echo " Running scoring pipeline..."
python src/scoring.py || true

# 4. Lancer Streamlit
echo " Starting Streamlit..."
streamlit run app/app.py --server.port=8501 --server.address=0.0.0.0