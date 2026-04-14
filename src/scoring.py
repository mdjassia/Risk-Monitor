import pandas as pd
import os

DATA_FOLDER = "data"
OUTPUT_FOLDER = "output"
OUTPUT_FILE = "risk_scores.csv"


def load_data():
    try:
        users = pd.read_csv(os.path.join(DATA_FOLDER, "users_clean.csv"))
        payments = pd.read_csv(os.path.join(DATA_FOLDER, "payments_clean.csv"))
        memberships = pd.read_csv(os.path.join(DATA_FOLDER, "memberships_clean.csv"))
        complaints = pd.read_csv(os.path.join(DATA_FOLDER, "complaints_clean.csv"))

        print("Données chargées avec succès")
        return users, payments, memberships, complaints

    except Exception as e:
        raise Exception(f"Erreur de chargement : {e}")


def prepare_users(users):
    # Renommer pour éviter confusion
    users = users.rename(columns={"id": "user_id"})
    return users


def compute_payment_features(payments):
    fraud_codes = ['stolen_card', 'fraudulent']

    pay_risk = payments.groupby('user_id').agg(
        nb_tentatives=('id', 'count'),
        taux_echec=('is_failed', 'mean'),
        fraude_stripe=('stripe_error_code', lambda x: x.isin(fraud_codes).any()),
        devises_diff=('currency', 'nunique')
    ).reset_index()

    return pay_risk


def compute_membership_features(memberships):
    mem_risk = memberships.groupby('user_id').agg(
        banni_fraude=('reason', lambda x: (x == 'fraud').any()),
        impayes_recurrents=('reason', lambda x: (x == 'payment_failed').sum())
    ).reset_index()

    return mem_risk


def compute_complaint_features(complaints):
    cibles = complaints.groupby('target_id').size().reset_index(name='plaintes_contre_lui')
    plaignants = complaints.groupby('reporter_id').size().reset_index(name='plaintes_deposees')

    return cibles, plaignants


def merge_all(users, pay_risk, mem_risk, cibles, plaignants):
    df = users.copy()

    df = df.merge(pay_risk, on='user_id', how='left')
    df = df.merge(mem_risk, on='user_id', how='left')
    df = df.merge(cibles, left_on='user_id', right_on='target_id', how='left')
    df = df.merge(plaignants, left_on='user_id', right_on='reporter_id', how='left')

    return df


def clean_data(df):
    numeric_cols = [
        'nb_tentatives', 'taux_echec', 'devises_diff',
        'impayes_recurrents', 'plaintes_contre_lui', 'plaintes_deposees'
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    bool_cols = ['fraude_stripe', 'banni_fraude']

    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].fillna(False)

    return df


def compute_risk_score(row):
    score = 0

    # CRITIQUE
    if row.get('fraude_stripe', False) or row.get('banni_fraude', False):
        return 100

    # HAUT RISQUE
    if row['nb_tentatives'] >= 3 and row['taux_echec'] > 0.5:
        score += 40

    # RISQUE MODÉRÉ
    score += min(30, row['plaintes_contre_lui'] * 10)

    if row['devises_diff'] > 1:
        score += 25

    # COMPORTEMENT SUSPECT
    if row['plaintes_deposees'] > 0 and row['taux_echec'] > 0.2:
        score += 15

    return min(100, score)


def apply_scoring(df):
    df['risk_score'] = df.apply(compute_risk_score, axis=1)
    return df


def save_output(df):
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    cols_to_keep = [
        'user_id',
        'email',
        'country',
        'risk_score',
        'nb_tentatives',
        'taux_echec'
    ]

    final_df = df[cols_to_keep].copy()

    output_path = os.path.join(OUTPUT_FOLDER, OUTPUT_FILE)
    final_df.to_csv(output_path, index=False)

    print(" Scoring terminé")
    print(f"Fichier sauvegardé : {output_path}")
    print(f"Utilisateurs scorés : {len(final_df)}")


def run_pipeline():
    print(" Lancement du pipeline de scoring...")

    users, payments, memberships, complaints = load_data()

    users = prepare_users(users)

    pay_risk = compute_payment_features(payments)
    mem_risk = compute_membership_features(memberships)
    cibles, plaignants = compute_complaint_features(complaints)

    df = merge_all(users, pay_risk, mem_risk, cibles, plaignants)

    df = clean_data(df)

    df = apply_scoring(df)

    save_output(df)


if __name__ == "__main__":
    run_pipeline()