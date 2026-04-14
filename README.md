#  Risk Monitor 

Système interne de détection et de scoring des utilisateurs à risque dans une marketplace d’abonnements partagés, basé sur l’analyse de données et l’aide à la décision via IA.

##  Objectif du projet

Ce projet vise à détecter les utilisateurs à risque sur une plateforme d’abonnement (type marketplace ou SaaS), en se basant sur leurs comportements :

-  Paiements  
-  Abonnements  
-  Interactions (plaintes)  

Dans ce projet, un "subscriber" correspond à un "membership", c’est-à-dire une relation entre un utilisateur et un abonnement.

Ainsi, le scoring est réalisé au niveau (user_id, subscription_id) et non au niveau global utilisateur.

##  1. Exploration et Data Cleaning

Avant toute étape de transformation, une phase d’exploration approfondie a été réalisée afin de maîtriser la structure et la qualité des données sources. 

**Cette étape avait pour objectifs :**
* Analyser chaque table individuellement afin de comprendre son rôle métier dans la plateforme.
* Étudier les colonnes pour identifier leur signification et leur type (numérique, catégoriel, temporel, etc.)
* Détecter les incohérences telles que :
    * valeurs manquantes
    * formats de données hétérogènes
    * doublons ou anomalies
* Comprendre les relations entre les tables (ex: users ↔ payments ↔ subscriptions).
* Identifier les premières hypothèses métier, notamment autour du comportement utilisateur et du risque.

---

### 1.1 Description des tables et identification des problemes
voir :  voir : [docs/tables.md](docs/tables.md) et [notebooks/exploration&clean_data.ipynb](notebooks/exploration&clean_data.ipynb)

### 1.2 nettoyage de données 

voir :  [notebooks/exploration&clean_data.ipynb](notebooks/exploration&clean_data.ipynb)

## 2. Feature Engineering pour le Risk Scoring

L’objectif est de construire un **score de risque par subscriber** (chaque ligne = un utilisateur dans un abonnement donné).  
Les features sont calculées à partir des tables nettoyées.

### 2.1 Features par membership (user + subscription)

| Feature | Description | Source | Utilisation |
|---------|-------------|--------|--------------|
| `nb_tentatives` | Nombre de tentatives de paiement de l’utilisateur pour cet abonnement | `payments` | Base du calcul du taux d’échec |
| `taux_echec` | Ratio échecs / tentatives (0 à 1) | `payments` | Pénalité si > 20% ou > 50% |
| `stripe_fraud_flag` | True si code Stripe = `stolen_card` ou `fraudulent` | `payments` | Score = 100 immédiat |
| `disputed` | Nombre de paiements contestés (litiges) | `payments` | +25 points par litige |
| `devises_diff` | Nombre de devises différentes utilisées | `payments` | Indicateur de card‑testing |
| `banni_fraude` | True si l’utilisateur a été banni de cet abonnement pour fraude | `memberships` | Score = 100 immédiat |
| `duree_jours` | Âge du membership (depuis `joined_at`) | `memberships` | Réduction du score pour les nouveaux |
| `est_actif` | True si `left_at` est vide | `memberships` | Permet de filtrer |
| `plaintes_recues` | Nombre de plaintes déposées contre l’utilisateur sur cet abonnement | `complaints` | Pénalité progressive (10 pts par plainte) |
| `user_anomaly` | True si le compte utilisateur a un status anormal (99, -1) | `users` | Score = 100 immédiat |
| `inactive` | True si `last_seen` > 90 jours | `users` | Réduction du score |
| `sub_taux_echec` | Taux d’échec global de l’abonnement (tous membres) | `payments` | Pénalité si > 40% |

### 2.2 Pondération et calcul du score (0 à 100)

Le score est calculé par la fonction `compute_risk_score(row)`.

**Règles critiques (score = 100)** :
- `stripe_fraud_flag` = True
- `banni_fraude` = True
- `sub_has_fraud` = True (fraude sur l’abonnement)
- `user_anomaly` = True

**Pénalités normales** :
- Taux d’échec > 50% → +40 points
- Taux d’échec entre 20% et 50% → +20 points
- Un seul paiement échoué (pas d’autre tentative) → +15 points
- `disputed` > 0 → +25 points
- `plaintes_recues` ≥ 3 → +30 points ; entre 1 et 2 → +15 points
- `sub_taux_echec` > 40% → +20 points

**Ajustements** :
- Nouveau subscriber (< 2 tentatives et < 30 jours) → -20 points
- Utilisateur inactif (`inactive` = True) → -15 points

**Borne finale** : `min(100, max(0, score))`

### 2.3 Edge cases gérés

| Cas | Traitement |
|-----|-------------|
| Aucun paiement | `nb_tentatives` = 0 → `taux_echec` = 0, aucune pénalité |
| Un seul paiement réussi | Score bas (0 sauf s’il y a d’autres signaux) |
| Nouveau subscriber (< 30 jours, < 2 paiements) | Score réduit de 20 points |
| Compte inactif (> 90 jours) | Score réduit de 15 points |
| Données manquantes | `fillna(0)` pour les numériques, `fillna(False)` pour les booléens |

### 2.4 Interprétation du score

| Score | Niveau | Action recommandée |
|-------|--------|--------------------|
| 0 – 20 |  Faible | Surveillance normale |
| 21 – 50 |  Modéré | Mettre en surveillance |
| 51 – 80 |  Élevé | Contacter l’utilisateur / owner |
| 81 – 100 |  Critique | Bloquer immédiatement |

---

### 2.5 Résultats du scoring

Le script `src/scoring.py` produit un fichier CSV `risk_scores.csv` contenant une ligne par membership avec les colonnes :
- `user_id`, `subscription_id`
- `risk_score`
- `nb_tentatives`, `taux_echec`, `plaintes_recues`, `disputed`, `duree_jours`, `est_actif`


 un même utilisateur peut avoir des scores très différents selon l’abonnement. C’est l’avantage du scoring par membership.

