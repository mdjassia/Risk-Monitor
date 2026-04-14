import pandas as pd
import os
from datetime import timedelta

DATA_FOLDER = "data"
OUTPUT_FOLDER = "output"
OUTPUT_FILE = "risk_scores.csv"

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
    users['last_seen'] = pd.to_datetime(users['last_seen'], utc=True, errors='coerce')
    # Gestion de status_missing : si la colonne n'existe pas, on utilise status.isna()
    if 'status_missing' in users.columns:
        users['user_anomaly'] = ((users['status'] == 99) | (users['status'] == -1) | users['status_missing']).astype(int)
    else:
        users['user_anomaly'] = ((users['status'] == 99) | (users['status'] == -1) | users['status'].isna()).astype(int)
    now = pd.Timestamp.now(tz='UTC')
    users['inactive'] = (users['last_seen'] < (now - timedelta(days=90))).astype(int)
    return users

def compute_payment_features_by_membership(payments):
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
    recues = complaints.groupby(['target_id', 'subscription_id']).size().reset_index(name='plaintes_recues')
    recues = recues.rename(columns={'target_id': 'user_id'})
    deposees = complaints.groupby(['reporter_id', 'subscription_id']).size().reset_index(name='plaintes_deposees')
    deposees = deposees.rename(columns={'reporter_id': 'user_id'})
    return recues, deposees

def compute_subscription_global_features(payments, subscriptions):
    sub_pay = payments.groupby('subscription_id').agg(
        sub_nb_tentatives=('id', 'count'),
        sub_nb_failed=('is_failed', 'sum'),
        sub_has_fraud=('stripe_error_code', lambda x: x.isin(['stolen_card', 'fraudulent']).any())
    ).reset_index()
    sub_pay['sub_taux_echec'] = sub_pay['sub_nb_failed'] / sub_pay['sub_nb_tentatives'].clip(lower=1)
    sub_info = subscriptions[['id', 'owner_id']].rename(columns={'id': 'subscription_id'})
    sub_info = sub_info.merge(sub_pay, on='subscription_id', how='left')
    return sub_info

def compute_owner_features(users, payments, complaints):
    pay_owner = payments.groupby('user_id').agg(
        owner_global_failure_rate=('is_failed', 'mean'),
        owner_has_fraud_stripe=('stripe_error_code', lambda x: x.isin(['stolen_card', 'fraudulent']).any()),
        owner_disputed=('status', lambda x: (x == 'disputed').sum())
    ).reset_index()
    complaints_owner = complaints.groupby('target_id').size().reset_index(name='owner_complaints_received')
    complaints_owner = complaints_owner.rename(columns={'target_id': 'user_id'})
    user_anomaly = users[['user_id', 'user_anomaly']]
    owner_feat = pay_owner.merge(complaints_owner, on='user_id', how='left')
    owner_feat = owner_feat.merge(user_anomaly, on='user_id', how='left')
    owner_feat.fillna({
        'owner_global_failure_rate': 0,
        'owner_has_fraud_stripe': False,
        'owner_disputed': 0,
        'owner_complaints_received': 0,
        'user_anomaly': False
    }, inplace=True)
    return owner_feat

def merge_all(memberships, pay_features, mem_features, recues, deposees, sub_global, users, owner_features):
    df = memberships[['user_id', 'subscription_id']].copy()
    df = df.merge(pay_features, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(mem_features, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(recues, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(deposees, on=['user_id', 'subscription_id'], how='left')
    df = df.merge(sub_global, on='subscription_id', how='left')
    df = df.merge(users[['user_id', 'user_anomaly', 'inactive']], on='user_id', how='left')
    
    # Fusion avec owner_features
    df = df.merge(owner_features, left_on='owner_id', right_on='user_id', how='left', suffixes=('', '_owner'))
    df = df.drop(columns=['user_id_owner'], errors='ignore')
    
    # Conversion des identifiants en entiers (remplacer NaN par 0)
    df['owner_id'] = df['owner_id'].fillna(0).astype(int)
    # user_id et subscription_id sont déjà int, mais on s'assure qu'ils le restent
    df['user_id'] = df['user_id'].astype(int)
    df['subscription_id'] = df['subscription_id'].astype(int)
    return df

def clean_data(df):
    numeric_cols = [
        'nb_tentatives', 'taux_echec', 'devises_diff', 'disputed',
        'duree_jours', 'impayes', 'plaintes_recues', 'plaintes_deposees',
        'sub_nb_tentatives', 'sub_taux_echec',
        'owner_global_failure_rate', 'owner_disputed', 'owner_complaints_received'
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    bool_cols = [
        'stripe_fraud_flag', 'banni_fraude', 'sub_has_fraud', 'user_anomaly', 'est_actif',
        'owner_has_fraud_stripe'
    ]
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].fillna(False)
    return df

def compute_risk_score(row):
    # Critiques
    if (row.get('stripe_fraud_flag') or row.get('banni_fraude') or 
        row.get('sub_has_fraud') or row.get('user_anomaly') or
        row.get('owner_has_fraud_stripe') or row.get('user_anomaly_owner')):
        return 100

    score = 0
    fr = row['taux_echec']
    if row['nb_tentatives'] >= 2:
        if fr > 0.5:
            score += 40
        elif fr > 0.2:
            score += 20
    elif row['nb_tentatives'] == 1 and fr == 1.0:
        score += 15

    if row['disputed'] > 0:
        score += 25

    plaintes = row['plaintes_recues']
    if plaintes >= 3:
        score += 30
    elif plaintes >= 1:
        score += 15

    if row['sub_taux_echec'] > 0.4:
        score += 20

    if row['owner_global_failure_rate'] > 0.3:
        score += 20
    if row['owner_disputed'] > 0:
        score += 15
    if row['owner_complaints_received'] >= 2:
        score += 15

    if row['nb_tentatives'] < 2 and row['duree_jours'] < 30:
        score = max(0, score - 20)

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
        'duree_jours', 'est_actif',
        'owner_id', 'owner_global_failure_rate', 'owner_complaints_received'
    ]
    existing_cols = [c for c in cols_to_keep if c in df.columns]
    final_df = df[existing_cols].copy()
    # Convertir les colonnes d'ID en int
    for col in ['user_id', 'subscription_id', 'owner_id', 'nb_tentatives',  'plaintes_recues', 'disputed',
        'duree_jours', 'est_actif',
        'owner_id', 'owner_global_failure_rate', 'owner_complaints_received']:
        if col in final_df.columns:
            final_df[col] = final_df[col].fillna(0).astype(int)
    output_path = os.path.join(OUTPUT_FOLDER, OUTPUT_FILE)
    final_df.to_csv(output_path, index=False)
    print(f"Scoring terminé. Fichier : {output_path}")
    print(f"Nombre de memberships scorés : {len(final_df)}")

def run_pipeline():
    print("Lancement du pipeline de scoring par membership (avec prise en compte du risque owner)...")
    users, payments, memberships, complaints, subscriptions = load_data()

    users = prepare_users(users)
    pay_features = compute_payment_features_by_membership(payments)
    mem_features = compute_membership_features(memberships)
    recues, deposees = compute_complaint_features_by_membership(complaints)
    sub_global = compute_subscription_global_features(payments, subscriptions)
    owner_features = compute_owner_features(users, payments, complaints)

    df = merge_all(memberships, pay_features, mem_features, recues, deposees, sub_global, users, owner_features)
    df = clean_data(df)
    df = apply_scoring(df)
    save_output(df)

if __name__ == "__main__":
    run_pipeline()