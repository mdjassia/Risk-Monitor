def build_prompt(user_data, avg_score, avg_failure):
    return f"""
Tu es un expert en détection de fraude.

Tu dois analyser un utilisateur ET proposer une décision.

OBJECTIFS :

1. Résumer le comportement utilisateur
2. Identifier les signaux de risque
3. Comparer avec la moyenne globale
4. Donner UNE recommandation :
   - SURVEILLER
   - AVERTIR
   - BLOQUER
   - IGNORER

FORMAT DE RÉPONSE (JSON STRICT) :

{{
  "summary": "...",
  "signals": ["...", "..."],
  "comparison": "...",
  "recommendation": "...",
  "confidence": 0-100,
  "justification": "..."
}}

DONNÉES UTILISATEUR :
{user_data}

MOYENNE :
score moyen: {avg_score}
failure moyen: {avg_failure}
"""