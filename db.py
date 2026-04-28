"""
Datu piekļuves slānis QuizBlitz (SQLite).

SQL tabulu lauku nosaukumi ir angliski (saderība ar esošu shēmu).
Funkciju parametri un iekšējās darbības dokumentētas latviski koda komentāros.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def connect(datnes_cels: str) -> sqlite3.Connection:
    """Atver datubāzes failu un ieslēdz FOREIGN KEY ievērošanu."""
    savienojums = sqlite3.connect(datnes_cels, check_same_thread=False)
    savienojums.row_factory = sqlite3.Row
    savienojums.execute("PRAGMA foreign_keys = ON")
    return savienojums


def init_schema(savienojums: sqlite3.Connection) -> None:
    savienojums.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quizzes (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'DRAFT',
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (owner_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            quiz_id TEXT NOT NULL,
            text TEXT,
            type TEXT,
            time_limit_seconds INTEGER,
            points INTEGER,
            order_index INTEGER,
            FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS answer_options (
            id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL,
            text TEXT,
            is_correct INTEGER NOT NULL DEFAULT 0,
            order_index INTEGER,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            pin TEXT NOT NULL,
            quiz_id TEXT NOT NULL,
            host_id TEXT NOT NULL,
            status TEXT NOT NULL,
            current_question_index INTEGER NOT NULL DEFAULT -1,
            question_start_time REAL,
            created_at TEXT,
            FOREIGN KEY (quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE,
            FOREIGN KEY (host_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_pin ON sessions(pin);

        CREATE TABLE IF NOT EXISTS participants (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            nickname TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            connected INTEGER NOT NULL DEFAULT 1,
            answers_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        );
        """
    )
    savienojums.commit()


def user_by_email(savienojums: sqlite3.Connection, email: str) -> dict[str, Any] | None:
    row = savienojums.execute("SELECT id, email, password_hash FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "email": row["email"], "password_hash": row["password_hash"]}


def user_create(savienojums: sqlite3.Connection, uid: str, email: str, password_hash: str) -> None:
    savienojums.execute(
        "INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)",
        (uid, email, password_hash),
    )
    savienojums.commit()


def _question_to_dict(savienojums: sqlite3.Connection, qid: str) -> dict[str, Any] | None:
    qrow = savienojums.execute(
        "SELECT id, quiz_id, text, type, time_limit_seconds, points, order_index FROM questions WHERE id = ?",
        (qid,),
    ).fetchone()
    if not qrow:
        return None
    options = []
    for orow in savienojums.execute(
        "SELECT id, text, is_correct, order_index FROM answer_options WHERE question_id = ? ORDER BY order_index",
        (qid,),
    ):
        options.append(
            {
                "id": orow["id"],
                "text": orow["text"],
                "isCorrect": bool(orow["is_correct"]),
                "orderIndex": orow["order_index"],
            }
        )
    return {
        "id": qrow["id"],
        "quiz_id": qrow["quiz_id"],
        "text": qrow["text"],
        "type": qrow["type"],
        "timeLimitSeconds": qrow["time_limit_seconds"],
        "points": qrow["points"],
        "orderIndex": qrow["order_index"],
        "answerOptions": options,
    }


def quiz_load_full(savienojums: sqlite3.Connection, qid: str) -> dict[str, Any] | None:
    row = savienojums.execute(
        "SELECT id, owner_id, title, description, status, created_at, updated_at FROM quizzes WHERE id = ?",
        (qid,),
    ).fetchone()
    if not row:
        return None
    questions = []
    for qrow in savienojums.execute(
        "SELECT id FROM questions WHERE quiz_id = ? ORDER BY order_index",
        (qid,),
    ):
        qd = _question_to_dict(savienojums, qrow["id"])
        if qd:
            questions.append(qd)
    return {
        "id": row["id"],
        "owner_id": row["owner_id"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "questions": questions,
    }


def quiz_list_for_owner(savienojums: sqlite3.Connection, owner_id: str) -> list[dict[str, Any]]:
    out = []
    for row in savienojums.execute(
        "SELECT id FROM quizzes WHERE owner_id = ? ORDER BY updated_at DESC",
        (owner_id,),
    ):
        full = quiz_load_full(savienojums, row["id"])
        if full:
            out.append(full)
    return out


def quiz_insert(savienojums: sqlite3.Connection, quiz: dict[str, Any]) -> None:
    savienojums.execute(
        """
        INSERT INTO quizzes (id, owner_id, title, description, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            quiz["id"],
            quiz["owner_id"],
            quiz["title"],
            quiz.get("description", ""),
            quiz["status"],
            quiz["createdAt"],
            quiz["updatedAt"],
        ),
    )
    savienojums.commit()


def quiz_delete(savienojums: sqlite3.Connection, qid: str) -> None:
    savienojums.execute("DELETE FROM quizzes WHERE id = ?", (qid,))
    savienojums.commit()


def quiz_patch(savienojums: sqlite3.Connection, qid: str, updates: dict[str, Any], updated_at: str) -> None:
    fields = []
    vals: list[Any] = []
    for k, col in (("title", "title"), ("description", "description"), ("status", "status")):
        if k in updates:
            fields.append(f"{col} = ?")
            vals.append(updates[k])
    if not fields:
        return
    vals.append(updated_at)
    vals.append(qid)
    savienojums.execute(
        f"UPDATE quizzes SET {', '.join(fields)}, updated_at = ? WHERE id = ?",
        vals,
    )
    savienojums.commit()


def question_insert(savienojums: sqlite3.Connection, question: dict[str, Any]) -> None:
    savienojums.execute(
        """
        INSERT INTO questions (id, quiz_id, text, type, time_limit_seconds, points, order_index)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question["id"],
            question["quiz_id"],
            question["text"],
            question["type"],
            question["timeLimitSeconds"],
            question["points"],
            question["orderIndex"],
        ),
    )
    for opt in question["answerOptions"]:
        savienojums.execute(
            """
            INSERT INTO answer_options (id, question_id, text, is_correct, order_index)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                opt["id"],
                question["id"],
                opt["text"],
                1 if opt.get("isCorrect") else 0,
                opt["orderIndex"],
            ),
        )
    savienojums.commit()


def question_patch(
    savienojums: sqlite3.Connection,
    question_id: str,
    text: str | None,
    time_limit: int | None,
    points: int | None,
    answer_options: list[dict[str, Any]] | None,
    quiz_id_for_touch: str,
    updated_at: str,
) -> None:
    if text is not None:
        savienojums.execute("UPDATE questions SET text = ? WHERE id = ?", (text, question_id))
    if time_limit is not None:
        savienojums.execute("UPDATE questions SET time_limit_seconds = ? WHERE id = ?", (time_limit, question_id))
    if points is not None:
        savienojums.execute("UPDATE questions SET points = ? WHERE id = ?", (points, question_id))
    if answer_options is not None:
        savienojums.execute("DELETE FROM answer_options WHERE question_id = ?", (question_id,))
        for i, o in enumerate(answer_options):
            savienojums.execute(
                """
                INSERT INTO answer_options (id, question_id, text, is_correct, order_index)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    o["id"],
                    question_id,
                    o["text"],
                    1 if o.get("isCorrect") else 0,
                    o.get("orderIndex", i),
                ),
            )
    savienojums.execute("UPDATE quizzes SET updated_at = ? WHERE id = ?", (updated_at, quiz_id_for_touch))
    savienojums.commit()


def question_get(savienojums: sqlite3.Connection, question_id: str) -> dict[str, Any] | None:
    return _question_to_dict(savienojums, question_id)


def question_delete_if_owner(
    savienojums: sqlite3.Connection, question_id: str, owner_id: str, updated_at: str
) -> bool:
    row = savienojums.execute(
        """
        SELECT q.quiz_id FROM questions q
        JOIN quizzes qu ON qu.id = q.quiz_id
        WHERE q.id = ? AND qu.owner_id = ?
        """,
        (question_id, owner_id),
    ).fetchone()
    if not row:
        return False
    qz = row["quiz_id"]
    cur = savienojums.execute("DELETE FROM questions WHERE id = ?", (question_id,))
    if cur.rowcount == 0:
        return False
    rows = savienojums.execute(
        "SELECT id FROM questions WHERE quiz_id = ? ORDER BY order_index",
        (qz,),
    ).fetchall()
    for i, r in enumerate(rows):
        savienojums.execute("UPDATE questions SET order_index = ? WHERE id = ?", (i, r["id"]))
    savienojums.execute("UPDATE quizzes SET updated_at = ? WHERE id = ?", (updated_at, qz))
    savienojums.commit()
    return True


def question_find_quiz_for_owner(savienojums: sqlite3.Connection, question_id: str, owner_id: str) -> tuple[str, dict[str, Any]] | None:
    row = savienojums.execute(
        """
        SELECT q.id AS quiz_id, qu.owner_id
        FROM questions q
        JOIN quizzes qu ON qu.id = q.quiz_id
        WHERE q.id = ?
        """,
        (question_id,),
    ).fetchone()
    if not row or row["owner_id"] != owner_id:
        return None
    qfull = _question_to_dict(savienojums, question_id)
    if not qfull:
        return None
    return row["quiz_id"], qfull


def session_insert(savienojums: sqlite3.Connection, session: dict[str, Any]) -> None:
    savienojums.execute(
        """
        INSERT INTO sessions (id, pin, quiz_id, host_id, status, current_question_index, question_start_time, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session["id"],
            session["pin"],
            session["quiz_id"],
            session["host_id"],
            session["status"],
            session["current_question_index"],
            session.get("question_start_time"),
            session["createdAt"],
        ),
    )
    savienojums.commit()


def session_update_fields(savienojums: sqlite3.Connection, sid: str, **fields: Any) -> None:
    if not fields:
        return
    cols = []
    vals: list[Any] = []
    for k, v in fields.items():
        cols.append(f"{k} = ?")
        vals.append(v)
    vals.append(sid)
    savienojums.execute(f"UPDATE sessions SET {', '.join(cols)} WHERE id = ?", vals)
    savienojums.commit()


def session_by_pin_waiting(savienojums: sqlite3.Connection, pin: str) -> dict[str, Any] | None:
    row = savienojums.execute(
        "SELECT * FROM sessions WHERE pin = ? AND status = 'WAITING'",
        (pin,),
    ).fetchone()
    if not row:
        return None
    return session_load(savienojums, row["id"])


def session_load(savienojums: sqlite3.Connection, sid: str) -> dict[str, Any] | None:
    row = savienojums.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    if not row:
        return None
    parts: dict[str, dict[str, Any]] = {}
    for prow in savienojums.execute("SELECT * FROM participants WHERE session_id = ?", (sid,)):
        try:
            answers = json.loads(prow["answers_json"] or "{}")
        except json.JSONDecodeError:
            answers = {}
        parts[prow["id"]] = {
            "id": prow["id"],
            "nickname": prow["nickname"],
            "score": prow["score"],
            "answers": answers,
            "connected": bool(prow["connected"]),
        }
    return {
        "id": row["id"],
        "pin": row["pin"],
        "quiz_id": row["quiz_id"],
        "host_id": row["host_id"],
        "status": row["status"],
        "current_question_index": row["current_question_index"],
        "question_start_time": row["question_start_time"],
        "createdAt": row["created_at"],
        "participants": parts,
    }


def participant_insert(
    savienojums: sqlite3.Connection,
    session_id: str,
    pid: str,
    nickname: str,
) -> None:
    savienojums.execute(
        """
        INSERT INTO participants (id, session_id, nickname, score, connected, answers_json)
        VALUES (?, ?, ?, 0, 1, '{}')
        """,
        (pid, session_id, nickname),
    )
    savienojums.commit()


def participant_update(savienojums: sqlite3.Connection, pid: str, score: int, answers: dict[str, Any]) -> None:
    savienojums.execute(
        "UPDATE participants SET score = ?, answers_json = ? WHERE id = ?",
        (score, json.dumps(answers), pid),
    )
    savienojums.commit()


def user_count(savienojums: sqlite3.Connection) -> int:
    row = savienojums.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    return int(row["c"]) if row else 0


def import_full_quiz(savienojums: sqlite3.Connection, quiz: dict[str, Any]) -> None:
    quiz_insert(savienojums, quiz)
    for q in quiz.get("questions", []):
        question_insert(savienojums, q)
