"""
VPS Trading Monitor - Server Centrale
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timezone
import json, os, threading

app = Flask(__name__)
CORS(app)

API_KEY    = os.environ.get("API_KEY", "tradingvps")
data_store = {}
data_lock  = threading.Lock()

# Nomi EA in memoria — si ripopolano automaticamente dalla dashboard
ea_names_store = {}
ea_names_lock  = threading.Lock()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

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
            data_store[vps_name][acc_key] = {**account, "received_at": now_iso()}
    print(f"[{now_iso()}] Ricevuto da {vps_name}: {len(accounts)} account")
    return jsonify({"status": "ok", "received": len(accounts)}), 200

@app.route("/api/data", methods=["GET"])
def get_data():
    with data_lock:
        result = []
        for vps_name, accounts in data_store.items():
            result.append({"vps_name": vps_name, "accounts": list(accounts.values())})
        return jsonify({"status": "ok", "updated_at": now_iso(),
                        "vps_count": len(result), "data": result})

@app.route("/api/names", methods=["GET"])
def get_names():
    with ea_names_lock:
        return jsonify({"status": "ok", "names": dict(ea_names_store),
                        "updated_at": now_iso()})

@app.route("/api/names", methods=["POST"])
def set_names():
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json(force=True, silent=True)
    if not payload or "names" not in payload:
        return jsonify({"error": "Campo 'names' mancante"}), 400
    names = payload["names"]
    if not isinstance(names, dict):
        return jsonify({"error": "'names' deve essere un oggetto"}), 400
    with ea_names_lock:
        ea_names_store.clear()
        ea_names_store.update({str(k): str(v) for k, v in names.items() if v})
    print(f"[{now_iso()}] Nomi EA aggiornati: {len(ea_names_store)} voci")
    return jsonify({"status": "ok", "saved": len(ea_names_store)}), 200

@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    with data_lock:
        vps_count = len(data_store)
        acc_count = sum(len(v) for v in data_store.values())
    with ea_names_lock:
        names_count = len(ea_names_store)
    return jsonify({"status": "online", "updated_at": now_iso(),
                    "vps_active": vps_count, "accounts": acc_count,
                    "ea_names": names_count})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Server avviato sulla porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
