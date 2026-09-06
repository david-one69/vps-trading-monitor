"""
VPS Trading Monitor - Server Centrale
"""
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timezone
import json, os, threading, base64, logging

import requests

app = Flask(__name__)
CORS(app, origins='*', allow_headers=['Content-Type', 'X-API-Key'])

log = logging.getLogger("vps-trading-monitor")
logging.basicConfig(level=logging.INFO)

API_KEY    = os.environ.get("API_KEY", "tradingvps")
data_store = {}
data_lock  = threading.Lock()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

# ══════════════════════════════════════════════════════════════════════════
#  PERSISTENZA SU GITHUB
# ══════════════════════════════════════════════════════════════════════════
# Render (piano free) azzera la RAM ad ogni riavvio/sleep. Nomi EA, tipi conto
# e account archiviati vengono quindi salvati anche come file JSON nel repo
# GitHub tramite le Contents API, cosi' un riavvio non li perde piu': al
# prossimo avvio del processo, lo store viene ri-idratato da GitHub.
#
# Config (variabili d'ambiente Render):
#   GITHUB_TOKEN  - Personal Access Token con permesso di scrittura sul repo
#                   (obbligatorio per la persistenza; se assente il server
#                   funziona comunque, ma solo in RAM come prima - nessun
#                   crash, solo un log di avviso)
#   GITHUB_REPO   - "utente/nome-repo" (default: david-one69/vps-trading-monitor)
#   GITHUB_BRANCH - branch su cui scrivere (default: main)
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "david-one69/vps-trading-monitor")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_API    = "https://api.github.com"
GITHUB_DATA_DIR = "data"  # cartella nel repo dove finiscono i file JSON

_github_enabled = bool(GITHUB_TOKEN)
if not _github_enabled:
    log.warning("GITHUB_TOKEN non configurato: nomi EA/tipi conto/archiviati "
                "NON sopravvivranno ai riavvii di Render (solo RAM).")

def _github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def github_read_json(filename):
    """Legge un file JSON dal repo. Ritorna (dict_o_None, sha_o_None)."""
    if not _github_enabled:
        return None, None
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{GITHUB_DATA_DIR}/{filename}"
    try:
        r = requests.get(url, headers=_github_headers(),
                          params={"ref": GITHUB_BRANCH}, timeout=10)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        payload = r.json()
        content = base64.b64decode(payload["content"]).decode("utf-8")
        return json.loads(content), payload["sha"]
    except Exception as e:
        log.warning(f"GitHub read fallita per {filename}: {e}")
        return None, None

def github_write_json(filename, data, message):
    """Scrive/aggiorna un file JSON nel repo. Ritorna True/False."""
    if not _github_enabled:
        return False
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{GITHUB_DATA_DIR}/{filename}"
    try:
        # Serve lo sha corrente per aggiornare un file esistente
        _, sha = github_read_json(filename)
        content_b64 = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii")
        body = {"message": message, "content": content_b64, "branch": GITHUB_BRANCH}
        if sha:
            body["sha"] = sha
        r = requests.put(url, headers=_github_headers(), json=body, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        log.warning(f"GitHub write fallita per {filename}: {e}")
        return False

# Nomi EA in memoria — si ripopolano automaticamente dalla dashboard
ea_names_store = {}
ea_names_lock  = threading.Lock()
# None = "mai modificato in questa esecuzione del processo". IMPORTANTE: non
# inizializzare a now_iso() qui — uno store appena svuotato con timestamp
# "adesso" sembrerebbe più recente di qualsiasi dato reale nel browser,
# causando la cancellazione dei dati su tutti i dispositivi al primo sync.
ea_names_updated_at = None

# Tipi account in memoria — challenge / funded / instant / live / demo
account_types_store = {}
account_types_lock  = threading.Lock()
account_types_updated_at = None

# Account archiviati in memoria — chiave "VPS_accountNumber" -> True
archived_accounts_store = {}
archived_accounts_lock  = threading.Lock()
archived_accounts_updated_at = None

def _hydrate_from_github():
    """Al boot del processo, ricarica gli store da GitHub se disponibili.
    Cosi' un riavvio Render non riparte da zero."""
    global ea_names_store, ea_names_updated_at
    global account_types_store, account_types_updated_at
    global archived_accounts_store, archived_accounts_updated_at

    data, _ = github_read_json("ea_names.json")
    if data:
        ea_names_store = data.get("names", {})
        ea_names_updated_at = data.get("updated_at")
        log.info(f"Nomi EA ripristinati da GitHub: {len(ea_names_store)} voci")

    data, _ = github_read_json("account_types.json")
    if data:
        account_types_store = data.get("types", {})
        account_types_updated_at = data.get("updated_at")
        log.info(f"Tipi account ripristinati da GitHub: {len(account_types_store)} voci")

    data, _ = github_read_json("archived_accounts.json")
    if data:
        archived_accounts_store = data.get("archived", {})
        archived_accounts_updated_at = data.get("updated_at")
        log.info(f"Account archiviati ripristinati da GitHub: {len(archived_accounts_store)} voci")

_hydrate_from_github()

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
        snapshot = dict(ea_names_store)
        ts = ea_names_updated_at
    persisted = github_write_json(
        "ea_names.json",
        {"names": snapshot, "updated_at": ts},
        f"Aggiorna nomi EA ({len(snapshot)} voci)"
    )
    print(f"[{now_iso()}] Nomi EA aggiornati: {len(snapshot)} voci"
          f" | GitHub: {'OK' if persisted else 'saltato/fallito (solo RAM)'}")
    return jsonify({"status": "ok", "saved": len(snapshot),
                    "updated_at": ts, "persisted": persisted}), 200

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
        snapshot = dict(account_types_store)
        ts = account_types_updated_at
    persisted = github_write_json(
        "account_types.json",
        {"types": snapshot, "updated_at": ts},
        f"Aggiorna tipi conto ({len(snapshot)} voci)"
    )
    print(f"[{now_iso()}] Tipi account aggiornati: {len(snapshot)} voci"
          f" | GitHub: {'OK' if persisted else 'saltato/fallito (solo RAM)'}")
    return jsonify({"status": "ok", "saved": len(snapshot),
                    "updated_at": ts, "persisted": persisted}), 200

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
        snapshot = dict(archived_accounts_store)
        ts = archived_accounts_updated_at
    persisted = github_write_json(
        "archived_accounts.json",
        {"archived": snapshot, "updated_at": ts},
        f"Aggiorna account archiviati ({len(snapshot)} voci)"
    )
    print(f"[{now_iso()}] Account archiviati aggiornati: {len(snapshot)} voci"
          f" | GitHub: {'OK' if persisted else 'saltato/fallito (solo RAM)'}")
    return jsonify({"status": "ok", "saved": len(snapshot),
                    "updated_at": ts, "persisted": persisted}), 200

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
                    "archived_accounts": archived_count,
                    "github_persistence": _github_enabled})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Server avviato sulla porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
