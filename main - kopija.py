"""
Quiz Platform — Flask Backend
Stress Release aesthetic • JWT auth • SSE real-time • In-memory state
"""

import json
import uuid
import time
import queue
import random
import string
import threading
from datetime import datetime, timedelta
from functools import wraps

import jwt
from flask import (
    Flask, request, jsonify, render_template,
    Response, stream_with_context, g
)

# ─── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = "stress-release-secret-2026"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# ─── In-memory stores ─────────────────────────────────────────────────────────
users   = {}   # email → {id, email, password_hash}
quizzes = {}   # quiz_id → quiz dict
sessions = {}  # session_id → session dict
participants = {}  # participant_id → participant dict

# SSE subscriber queues: session_id → list of Queue objects
sse_subscribers: dict[str, list[queue.Queue]] = {}
sse_lock = threading.Lock()


# ─── Helpers ──────────────────────────────────────────────────────────────────
def new_id(): return str(uuid.uuid4())

def ts(): return datetime.utcnow().isoformat() + "Z"

def make_pin():
    return "".join(random.choices(string.digits, k=6))

def hash_pw(pw):
    import hashlib
    return hashlib.sha256(pw.encode()).hexdigest()

def make_jwt(payload: dict) -> str:
    payload["exp"] = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm=JWT_ALGORITHM)

def decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, app.config["SECRET_KEY"], algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None

def err(status, code, message):
    return jsonify({"statusCode": status, "code": code, "message": message, "timestamp": ts()}), status

def broadcast(session_id: str, event: str, data: dict):
    """Push SSE event to all subscribers of a session."""
    payload = json.dumps({"event": event, "data": data})
    with sse_lock:
        subs = sse_subscribers.get(session_id, [])
        dead = []
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            subs.remove(q)

# ─── Auth decorators ──────────────────────────────────────────────────────────
def require_host(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return err(401, "UNAUTHORIZED", "Missing token")
        token = auth.split(" ", 1)[1]
        payload = decode_jwt(token)
        if not payload or "user_id" not in payload:
            return err(401, "UNAUTHORIZED", "Invalid or expired token")
        g.user_id = payload["user_id"]
        g.user_email = payload.get("email", "")
        return f(*args, **kwargs)
    return wrapper

def require_participant(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth.split(" ", 1)[1] if auth.startswith("Bearer ") else ""
        payload = decode_jwt(token)
        if not payload or "participant_id" not in payload:
            return err(401, "UNAUTHORIZED", "Invalid participant token")
        g.participant_id = payload["participant_id"]
        g.session_id = payload.get("session_id")
        return f(*args, **kwargs)
    return wrapper


# ─── Seed demo data ───────────────────────────────────────────────────────────
def seed():
    uid = new_id()
    users["demo@quiz.com"] = {"id": uid, "email": "demo@quiz.com", "password_hash": hash_pw("password123")}
    qid = new_id()
    q1, q2, q3 = new_id(), new_id(), new_id()
    a1, a2, a3, a4 = new_id(), new_id(), new_id(), new_id()
    a5, a6, a7, a8 = new_id(), new_id(), new_id(), new_id()
    at, af = new_id(), new_id()
    quizzes[qid] = {
        "id": qid, "owner_id": uid, "title": "Tech Trivia Blitz",
        "description": "Test your nerdy knowledge!", "status": "PUBLISHED",
        "createdAt": ts(), "updatedAt": ts(),
        "questions": [
            {
                "id": q1, "quiz_id": qid, "text": "What does CPU stand for?",
                "type": "SINGLE_CHOICE", "timeLimitSeconds": 20, "points": 1000,
                "orderIndex": 0,
                "answerOptions": [
                    {"id": a1, "text": "Central Processing Unit", "isCorrect": True, "orderIndex": 0},
                    {"id": a2, "text": "Computer Personal Unit", "isCorrect": False, "orderIndex": 1},
                    {"id": a3, "text": "Core Power Utility", "isCorrect": False, "orderIndex": 2},
                    {"id": a4, "text": "Central Program Utility", "isCorrect": False, "orderIndex": 3},
                ]
            },
            {
                "id": q2, "quiz_id": qid, "text": "Python is an interpreted language.",
                "type": "TRUE_FALSE", "timeLimitSeconds": 15, "points": 500,
                "orderIndex": 1,
                "answerOptions": [
                    {"id": at, "text": "True", "isCorrect": True, "orderIndex": 0},
                    {"id": af, "text": "False", "isCorrect": False, "orderIndex": 1},
                ]
            },
            {
                "id": q3, "quiz_id": qid, "text": "Which company created JavaScript?",
                "type": "SINGLE_CHOICE", "timeLimitSeconds": 20, "points": 1000,
                "orderIndex": 2,
                "answerOptions": [
                    {"id": a5, "text": "Netscape", "isCorrect": True, "orderIndex": 0},
                    {"id": a6, "text": "Microsoft", "isCorrect": False, "orderIndex": 1},
                    {"id": a7, "text": "Google", "isCorrect": False, "orderIndex": 2},
                    {"id": a8, "text": "Sun Microsystems", "isCorrect": False, "orderIndex": 3},
                ]
            },
        ]
    }

seed()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    email = body.get("email", "").lower().strip()
    password = body.get("password", "")
    user = users.get(email)
    if not user or user["password_hash"] != hash_pw(password):
        return err(401, "INVALID_CREDENTIALS", "Invalid email or password")
    token = make_jwt({"user_id": user["id"], "email": email})
    return jsonify({"accessToken": token, "user": {"id": user["id"], "email": email}})


@app.post("/api/v1/auth/register")
def register():
    body = request.get_json(silent=True) or {}
    email = body.get("email", "").lower().strip()
    password = body.get("password", "")
    if not email or len(password) < 8:
        return err(400, "BAD_REQUEST", "Email required and password must be at least 8 characters")
    if email in users:
        return err(409, "CONFLICT", "Email already registered")
    uid = new_id()
    users[email] = {"id": uid, "email": email, "password_hash": hash_pw(password)}
    token = make_jwt({"user_id": uid, "email": email})
    return jsonify({"accessToken": token, "user": {"id": uid, "email": email}}), 201


# ═══════════════════════════════════════════════════════════════════════════════
# QUIZ ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/quizzes")
@require_host
def list_quizzes():
    owned = [
        {**q, "_count": {"questions": len(q["questions"])}, "questions": undefined_skip(q)}
        for q in quizzes.values()
        if q["owner_id"] == g.user_id
    ]
    return jsonify(owned)

def undefined_skip(q):
    # Return quiz without full question details for list view
    return [{"id": x["id"], "text": x["text"][:60]} for x in q["questions"]]


@app.post("/api/v1/quizzes")
@require_host
def create_quiz():
    body = request.get_json(silent=True) or {}
    qid = new_id()
    quiz = {
        "id": qid, "owner_id": g.user_id,
        "title": body.get("title", "Untitled Quiz"),
        "description": "", "status": "DRAFT",
        "createdAt": ts(), "updatedAt": ts(),
        "questions": []
    }
    quizzes[qid] = quiz
    return jsonify({**quiz, "_count": {"questions": 0}}), 201


@app.get("/api/v1/quizzes/<qid>")
@require_host
def get_quiz(qid):
    quiz = quizzes.get(qid)
    if not quiz:
        return err(404, "NOT_FOUND", "Quiz not found")
    if quiz["owner_id"] != g.user_id:
        return err(403, "FORBIDDEN", "You don't have permission to do that.")
    return jsonify({**quiz, "_count": {"questions": len(quiz["questions"])}})


@app.patch("/api/v1/quizzes/<qid>")
@require_host
def patch_quiz(qid):
    quiz = quizzes.get(qid)
    if not quiz or quiz["owner_id"] != g.user_id:
        return err(404, "NOT_FOUND", "Quiz not found")
    body = request.get_json(silent=True) or {}
    for field in ("title", "description", "status"):
        if field in body:
            quiz[field] = body[field]
    quiz["updatedAt"] = ts()
    return jsonify(quiz)


@app.delete("/api/v1/quizzes/<qid>")
@require_host
def delete_quiz(qid):
    quiz = quizzes.get(qid)
    if not quiz or quiz["owner_id"] != g.user_id:
        return err(404, "NOT_FOUND", "Quiz not found")
    del quizzes[qid]
    return "", 204


# ═══════════════════════════════════════════════════════════════════════════════
# QUESTION ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/quizzes/<qid>/questions")
@require_host
def add_question(qid):
    quiz = quizzes.get(qid)
    if not quiz or quiz["owner_id"] != g.user_id:
        return err(404, "NOT_FOUND", "Quiz not found")
    body = request.get_json(silent=True) or {}
    text = body.get("text", "").strip()
    if not text:
        return err(400, "BAD_REQUEST", "Question text is required")
    options = body.get("answerOptions", [])
    if not any(o.get("isCorrect") for o in options):
        return err(400, "BAD_REQUEST", "At least one option must be marked correct")
    question = {
        "id": new_id(), "quiz_id": qid,
        "text": text,
        "type": body.get("type", "SINGLE_CHOICE"),
        "timeLimitSeconds": body.get("timeLimitSeconds", 20),
        "points": body.get("points", 1000),
        "orderIndex": len(quiz["questions"]),
        "answerOptions": [
            {"id": new_id(), "text": o["text"], "isCorrect": o.get("isCorrect", False), "orderIndex": i}
            for i, o in enumerate(options)
        ]
    }
    quiz["questions"].append(question)
    quiz["updatedAt"] = ts()
    return jsonify(question), 201


@app.patch("/api/v1/questions/<question_id>")
@require_host
def patch_question(question_id):
    for quiz in quizzes.values():
        if quiz["owner_id"] != g.user_id:
            continue
        for i, q in enumerate(quiz["questions"]):
            if q["id"] == question_id:
                body = request.get_json(silent=True) or {}
                for field in ("text", "timeLimitSeconds", "points"):
                    if field in body:
                        q[field] = body[field]
                if "answerOptions" in body:
                    q["answerOptions"] = [
                        {"id": new_id(), "text": o["text"], "isCorrect": o.get("isCorrect", False), "orderIndex": i2}
                        for i2, o in enumerate(body["answerOptions"])
                    ]
                quiz["updatedAt"] = ts()
                return jsonify(q)
    return err(404, "NOT_FOUND", "Question not found")


@app.delete("/api/v1/questions/<question_id>")
@require_host
def delete_question(question_id):
    for quiz in quizzes.values():
        if quiz["owner_id"] != g.user_id:
            continue
        before = len(quiz["questions"])
        quiz["questions"] = [q for q in quiz["questions"] if q["id"] != question_id]
        if len(quiz["questions"]) < before:
            quiz["updatedAt"] = ts()
            return "", 204
    return err(404, "NOT_FOUND", "Question not found")


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/sessions")
@require_host
def create_session():
    body = request.get_json(silent=True) or {}
    quiz_id = body.get("quizId")
    quiz = quizzes.get(quiz_id)
    if not quiz:
        return err(404, "NOT_FOUND", "Quiz not found")
    if quiz["owner_id"] != g.user_id:
        return err(403, "FORBIDDEN", "You don't have permission to do that.")
    if quiz["status"] != "PUBLISHED":
        return err(400, "BAD_REQUEST", "Only published quizzes can be started")
    sid = new_id()
    pin = make_pin()
    sessions[sid] = {
        "id": sid, "pin": pin, "quiz_id": quiz_id, "host_id": g.user_id,
        "status": "WAITING",  # WAITING | ACTIVE | FINISHED
        "current_question_index": -1,
        "question_start_time": None,
        "createdAt": ts(),
        "participants": {},   # participant_id → {id, nickname, score, answers:{q_id: opt_id}}
    }
    with sse_lock:
        sse_subscribers[sid] = []
    return jsonify({"sessionId": sid, "pin": pin}), 201


@app.get("/api/v1/sessions/<sid>")
@require_host
def get_session(sid):
    session = sessions.get(sid)
    if not session or session["host_id"] != g.user_id:
        return err(404, "NOT_FOUND", "Session not found")
    quiz = quizzes.get(session["quiz_id"], {})
    return jsonify({
        "id": sid, "pin": session["pin"], "status": session["status"],
        "quizTitle": quiz.get("title", ""),
        "participantCount": len(session["participants"])
    })


# ─── Player join ──────────────────────────────────────────────────────────────

@app.post("/api/v1/join")
def join_by_pin():
    body = request.get_json(silent=True) or {}
    pin = str(body.get("pin", "")).strip()
    session = next((s for s in sessions.values() if s["pin"] == pin and s["status"] == "WAITING"), None)
    if not session:
        return err(404, "NOT_FOUND", "Session not accepting new players")
    quiz = quizzes.get(session["quiz_id"], {})
    return jsonify({"sessionId": session["id"], "quizTitle": quiz.get("title", "")})


@app.post("/api/v1/join/<sid>/identify")
def identify(sid):
    session = sessions.get(sid)
    if not session:
        return err(404, "NOT_FOUND", "Session not found")
    if session["status"] != "WAITING":
        return err(400, "BAD_REQUEST", "Session is not accepting new players")
    body = request.get_json(silent=True) or {}
    nickname = body.get("nickname", "").strip()
    if not nickname:
        return err(400, "BAD_REQUEST", "Nickname is required")
    if any(p["nickname"] == nickname for p in session["participants"].values()):
        return err(409, "CONFLICT", "Nickname already taken")
    pid = new_id()
    session["participants"][pid] = {"id": pid, "nickname": nickname, "score": 0, "answers": {}, "connected": True}
    token = make_jwt({"participant_id": pid, "session_id": sid})
    broadcast(sid, "lobby:participant_joined", {"id": pid, "nickname": nickname})
    broadcast(sid, "lobby:participant_list", {
        "participants": [{"id": p["id"], "nickname": p["nickname"]} for p in session["participants"].values()]
    })
    return jsonify({"participantToken": token, "participantId": pid, "nickname": nickname})


# ─── Game control (host emits via REST since no WS) ───────────────────────────

@app.post("/api/v1/sessions/<sid>/start")
@require_host
def start_game(sid):
    session = sessions.get(sid)
    if not session or session["host_id"] != g.user_id:
        return err(404, "NOT_FOUND", "Session not found")
    if not session["participants"]:
        return err(400, "BAD_REQUEST", "Need at least one participant")
    session["status"] = "ACTIVE"
    broadcast(sid, "game:started", {"sessionId": sid})
    return _send_next_question(sid)


@app.post("/api/v1/sessions/<sid>/next-question")
@require_host
def next_question(sid):
    session = sessions.get(sid)
    if not session or session["host_id"] != g.user_id:
        return err(404, "NOT_FOUND", "Session not found")
    return _send_next_question(sid)


def _send_next_question(sid):
    session = sessions[sid]
    quiz = quizzes.get(session["quiz_id"])
    idx = session["current_question_index"] + 1
    if idx >= len(quiz["questions"]):
        return _end_game(sid)
    session["current_question_index"] = idx
    session["question_start_time"] = time.time()
    q = quiz["questions"][idx]
    broadcast(sid, "game:question_started", {
        "questionIndex": idx,
        "totalQuestions": len(quiz["questions"]),
        "id": q["id"],
        "text": q["text"],
        "type": q["type"],
        "timeLimitSeconds": q["timeLimitSeconds"],
        "points": q["points"],
        "timeRemainingMs": q["timeLimitSeconds"] * 1000,
        "answerOptions": [{"id": o["id"], "text": o["text"]} for o in q["answerOptions"]],
        "answerOptionsWithCorrect": q["answerOptions"],  # host only
    })
    return jsonify({"questionIndex": idx, "questionId": q["id"]})


@app.post("/api/v1/sessions/<sid>/end-question")
@require_host
def end_question(sid):
    session = sessions.get(sid)
    if not session or session["host_id"] != g.user_id:
        return err(404, "NOT_FOUND", "Session not found")
    quiz = quizzes.get(session["quiz_id"])
    idx = session["current_question_index"]
    if idx < 0 or idx >= len(quiz["questions"]):
        return err(400, "BAD_REQUEST", "No active question")
    q = quiz["questions"][idx]
    correct_ids = {o["id"] for o in q["answerOptions"] if o["isCorrect"]}
    total_participants = len(session["participants"])
    total_answers = sum(1 for p in session["participants"].values() if q["id"] in p["answers"])
    answer_stats = {}
    for o in q["answerOptions"]:
        answer_stats[o["id"]] = sum(
            1 for p in session["participants"].values()
            if p["answers"].get(q["id"]) == o["id"]
        )
    broadcast(sid, "game:question_ended", {
        "questionId": q["id"],
        "correctOptionIds": list(correct_ids),
        "stats": {
            "totalAnswers": total_answers,
            "totalParticipants": total_participants,
            "byOption": answer_stats
        },
        "answerOptions": q["answerOptions"],
    })
    leaderboard = _build_leaderboard(session)
    broadcast(sid, "game:leaderboard", {"leaderboard": leaderboard})
    return jsonify({"stats": {"totalAnswers": total_answers}, "leaderboard": leaderboard})


@app.post("/api/v1/sessions/<sid>/end-game")
@require_host
def end_game_route(sid):
    session = sessions.get(sid)
    if not session or session["host_id"] != g.user_id:
        return err(404, "NOT_FOUND", "Session not found")
    return _end_game(sid)


def _end_game(sid):
    session = sessions[sid]
    session["status"] = "FINISHED"
    leaderboard = _build_leaderboard(session)
    broadcast(sid, "game:ended", {"leaderboard": leaderboard})
    return jsonify({"status": "FINISHED", "leaderboard": leaderboard})


def _build_leaderboard(session):
    ranked = sorted(session["participants"].values(), key=lambda p: p["score"], reverse=True)
    return [{"rank": i + 1, "id": p["id"], "nickname": p["nickname"], "score": p["score"]}
            for i, p in enumerate(ranked)]


# ─── Player answer ────────────────────────────────────────────────────────────

@app.post("/api/v1/answer")
@require_participant
def submit_answer():
    session = sessions.get(g.session_id)
    if not session or session["status"] != "ACTIVE":
        return err(400, "NOT_ACTIVE", "The game is not running right now")
    participant = session["participants"].get(g.participant_id)
    if not participant:
        return err(404, "NOT_FOUND", "Participant not found")
    quiz = quizzes.get(session["quiz_id"])
    idx = session["current_question_index"]
    q = quiz["questions"][idx]
    body = request.get_json(silent=True) or {}
    option_id = body.get("optionId")
    if q["id"] in participant["answers"]:
        return err(400, "ALREADY_ANSWERED", "You already answered this question")
    participant["answers"][q["id"]] = option_id
    correct_option_ids = {o["id"] for o in q["answerOptions"] if o["isCorrect"]}
    is_correct = option_id in correct_option_ids
    elapsed = time.time() - (session["question_start_time"] or time.time())
    time_limit = q["timeLimitSeconds"]
    speed_bonus = max(0, 1 - elapsed / time_limit)
    points_earned = int(q["points"] * speed_bonus) if is_correct else 0
    participant["score"] += points_earned
    broadcast(g.session_id, "answer:acknowledged", {
        "participantId": g.participant_id,
        "questionId": q["id"],
        "isCorrect": is_correct,
        "pointsEarned": points_earned,
        "totalScore": participant["score"],
        "elapsedSeconds": round(elapsed, 1),
    })
    return jsonify({
        "isCorrect": is_correct,
        "pointsEarned": points_earned,
        "totalScore": participant["score"],
        "elapsedSeconds": round(elapsed, 1),
    })


# ─── Participant state (for reconnect) ────────────────────────────────────────

@app.get("/api/v1/participant/state")
@require_participant
def participant_state():
    session = sessions.get(g.session_id)
    if not session:
        return err(404, "NOT_FOUND", "Session not found")
    participant = session["participants"].get(g.participant_id)
    quiz = quizzes.get(session["quiz_id"])
    current_q = None
    has_answered = False
    if session["current_question_index"] >= 0:
        q = quiz["questions"][session["current_question_index"]]
        elapsed = time.time() - (session["question_start_time"] or time.time())
        remaining_ms = max(0, int((q["timeLimitSeconds"] - elapsed) * 1000))
        has_answered = q["id"] in participant["answers"]
        current_q = {
            "id": q["id"], "text": q["text"], "type": q["type"],
            "timeLimitSeconds": q["timeLimitSeconds"],
            "timeRemainingMs": remaining_ms,
            "answerOptions": [{"id": o["id"], "text": o["text"]} for o in q["answerOptions"]],
            "questionIndex": session["current_question_index"],
            "totalQuestions": len(quiz["questions"]),
        }
    return jsonify({
        "sessionState": {"status": session["status"]},
        "currentQuestion": current_q,
        "hasAnsweredCurrentQuestion": has_answered,
        "score": participant["score"] if participant else 0,
    })


# ─── SSE stream ───────────────────────────────────────────────────────────────

@app.get("/api/v1/sessions/<sid>/events")
def sse_stream(sid):
    """Server-Sent Events endpoint. Both host and player connect here."""
    session = sessions.get(sid)
    if not session:
        return err(404, "NOT_FOUND", "Session not found")

    q = queue.Queue(maxsize=100)
    with sse_lock:
        sse_subscribers.setdefault(sid, []).append(q)

    # Send initial state
    quiz = quizzes.get(session["quiz_id"], {})
    initial = json.dumps({
        "event": "session:state",
        "data": {
            "status": session["status"],
            "pin": session["pin"],
            "quizTitle": quiz.get("title", ""),
            "participants": [
                {"id": p["id"], "nickname": p["nickname"]}
                for p in session["participants"].values()
            ]
        }
    })

    @stream_with_context
    def generate():
        yield f"data: {initial}\n\n"
        while True:
            try:
                payload = q.get(timeout=25)
                yield f"data: {payload}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"  # keep-alive

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE ROUTES
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
    print("🎮  Quiz Platform running at http://localhost:5000")
    print("📧  Demo login: demo@quiz.com / password123")
    app.run(debug=True, threaded=True)