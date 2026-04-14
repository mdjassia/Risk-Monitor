import pandas as pd
import os
from datetime import timedelta

DATA_FOLDER = "data"
OUTPUT_FOLDER = "output"
OUTPUT_FILE = "risk_scores_by_membership.csv"

def load_data():
    try:
        users = pd.read_csv(os.path.join(DATA_FOLDER, "users_clean.csv"))
        payments = pd.read_csv(os.path.join(DATA_FOLDER, "payments_clean.csv"))
        memberships = pd.read_csv(os.path.join(DATA_FOLDER, "memberships_clean.csv"))
        complaints = pd.read_csv(os.path.join(DATA_FOLDER, "complaints_clean.csv"))
        subscriptions = pd.read_csv(os.path.join(DATA_FOLDER, "subscriptions_clean.csv"))
        print("Données chargées avec succès")
        return users, payments, memberships, complaints, subscriptions
    except Exception as e:
        raise Exception(f"Erreur de chargement : {e}")

def prepare_users(users):
    users = users.rename(columns={"id": "user_id"})
    # Convertir last_seen en datetime UTC
    users['last_seen'] = pd.to_datetime(users['last_seen'], utc=True, errors='coerce')
    # Flag anomalies utilisateur (status_missing doit exister, sinon utiliser status.isna())
    users['user_anomaly'] = ((users['status'] == 99) | (users['status'] == -1) | users['status_missing']).astype(int)
    now = pd.Timestamp.now(tz='UTC')
    users['inactive'] = (users['last_seen'] < (now - timedelta(days=90))).astype(int)
    return users

def compute_payment_features_by_membership(payments):
    """
    Features de paiement au niveau (user_id, subscription_id)
    """
    pay = payments.groupby(['user_id', 'subscription_id']).agg(
        nb_tentatives=('id', 'count'),
        nb_failed=('is_failed', 'sum'),
        stripe_fraud_flag=('stripe_error_code', lambda x: x.isin(['stolen_card', 'fraudulent']).any()),
        disputed=('status', lambda x: (x == 'disputed').sum()),
        devises_diff=('currency', 'nunique'),
        dernier_paiement=('created_at', 'max')
    ).reset_index()
    pay['taux_echec'] = pay['nb_failed'] / pay['nb_tentatives'].clip(lower=1)
    return pay

def compute_membership_features(memberships):
    """
    Features propres au membership (durée, raison de départ, etc.)
    """
    mem = memberships.copy()
    mem['joined_at'] = pd.to_datetime(mem['joined_at'], utc=True)
    mem['left_at'] = pd.to_datetime(mem['left_at'], utc=True)
    now = pd.Timestamp.now(tz='UTC')
    mem['duree_jours'] = (now - mem['joined_at']).dt.days
    mem['est_actif'] = mem['left_at'].isna()
    mem['banni_fraude'] = (mem['reason'] == 'fraud').astype(int)
    mem['impayes'] = (mem['reason'] == 'payment_failed').astype(int)
    return mem[['user_id', 'subscription_id', 'duree_jours', 'est_actif', 'banni_fraude', 'impayes']]

def compute_complaint_features_by_membership(complaints):
    """
    Plaintes au niveau (user_id, subscription_id) : reçues et déposées
    """
    # Plaintes reçues (target)
    recues = complaints.groupby(['target_id', 'subscription_id']).size().reset_index(name='plaintes_recues')
    recues = recues.rename(columns={'target_id': 'user_id'})
    # Plaintes déposées (reporter)
    deposees = complaints.groupby(['reporter_id', 'subscription_id']).size().reset_index(name='plaintes_deposees')
    deposees = deposees.rename(columns={'reporter_id': 'user_id'})
    return recues, deposees

def compute_subscription_global_features(payments, subscriptions):
    """
    Features globales de la subscription (taux d'échec global, etc.)
    """
    sub_pay = payments.groupby('subscription_id').agg(
        sub_nb_tentatives=('id', 'count'),
        sub_nb_failed=('is_failed', 'sum'),
        sub_has_fraud=('stripe_error_code', lambda x: x.isin(['stolen_card', 'fraudulent']).any())
    ).reset_index()
    sub_pay['sub_taux_echec'] = sub_pay['sub_nb_failed'] / sub_pay['sub_nb_tentatives'].clip(lower=1)
    # Ajouter le propriétaire
    sub_info = subscriptions[['id', 'owner_id']].rename(columns={'id': 'subscription_id'})
    sub_info = sub_info.merge(sub_pay, on='subscription_id', how='left')
    return sub_info

def merge_all(memberships, pay_features, mem_features, recues, deposees, sub_global, users):
    df = memberships[['user_id', 'subscription_id']].copy()
    df = df.merge(pay_features, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(mem_features, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(recues, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(deposees, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(sub_global, on='subscription_id', how='left')
    df = df.merge(users[['user_id', 'user_anomaly', 'inactive']], on='user_id', how='left')
    return df

def clean_data(df):
    numeric_cols = [
        'nb_tentatives', 'taux_echec', 'devises_diff', 'disputed',
        'duree_jours', 'impayes', 'plaintes_recues', 'plaintes_deposees',
        'sub_nb_tentatives', 'sub_taux_echec'
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    bool_cols = ['stripe_fraud_flag', 'banni_fraude', 'sub_has_fraud', 'user_anomaly', 'est_actif']
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].fillna(False)
    return df

def compute_risk_score(row):
    """
    Score individuel pour un membership (user + subscription)
    """
    # 1. Critiques : fraude avérée ou anomalie utilisateur
    if row.get('stripe_fraud_flag') or row.get('banni_fraude') or row.get('sub_has_fraud') or row.get('user_anomaly'):
        return 100

    score = 0

    # 2. Taux d'échec du user sur CETTE subscription
    fr = row['taux_echec']
    if row['nb_tentatives'] >= 2:
        if fr > 0.5:
            score += 40
        elif fr > 0.2:
            score += 20
    elif row['nb_tentatives'] == 1 and fr == 1.0:
        # Un seul paiement échoué = suspect mais pas critique
        score += 15

    # 3. Litiges sur cette subscription
    if row['disputed'] > 0:
        score += 25

    # 4. Plaintes reçues par l'utilisateur sur cette subscription
    plaintes = row['plaintes_recues']
    if plaintes >= 3:
        score += 30
    elif plaintes >= 1:
        score += 15

    # 5. Comportement de la subscription globale
    if row['sub_taux_echec'] > 0.4:
        score += 20

    # 6. Nouveau subscriber (peu d'historique) : on ne pénalise pas trop
    if row['nb_tentatives'] < 2 and row['duree_jours'] < 30:
        # Réduction du score pour les nouveaux
        score = max(0, score - 20)

    # 7. Inactivité de l'utilisateur (réduction)
    if row['inactive']:
        score = max(0, score - 15)

    return min(100, score)

def apply_scoring(df):
    df['risk_score'] = df.apply(compute_risk_score, axis=1)
    return df

def save_output(df):
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    cols_to_keep = [
        'user_id', 'subscription_id', 'risk_score',
        'nb_tentatives', 'taux_echec', 'plaintes_recues', 'disputed',
        'duree_jours', 'est_actif'
    ]
    final_df = df[cols_to_keep].copy()
    output_path = os.path.join(OUTPUT_FOLDER, OUTPUT_FILE)
    final_df.to_csv(output_path, index=False)
    print(f"Scoring terminé. Fichier : {output_path}")
    print(f"Nombre de memberships scorés : {len(final_df)}")

def run_pipeline():
    print("Lancement du pipeline de scoring par membership...")
    users, payments, memberships, complaints, subscriptions = load_data()

    users = prepare_users(users)
    pay_features = compute_payment_features_by_membership(payments)
    mem_features = compute_membership_features(memberships)
    recues, deposees = compute_complaint_features_by_membership(complaints)
    sub_global = compute_subscription_global_features(payments, subscriptions)

    df = merge_all(memberships, pay_features, mem_features, recues, deposees, sub_global, users)
    df = clean_data(df)
    df = apply_scoring(df)
    save_output(df)

if __name__ == "__main__":
    run_pipeline()