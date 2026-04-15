import sys
import os

# Permet d'importer src/agent.py depuis n'importe où
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

# Import agent IA
try:
    from src.agent import analyze_subscriber, log_rejected_decision
    AGENT_AVAILABLE = True
except ImportError:
    AGENT_AVAILABLE = False

# ============================================================
# CONFIG
# ============================================================

st.set_page_config(page_title="Risk Monitor v2", layout="wide")

FILE_PATH   = "output/risk_scores.csv"
ACTIONS_FILE = "output/actions.csv"

# ============================================================
# LOAD DATA
# ============================================================

@st.cache_data
def load_data():
    if os.path.exists(FILE_PATH):
        return pd.read_csv(FILE_PATH)
    return pd.DataFrame()

df_full = load_data()   # dataset complet — utilisé pour les stats IA
df = df_full.copy()     # sera filtré ensuite

if df.empty:
    st.error("No data found. Lance d'abord : python src/scoring.py")
    st.stop()

# ============================================================
# PERSISTANCE DES ACTIONS
# ============================================================

def load_actions():
    if os.path.exists(ACTIONS_FILE):
        try:
            a = pd.read_csv(ACTIONS_FILE)
            if "key" in a.columns and "action" in a.columns:
                return dict(zip(a["key"].astype(str), a["action"]))
        except Exception:
            pass
    return {}

def save_action(user_id, subscription_id, action):
    key = f"{user_id}_{subscription_id}"
    actions = load_actions()
    actions[key] = action
    rows = [{"key": k, "action": v} for k, v in actions.items()]
    pd.DataFrame(rows).to_csv(ACTIONS_FILE, index=False)

def get_action(user_id, subscription_id):
    return load_actions().get(f"{user_id}_{subscription_id}", None)

# ============================================================
# SESSION STATE
# ============================================================

if "page" not in st.session_state:
    st.session_state.page = "Accueil"

# ============================================================
# KPIs
# ============================================================

def show_kpis(data):
    total  = len(data)
    crit   = len(data[data["risk_level"] == "CRITIQUE"])
    elev   = len(data[data["risk_level"] == "ÉLEVÉ"])
    mod    = len(data[data["risk_level"] == "MODÉRÉ"])
    faible = len(data[data["risk_level"] == "FAIBLE"])

    def pct(x):
        return f"{(x/total*100):.1f}%" if total else "0%"

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("Total memberships", total)
    with c2: st.metric("🔴 Critiques", crit,  pct(crit))
    with c3: st.metric("🟠 Élevé",     elev,  pct(elev))
    with c4: st.metric("🟡 Modéré",    mod,   pct(mod))
    with c5: st.metric("🟢 Faible",    faible, pct(faible))

def get_csv(data):
    return data.to_csv(index=False).encode("utf-8")

# ============================================================
# NAVBAR
# ============================================================

col1, col2 = st.columns([2, 3])

with col1:
    st.markdown("## 🚨 Risk Monitor v2")

with col2:
    n1, n2, n3, n4 = st.columns(4)
    with n1:
        if st.button("🏠 Accueil"):
            st.session_state.page = "Accueil"
    with n2:
        if st.button("📊 Visualisation"):
            st.session_state.page = "Visualisation"
    with n3:
        if st.button("📈 Statistiques"):
            st.session_state.page = "Statistiques"
    with n4:
        st.download_button(
            "⬇️ Export CSV",
            data=get_csv(df_full),
            file_name=f"risk_scores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

st.markdown("---")

# ============================================================
# SIDEBAR FILTRES
# ============================================================

st.sidebar.title("🔎 Filtres")
risk_levels    = df["risk_level"].dropna().unique().tolist()
segments       = df["segment"].dropna().unique().tolist()
selected_levels   = st.sidebar.multiselect("Risk level", risk_levels, default=risk_levels)
selected_segments = st.sidebar.multiselect("Segments",   segments,    default=segments)
score_range       = st.sidebar.slider("Risk score", 0, 100, (0, 100))

df = df[
    (df["risk_level"].isin(selected_levels)) &
    (df["segment"].isin(selected_segments)) &
    (df["risk_score"].between(score_range[0], score_range[1]))
]

# ============================================================
# PAGE 1 — ACCUEIL
# ============================================================

if st.session_state.page == "Accueil":

    st.title("🏠 Accueil")
    show_kpis(df)
    st.markdown("---")

    # Table complète avec colonne action
    st.subheader("📋 Table des memberships")
    actions_dict = load_actions()
    df_display = df.copy()
    df_display["action"] = df_display.apply(
        lambda r: actions_dict.get(f"{r['user_id']}_{r['subscription_id']}", "—"),
        axis=1,
    )
    # Mettre les colonnes lisibles en premier
    priority_cols = ["subscriber_email", "brand", "owner_email", "segment",
                     "risk_score", "risk_level", "action"]
    other_cols    = [c for c in df_display.columns if c not in priority_cols]
    ordered_cols  = [c for c in priority_cols if c in df_display.columns] + other_cols
    st.dataframe(df_display[ordered_cols], use_container_width=True)

    st.markdown("---")
    st.subheader("👤 Détails subscriber")

    email_col = "subscriber_email" if "subscriber_email" in df.columns else "user_id"
    if email_col in df.columns:
        selected_email = st.selectbox("Choisir un subscriber", sorted(df[email_col].dropna().unique()))
        user_data = df[df[email_col] == selected_email]

        for _, row in user_data.iterrows():
            user_id        = row["user_id"]
            sub_id         = row["subscription_id"]
            brand          = row.get("brand", sub_id)
            current_action = get_action(user_id, sub_id)
            ai_key         = f"ai_result_{user_id}_{sub_id}"

            with st.expander(
                f"Membership — {brand} | "
                f"Score: {row['risk_score']} | {row['risk_level']}"
            ):
                # ── Données brutes ──
                st.write(row.to_frame().T)

                # ── Statut action actuelle ──
                if current_action == "blocked":
                    st.error("⛔ Statut actuel : BLOQUÉ")
                elif current_action == "monitored":
                    st.warning("👁️ Statut actuel : SURVEILLÉ")
                else:
                    st.info("Aucune action enregistrée")

                st.markdown("---")

                # ════════════════════════════════════════
                # SECTION AGENT IA
                # ════════════════════════════════════════
                st.subheader("🤖 Analyse IA")

                if not AGENT_AVAILABLE:
                    st.warning("Module agent non disponible. Vérifie l'installation.")

                else:
                    # Bouton d'analyse
                    if st.button("🤖 Lancer l'analyse IA", key=f"ai_btn_{user_id}_{sub_id}"):
                        with st.spinner("Appel Claude en cours..."):
                            result = analyze_subscriber(row.to_dict(), df_full)
                        st.session_state[ai_key] = {
                            "result": result,
                            "status": "done",
                        }
                        st.rerun()

                    # Affichage du résultat
                    ai_state = st.session_state.get(ai_key)

                    if ai_state:
                        result   = ai_state["result"]
                        analyste = result.get("analyste", {})
                        decideur = result.get("decideur", {})
                        meta     = result.get("meta", {})

                        # Badge source
                        if meta.get("source") == "fallback_rules":
                            st.warning(
                                f"⚠️ Mode hors-ligne — API indisponible. "
                                f"Erreur : {meta.get('error', '')}"
                            )
                        else:
                            st.caption(
                                f"Modèle : {meta.get('model')} | "
                                f"Latence : {meta.get('latency_ms')} ms"
                            )

                        # Rapport analyste
                        with st.container():
                            st.markdown(
                                f"**Résumé :** {analyste.get('behavior_summary', '')}"
                            )
                            signals = analyste.get("alert_signals", [])
                            if signals:
                                st.markdown("**Signaux d'alerte :**")
                                for s in signals:
                                    st.markdown(f"- ⚠️ {s}")
                            st.info(
                                f"**vs Population :** {analyste.get('vs_population', '')}"
                            )

                        # Recommandation
                        action = decideur.get("action", "?")
                        conf   = decideur.get("confidence", 0)

                        color_fn = {
                            "bloquer":    st.error,
                            "avertir":    st.warning,
                            "surveiller": st.info,
                            "ignorer":    st.success,
                        }.get(action, st.info)

                        color_fn(
                            f"Recommandation IA : **{action.upper()}** "
                            f"(confiance : {conf:.0%})"
                        )
                        st.write(f"**Justification :** {decideur.get('justification', '')}")

                        # Boutons Accepter / Rejeter
                        status = ai_state.get("status", "done")

                        if status == "done":
                            action_map = {
                                "bloquer":    "blocked",
                                "avertir":    "monitored",
                                "surveiller": "monitored",
                                "ignorer":    "clear",
                            }
                            col_acc, col_rej = st.columns(2)

                            with col_acc:
                                if st.button(
                                    "✅ Accepter la recommandation",
                                    key=f"ai_accept_{user_id}_{sub_id}",
                                ):
                                    save_action(
                                        user_id, sub_id,
                                        action_map.get(action, "monitored"),
                                    )
                                    st.session_state[ai_key]["status"] = "accepted"
                                    st.success("Décision appliquée.")
                                    st.rerun()

                            with col_rej:
                                if st.button(
                                    "❌ Rejeter",
                                    key=f"ai_reject_{user_id}_{sub_id}",
                                ):
                                    log_rejected_decision(
                                        user_id, sub_id,
                                        action, conf,
                                        decideur.get("justification", ""),
                                    )
                                    st.session_state[ai_key]["status"] = "rejected"
                                    st.rerun()

                        elif status == "accepted":
                            st.success("✅ Recommandation acceptée et appliquée.")

                        elif status == "rejected":
                            st.error("❌ Recommandation rejetée — rejet loggé.")

                st.markdown("---")

                # ── Actions manuelles ──
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("⛔ Bloquer", key=f"block_{user_id}_{sub_id}"):
                        save_action(user_id, sub_id, "blocked")
                        st.success("Bloqué")
                        st.rerun()
                with col2:
                    if st.button("👁️ Surveiller", key=f"monitor_{user_id}_{sub_id}"):
                        save_action(user_id, sub_id, "monitored")
                        st.info("Mis en surveillance")
                        st.rerun()
                with col3:
                    if st.button("✅ Réinitialiser", key=f"reset_{user_id}_{sub_id}"):
                        save_action(user_id, sub_id, "clear")
                        st.success("Réinitialisé")
                        st.rerun()

# ============================================================
# PAGE 2 — VISUALISATION
# ============================================================

elif st.session_state.page == "Visualisation":

    st.title("📊 Visualisation")
    show_kpis(df)

    col1, col2 = st.columns(2)
    with col1:
        fig = px.histogram(df, x="risk_score", color="risk_level", nbins=20,
                           title="Distribution des scores de risque")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig = px.pie(df, names="segment", title="Répartition par segment")
        st.plotly_chart(fig, use_container_width=True)

# ============================================================
# PAGE 3 — STATISTIQUES
# ============================================================

elif st.session_state.page == "Statistiques":

    st.title("📈 Statistiques avancées")
    show_kpis(df)
    st.markdown("---")

    # Stats générales
    st.markdown("## Analyse des données")
    c1, c2, c3 = st.columns(3)
    with c1: st.metric("Score moyen",   f"{df['risk_score'].mean():.1f}")
    with c2: st.metric("Score médian",  f"{df['risk_score'].median():.1f}")
    with c3: st.metric("Écart-type",    f"{df['risk_score'].std():.1f}")

    c4, c5, c6 = st.columns(3)
    with c4: st.metric("Taux d'échec moyen", f"{df['payment_failure_rate'].mean():.1%}")
    with c5: st.metric("Fraude Stripe", len(df[df["has_stripe_fraud_code"] == True]))
    with c6: st.metric("Plaintes moyennes", f"{df['complaints_received'].mean():.2f}")

    st.markdown("---")

    # Actions opérateur
    st.subheader("📋 Historique des actions opérateur")
    actions_dict = load_actions()
    if actions_dict:
        actions_rows = [
            {"user_id": k.split("_")[0], "subscription_id": k.split("_")[1], "action": v}
            for k, v in actions_dict.items()
            if v != "clear" and len(k.split("_")) == 2
        ]
        if actions_rows:
            st.dataframe(pd.DataFrame(actions_rows), use_container_width=True)
        else:
            st.info("Aucune action enregistrée.")
    else:
        st.info("Aucune action enregistrée.")

    st.markdown("---")

    # Suivi des appels IA
    st.subheader("🤖 Suivi des appels IA")
    ai_logs_path = "output/ai_logs.csv"

    if os.path.exists(ai_logs_path):
        ai_logs = pd.read_csv(ai_logs_path)
        if not ai_logs.empty:
            m1, m2, m3, m4 = st.columns(4)
            with m1: st.metric("Total appels IA", len(ai_logs))
            with m2: st.metric("Appels Ollama",
                                len(ai_logs[ai_logs["source"] == "ollama"]))
            with m3: st.metric("Fallbacks règles",
                                len(ai_logs[ai_logs["source"] == "fallback_rules"]))
            with m4: st.metric("Latence moyenne",
                                f"{ai_logs['latency_ms'].mean():.0f} ms")

            st.dataframe(ai_logs.tail(20), use_container_width=True)
        else:
            st.info("Aucun appel IA enregistré pour l'instant.")
    else:
        st.info("Lance une analyse IA depuis la page Accueil pour voir les logs ici.")

    # Décisions rejetées
    rejected_path = "output/rejected_decisions.csv"
    if os.path.exists(rejected_path):
        rejected = pd.read_csv(rejected_path)
        if not rejected.empty:
            st.markdown("---")
            st.subheader("❌ Décisions IA rejetées par l'opérateur")
            st.dataframe(rejected, use_container_width=True)

# ============================================================
# FOOTER
# ============================================================

st.markdown("---")
st.caption(f"Risk Monitor v2 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
