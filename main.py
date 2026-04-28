"""
QuizBlitz — Flask servera slānis.

Autentifikācija (JWT), SSE notikumi, SQLite datu glabāšana.
JSON API atslēgas, kļūdu kodi, JWT prasījumu lauki un SSE — latviski.
"""

from __future__ import annotations

import json
import os
import queue
import random
import string
import threading
import time
import uuid
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import Flask, Response, g, jsonify, render_template, request, stream_with_context

import db as dbmod

# ─── Lietotnes iestatījumi ─────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = "stress-release-secret-2026"
DATABASE_PATH = os.environ.get(
    "QUIZBLITZ_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "quizblitz.db"),
)

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# SSE abonentu rindas: sesijas_id → Queue saraksts
sse_subscribers: dict[str, list[queue.Queue]] = {}
sse_lock = threading.Lock()


def iegut_savienojumu() -> sqlite3.Connection:
    """Atgriež pieprasījuma SQLite savienojumu ( Flask g konteksts )."""
    if "savienojums" not in g:
        g.savienojums = dbmod.connect(DATABASE_PATH)
    return g.savienojums


@app.teardown_appcontext
def _close_db(_exc):
    sav = g.pop("savienojums", None)
    if sav is not None:
        sav.close()


def init_app_db():
    """Izveido tabulas un demonstrācijas datus, ja datubāze ir tukša."""
    savienojums = dbmod.connect(DATABASE_PATH)
    try:
        dbmod.init_schema(savienojums)
        if dbmod.user_count(savienojums) == 0:
            seed_demo(savienojums)
    finally:
        savienojums.close()


# ─── Palīgfunkcijas ───────────────────────────────────────────────────────────
def jauns_id() -> str:
    return str(uuid.uuid4())


def laika_zime() -> str:
    return datetime.utcnow().isoformat() + "Z"


def izveidot_pin_kodu() -> str:
    return "".join(random.choices(string.digits, k=6))


def jauc_paroli(parole: str) -> str:
    import hashlib

    return hashlib.sha256(parole.encode()).hexdigest()


def izveidot_jwt(satura_kopa: dict) -> str:
    satura_kopa["exp"] = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    return jwt.encode(satura_kopa, app.config["SECRET_KEY"], algorithm=JWT_ALGORITHM)


def atsifret_jwt(tokenis: str) -> dict | None:
    try:
        return jwt.decode(tokenis, app.config["SECRET_KEY"], algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def kludas_atbilde(statuss, kods, zinojums):
    return (
        jsonify(
            {
                "statusa_kods": statuss,
                "kludas_kods": kods,
                "zinojums": zinojums,
                "laika_zime": laika_zime(),
            }
        ),
        statuss,
    )


def izplatit_sse(sesijas_id: str, notikums: str, dati: dict):
    """Nosūta notikumu visiem SSE klausītājiem dotajai sesijai."""
    ielade = json.dumps({"notikums": notikums, "dati": dati})
    with sse_lock:
        abonenti = sse_subscribers.get(sesijas_id, [])
        nevajadzigi = []
        for rinda in abonenti:
            try:
                rinda.put_nowait(ielade)
            except queue.Full:
                nevajadzigi.append(rinda)
        for rinda in nevajadzigi:
            abonenti.remove(rinda)


# ─── JSON atbilžu kartēšana (DB vērtības → latviskie lauki) ────────────────────
_STATUSS_NO_DB_UZ_API = {
    "DRAFT": "MELNRAKSTS",
    "PUBLISHED": "PUBLICETS",
    "WAITING": "GAIDA",
    "ACTIVE": "NOTIEK",
    "FINISHED": "PABEIGTS",
}
_STATUSS_NO_API_UZ_DB = {v: k for k, v in _STATUSS_NO_DB_UZ_API.items()}


def statuss_api(db_vertiba: str) -> str:
    return _STATUSS_NO_DB_UZ_API.get(db_vertiba, db_vertiba)


def statuss_db(api_vertiba: str) -> str:
    return _STATUSS_NO_API_UZ_DB.get(api_vertiba, api_vertiba)


def variants_izeja(o: dict) -> dict:
    return {
        "id": o["id"],
        "teksts": o["text"],
        "pareizi": o["isCorrect"],
        "kartiba": o["orderIndex"],
    }


def jautajuma_izeja(q: dict) -> dict:
    return {
        "id": q["id"],
        "viktorinas_id": q["quiz_id"],
        "teksts": q["text"],
        "tips": q["type"],
        "laika_limits_sekundes": q["timeLimitSeconds"],
        "punkti": q["points"],
        "kartiba": q["orderIndex"],
        "atbilzu_varianti": [variants_izeja(o) for o in q["answerOptions"]],
    }


def kvizes_izeja(q: dict) -> dict:
    return {
        "id": q["id"],
        "ipasnieka_id": q["owner_id"],
        "nosaukums": q["title"],
        "apraksts": q.get("description", ""),
        "statuss": statuss_api(q["status"]),
        "izveidots": q["createdAt"],
        "atjauninats": q["updatedAt"],
        "jautajumi": [jautajuma_izeja(j) for j in q["questions"]],
    }


def jautajuma_saisinajums(x: dict) -> dict:
    return {"id": x["id"], "teksts": x["text"][:60]}


def kvizes_saraksta_viens(q: dict) -> dict:
    return {
        "id": q["id"],
        "ipasnieka_id": q["owner_id"],
        "nosaukums": q["title"],
        "apraksts": q.get("description", ""),
        "statuss": statuss_api(q["status"]),
        "izveidots": q["createdAt"],
        "atjauninats": q["updatedAt"],
        "skaits": {"jautajumi": len(q["questions"])},
        "jautajumi": [jautajuma_saisinajums(x) for x in q["questions"]],
    }


# ─── Autentifikācijas dekoratori ──────────────────────────────────────────────
def prasa_saimnieku(f):
    """Pieprasa derīgu JWT ar lietotaja_id (saimnieks / pasākuma veidotājs)."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        arhivs = request.headers.get("Authorization", "")
        if not arhivs.startswith("Bearer "):
            return kludas_atbilde(401, "NAV_AUTORIZETS", "Trūkst pilnvaras žetona")
        tokenis = arhivs.split(" ", 1)[1]
        ielade = atsifret_jwt(tokenis)
        if not ielade or "lietotaja_id" not in ielade:
            return kludas_atbilde(401, "NAV_AUTORIZETS", "Nederīgs vai beidzies žetons")
        g.lietotaja_id = ielade["lietotaja_id"]
        g.lietotaja_epasts = ielade.get("epasts", "")
        return f(*args, **kwargs)

    return wrapper


def prasa_dalibnieku(f):
    """Pieprasa derīgu JWT ar dalibnieka_id (spēlētājs)."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        arhivs = request.headers.get("Authorization", "")
        tokenis = arhivs.split(" ", 1)[1] if arhivs.startswith("Bearer ") else ""
        ielade = atsifret_jwt(tokenis)
        if not ielade or "dalibnieka_id" not in ielade:
            return kludas_atbilde(401, "NAV_AUTORIZETS", "Nederīgs dalībnieka žetons")
        g.dalibnieka_id = ielade["dalibnieka_id"]
        g.sesijas_id = ielade.get("sesijas_id")
        return f(*args, **kwargs)

    return wrapper


# ─── Demonstrācijas dati (tikai tukšai DB) ────────────────────────────────────
def seed_demo(savienojums: sqlite3.Connection):
    """Aizpilda vienu demo lietotāju un publicētu viktorīnu."""
    lietotaja_id = jauns_id()
    dbmod.user_create(savienojums, lietotaja_id, "demo@quiz.com", jauc_paroli("password123"))
    qid = jauns_id()
    q1, q2, q3 = jauns_id(), jauns_id(), jauns_id()
    a1, a2, a3, a4 = jauns_id(), jauns_id(), jauns_id(), jauns_id()
    a5, a6, a7, a8 = jauns_id(), jauns_id(), jauns_id(), jauns_id()
    at, af = jauns_id(), jauns_id()
    quiz = {
        "id": qid,
        "owner_id": lietotaja_id,
        "title": "Tehnoloģiju viktorīna",
        "description": "Pārbaudi savas zināšanas!",
        "status": "PUBLISHED",
        "createdAt": laika_zime(),
        "updatedAt": laika_zime(),
        "questions": [
            {
                "id": q1,
                "quiz_id": qid,
                "text": "Ko nozīmē saīsinājums CPU?",
                "type": "SINGLE_CHOICE",
                "timeLimitSeconds": 20,
                "points": 1000,
                "orderIndex": 0,
                "answerOptions": [
                    {"id": a1, "text": "Centrālā apstrādes ierīce", "isCorrect": True, "orderIndex": 0},
                    {"id": a2, "text": "Datora personiskā vienība", "isCorrect": False, "orderIndex": 1},
                    {"id": a3, "text": "Kodola energijas serviss", "isCorrect": False, "orderIndex": 2},
                    {"id": a4, "text": "Centrālā programmu apkalpošana", "isCorrect": False, "orderIndex": 3},
                ],
            },
            {
                "id": q2,
                "quiz_id": qid,
                "text": "Python ir interpretēta valoda.",
                "type": "TRUE_FALSE",
                "timeLimitSeconds": 15,
                "points": 500,
                "orderIndex": 1,
                "answerOptions": [
                    {"id": at, "text": "Patiess", "isCorrect": True, "orderIndex": 0},
                    {"id": af, "text": "Nepatiess", "isCorrect": False, "orderIndex": 1},
                ],
            },
            {
                "id": q3,
                "quiz_id": qid,
                "text": "Kura kompānija 1995. gadā izveidoja JavaScript?",
                "type": "SINGLE_CHOICE",
                "timeLimitSeconds": 20,
                "points": 1000,
                "orderIndex": 2,
                "answerOptions": [
                    {"id": a5, "text": "Netscape", "isCorrect": True, "orderIndex": 0},
                    {"id": a6, "text": "Microsoft", "isCorrect": False, "orderIndex": 1},
                    {"id": a7, "text": "Google", "isCorrect": False, "orderIndex": 2},
                    {"id": a8, "text": "Sun Microsystems", "isCorrect": False, "orderIndex": 3},
                ],
            },
        ],
    }
    dbmod.import_full_quiz(savienojums, quiz)


init_app_db()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTENTIFIKĀCIJAS MARŠRUTI
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    epasts = body.get("epasts", body.get("email", "")).lower().strip()
    parole = body.get("parole", body.get("password", ""))
    savienojums = iegut_savienojumu()
    lietotajs = dbmod.user_by_email(savienojums, epasts)
    if not lietotajs or lietotajs["password_hash"] != jauc_paroli(parole):
        return kludas_atbilde(401, "NEPAREIZAS_PIESAISTES", "Nepareizs e-pasts vai parole")
    token = izveidot_jwt({"lietotaja_id": lietotajs["id"], "epasts": epasts})
    return jsonify(
        {"piekļuves_zetons": token, "lietotajs": {"id": lietotajs["id"], "epasts": epasts}}
    )


@app.post("/api/v1/auth/register")
def register():
    body = request.get_json(silent=True) or {}
    epasts = body.get("epasts", body.get("email", "")).lower().strip()
    parole = body.get("parole", body.get("password", ""))
    if not epasts or len(parole) < 8:
        return kludas_atbilde(400, "SLIKTS_PIEPRASIJUMS", "E-pasts obligāts; parolei vismaz 8 rakstzīmes")
    savienojums = iegut_savienojumu()
    if dbmod.user_by_email(savienojums, epasts):
        return kludas_atbilde(409, "KONFLIKTS", "Šis e-pasts jau reģistrēts")
    uid = jauns_id()
    dbmod.user_create(savienojums, uid, epasts, jauc_paroli(parole))
    token = izveidot_jwt({"lietotaja_id": uid, "epasts": epasts})
    return (
        jsonify({"piekļuves_zetons": token, "lietotajs": {"id": uid, "epasts": epasts}}),
        201,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# VIKTORĪNU MARŠRUTI
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/api/v1/quizzes")
@prasa_saimnieku
def list_quizzes():
    savienojums = iegut_savienojumu()
    saraksts = [
kvizes_saraksta_viens(q)
        for q in dbmod.quiz_list_for_owner(savienojums, g.lietotaja_id)
    ]
    return jsonify(saraksts)


@app.post("/api/v1/quizzes")
@prasa_saimnieku
def create_quiz():
    body = request.get_json(silent=True) or {}
    savienojums = iegut_savienojumu()
    qid = jauns_id()
    nosaukums = body.get("nosaukums", body.get("title", "Bez nosaukuma viktorīna"))
    quiz = {
        "id": qid,
        "owner_id": g.lietotaja_id,
        "title": nosaukums,
        "description": "",
        "status": "DRAFT",
        "createdAt": laika_zime(),
        "updatedAt": laika_zime(),
        "questions": [],
    }
    dbmod.quiz_insert(savienojums, quiz)
    ieladets = dbmod.quiz_load_full(savienojums, qid)
    return jsonify(kvizes_saraksta_viens(ieladets)), 201


@app.get("/api/v1/quizzes/<qid>")
@prasa_saimnieku
def get_quiz(qid):
    savienojums = iegut_savienojumu()
    quiz = dbmod.quiz_load_full(savienojums, qid)
    if not quiz:
        return kludas_atbilde(404, "NAV_ATRASTS", "Viktorīna nav atrasta")
    if quiz["owner_id"] != g.lietotaja_id:
        return kludas_atbilde(403, "NAV_PIEKLUVE", "Nav tiesību veikt šo darbību.")
    return jsonify(kvizes_izeja(quiz))


@app.patch("/api/v1/quizzes/<qid>")
@prasa_saimnieku
def patch_quiz(qid):
    savienojums = iegut_savienojumu()
    quiz = dbmod.quiz_load_full(savienojums, qid)
    if not quiz or quiz["owner_id"] != g.lietotaja_id:
        return kludas_atbilde(404, "NAV_ATRASTS", "Viktorīna nav atrasta")
    body = request.get_json(silent=True) or {}
    updates = {}
    if "nosaukums" in body:
        updates["title"] = body["nosaukums"]
    if "title" in body and "nosaukums" not in body:
        updates["title"] = body["title"]
    if "apraksts" in body:
        updates["description"] = body["apraksts"]
    if "description" in body and "apraksts" not in body:
        updates["description"] = body["description"]
    if "statuss" in body:
        updates["status"] = statuss_db(body["statuss"])
    if "status" in body and "statuss" not in body:
        updates["status"] = body["status"]
    now = laika_zime()
    if updates:
        dbmod.quiz_patch(savienojums, qid, updates, now)
    quiz = dbmod.quiz_load_full(savienojums, qid)
    return jsonify(kvizes_izeja(quiz))


@app.delete("/api/v1/quizzes/<qid>")
@prasa_saimnieku
def delete_quiz(qid):
    savienojums = iegut_savienojumu()
    quiz = dbmod.quiz_load_full(savienojums, qid)
    if not quiz or quiz["owner_id"] != g.lietotaja_id:
        return kludas_atbilde(404, "NAV_ATRASTS", "Viktorīna nav atrasta")
    dbmod.quiz_delete(savienojums, qid)
    return "", 204


# ═══════════════════════════════════════════════════════════════════════════════
# JAUTĀJUMU MARŠRUTI
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/quizzes/<qid>/questions")
@prasa_saimnieku
def add_question(qid):
    savienojums = iegut_savienojumu()
    quiz = dbmod.quiz_load_full(savienojums, qid)
    if not quiz or quiz["owner_id"] != g.lietotaja_id:
        return kludas_atbilde(404, "NAV_ATRASTS", "Viktorīna nav atrasta")
    body = request.get_json(silent=True) or {}
    raw_opts = body.get("atbilzu_varianti", body.get("answerOptions", []))
    text = (body.get("teksts") or body.get("text") or "").strip()
    if not text:
        return kludas_atbilde(400, "SLIKTS_PIEPRASIJUMS", "Jautājuma teksts obligāts")

    def _optteksts(o):
        if "teksts" in o:
            return o["teksts"]
        return o.get("text", "")

    def _optpareizi(o):
        if "pareizi" in o:
            return o.get("pareizi", False)
        return o.get("isCorrect", False)

    if not any(_optpareizi(o) for o in raw_opts):
        return kludas_atbilde(400, "SLIKTS_PIEPRASIJUMS", "Vismaz vienam variantam jābūt atzīmētam kā pareizam")
    question = {
        "id": jauns_id(),
        "quiz_id": qid,
        "text": text,
        "type": body.get("tips", body.get("type", "SINGLE_CHOICE")),
        "timeLimitSeconds": body.get("laika_limits_sekundes", body.get("timeLimitSeconds", 20)),
        "points": body.get("punkti", body.get("points", 1000)),
        "orderIndex": len(quiz["questions"]),
        "answerOptions": [
            {
                "id": jauns_id(),
                "text": _optteksts(o),
                "isCorrect": _optpareizi(o),
                "orderIndex": i,
            }
            for i, o in enumerate(raw_opts)
        ],
    }
    dbmod.question_insert(savienojums, question)
    now = laika_zime()
    savienojums.execute("UPDATE quizzes SET updated_at = ? WHERE id = ?", (now, qid))
    savienojums.commit()
    return jsonify(jautajuma_izeja(question)), 201


@app.patch("/api/v1/questions/<question_id>")
@prasa_saimnieku
def patch_question(question_id):
    savienojums = iegut_savienojumu()
    found = dbmod.question_find_quiz_for_owner(savienojums, question_id, g.lietotaja_id)
    if not found:
        return kludas_atbilde(404, "NAV_ATRASTS", "Jautājums nav atrasts")
    qz_id, _ = found
    body = request.get_json(silent=True) or {}
    text = None
    if "teksts" in body:
        text = body["teksts"]
    elif "text" in body:
        text = body["text"]
    tsl = None
    if "laika_limits_sekundes" in body:
        tsl = body["laika_limits_sekundes"]
    elif "timeLimitSeconds" in body:
        tsl = body["timeLimitSeconds"]
    pts = None
    if "punkti" in body:
        pts = body["punkti"]
    elif "points" in body:
        pts = body["points"]
    new_opts = None
    raw_opts = body.get("atbilzu_varianti", body.get("answerOptions"))
    if raw_opts is not None:

        def _optteksts(o):
            if "teksts" in o:
                return o["teksts"]
            return o.get("text", "")

        def _optpareizi(o):
            if "pareizi" in o:
                return o.get("pareizi", False)
            return o.get("isCorrect", False)

        new_opts = [
            {"id": jauns_id(), "text": _optteksts(o), "isCorrect": _optpareizi(o), "orderIndex": i2}
            for i2, o in enumerate(raw_opts)
        ]
    now = laika_zime()
    dbmod.question_patch(savienojums, question_id, text, tsl, pts, new_opts, qz_id, now)
    updated = dbmod.question_get(savienojums, question_id)
    if not updated:
        return kludas_atbilde(404, "NAV_ATRASTS", "Jautājums nav atrasts")
    return jsonify(jautajuma_izeja(updated))


@app.delete("/api/v1/questions/<question_id>")
@prasa_saimnieku
def delete_question(question_id):
    savienojums = iegut_savienojumu()
    if dbmod.question_delete_if_owner(savienojums, question_id, g.lietotaja_id, laika_zime()):
        return "", 204
    return kludas_atbilde(404, "NAV_ATRASTS", "Jautājums nav atrasts")


# ═══════════════════════════════════════════════════════════════════════════════
# SESIJAS UN SPĒLES MARŠRUTI
# ═══════════════════════════════════════════════════════════════════════════════


@app.post("/api/v1/sessions")
@prasa_saimnieku
def create_session():
    body = request.get_json(silent=True) or {}
    savienojums = iegut_savienojumu()
    quiz_id = body.get("viktorinas_id", body.get("quizId"))
    quiz = dbmod.quiz_load_full(savienojums, quiz_id)
    if not quiz:
        return kludas_atbilde(404, "NAV_ATRASTS", "Viktorīna nav atrasta")
    if quiz["owner_id"] != g.lietotaja_id:
        return kludas_atbilde(403, "NAV_PIEKLUVE", "Nav tiesību veikt šo darbību.")
    if quiz["status"] != "PUBLISHED":
        return kludas_atbilde(400, "SLIKTS_PIEPRASIJUMS", "Var sākt tikai publicētas viktorīnas")
    sid = jauns_id()
    pin = izveidot_pin_kodu()
    session = {
        "id": sid,
        "pin": pin,
        "quiz_id": quiz_id,
        "host_id": g.lietotaja_id,
        "status": "WAITING",
        "current_question_index": -1,
        "question_start_time": None,
        "createdAt": laika_zime(),
        "participants": {},
    }
    dbmod.session_insert(savienojums, session)
    with sse_lock:
        sse_subscribers[sid] = []
    return jsonify({"sesijas_id": sid, "pina_kods": pin}), 201


@app.get("/api/v1/sessions/<sid>")
@prasa_saimnieku
def get_session(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session or session["host_id"] != g.lietotaja_id:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")
    quiz = dbmod.quiz_load_full(savienojums, session["quiz_id"]) or {}
    return jsonify(
        {
            "id": sid,
            "pina_kods": session["pin"],
            "statuss": statuss_api(session["status"]),
            "viktorinas_nosaukums": quiz.get("title", ""),
            "dalibnieku_skaits": len(session["participants"]),
        }
    )


@app.post("/api/v1/join")
def join_by_pin():
    body = request.get_json(silent=True) or {}
    pin = str(body.get("pina_kods", body.get("pin", ""))).strip()
    savienojums = iegut_savienojumu()
    session = dbmod.session_by_pin_waiting(savienojums, pin)
    if not session:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nepieņem jaunus spēlētājus")
    quiz = dbmod.quiz_load_full(savienojums, session["quiz_id"]) or {}
    return jsonify({"sesijas_id": session["id"], "viktorinas_nosaukums": quiz.get("title", "")})


@app.post("/api/v1/join/<sid>/identify")
def identify(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")
    if session["status"] != "WAITING":
        return kludas_atbilde(400, "SLIKTS_PIEPRASIJUMS", "Sesija nepieņem jaunus spēlētājus")
    body = request.get_json(silent=True) or {}
    nickname = (body.get("segvards") or body.get("nickname") or "").strip()
    if not nickname:
        return kludas_atbilde(400, "SLIKTS_PIEPRASIJUMS", "Segvārds obligāts")
    if any(p["nickname"] == nickname for p in session["participants"].values()):
        return kludas_atbilde(409, "KONFLIKTS", "Segvārds jau aizņemts")
    pid = jauns_id()
    dbmod.participant_insert(savienojums, sid, pid, nickname)
    session = dbmod.session_load(savienojums, sid)
    token = izveidot_jwt({"dalibnieka_id": pid, "sesijas_id": sid})
    izplatit_sse(sid, "gaiditava_dalibnieks_pievienojies", {"id": pid, "segvards": nickname})
    izplatit_sse(
        sid,
        "gaiditava_dalibnieki",
        {
            "dalibnieki": [
                {"id": p["id"], "segvards": p["nickname"]} for p in session["participants"].values()
            ]
        },
    )
    return jsonify({"dalibnieka_zetons": token, "dalibnieka_id": pid, "segvards": nickname})


@app.post("/api/v1/sessions/<sid>/start")
@prasa_saimnieku
def start_game(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session or session["host_id"] != g.lietotaja_id:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")
    if not session["participants"]:
        return kludas_atbilde(400, "SLIKTS_PIEPRASIJUMS", "Nepieciešams vismaz viens dalībnieks")
    dbmod.session_update_fields(savienojums, sid, status="ACTIVE")
    izplatit_sse(sid, "spele_sakusies", {"sesijas_id": sid})
    return _send_next_question(sid)


@app.post("/api/v1/sessions/<sid>/next-question")
@prasa_saimnieku
def next_question(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session or session["host_id"] != g.lietotaja_id:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")
    return _send_next_question(sid)


def _send_next_question(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")
    quiz = dbmod.quiz_load_full(savienojums, session["quiz_id"])
    idx = session["current_question_index"] + 1
    print(f"[JAUTĀJUMS] Sesija={sid} pāriet uz jautājuma indeksu={idx} (kopā={len(quiz['questions'])})")
    if idx >= len(quiz["questions"]):
        print(f"[JAUTĀJUMS] Nav vairāk jautājumu — beidz spēli sesijai={sid}")
        return _end_game(sid)
    session["current_question_index"] = idx
    session["question_start_time"] = time.time()
    dbmod.session_update_fields(
        savienojums,
        sid,
        current_question_index=idx,
        question_start_time=session["question_start_time"],
    )
    q = quiz["questions"][idx]
    print(f"[JAUTĀJUMS] Sūta spele_jautajums_sakas id={q['id']} laikaLimits={q['timeLimitSeconds']}s")
    izplatit_sse(
        sid,
        "spele_jautajums_sakas",
        {
            "jautajuma_indekss": idx,
            "jautajumu_kopskaits": len(quiz["questions"]),
            "id": q["id"],
            "teksts": q["text"],
            "tips": q["type"],
            "laika_limits_sekundes": q["timeLimitSeconds"],
            "punkti": q["points"],
            "atlikusais_laiks_ms": q["timeLimitSeconds"] * 1000,
            "atbilzu_varianti": [{"id": o["id"], "teksts": o["text"]} for o in q["answerOptions"]],
            "atbilzu_varianti_ar_pareizo": [variants_izeja(o) for o in q["answerOptions"]],
        },
    )
    return jsonify({"jautajuma_indekss": idx, "jautajuma_id": q["id"]})


def _end_question_logic(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session:
        print(f"[JAUT-BEIGAS-LOĢIKA] Sesija {sid} nav atrasta.")
        return None

    quiz = dbmod.quiz_load_full(savienojums, session["quiz_id"])
    idx = session["current_question_index"]

    if idx < 0 or idx >= len(quiz["questions"]):
        print(f"[JAUT-BEIGAS-LOĢIKA] Nederīgs jautājuma indekss={idx} sesijai={sid}.")
        return None

    q = quiz["questions"][idx]
    correct_ids = {o["id"] for o in q["answerOptions"] if o["isCorrect"]}
    total_participants = len(session["participants"])
    total_answers = sum(1 for p in session["participants"].values() if q["id"] in p["answers"])

    print(f"[JAUT-BEIGAS-LOĢIKA] sesija={sid} jaut={q['id']} atbildējuši={total_answers}/{total_participants}")

    answer_stats = {}
    for o in q["answerOptions"]:
        answer_stats[o["id"]] = sum(
            1 for p in session["participants"].values() if p["answers"].get(q["id"]) == o["id"]
        )

    print(f"[JAUT-BEIGAS-LOĢIKA] Sūta spele_jautajums_beidzas sesijai={sid}")
    izplatit_sse(
        sid,
        "spele_jautajums_beidzas",
        {
            "jautajuma_id": q["id"],
            "pareizo_opciju_id": list(correct_ids),
            "statistika": {
                "kopat_atbildes": total_answers,
                "kopat_dalibnieki": total_participants,
                "pec_opcijas": answer_stats,
            },
            "atbilzu_varianti": [variants_izeja(o) for o in q["answerOptions"]],
        },
    )

    leaderboard = _build_leaderboard(session)
    izplatit_sse(sid, "spele_lideru_tabula", {"lideru_tabula": leaderboard})

    return {"statistika": {"kopat_atbildes": total_answers}, "lideru_tabula": leaderboard}


@app.post("/api/v1/sessions/<sid>/end-question")
@prasa_saimnieku
def end_question(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session or session["host_id"] != g.lietotaja_id:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")

    print(f"[JAUT-BEIGAS] Izsaukta sesijai={sid} saimnieks={g.lietotaja_id}")
    result = _end_question_logic(sid)
    if not result:
        print("[JAUT-BEIGAS] _end_question_logic atgrieza None — nav aktīva jautājuma?")
        return kludas_atbilde(400, "SLIKTS_PIEPRASIJUMS", "Nav aktīva jautājuma")

    print(f"[JAUT-BEIGAS] Gatavs. kopā atbildes={result['statistika']['kopat_atbildes']}")
    return jsonify(result)


@app.post("/api/v1/sessions/<sid>/end-game")
@prasa_saimnieku
def end_game_route(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session or session["host_id"] != g.lietotaja_id:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")
    return _end_game(sid)


def _end_game(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")
    dbmod.session_update_fields(savienojums, sid, status="FINISHED")
    session = dbmod.session_load(savienojums, sid)
    leaderboard = _build_leaderboard(session)
    izplatit_sse(sid, "spele_beigusies", {"lideru_tabula": leaderboard})
    return jsonify({"statuss": "PABEIGTS", "lideru_tabula": leaderboard})


def _build_leaderboard(session):
    ranked = sorted(session["participants"].values(), key=lambda p: p["score"], reverse=True)
    return [
        {"vieta": i + 1, "id": p["id"], "segvards": p["nickname"], "punkti": p["score"]}
        for i, p in enumerate(ranked)
    ]


@app.post("/api/v1/answer")
@prasa_dalibnieku
def submit_answer():
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, g.sesijas_id)
    if not session or session["status"] != "ACTIVE":
        return kludas_atbilde(400, "NAV_AKTIVS", "Spēle pašlaik nenotiek")
    participant = session["participants"].get(g.dalibnieka_id)
    if not participant:
        return kludas_atbilde(404, "NAV_ATRASTS", "Dalībnieks nav atrasts")

    quiz = dbmod.quiz_load_full(savienojums, session["quiz_id"])
    idx = session["current_question_index"]
    q = quiz["questions"][idx]
    body = request.get_json(silent=True) or {}
    option_id = body.get("opcijas_id", body.get("optionId"))

    print(f"[ATBILDE] dalībnieks={g.dalibnieka_id} jautājums={q['id']} opcija={option_id}")

    if q["id"] in participant["answers"]:
        print(f"[ATBILDE] Jau atbildēts — dublikāts noraidīts dalībniekam={g.dalibnieka_id}")
        return kludas_atbilde(400, "JAU_ATBILDETS", "Šo jautājumu jau esi atbildējis")

    answers = dict(participant["answers"])
    answers[q["id"]] = option_id
    correct_option_ids = {o["id"] for o in q["answerOptions"] if o["isCorrect"]}
    is_correct = option_id is not None and option_id in correct_option_ids
    elapsed = time.time() - (session["question_start_time"] or time.time())
    time_limit = q["timeLimitSeconds"]
    speed_bonus = max(0, 1 - elapsed / time_limit)
    points_earned = int(q["points"] * speed_bonus) if is_correct else 0
    new_score = participant["score"] + points_earned

    participant["answers"] = answers
    participant["score"] = new_score
    dbmod.participant_update(savienojums, g.dalibnieka_id, new_score, answers)

    print(
        f"[ATBILDE] pareizi={is_correct} pagājis={elapsed:.1f}s punkti={points_earned} summa={new_score}"
    )

    izplatit_sse(
        g.sesijas_id,
        "atbilde_apstiprinata",
        {
            "dalibnieka_id": g.dalibnieka_id,
            "jautajuma_id": q["id"],
            "pareizi": is_correct,
            "iegutie_punkti": points_earned,
            "kopejie_punkti": new_score,
            "pagajusas_sekundes": round(elapsed, 1),
        },
    )

    session = dbmod.session_load(savienojums, g.sesijas_id)
    total_participants = len(session["participants"])
    total_answers = sum(1 for p in session["participants"].values() if q["id"] in p["answers"])
    print(f"[ATBILDE] Progresss: {total_answers}/{total_participants} dalībnieki atbildējuši")

    if total_participants > 0 and total_answers >= total_participants:
        print(f"[ATBILDE] Visi atbildējuši — automātiski beidz jautājumu sesijai={g.sesijas_id}")
        _end_question_logic(g.sesijas_id)

    return jsonify(
        {
            "pareizi": is_correct,
            "iegutie_punkti": points_earned,
            "kopejie_punkti": new_score,
            "pagajusas_sekundes": round(elapsed, 1),
        }
    )


@app.get("/api/v1/participant/state")
@prasa_dalibnieku
def participant_state():
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, g.sesijas_id)
    if not session:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")
    participant = session["participants"].get(g.dalibnieka_id)
    quiz = dbmod.quiz_load_full(savienojums, session["quiz_id"])
    current_q = None
    has_answered = False
    if session["current_question_index"] >= 0:
        q = quiz["questions"][session["current_question_index"]]
        elapsed = time.time() - (session["question_start_time"] or time.time())
        remaining_ms = max(0, int((q["timeLimitSeconds"] - elapsed) * 1000))
        has_answered = q["id"] in participant["answers"]
        current_q = {
            "id": q["id"],
            "teksts": q["text"],
            "tips": q["type"],
            "laika_limits_sekundes": q["timeLimitSeconds"],
            "atlikusais_laiks_ms": remaining_ms,
            "atbilzu_varianti": [{"id": o["id"], "teksts": o["text"]} for o in q["answerOptions"]],
            "jautajuma_indekss": session["current_question_index"],
            "jautajumu_kopskaits": len(quiz["questions"]),
        }
    return jsonify(
        {
            "sesijas_stavoklis": {"statuss": statuss_api(session["status"])},
            "pasreizejais_jautajums": current_q,
            "atbildets_uz_pasreizejo": has_answered,
            "punkti": participant["score"] if participant else 0,
        }
    )


@app.get("/api/v1/sessions/<sid>/events")
def sse_stream(sid):
    savienojums = iegut_savienojumu()
    session = dbmod.session_load(savienojums, sid)
    if not session:
        return kludas_atbilde(404, "NAV_ATRASTS", "Sesija nav atrasta")

    q_sse = queue.Queue(maxsize=100)
    with sse_lock:
        sse_subscribers.setdefault(sid, []).append(q_sse)

    quiz = dbmod.quiz_load_full(savienojums, session["quiz_id"]) or {}
    initial = json.dumps(
        {
            "notikums": "sesijas_stavoklis",
            "dati": {
                "statuss": statuss_api(session["status"]),
                "pina_kods": session["pin"],
                "viktorinas_nosaukums": quiz.get("title", ""),
                "dalibnieki": [
                    {"id": p["id"], "segvards": p["nickname"]} for p in session["participants"].values()
                ],
            },
        }
    )

    @stream_with_context
    def generate():
        yield f"data: {initial}\n\n"
        while True:
            try:
                payload = q_sse.get(timeout=25)
                yield f"data: {payload}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# LAPPU MARŠRUTI (SPA)
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/login")
def page_login():
    return render_template("index.html")


@app.get("/<path:path>")
def spa(path):
    return render_template("index.html")


if __name__ == "__main__":
    print("🎮  QuizBlitz serveris — http://localhost:5000")
    print(f"💾  Datubāze: {DATABASE_PATH}")
    print("📧  Demo pieraksts: demo@quiz.com / password123")
    app.run(debug=True, threaded=True)
