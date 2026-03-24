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
API_KEY = os.environ.get("API_KEY", "tradingvps")
# ──────────────────────────────────────────────────────────

# Storage in memoria (i dati vengono ricaricati ad ogni riavvio del server)
# Per Render.com free tier questo va benissimo — le VPS reinviano ogni minuto
data_store = {}
data_lock  = threading.Lock()

# ── Nomi EA personalizzati ────────────────────────────────
# Salvati su file JSON per persistere tra riavvii di Render.
# Nota: Render.com free tier usa filesystem effimero — in caso di deploy
# i dati si perdono, ma le VPS reinviano i trade e la dashboard
# può reimportare i nomi. Per persistenza totale usare un DB esterno.
EA_NAMES_FILE = "ea_names.json"
ea_names_lock = threading.Lock()

def load_ea_names_from_disk():
    try:
        if os.path.exists(EA_NAMES_FILE):
            with open(EA_NAMES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_ea_names_to_disk(names):
    try:
        with open(EA_NAMES_FILE, "w", encoding="utf-8") as f:
            json.dump(names, f, ensure_ascii=False)
    except Exception as e:
        print(f"Errore salvataggio nomi EA: {e}")

ea_names_store = load_ea_names_from_disk()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ── Endpoint: le VPS inviano i dati qui ──────────────────
@app.route("/api/update", methods=["POST"])
def update():
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
        result = []
        for vps_name, accounts in data_store.items():
            result.append({
                "vps_name": vps_name,
                "accounts": list(accounts.values()),
            })

        return jsonify({
            "status":     "ok",
            "updated_at": now_iso(),
            "vps_count":  len(result),
            "data":       result,
        })


# ── Endpoint: GET nomi EA ─────────────────────────────────
@app.route("/api/names", methods=["GET"])
def get_names():
    with ea_names_lock:
        return jsonify({
            "status": "ok",
            "names":  ea_names_store,
            "updated_at": now_iso(),
        })


# ── Endpoint: POST nomi EA (salva) ───────────────────────
@app.route("/api/names", methods=["POST"])
def set_names():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(force=True, silent=True)
    if not payload or "names" not in payload:
        return jsonify({"error": "Invalid JSON — atteso campo 'names'"}), 400

    names = payload["names"]
    if not isinstance(names, dict):
        return jsonify({"error": "Il campo 'names' deve essere un oggetto"}), 400

    with ea_names_lock:
        ea_names_store.clear()
        ea_names_store.update({str(k): str(v) for k, v in names.items() if v})
        save_ea_names_to_disk(ea_names_store)

    print(f"[{now_iso()}] Nomi EA aggiornati: {len(ea_names_store)} voci")
    return jsonify({"status": "ok", "saved": len(ea_names_store)}), 200


# ── Health check ──────────────────────────────────────────
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
