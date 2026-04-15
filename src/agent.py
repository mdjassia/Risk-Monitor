"""
Agent IA Risk Monitor — Analyste & Décideur (v1 — Ollama local)
================================================================

Rôles couverts :
  - Analyste  : résumé structuré du comportement d'un subscriber
  - Décideur  : recommandation d'action avec niveau de confiance

Modèle      : mistral (via Ollama local — gratuit, aucune clé API)
Fallback    : analyse rule-based si Ollama est indisponible
Logs        : chaque appel loggé dans output/ai_logs.csv
Rejetés     : décisions rejetées loggées dans output/rejected_decisions.csv

Prérequis :
  1. Installer Ollama : https://ollama.com
  2. Lancer : ollama pull mistral
  3. Ollama tourne en arrière-plan sur http://localhost:11434
"""

import json
import os
import re
import time
from datetime import datetime

import requests
import pandas as pd


_OLLAMA_BASE = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_URL   = _OLLAMA_BASE.rstrip("/") + "/api/generate"
# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────


MODEL        = "llama3.2:3b"
TIMEOUT_SEC  = 120

AI_LOGS_FILE          = "output/ai_logs.csv"
REJECTED_DECISIONS_FILE = "output/rejected_decisions.csv"

VALID_ACTIONS = {"surveiller", "avertir", "bloquer", "ignorer"}

# ──────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Tu es un expert en detection de fraude. Reponds en JSON avec exactement ces 6 cles :

summary   : 1 phrase avec les chiffres reels (paiements, taux echec, score)
signals   : liste des alertes vraies parmi : "Taux echec paiement a N%", "Code fraude Stripe detecte", "N litige(s)", "N plaintes recues", "Abonnement risque echec N%", "Owner historique fraude". Liste vide [] si aucune.
vs_pop    : "echec N% vs moyenne M%, score S vs moyenne W" avec les chiffres reels des donnees
action    : exactement un de : ignorer / surveiller / avertir / bloquer
confidence: nombre entre 0.0 et 1.0
reason    : 1 phrase justifiant l action

Regles action : ignorer si score<40 sans signal ; surveiller si score 40-60 ou 1 signal ; avertir si score 60-80 ou 2+ signaux ; bloquer si fraude Stripe ou score>80

Exemple (chiffres fictifs) : {"summary":"3 paiements, 67% echec, score 45/100 MODERE","signals":["Taux echec paiement a 67%","Abonnement risque echec 52%"],"vs_pop":"echec 67% vs moyenne 18%, score 45 vs moyenne 31","action":"surveiller","confidence":0.75,"reason":"Taux echec 3x superieur a la moyenne, pas de fraude confirmee"}""".strip()


# ──────────────────────────────────────────────────────────────
# STATS
# ──────────────────────────────────────────────────────────────

def compute_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"total": 0, "avg_score": 0, "avg_failure_rate": 0,
                "avg_complaints": 0, "pct_fraud": 0}
    return {
        "total":            len(df),
        "avg_score":        df["risk_score"].mean()           if "risk_score"           in df.columns else 0,
        "avg_failure_rate": df["payment_failure_rate"].mean() if "payment_failure_rate" in df.columns else 0,
        "avg_complaints":   df["complaints_received"].mean()  if "complaints_received"  in df.columns else 0,
        "pct_fraud":        (df["has_stripe_fraud_code"].sum() / len(df) * 100)
                            if "has_stripe_fraud_code" in df.columns else 0,
    }


# ──────────────────────────────────────────────────────────────
# USER MESSAGE
# ──────────────────────────────────────────────────────────────

def _build_user_message(row: dict, stats: dict) -> str:
    pf       = row.get("payment_failure_rate", 0) or 0
    sub_pf   = row.get("sub_payment_failure_rate", 0) or 0
    owner_pf = row.get("owner_payment_failure_rate", 0) or 0

    return (
        f"Donnees subscriber:\n"
        f"- Segment: {row.get('segment')} | Score risque: {row.get('risk_score')}/100 | Niveau: {row.get('risk_level')}\n"
        f"- Paiements: {int(row.get('payment_count',0))} tentatives, taux echec={pf*100:.0f}% | Fraude Stripe: {'OUI' if row.get('has_stripe_fraud_code') else 'non'} | Litiges: {int(row.get('dispute_count',0))}\n"
        f"- Plaintes recues: {int(row.get('complaints_received',0))} | Plaintes deposees: {int(row.get('complaints_filed',0))}\n"
        f"- Taux echec abonnement: {sub_pf*100:.0f}% | Taux echec owner: {owner_pf*100:.0f}% | Owner fraude: {'OUI' if row.get('owner_has_fraud_code') else 'non'}\n"
        f"Moyennes base ({stats.get('total',0)} membres): score moyen={stats.get('avg_score',0):.0f}/100, taux echec moyen={stats.get('avg_failure_rate',0)*100:.0f}%"
    )


# ──────────────────────────────────────────────────────────────
# PARSE & VALIDATE
# ──────────────────────────────────────────────────────────────

def _parse_response(text: str) -> dict:
    text = text.strip()

    # Essai direct
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Extraire le premier objet JSON trouvé
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("Aucun JSON trouvé dans la réponse")
        data = json.loads(match.group())

    # Normalisation des clés — le modèle peut utiliser des variantes en anglais/français
    _ANALYSTE_ALIASES = ["analyste", "analyst", "analysis", "analyse"]
    _DECIDEUR_ALIASES = ["decideur", "decision", "decider", "recommandation", "recommendation"]

    for alias in _ANALYSTE_ALIASES:
        if alias in data and alias != "analyste":
            data["analyste"] = data.pop(alias)
            break

    for alias in _DECIDEUR_ALIASES:
        if alias in data and alias != "decideur":
            data["decideur"] = data.pop(alias)
            break

    if "analyste" not in data or "decideur" not in data:
        raise ValueError(f"Clés manquantes dans la réponse: {list(data.keys())}")

    action = data["decideur"].get("action", "")
    if action not in VALID_ACTIONS:
        raise ValueError(f"Action invalide: '{action}'")

    conf = data["decideur"].get("confidence", 0.5)
    data["decideur"]["confidence"] = max(0.0, min(1.0, float(conf)))

    return data


# ──────────────────────────────────────────────────────────────
# FALLBACK RULE-BASED
# ──────────────────────────────────────────────────────────────

def _rule_based_fallback(row: dict) -> dict:
    score      = row.get("risk_score", 0) or 0
    pf         = row.get("payment_failure_rate", 0) or 0
    fraud      = bool(row.get("has_stripe_fraud_code", False))
    disputes   = int(row.get("dispute_count", 0) or 0)
    complaints = int(row.get("complaints_received", 0) or 0)

    signals = []
    if fraud:
        signals.append("Code fraude Stripe détecté")
    if pf >= 0.75:
        signals.append(f"Taux d'échec très élevé ({pf:.0%})")
    elif pf >= 0.5:
        signals.append(f"Taux d'échec élevé ({pf:.0%})")
    if disputes > 0:
        signals.append(f"{disputes} litige(s) enregistré(s)")
    if complaints >= 2:
        signals.append(f"{complaints} plainte(s) reçue(s)")
    if row.get("left_for_fraud"):
        signals.append("Membership résilié pour fraude")

    if score >= 80 or fraud:
        action, confidence = "bloquer", 0.75
    elif score >= 60:
        action, confidence = "avertir", 0.65
    elif score >= 40:
        action, confidence = "surveiller", 0.65
    else:
        action, confidence = "ignorer", 0.75

    return {
        "analyste": {
            "behavior_summary": (
                f"Analyse hors-ligne — score {score}/100 "
                f"({row.get('risk_level', 'N/A')}). "
                f"{len(signals)} signal(s) détecté(s)."
            ),
            "alert_signals": signals or ["Aucun signal critique détecté"],
            "vs_population": "Comparaison indisponible (mode hors-ligne).",
        },
        "decideur": {
            "action": action,
            "confidence": confidence,
            "justification": (
                f"Recommandation basée sur le score calculé ({score}/100). "
                "Relance l'analyse IA quand Ollama est disponible."
            ),
        },
        "_fallback": True,
    }


# ──────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────

def _log_ai_call(row: dict) -> None:
    os.makedirs("output", exist_ok=True)
    exists = os.path.exists(AI_LOGS_FILE)
    pd.DataFrame([row]).to_csv(AI_LOGS_FILE, mode="a", header=not exists, index=False)


def log_rejected_decision(user_id, subscription_id, proposed_action, confidence, justification):
    os.makedirs("output", exist_ok=True)
    exists = os.path.exists(REJECTED_DECISIONS_FILE)
    row = {
        "timestamp":       datetime.utcnow().isoformat(),
        "user_id":         user_id,
        "subscription_id": subscription_id,
        "proposed_action": proposed_action,
        "confidence":      confidence,
        "justification":   justification,
    }
    pd.DataFrame([row]).to_csv(REJECTED_DECISIONS_FILE, mode="a", header=not exists, index=False)


# ──────────────────────────────────────────────────────────────
# POINT D'ENTRÉE PRINCIPAL
# ──────────────────────────────────────────────────────────────

def analyze_subscriber(row: dict, df: pd.DataFrame) -> dict:
    """
    Analyse un subscriber via Ollama (Mistral local).
    En cas d'erreur → fallback rule-based avec même structure de retour.
    """
    t0        = time.time()
    source    = "ollama"
    error_msg = None
    stats     = compute_stats(df)

    user_id = row.get("user_id", "?")
    sub_id  = row.get("subscription_id", "?")

    try:
        full_prompt = _SYSTEM_PROMPT + "\n\n" + _build_user_message(row, stats)

        response = requests.post(
            OLLAMA_URL,
            json={
                "model":   MODEL,
                "prompt":  full_prompt,
                "stream":  False,
                "format":  "json",          # force JSON valide — élimine les erreurs de parse
                "options": {"num_predict": 450},  # assez pour le JSON complet
            },
            timeout=TIMEOUT_SEC,
        )
        response.raise_for_status()

        content = response.json()["response"]
        result  = _parse_response(content)

    except requests.exceptions.ConnectionError:
        source    = "fallback_rules"
        error_msg = "Ollama indisponible — lance 'ollama serve' en arrière-plan"
        result    = _rule_based_fallback(row)

    except requests.exceptions.Timeout:
        source    = "fallback_rules"
        error_msg = f"Timeout ({TIMEOUT_SEC}s) — modèle trop lent"
        result    = _rule_based_fallback(row)

    except (ValueError, KeyError, json.JSONDecodeError) as e:
        source    = "fallback_rules"
        error_msg = f"Réponse invalide du modèle: {e}"
        result    = _rule_based_fallback(row)

    except Exception as e:
        source    = "fallback_rules"
        error_msg = f"Erreur inattendue: {e}"
        result    = _rule_based_fallback(row)

    latency_ms = int((time.time() - t0) * 1000)

    _log_ai_call({
        "timestamp":       datetime.utcnow().isoformat(),
        "user_id":         user_id,
        "subscription_id": sub_id,
        "model":           MODEL if source == "ollama" else None,
        "source":          source,
        "latency_ms":      latency_ms,
        "recommendation":  result.get("decideur", {}).get("action", "?"),
        "error":           error_msg,
    })

    result["meta"] = {
        "source":     source,
        "model":      MODEL if source == "ollama" else None,
        "latency_ms": latency_ms,
        "error":      error_msg,
    }

    return result
