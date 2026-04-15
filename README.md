# Risk Monitor

Système interne de détection et de scoring des utilisateurs à risque dans une marketplace d'abonnements partagés, basé sur l'analyse de données et l'aide à la décision via IA.

## Objectif du projet

Ce projet vise à détecter les utilisateurs à risque sur une plateforme d'abonnement (type marketplace ou SaaS), en se basant sur leurs comportements :

- Paiements
- Abonnements
- Interactions (plaintes)

Dans ce projet, un "subscriber" correspond à un "membership", c'est-à-dire une relation entre un utilisateur et un abonnement.

Ainsi, le scoring est réalisé au niveau `(user_id, subscription_id)` et non au niveau global utilisateur.

---

## Étapes du projet

### Épreuve 1 — Exploration et Data Cleaning

Avant toute transformation, une phase d'exploration approfondie a été réalisée pour comprendre et nettoyer les données sources.

**Objectifs :**
- Analyser chaque table et comprendre son rôle métier
- Détecter les incohérences (valeurs manquantes, formats hétérogènes, doublons)
- Comprendre les relations entre tables (users ↔ payments ↔ subscriptions)
- Formuler les hypothèses sur les données non documentées

Voir : [docs/tables.md](docs/tables.md) — description des tables + anomalies détectées  
Voir : [notebooks/exploration&clean_data.ipynb](notebooks/exploration&clean_data.ipynb) — démarche complète

---

### Épreuve 2 — Scoring de risque

Un score de risque (0–100) est calculé pour chaque membership à partir de 5 dimensions :

| Dimension | Exemples de signaux |
|-----------|-------------------|
| Paiements | taux d'échec, code fraude Stripe, litiges |
| Comportement | motif de départ, ancienneté |
| Plaintes | plaintes reçues, plaintes déposées |
| Contexte abonnement | taux d'échec global de l'abonnement |
| Contexte owner | taux d'échec et fraude du propriétaire |

| Score | Niveau | Action |
|-------|--------|--------|
| 0–39 | Faible | Surveillance normale |
| 40–59 | Modéré | Mettre en surveillance |
| 60–79 | Élevé | Contacter l'utilisateur |
| 80–100 | Critique | Bloquer immédiatement |

Voir : [docs/scoring.md](docs/scoring.md) — features, pondérations, edge cases, segmentation

---

### Épreuve 3 — Interface opérationnelle (Streamlit)

Dashboard interactif permettant à un opérateur de :
- Voir la liste des memberships triés par score de risque
- Filtrer par niveau, segment, score
- Consulter le détail d'un subscriber (paiements, plaintes, flags)
- Appliquer une action : **Bloquer**, **Surveiller**, **Réinitialiser**
- Les actions **persistent** entre les sessions (sauvegardées dans `output/actions.csv`)

---

### Épreuve 4 — Agent IA (Ollama llama3.2:3b)

L'agent remplit deux rôles par appel :

**Analyste** — génère un résumé structuré du comportement observé, identifie les signaux d'alerte et compare le subscriber aux moyennes de la base.

**Décideur** — propose une action (ignorer / surveiller / avertir / bloquer) avec un niveau de confiance et une justification.

L'opérateur peut **accepter** ou **rejeter** la recommandation. Les rejets sont loggés dans `output/rejected_decisions.csv` pour analyse ultérieure.

**Pourquoi Ollama (modèle local) ?**
- Aucun coût — pas d'API key, pas de facturation
- Privacy — les données subscribers ne quittent pas la machine
- Fallback automatique — si Ollama est indisponible, l'agent bascule sur des règles déterministes qui produisent la même structure de réponse

Voir : [prompts/](prompts/) — prompts versionnés avec explication des choix

---

## Choix techniques

| Choix | Justification |
|-------|---------------|
| **Scoring par membership** | Un même user peut être risqué dans un abonnement et normal dans un autre — le contexte owner change tout |
| **Score additif (pas de règles critiques)** | Évite les faux positifs sur un signal isolé — un subscriber frauduleux cumule plusieurs signaux |
| **Segmentation NOUVEAU / ACTIF / ANCIEN** | Un membre de 10 jours ne peut pas être jugé comme un membre de 2 ans — ajustements différenciés |
| **Ollama local** | Gratuit, privacy, pas de dépendance cloud |
| **Fallback rule-based** | L'interface reste utilisable même si le modèle IA est indisponible |
| **Persistance CSV** | Simple, lisible, pas de dépendance base de données pour ce volume |

---

## Architecture

```
Risk-Monitor/
│
├── data/
│   ├── risk_monitor_dataset.sqlite   # Données sources
│   └── *_clean.csv                   # Générés par le notebook
│
├── notebooks/
│   └── exploration&clean_data.ipynb  # Exploration + nettoyage
│
├── src/
│   ├── scoring.py                    # Pipeline de scoring
│   └── agent.py                      # Agent IA (Ollama)
│
├── app/
│   └── app.py                        # Interface Streamlit
│
├── output/
│   ├── risk_scores.csv               # Scores (généré par scoring.py)
│   ├── actions.csv                   # Actions opérateur (persistées)
│   ├── ai_logs.csv                   # Logs des appels IA
│   └── rejected_decisions.csv        # Décisions IA rejetées
│
├── docs/
│   ├── tables.md                     # Tables + anomalies détectées
│   └── scoring.md                    # Système de scoring détaillé
│
└── prompts/                          # Prompts IA versionnés
```

---

## Lancer le projet

```bash
# 1. Installer les dépendances
pip install -r requirements.txt

# 2. Générer les scores (après avoir exécuté le notebook de nettoyage)
python src/scoring.py

# 3. (Optionnel) Télécharger le modèle IA local
ollama pull llama3.2:3b

# 4. Lancer l'interface
streamlit run app/app.py
```

> Le notebook de nettoyage doit être exécuté en premier pour générer les CSV dans `data/`.

---

## Hypothèses sur les données

Aucun dictionnaire de données n'était fourni. Les hypothèses suivantes ont été déduites par exploration :

| Hypothèse | Justification |
|-----------|---------------|
| `status` = 99 ou -1 dans `users` → compte anormal | Valeurs isolées hors codes normaux, associées à des comportements suspects |
| `success` et `succeeded` → même statut | Doublons sémantiques identifiés par comparaison des montants et dates |
| `left_at` vide → membership actif | Cohérent avec les lignes où le statut est "actif" |
| Timestamps UTC hétérogènes → normalisés en UTC | Plusieurs fuseaux détectés dans les colonnes de dates |
| `reporter_id` = `target_id` → auto-plainte invalide | Supprimé (aberration métier impossible en production) |

---

## Limites connues

| Limite | Impact |
|--------|--------|
| Scoring basé sur des règles expertes | Les pondérations sont arbitraires, pas calibrées sur des données labellisées |
| Qualité de la réponse IA variable | llama3.2:3b peut produire des JSON malformés — le fallback rule-based compense |
| Pas de temporalité dans le scoring | Un taux d'échec récent n'est pas distingué d'un taux d'échec ancien |
| Actions opérateur non horodatées | L'historique des changements n'est pas tracé, seulement l'état final |
| Données statiques | Pas de mise à jour en temps réel — relancer `scoring.py` pour actualiser |

---

## Pistes d'évolution

- **Modèle supervisé** : avec des labels fraude/non-fraude, remplacer les règles par un XGBoost entraîné sur l'historique
- **Détection de patterns collectifs** : identifier des groupes de subscribers qui rejoignent le même owner à quelques minutes d'intervalle
- **Horodatage des actions** : logger chaque décision opérateur avec timestamp
- **Mise à jour incrémentale** : recalculer uniquement les memberships modifiés
- **Déploiement** : containeriser avec Docker, déployer sur Render ou Railway
