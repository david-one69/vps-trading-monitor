"""
VPS Trading Monitor - Server Centrale
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timezone
import json, os, threading

app = Flask(__name__)
CORS(app, origins='*', allow_headers=['Content-Type', 'X-API-Key'])

API_KEY    = os.environ.get("API_KEY", "tradingvps")
data_store = {}
data_lock  = threading.Lock()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# Nomi EA in memoria — si ripopolano automaticamente dalla dashboard
ea_names_store = {}
ea_names_lock  = threading.Lock()
ea_names_updated_at = now_iso()  # timestamp REALE dell'ultima modifica (non della richiesta)

# Tipi account in memoria — challenge / funded / instant / live / demo
account_types_store = {}
account_types_lock  = threading.Lock()
account_types_updated_at = now_iso()

# Account archiviati in memoria — chiave "VPS_accountNumber" -> True
# Esclusione DEFINITIVA dalle statistiche (es. challenge fallite), sincronizzata
# tra tutti i dispositivi. Non va confusa con account_types: qui non c'è
# categoria, solo dentro/fuori dall'archivio.
archived_accounts_store = {}
archived_accounts_lock  = threading.Lock()
archived_accounts_updated_at = now_iso()

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
                        "updated_at": ea_names_updated_at})

@app.route("/api/names", methods=["POST"])
def set_names():
    global ea_names_updated_at
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
        ea_names_updated_at = now_iso()
    print(f"[{now_iso()}] Nomi EA aggiornati: {len(ea_names_store)} voci")
    return jsonify({"status": "ok", "saved": len(ea_names_store),
                    "updated_at": ea_names_updated_at}), 200

@app.route("/api/account_types", methods=["GET"])
def get_account_types():
    with account_types_lock:
        return jsonify({"status": "ok", "types": dict(account_types_store),
                        "updated_at": account_types_updated_at})

@app.route("/api/account_types", methods=["POST"])
def set_account_types():
    global account_types_updated_at
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json(force=True, silent=True)
    if not payload or "types" not in payload:
        return jsonify({"error": "Campo 'types' mancante"}), 400
    types = payload["types"]
    if not isinstance(types, dict):
        return jsonify({"error": "'types' deve essere un oggetto"}), 400
    valid = {"challenge","funded","instant","live","demo","instant_v"}
    with account_types_lock:
        account_types_store.clear()
        account_types_store.update({str(k): str(v) for k, v in types.items() if v in valid})
        account_types_updated_at = now_iso()
    print(f"[{now_iso()}] Tipi account aggiornati: {len(account_types_store)} voci")
    return jsonify({"status": "ok", "saved": len(account_types_store),
                    "updated_at": account_types_updated_at}), 200

@app.route("/api/archived_accounts", methods=["GET"])
def get_archived_accounts():
    with archived_accounts_lock:
        return jsonify({"status": "ok", "archived": dict(archived_accounts_store),
                        "updated_at": archived_accounts_updated_at})

@app.route("/api/archived_accounts", methods=["POST"])
def set_archived_accounts():
    global archived_accounts_updated_at
    if request.headers.get("X-API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401
    payload = request.get_json(force=True, silent=True)
    if not payload or "archived" not in payload:
        return jsonify({"error": "Campo 'archived' mancante"}), 400
    archived = payload["archived"]
    if not isinstance(archived, dict):
        return jsonify({"error": "'archived' deve essere un oggetto"}), 400
    with archived_accounts_lock:
        archived_accounts_store.clear()
        archived_accounts_store.update({str(k): True for k, v in archived.items() if v})
        archived_accounts_updated_at = now_iso()
    print(f"[{now_iso()}] Account archiviati aggiornati: {len(archived_accounts_store)} voci")
    return jsonify({"status": "ok", "saved": len(archived_accounts_store),
                    "updated_at": archived_accounts_updated_at}), 200

@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health():
    with data_lock:
        vps_count = len(data_store)
        acc_count = sum(len(v) for v in data_store.values())
    with ea_names_lock:
        names_count = len(ea_names_store)
    with account_types_lock:
        types_count = len(account_types_store)
    with archived_accounts_lock:
        archived_count = len(archived_accounts_store)
    return jsonify({"status": "online", "updated_at": now_iso(),
                    "vps_active": vps_count, "accounts": acc_count,
                    "ea_names": names_count, "account_types": types_count,
                    "archived_accounts": archived_count})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Server avviato sulla porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
