"""
VPS Trading Monitor - Server Centrale
Riceve dati dalle VPS e li serve alla dashboard.
Deploy su Render.com (piano gratuito)
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timezone
import json
import os
import threading

app = Flask(__name__)
CORS(app)  # Permette alla dashboard di chiamare l'API da qualsiasi dominio

# ─── Configurazione ───────────────────────────────────────
API_KEY = os.environ.get("API_KEY", "trading2024abc")
# ──────────────────────────────────────────────────────────

# Storage in memoria (i dati vengono ricaricati ad ogni riavvio del server)
# Per Render.com free tier questo va benissimo — le VPS reinviano ogni minuto
data_store = {}
data_lock  = threading.Lock()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── Endpoint: le VPS inviano i dati qui ──────────────────
@app.route("/api/update", methods=["POST"])
def update():
    # Verifica API key
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"error": "Invalid JSON"}), 400

    vps_name = payload.get("vps_name", "unknown")
    accounts = payload.get("accounts", [])

    with data_lock:
        if vps_name not in data_store:
            data_store[vps_name] = {}

        for account in accounts:
            acc_key = f"{account.get('terminal','?')}_{account.get('account_number','?')}"
            data_store[vps_name][acc_key] = {
                **account,
                "received_at": now_iso(),
            }

    print(f"[{now_iso()}] Ricevuto da {vps_name}: {len(accounts)} account")
    return jsonify({"status": "ok", "received": len(accounts)}), 200


# ── Endpoint: la dashboard legge i dati da qui ───────────
@app.route("/api/data", methods=["GET"])
def get_data():
    with data_lock:
        # Ricostruisce struttura per VPS
        result = []
        for vps_name, accounts in data_store.items():
            accs_list = []
            for acc_key, acc_data in accounts.items():
                accs_list.append(acc_data)

            result.append({
                "vps_name": vps_name,
                "accounts": accs_list,
            })

        return jsonify({
            "status":     "ok",
            "updated_at": now_iso(),
            "vps_count":  len(result),
            "data":       result,
        })


# ── Health check (Render lo usa per tenere sveglio il server) ──
@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    with data_lock:
        vps_count = len(data_store)
        acc_count = sum(len(v) for v in data_store.values())
    return jsonify({
        "status":     "online",
        "updated_at": now_iso(),
        "vps_active": vps_count,
        "accounts":   acc_count,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Server avviato sulla porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
