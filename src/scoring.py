"""
SYSTÈME DE SCORING PAR MEMBERSHIP (v2) - ROBUSTE ET CALIBRÉ
============================================================

Approche:
1. Segmenter les memberships (NOUVEAU / ACTIF / DORMANT / ANCIEN)
2. Pour chaque segment, scorer 0-100 indépendamment
3. Chaque feature contribue avec un poids expliqué
4. Pas de "critiques" brutaux → granularité totale

Philosophie:
- Un seul flag "fraude" = +20-30 points (pas 100)
- "Critiques" seulement si MULTIPLES flags + paiements échoués
- Nouveau member = score bas par défaut (pas assez de data)
- Dormant = score bas (pas d'activité = pas de risque)
"""

import pandas as pd
import os
from datetime import timedelta, datetime
import numpy as np

DATA_FOLDER = "data"
OUTPUT_FOLDER = "output"
OUTPUT_FILE = "risk_scores.csv"

# ============================================================
# 1. LOAD DATA
# ============================================================

def load_data():
    try:
        users = pd.read_csv(os.path.join(DATA_FOLDER, "users_clean.csv"))
        payments = pd.read_csv(os.path.join(DATA_FOLDER, "payments_clean.csv"))
        memberships = pd.read_csv(os.path.join(DATA_FOLDER, "memberships_clean.csv"))
        complaints = pd.read_csv(os.path.join(DATA_FOLDER, "complaints_clean.csv"))
        subscriptions = pd.read_csv(os.path.join(DATA_FOLDER, "subscriptions_clean.csv"))
        print("✓ Données chargées")
        return users, payments, memberships, complaints, subscriptions
    except Exception as e:
        raise Exception(f"Erreur: {e}")


# ============================================================
# 2. PREPARE: User
# ============================================================

def prepare_users(users):
    """Préparer les données utilisateurs"""
    users = users.rename(columns={"id": "user_id"})
    users['last_seen'] = pd.to_datetime(users['last_seen'], utc=True, errors='coerce')
    
    # Flag utilisateur suspect (status anomalous)
    users['is_user_anomaly'] = ((users['status'] == 99) | (users['status'] == -1) | 
                                 users['status'].isna()).astype(int)
    
    # Flag inactif (last_seen > 90 jours)
    now = pd.Timestamp.now(tz='UTC')
    users['is_user_inactive'] = (users['last_seen'] < (now - timedelta(days=90))).astype(int)
    
    return users[['user_id', 'is_user_anomaly', 'is_user_inactive']]


# ============================================================
# 3. FEATURES: Payment Features par Membership
# ============================================================

def compute_payment_features(payments):
    """
    Features par (user_id, subscription_id):
    - Taux d'échec
    - Fraude Stripe détectée
    - Disputes
    - Diversité de devises
    - Jours depuis dernier paiement
    """
    pay = payments.copy()
    pay['created_at'] = pd.to_datetime(pay['created_at'], utc=True, errors='coerce')
    
    pay_grouped = pay.groupby(['user_id', 'subscription_id']).agg(
        payment_count=('id', 'count'),
        payment_failed_count=('is_failed', 'sum'),
        has_stripe_fraud_code=('stripe_error_code', lambda x: x.isin(['stolen_card', 'fraudulent']).any()),
        dispute_count=('status', lambda x: (x == 'disputed').sum()),
        currency_diversity=('currency', 'nunique'),
        days_since_last_payment=('created_at', lambda x: (pd.Timestamp.now(tz='UTC') - pd.to_datetime(x).max()).days 
                                                           if pd.to_datetime(x).max() is not pd.NaT else 999)
    ).reset_index()
    
    pay_grouped['payment_failure_rate'] = (
        pay_grouped['payment_failed_count'] / pay_grouped['payment_count'].clip(lower=1)
    ).round(3)
    
    return pay_grouped


# ============================================================
# 4. FEATURES: Membership Features
# ============================================================

def compute_membership_features(memberships):
    """
    Features par membership:
    - Durée d'adhésion (jours)
    - Actif ou quitté
    - Raison de départ
    """
    mem = memberships.copy()
    mem['joined_at'] = pd.to_datetime(mem['joined_at'], utc=True, errors='coerce')
    mem['left_at'] = pd.to_datetime(mem['left_at'], utc=True, errors='coerce')
    
    now = pd.Timestamp.now(tz='UTC')
    mem['membership_days'] = (now - mem['joined_at']).dt.days
    mem['is_active'] = mem['left_at'].isna().astype(int)
    mem['left_for_fraud'] = (mem['reason'] == 'fraud').astype(int)
    mem['left_for_payment_failed'] = (mem['reason'] == 'payment_failed').astype(int)
    
    return mem[['user_id', 'subscription_id', 'membership_days', 'is_active', 'left_for_fraud', 'left_for_payment_failed']]


# ============================================================
# 5. FEATURES: Complaints
# ============================================================

def compute_complaint_features(complaints):
    """
    Plaintes reçues ET déposées par (user_id, subscription_id)
    """
    # Plaintes REÇUES
    received = complaints.groupby(['target_id', 'subscription_id']).size().reset_index(name='complaints_received')
    received = received.rename(columns={'target_id': 'user_id'})
    
    # Plaintes DÉPOSÉES
    filed = complaints.groupby(['reporter_id', 'subscription_id']).size().reset_index(name='complaints_filed')
    filed = filed.rename(columns={'reporter_id': 'user_id'})
    
    return received, filed


# ============================================================
# 6. FEATURES: Subscription Global
# ============================================================

def compute_subscription_features(payments, subscriptions):
    """
    Features au niveau subscription (impact global):
    - Taux d'échec global
    - Fraude détectée dans la subscription
    """
    sub_pay = payments.groupby('subscription_id').agg(
        sub_payment_count=('id', 'count'),
        sub_payment_failed_count=('is_failed', 'sum'),
        sub_has_fraud_code=('stripe_error_code', lambda x: x.isin(['stolen_card', 'fraudulent']).any())
    ).reset_index()
    
    sub_pay['sub_payment_failure_rate'] = (
        sub_pay['sub_payment_failed_count'] / sub_pay['sub_payment_count'].clip(lower=1)
    ).round(3)
    
    # Ajouter owner_id
    sub_info = subscriptions[['id', 'owner_id']].rename(columns={'id': 'subscription_id'})
    sub_info = sub_info.merge(sub_pay, on='subscription_id', how='left')
    
    return sub_info


# ============================================================
# 7. FEATURES: Owner Features
# ============================================================

def compute_owner_features(payments, users, complaints):
    """
    Historique du propriétaire:
    - Taux d'échec global
    - Fraude détectée
    - Plaintes reçues
    """
    # Taux d'échec global du propriétaire
    owner_pay = payments.groupby('user_id').agg(
        owner_payment_failure_rate=('is_failed', 'mean'),
        owner_has_fraud_code=('stripe_error_code', lambda x: x.isin(['stolen_card', 'fraudulent']).any()),
        owner_dispute_count=('status', lambda x: (x == 'disputed').sum())
    ).reset_index()
    
    # Plaintes reçues
    owner_complaints = complaints.groupby('target_id').size().reset_index(name='owner_complaints_received')
    owner_complaints = owner_complaints.rename(columns={'target_id': 'user_id'})
    
    # Anomalie utilisateur
    owner_anomaly = users[['user_id', 'is_user_anomaly']].rename(columns={'is_user_anomaly': 'owner_is_anomaly'})
    
    # Merge
    owner_feat = owner_pay.merge(owner_complaints, on='user_id', how='left')
    owner_feat = owner_feat.merge(owner_anomaly, on='user_id', how='left')
    owner_feat.fillna({
        'owner_payment_failure_rate': 0,
        'owner_has_fraud_code': False,
        'owner_dispute_count': 0,
        'owner_complaints_received': 0,
        'owner_is_anomaly': 0
    }, inplace=True)
    
    return owner_feat.rename(columns={'user_id': 'owner_id'})


# ============================================================
# 8. MERGE ALL FEATURES
# ============================================================

def merge_all_features(memberships, pay_feat, mem_feat, complaints_received, complaints_filed, 
                       sub_feat, owner_feat):
    """
    Créer une table unique par membership avec toutes les features
    """
    df = memberships[['user_id', 'subscription_id']].copy()
    
    # Payment features
    df = df.merge(pay_feat, on=['user_id', 'subscription_id'], how='left')
    
    # Membership features
    df = df.merge(mem_feat, on=['user_id', 'subscription_id'], how='left')
    
    # Complaints
    df = df.merge(complaints_received, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(complaints_filed, on=['user_id', 'subscription_id'], how='left')
    
    # Subscription features
    df = df.merge(sub_feat, on='subscription_id', how='left')
    
    # Owner features
    df = df.merge(owner_feat, on='owner_id', how='left')
    
    return df


# ============================================================
# 9. CLEAN DATA
# ============================================================

def clean_data(df):
    """Remplir les NaN avec des valeurs par défaut sensées"""
    numeric_cols = [
        'payment_count', 'payment_failed_count', 'dispute_count', 'currency_diversity',
        'days_since_last_payment', 'payment_failure_rate',
        'membership_days', 'complaints_received', 'complaints_filed',
        'sub_payment_count', 'sub_payment_failed_count', 'sub_payment_failure_rate',
        'owner_payment_failure_rate', 'owner_dispute_count', 'owner_complaints_received'
    ]
    
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    
    bool_cols = [
        'has_stripe_fraud_code', 'is_active', 'left_for_fraud', 'left_for_payment_failed',
        'sub_has_fraud_code', 'owner_has_fraud_code', 'owner_is_anomaly'
    ]
    
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(bool)
    
    return df


# ============================================================
# 10. SEGMENT: Classify membership type
# ============================================================

def classify_segment(row):
    """
    Segmenter les memberships pour un scoring différencié:
    - NOUVEAU : < 30 jours
    - ACTIF : >= 30 jours et actif
    - DORMANT : inactif depuis 90+ jours
    - ANCIEN : quitté depuis longtemps
    """
    if row['membership_days'] < 30:
        return 'NOUVEAU'
    elif row['is_active'] == 0:
        return 'ANCIEN'
    else:
        return 'ACTIF'


# ============================================================
# 11. SCORING FUNCTION (LE CŒUR)
# ============================================================

def compute_risk_score(row):
    """
    Système de scoring ROBUSTE et CALIBRÉ
    
    Approche:
    - Chaque feature = points (0-100 max)
    - Pondération explicite et justifiée
    - Granularité complète 0-100
    - Pas de "return 100" rapide
    """
    
    score = 0.0
    max_score = 100.0
    
    segment = row['segment']
    
    # ==========================================
    # SECTION 1: PAIEMENTS (Domaine critique)
    # ==========================================
    
    # 1.1 - Taux d'échec personnel (user dans cette subscription)
    # Logique: Plus d'échecs = plus risqué
    failure_rate = row['payment_failure_rate']
    
    if row['payment_count'] >= 3:  # Au moins 3 tentatives pour évaluer
        if failure_rate == 1.0:  # 100% d'échec
            score += 35
        elif failure_rate >= 0.75:  # 75%+ d'échec
            score += 28
        elif failure_rate >= 0.5:   # 50%+ d'échec
            score += 18
        elif failure_rate >= 0.25:  # 25%+ d'échec
            score += 8
    elif row['payment_count'] == 2:
        if failure_rate >= 0.5:  # 50%+ d'échec sur 2
            score += 15
    elif row['payment_count'] == 1:
        if failure_rate == 1.0:  # 1 paiement échoué
            score += 8
    
    # 1.2 - Fraude Stripe détectée (stolen_card, fraudulent)
    # Logique: Fraude confirmée = risque objectif MAIS pas automatiquement 100
    if row['has_stripe_fraud_code']:
        score += 25
    
    # 1.3 - Disputes
    # Logique: Paiement disputé = montant réclamé, signe de problème
    if row['dispute_count'] > 0:
        score += min(20, row['dispute_count'] * 10)
    
    # 1.4 - Card Testing (plusieurs devises en peu de temps)
    # Logique: Si > 2 devises = test de cartes
    if row['currency_diversity'] > 2:
        score += 15
    
    # ==========================================
    # SECTION 2: ADHÉSION & COMPORTEMENT
    # ==========================================
    
    # 2.1 - Raison de départ (si applicable)
    # Logique: Bannissement pour fraude = historique grave
    if row['left_for_fraud']:
        score += 30
    
    if row['left_for_payment_failed']:
        score += 15
    
    # 2.2 - Inactivité (dormant)
    # Logique: Inactif > 90j = faible risque (rien à faire)
    if segment == 'DORMANT':
        score = max(0, score - 10)
    
    # ==========================================
    # SECTION 3: PLAINTES
    # ==========================================
    
    # 3.1 - Plaintes REÇUES (contre ce member)
    # Logique: Signalements = réputation compromise
    complaints_recv = row['complaints_received']
    if complaints_recv >= 2:
        score += 20
    elif complaints_recv >= 1:
        score += 8
    
    # 3.2 - Plaintes DÉPOSÉES (par ce member)
    # Logique: Si dépose beaucoup = litigieux
    complaints_filed = row['complaints_filed']
    if complaints_filed >= 2:
        score += 12
    
    # ==========================================
    # SECTION 4: SUBSCRIPTION CONTEXT
    # ==========================================
    
    # 4.1 - Taux d'échec global de la subscription
    # Logique: Si subscription entière a problèmes = tous impactés
    sub_failure_rate = row['sub_payment_failure_rate']
    if sub_failure_rate >= 0.5:
        score += 15
    elif sub_failure_rate >= 0.3:
        score += 8
    
    # 4.2 - Fraude dans la subscription
    # Logique: Fraude ailleurs = contexte risqué
    if row['sub_has_fraud_code']:
        score += 12
    
    # ==========================================
    # SECTION 5: OWNER CONTEXT
    # ==========================================
    
    # 5.1 - Taux d'échec global du propriétaire
    # Logique: Owner problématique = sa subscription problématique
    owner_failure_rate = row['owner_payment_failure_rate']
    if owner_failure_rate >= 0.4:
        score += 18
    elif owner_failure_rate >= 0.2:
        score += 8
    
    # 5.2 - Fraude du propriétaire
    # Logique: Owner avec historique fraude = tout suspecter
    if row['owner_has_fraud_code']:
        score += 20
    
    # 5.3 - Disputes du propriétaire
    # Logique: Owner litigieux = problème systémique
    if row['owner_dispute_count'] > 1:
        score += 12
    
    # 5.4 - Plaintes contre propriétaire
    # Logique: Owner signalé souvent = signe d'arnaque
    owner_complaints = row['owner_complaints_received']
    if owner_complaints >= 3:
        score += 15
    elif owner_complaints >= 1:
        score += 8
    
    # 5.5 - Anomalie propriétaire (status -1 ou 99)
    # Logique: Account compromis ou fraud
    if row['owner_is_anomaly']:
        score += 20
    
    # ==========================================
    # SECTION 6: SEGMENT-SPECIFIC ADJUSTMENTS
    # ==========================================
    
    if segment == 'NOUVEAU':
        # Nouveau member = peu de historique = bénéfice du doute
        # Sauf s'il y a VRAIMENT du problème (fraude + échec)
        if not (row['has_stripe_fraud_code'] or row['left_for_fraud']):
            score = max(0, score - 15)  # Réduction si pas de flagrant
    
    if segment == 'ANCIEN':
        # Ancien member = a quitté
        # Si raison bonne (normal departure) = risque bas
        if not row['left_for_fraud']:
            score = max(0, score - 20)
    
    # ==========================================
    # CAP THE SCORE
    # ==========================================
    
    score = min(100, max(0, score))
    
    return round(score, 1)


# ============================================================
# 12. APPLY SCORING
# ============================================================

def apply_scoring(df):
    """Appliquer le scoring et créer des catégories"""
    df['risk_score'] = df.apply(compute_risk_score, axis=1)
    
    # Catégories pour UX
    def risk_category(score):
        if score >= 80:
            return 'CRITIQUE'
        elif score >= 60:
            return 'ÉLEVÉ'
        elif score >= 40:
            return 'MODÉRÉ'
        else:
            return 'FAIBLE'
    
    df['risk_level'] = df['risk_score'].apply(risk_category)
    
    return df


# ============================================================
# 13. SAVE OUTPUT
# ============================================================

def save_output(df):
    """Sauvegarder le CSV final"""
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    
    cols_to_keep = [
        'user_id', 'subscription_id', 'owner_id',
        'segment', 'risk_score', 'risk_level',
        'membership_days', 'is_active',
        'payment_count', 'payment_failure_rate',
        'has_stripe_fraud_code', 'dispute_count',
        'complaints_received', 'complaints_filed',
        'sub_payment_failure_rate', 'owner_payment_failure_rate',
        'owner_has_fraud_code', 'owner_complaints_received'
    ]
    
    existing_cols = [c for c in cols_to_keep if c in df.columns]
    final_df = df[existing_cols].copy()
    
    # Conversions de types
    for col in ['user_id', 'subscription_id', 'owner_id', 'membership_days', 'is_active',
                'payment_count', 'dispute_count', 'complaints_received', 'complaints_filed',
                'owner_dispute_count', 'owner_complaints_received']:
        if col in final_df.columns:
            final_df[col] = final_df[col].fillna(0).astype(int)
    
    output_path = os.path.join(OUTPUT_FOLDER, OUTPUT_FILE)
    final_df.to_csv(output_path, index=False)
    
    print(f"\n✓ Scoring terminé")
    print(f"  Fichier: {output_path}")
    print(f"  Memberships scorés: {len(final_df)}")
    print(f"\n📊 Distribution des scores:")
    print(final_df['risk_score'].describe())
    print(f"\n📈 Par niveau:")
    print(final_df['risk_level'].value_counts().sort_index())
    print(f"\n🎯 Par segment:")
    print(final_df['segment'].value_counts())


# ============================================================
# 14. MAIN PIPELINE
# ============================================================

def run_pipeline():
    print("\n" + "=" * 60)
    print("SCORING PIPELINE V2 - ROBUSTE ET CALIBRÉ")
    print("=" * 60 + "\n")
    
    # Load
    users, payments, memberships, complaints, subscriptions = load_data()
    
    # Prepare
    print("📋 Préparation des données...")
    users = prepare_users(users)
    
    # Features
    print("🔧 Calcul des features...")
    pay_feat = compute_payment_features(payments)
    mem_feat = compute_membership_features(memberships)
    complaints_received, complaints_filed = compute_complaint_features(complaints)
    sub_feat = compute_subscription_features(payments, subscriptions)
    owner_feat = compute_owner_features(payments, users, complaints)
    
    # Merge
    print("🔗 Fusion des données...")
    df = merge_all_features(memberships, pay_feat, mem_feat, complaints_received, complaints_filed,
                            sub_feat, owner_feat)
    
    # Clean
    print("🧹 Nettoyage...")
    df = clean_data(df)
    
    # Segment
    print("📌 Segmentation...")
    df['segment'] = df.apply(classify_segment, axis=1)
    
    # Score
    print("⚖️  Scoring...")
    df = apply_scoring(df)
    
    # Save
    print("💾 Sauvegarde...")
    save_output(df)
    
    print("\n" + "=" * 60)
    print("✓ Pipeline terminé avec succès !")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_pipeline()