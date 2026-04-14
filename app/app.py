import streamlit as st
import pandas as pd
import plotly.express as px
import os
from datetime import datetime


st.set_page_config(page_title="Risk Monitor v2", layout="wide")

FILE_PATH = "output/risk_scores.csv"
ACTIONS_FILE = "output/actions.csv"

@st.cache_data
def load_data():
    if os.path.exists(FILE_PATH):
        return pd.read_csv(FILE_PATH)
    return pd.DataFrame()

df = load_data()

if df.empty:
    st.error("No data found")
    st.stop()


def load_actions():
    """Charge les actions depuis le fichier CSV."""
    if os.path.exists(ACTIONS_FILE):
        try:
            actions_df = pd.read_csv(ACTIONS_FILE)
            if "key" in actions_df.columns and "action" in actions_df.columns:
                return dict(zip(actions_df["key"].astype(str), actions_df["action"]))
        except Exception:
            pass
    return {}

def save_action(user_id, subscription_id, action):
    """Sauvegarde une action dans le fichier CSV (écrase l'ancienne si elle existe)."""
    key = f"{user_id}_{subscription_id}"
    actions = load_actions()
    actions[key] = action

    rows = [{"key": k, "action": v} for k, v in actions.items()]
    pd.DataFrame(rows).to_csv(ACTIONS_FILE, index=False)

def get_action(user_id, subscription_id):
    """Retourne l'action actuelle pour un membership donné."""
    key = str(user_id) + "_" + str(subscription_id)
    return load_actions().get(key, None)


if "page" not in st.session_state:
    st.session_state.page = "Accueil"


def show_kpis(data):
    total = len(data)

    crit = len(data[data["risk_level"] == "CRITIQUE"])
    elev = len(data[data["risk_level"] == "ÉLEVÉ"])
    mod = len(data[data["risk_level"] == "MODÉRÉ"])
    faible = len(data[data["risk_level"] == "FAIBLE"])

    def pct(x):
        return f"{(x/total*100):.1f}%" if total else "0%"

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.metric("Total memberships", total)

    with c2:
        st.metric("🔴 Critiques", crit, pct(crit))

    with c3:
        st.metric("🟠 Élevé", elev, pct(elev))

    with c4:
        st.metric("🟡 Modéré", mod, pct(mod))

    with c5:
        st.metric("🟢 Faible", faible, pct(faible))


def get_csv(data):
    return data.to_csv(index=False).encode("utf-8")

# ============================================================
# NAVBAR
# ============================================================

col1, col2 = st.columns([2, 3])

with col1:
    st.markdown("##  Risk Monitor ")

with col2:
    n1, n2, n3, n4 = st.columns(4)

    with n1:
        if st.button(" Accueil"):
            st.session_state.page = "Accueil"

    with n2:
        if st.button(" Visualisation"):
            st.session_state.page = "Visualisation"

    with n3:
        if st.button(" Statistiques"):
            st.session_state.page = "Statistiques"

    with n4:
        st.download_button(
            " Download CSV",
            data=get_csv(df),
            file_name=f"risk_scores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )

st.markdown("---")


st.sidebar.title("🔎 Filtres")

risk_levels = df["risk_level"].dropna().unique().tolist()
segments = df["segment"].dropna().unique().tolist()

selected_levels = st.sidebar.multiselect("Risk level", risk_levels, default=risk_levels)
selected_segments = st.sidebar.multiselect("Segments", segments, default=segments)

score_range = st.sidebar.slider("Risk score", 0, 100, (0, 100))

# APPLY FILTERS
df = df[
    (df["risk_level"].isin(selected_levels)) &
    (df["segment"].isin(selected_segments)) &
    (df["risk_score"].between(score_range[0], score_range[1]))
]


if st.session_state.page == "Accueil":

    st.title(" Accueil")

    show_kpis(df)

    st.markdown("---")
    st.subheader(" Table complète")

    # Enrichir la table avec les actions persistées
    actions_dict = load_actions()
    df_display = df.copy()
    df_display["action"] = df_display.apply(
        lambda row: actions_dict.get(f"{row['user_id']}_{row['subscription_id']}", "—"),
        axis=1
    )

    st.dataframe(df_display, use_container_width=True)

    st.markdown("---")
    st.subheader("👤 Détails utilisateur")

    if "user_id" in df.columns:
        user_id = st.selectbox("Choisir user_id", df["user_id"].unique())

        user_data = df[df["user_id"] == user_id]

        # Afficher les memberships avec leur action actuelle
        for _, row in user_data.iterrows():
            sub_id = row["subscription_id"]
            current_action = get_action(user_id, sub_id)

            with st.expander(f"Membership — Subscription {sub_id} | Score: {row['risk_score']} | {row['risk_level']}"):
                st.write(row.to_frame().T)

                # Badge action actuelle
                if current_action == "blocked":
                    st.error(f" Statut actuel : BLOQUÉ")
                elif current_action == "monitored":
                    st.warning(f" Statut actuel : SURVEILLÉ")
                else:
                    st.info("Aucune action enregistrée")

                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button(f" Bloquer", key=f"block_{user_id}_{sub_id}"):
                        save_action(user_id, sub_id, "blocked")
                        st.success("Action sauvegardée : BLOQUÉ")
                        st.rerun()

                with col2:
                    if st.button(f" Surveiller", key=f"monitor_{user_id}_{sub_id}"):
                        save_action(user_id, sub_id, "monitored")
                        st.info("Action sauvegardée : SURVEILLÉ")
                        st.rerun()

                with col3:
                    if st.button(f" Réinitialiser", key=f"reset_{user_id}_{sub_id}"):
                        save_action(user_id, sub_id, "clear")
                        st.success("Action réinitialisée")
                        st.rerun()



elif st.session_state.page == "Visualisation":

    st.title(" Visualisation")

    show_kpis(df)

    col1, col2 = st.columns(2)

    with col1:
        fig = px.histogram(df, x="risk_score", color="risk_level", nbins=20)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = px.pie(df, names="segment")
        st.plotly_chart(fig, use_container_width=True)


elif st.session_state.page == "Statistiques":

    st.title(" Statistiques avancées")

    show_kpis(df)

    st.markdown("---")
    st.markdown("##  Analyse détaillée")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric("Score moyen", f"{df['risk_score'].mean():.1f}")

    with c2:
        st.metric("Score médian", f"{df['risk_score'].median():.1f}")

    with c3:
        st.metric("Écart-type", f"{df['risk_score'].std():.1f}")

    c4, c5, c6 = st.columns(3)

    with c4:
        st.metric("Taux d'échec moyen", f"{df['payment_failure_rate'].mean():.1%}")

    with c5:
        fraud = len(df[df["has_stripe_fraud_code"] == True])
        st.metric("Fraude Stripe", fraud)

    with c6:
        st.metric("Plaintes moyennes", f"{df['complaints_received'].mean():.2f}")

    # Tableau des actions enregistrées
    st.markdown("---")
    st.subheader(" Historique des actions opérateur")

    actions_dict = load_actions()
    if actions_dict:
        actions_rows = []
        for key, action in actions_dict.items():
            if action != "clear":
                parts = key.split("_")
                if len(parts) == 2:
                    actions_rows.append({
                        "user_id": parts[0],
                        "subscription_id": parts[1],
                        "action": action
                    })
        if actions_rows:
            st.dataframe(pd.DataFrame(actions_rows), use_container_width=True)
        else:
            st.info("Aucune action enregistrée.")
    else:
        st.info("Aucune action enregistrée.")


st.markdown("---")
st.caption(f"Risk Monitor v2 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
