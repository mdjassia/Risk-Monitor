
### 2.1 Features par membership (user + subscription)

| Feature (nom dans le code) | Description | Source | Utilisation |
|---------|-------------|--------|--------------|
| `payment_count` | Nombre de tentatives de paiement pour cet abonnement | `payments` | Seuil minimal pour évaluer le taux d'échec |
| `payment_failure_rate` | Ratio échecs / tentatives (0 à 1) | `payments` | Pénalité progressive selon le taux |
| `has_stripe_fraud_code` | True si code Stripe = `stolen_card` ou `fraudulent` | `payments` | +25 points |
| `dispute_count` | Nombre de paiements contestés (litiges) | `payments` | +10 points par litige (max +20) |
| `currency_diversity` | Nombre de devises différentes utilisées | `payments` | +15 points si > 2 devises (card-testing) |
| `left_for_fraud` | True si le membership s'est terminé pour motif `fraud` | `memberships` | +30 points |
| `left_for_payment_failed` | True si le membership s'est terminé pour motif `payment_failed` | `memberships` | +15 points |
| `membership_days` | Âge du membership en jours (depuis `joined_at`) | `memberships` | Utilisé pour la segmentation |
| `is_active` | True si `left_at` est vide | `memberships` | Utilisé pour la segmentation |
| `complaints_received` | Plaintes déposées contre l'utilisateur sur cet abonnement | `complaints` | +8 pts si >= 1, +20 pts si >= 2 |
| `complaints_filed` | Plaintes déposées par l'utilisateur | `complaints` | +12 pts si >= 2 (comportement litigieux) |
| `is_user_inactive` | True si `last_seen` > 90 jours | `users` | Utilisé dans la segmentation DORMANT |
| `sub_payment_failure_rate` | Taux d'échec global de l'abonnement (tous membres) | `payments` | +8 pts si >= 30%, +15 pts si >= 50% |
| `sub_has_fraud_code` | True si un code Stripe frauduleux existe dans l'abonnement | `payments` | +12 points |

| **Features du propriétaire (owner)** | | | |
|---------|-------------|--------|--------------|
| `owner_payment_failure_rate` | Taux d'échec global du propriétaire (tous ses paiements) | `payments` | +8 pts si >= 20%, +18 pts si >= 40% |
| `owner_has_fraud_code` | True si le propriétaire a un code Stripe frauduleux | `payments` | +20 points |
| `owner_dispute_count` | Nombre de litiges du propriétaire (tous abonnements) | `payments` | +12 points si > 1 |
| `owner_complaints_received` | Nombre de plaintes reçues par le propriétaire | `complaints` | +8 pts si >= 1, +15 pts si >= 3 |
| `owner_is_anomaly` | True si le compte propriétaire a un status anormal (99, -1) | `users` | +20 points |

### 2.2 Pondération et calcul du score (0 à 100)

Le score est calculé par la fonction `compute_risk_score(row)` dans [src/scoring.py](src/scoring.py).

**Section 1 — Paiements (domaine critique)**

| Condition | Points |
|-----------|--------|
| >= 3 paiements et taux d'échec = 100% | +35 |
| >= 3 paiements et taux d'échec >= 75% | +28 |
| >= 3 paiements et taux d'échec >= 50% | +18 |
| >= 3 paiements et taux d'échec >= 25% | +8 |
| 2 paiements et taux d'échec >= 50% | +15 |
| 1 paiement échoué | +8 |
| `has_stripe_fraud_code` = True | +25 |
| `dispute_count` > 0 | +10 par litige (max +20) |
| `currency_diversity` > 2 | +15 |

**Section 2 — Adhésion & comportement**

| Condition | Points |
|-----------|--------|
| `left_for_fraud` = True | +30 |
| `left_for_payment_failed` = True | +15 |
| Segment DORMANT | -10 |

**Section 3 — Plaintes**

| Condition | Points |
|-----------|--------|
| `complaints_received` >= 2 | +20 |
| `complaints_received` = 1 | +8 |
| `complaints_filed` >= 2 | +12 |

**Section 4 — Contexte abonnement**

| Condition | Points |
|-----------|--------|
| `sub_payment_failure_rate` >= 50% | +15 |
| `sub_payment_failure_rate` >= 30% | +8 |
| `sub_has_fraud_code` = True | +12 |

**Section 5 — Contexte propriétaire**

| Condition | Points |
|-----------|--------|
| `owner_payment_failure_rate` >= 40% | +18 |
| `owner_payment_failure_rate` >= 20% | +8 |
| `owner_has_fraud_code` = True | +20 |
| `owner_dispute_count` > 1 | +12 |
| `owner_complaints_received` >= 3 | +15 |
| `owner_complaints_received` >= 1 | +8 |
| `owner_is_anomaly` = True | +20 |

**Section 6 — Ajustements par segment**

| Segment | Condition | Ajustement |
|---------|-----------|------------|
| NOUVEAU | Pas de fraude Stripe ni de `left_for_fraud` | -15 (bénéfice du doute) |
| ANCIEN | Pas de `left_for_fraud` | -20 (a quitté normalement) |

**Borne finale** : `min(100, max(0, score))`

### 2.3 Segmentation des memberships

Avant le scoring, chaque membership est classé dans un segment :

| Segment | Critère |
|---------|---------|
| NOUVEAU | `membership_days` < 30 jours |
| ACTIF | >= 30 jours et `is_active` = True |
| ANCIEN | `is_active` = False |

### 2.4 Edge cases gérés

| Cas | Traitement |
|-----|-------------|
| Aucun paiement | `payment_count` = 0 → `payment_failure_rate` = 0, aucune pénalité |
| Un seul paiement réussi | Score bas (0 sauf s'il y a d'autres signaux) |
| Nouveau subscriber (< 30 jours) | Score réduit de 15 points si pas de fraude confirmée |
| Membre inactif | Classé DORMANT → score réduit de 10 points |
| Données manquantes | `fillna(0)` pour les numériques, `fillna(False)` pour les booléens |

### 2.5 Interprétation du score

| Score | Niveau | Action recommandée |
|-------|--------|--------------------|
| 0 – 39 | Faible | Surveillance normale |
| 40 – 59 | Modéré | Mettre en surveillance |
| 60 – 79 | Élevé | Contacter l'utilisateur / owner |
| 80 – 100 | Critique | Bloquer immédiatement |

---

### 2.6 Résultats du scoring

Le script `src/scoring.py` produit un fichier CSV `output/risk_scores.csv` contenant une ligne par membership avec les colonnes :

| Colonne | Description |
|---------|-------------|
| `user_id` | Identifiant de l'utilisateur |
| `subscription_id` | Identifiant de l'abonnement |
| `owner_id` | Identifiant du propriétaire |
| `segment` | NOUVEAU / ACTIF / ANCIEN |
| `risk_score` | Score de 0 à 100 |
| `risk_level` | FAIBLE / MODÉRÉ / ÉLEVÉ / CRITIQUE |
| `membership_days` | Ancienneté du membership |
| `is_active` | Membership actif ou non |
| `payment_count` | Nombre de tentatives de paiement |
| `payment_failure_rate` | Taux d'échec des paiements |
| `has_stripe_fraud_code` | Fraude Stripe détectée |
| `dispute_count` | Nombre de litiges |
| `complaints_received` | Plaintes reçues |
| `complaints_filed` | Plaintes déposées |
| `sub_payment_failure_rate` | Taux d'échec global de l'abonnement |
| `owner_payment_failure_rate` | Taux d'échec global du propriétaire |
| `owner_has_fraud_code` | Fraude Stripe détectée chez le propriétaire |
| `owner_complaints_received` | Plaintes reçues par le propriétaire |

Un même utilisateur peut avoir des scores très différents selon l'abonnement (car le risque dépend aussi du propriétaire et du contexte de la subscription). C'est l'avantage du scoring par membership.
