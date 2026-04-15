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

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/chat"
MODEL        = "llama3.2:3b"
TIMEOUT_SEC  = 120

AI_LOGS_FILE          = "output/ai_logs.csv"
REJECTED_DECISIONS_FILE = "output/rejected_decisions.csv"

VALID_ACTIONS = {"surveiller", "avertir", "bloquer", "ignorer"}

# ──────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """Tu es un expert en détection de fraude. Analyse les données d'un subscriber et réponds UNIQUEMENT en JSON valide, sans texte autour.

Signaux à détecter (utilise uniquement ceux qui sont vrais) :
- "Taux d'échec paiement élevé (X%)" si echec > 40%
- "Code fraude Stripe détecté" si Fraude=OUI
- "Litige(s) enregistré(s)" si Litiges > 0
- "Plaintes reçues contre lui" si Plaintes_recues > 0
- "Abonnement à risque élevé" si Sub_echec > 40%
- "Owner problématique" si Owner_fraude=OUI ou Owner_echec > 40%

Actions : ignorer (score bas, aucun signal) | surveiller (1-2 signaux faibles) | avertir (signaux sérieux) | bloquer (fraude confirmée)

Format de réponse obligatoire :
{"analyste":{"behavior_summary":"1-2 phrases factuelles","alert_signals":["signal concret"],"vs_population":"comparaison avec moyennes"},"decideur":{"action":"ignorer|surveiller|avertir|bloquer","confidence":0.0,"justification":"1 phrase"}}""".strip()


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
        f"Données subscriber:\n"
        f"- Segment: {row.get('segment')} | Score risque: {row.get('risk_score')}/100 | Niveau: {row.get('risk_level')}\n"
        f"- Paiements: {int(row.get('payment_count',0))} tentatives, {pf:.0%} d'échec | Fraude Stripe: {'OUI' if row.get('has_stripe_fraud_code') else 'non'} | Litiges: {int(row.get('dispute_count',0))}\n"
        f"- Plaintes reçues: {int(row.get('complaints_received',0))} | Plaintes déposées: {int(row.get('complaints_filed',0))}\n"
        f"- Taux échec abonnement: {sub_pf:.0%} | Owner échec: {owner_pf:.0%} | Owner fraude: {'OUI' if row.get('owner_has_fraud_code') else 'non'}\n"
        f"Moyennes base ({stats.get('total',0)} membres): score moyen={stats.get('avg_score',0):.0f}/100, échec moyen={stats.get('avg_failure_rate',0):.0%}"
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

    # Validation
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
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": _build_user_message(row, stats)},
                ],
                "stream": False,
            },
            timeout=TIMEOUT_SEC,
        )
        response.raise_for_status()

        content = response.json()["message"]["content"]
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
