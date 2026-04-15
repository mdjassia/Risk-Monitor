# Prompt v1 — Analyste & Décideur

## Rôles couverts

- **Analyste** : résumé factuel du comportement, signaux d'alerte, comparaison à la base
- **Décideur** : recommandation d'action + niveau de confiance + justification

## Modèle utilisé

`llama3.2:3b` via Ollama (local) — choix justifié dans le README.

## Prompt système

```
Tu es un expert en detection de fraude. Analyse les donnees et reponds en JSON.

SIGNAUX (seulement si vrais) :
- Si echec_paiement > 40% : "Taux echec paiement a X%"
- Si Fraude_Stripe=OUI : "Code fraude Stripe detecte"
- Si Litiges > 0 : "X litige(s) enregistre(s)"
- Si Plaintes_recues > 1 : "X plaintes recues"
- Si Sub_echec > 40% : "Abonnement risque, echec X%"
- Si Owner_fraude=OUI : "Owner avec historique fraude"

DECISION :
- ignorer : score < 40 et 0 signal
- surveiller : score 40-60 ou 1 signal faible
- avertir : score 60-80 ou 2+ signaux
- bloquer : Fraude_Stripe=OUI ou score > 80

FORMAT JSON :
{"analyste":{"behavior_summary":"...","alert_signals":[...],"vs_population":"..."},"decideur":{"action":"...","confidence":0.0,"justification":"..."}}
```

## Choix de conception

| Choix | Raison |
|-------|--------|
| Prompt en anglais sans accents | Les LLMs locaux gèrent mieux les prompts ASCII — moins d'erreurs de tokenization |
| `"format": "json"` dans la requête Ollama | Force le modèle à produire du JSON valide — élimine les erreurs de parse |
| `num_predict: 350` | Limite la longueur de la réponse pour éviter les coupures de JSON |
| Signaux explicitement listés avec seuils | Évite les hallucinations — le modèle ne peut signaler que des faits présents dans les données |
| 4 niveaux d'action (ignorer/surveiller/avertir/bloquer) | Granularité plus fine que 3 boutons — "avertir" et "surveiller" mappent tous deux sur le bouton "Surveiller" dans l'interface |
| Fallback rule-based | Si le modèle timeout ou génère du JSON invalide, l'opérateur reçoit quand même une recommandation basée sur le score calculé |

## Mapping actions IA → boutons interface

| Recommandation IA | Bouton appliqué | Action enregistrée |
|-------------------|-----------------|-------------------|
| `ignorer` | Réinitialiser | `clear` |
| `surveiller` | Surveiller | `monitored` |
| `avertir` | Surveiller | `monitored` |
| `bloquer` | Bloquer | `blocked` |

## Gestion des limites

| Risque | Mitigation |
|--------|-----------|
| JSON malformé | `format: json` + extraction regex en fallback |
| Timeout modèle | Fallback rule-based automatique, loggé dans `ai_logs.csv` |
| Hallucination de signaux | Signaux restreints à une liste fixe avec seuils numériques |
| Ollama indisponible | Fallback rule-based, même structure de réponse |

## Itération v1 → améliorations possibles

- Passer à un modèle plus grand (mistral 7B) pour une meilleure qualité de justification
- Ajouter l'historique des dernières décisions dans le contexte
- Utiliser few-shot examples pour améliorer la cohérence du JSON
