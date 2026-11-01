"""題庫與作答紀錄的核心邏輯（純標準函式庫，供 server.py 與 cli.py 共用）。"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
QUIZ_DIR = ROOT / "quizzes"
HISTORY_DIR = ROOT / "history"

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MIN_OPTIONS, MAX_OPTIONS = 2, 6
MIN_CHAPTER, MAX_CHAPTER = 1, 8
MAX_ITEMS_PER_ATTEMPT = 500


class QuizError(ValueError):
    """題庫或作答資料不合法。訊息可直接顯示給使用者。"""


# ---------- 驗證 ----------

def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise QuizError(msg)


def validate_question(q: Any, where: str) -> None:
    _require(isinstance(q, dict), f"{where}: 題目必須是物件")
    _require(isinstance(q.get("id"), str) and ID_RE.match(q["id"]), f"{where}: id 不合法")
    ch = q.get("chapter")
    _require(isinstance(ch, int) and MIN_CHAPTER <= ch <= MAX_CHAPTER, f"{where}: chapter 需為 1~8")
    _require(isinstance(q.get("question"), str) and q["question"].strip(), f"{where}: question 不可空白")
    opts = q.get("options")
    _require(isinstance(opts, list) and MIN_OPTIONS <= len(opts) <= MAX_OPTIONS,
             f"{where}: options 需 {MIN_OPTIONS}~{MAX_OPTIONS} 個")
    _require(all(isinstance(o, str) and o.strip() for o in opts), f"{where}: 選項不可空白")
    _require(len(set(opts)) == len(opts), f"{where}: 選項重複")
    ans = q.get("answer")
    _require(isinstance(ans, int) and not isinstance(ans, bool) and 0 <= ans < len(opts),
             f"{where}: answer 需為選項索引 0~{len(opts) - 1}")
    for key in ("section", "explanation"):
        _require(isinstance(q.get(key, ""), str), f"{where}: {key} 需為字串")
    _require(isinstance(q.get("tags", []), list), f"{where}: tags 需為陣列")


def validate_quiz(quiz: Any, expected_id: str | None = None) -> None:
    _require(isinstance(quiz, dict), "題庫檔必須是 JSON 物件")
    qid = quiz.get("id")
    _require(isinstance(qid, str) and ID_RE.match(qid), "題庫 id 不合法（僅限英數、-、_）")
    if expected_id is not None:
        _require(qid == expected_id, f"題庫 id「{qid}」需與檔名「{expected_id}」相同")
    _require(isinstance(quiz.get("title"), str) and quiz["title"].strip(), "title 不可空白")
    questions = quiz.get("questions")
    _require(isinstance(questions, list) and questions, "questions 不可為空")
    seen: set[str] = set()
    for i, q in enumerate(questions, 1):
        validate_question(q, f"第 {i} 題")
        _require(q["id"] not in seen, f"第 {i} 題: id「{q['id']}」重複")
        seen.add(q["id"])


# ---------- 題庫 ----------

def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise QuizError(f"{path.name} 不是合法 JSON：{e}") from e


def load_quiz(quiz_id: str, quiz_dir: Path | None = None) -> dict:
    _require(bool(ID_RE.match(quiz_id or "")), "題庫 id 不合法")
    path = (quiz_dir or QUIZ_DIR) / f"{quiz_id}.json"
    _require(path.is_file(), f"找不到題庫「{quiz_id}」")
    quiz = _read_json(path)
    validate_quiz(quiz, expected_id=quiz_id)
    return quiz


def list_quizzes(quiz_dir: Path | None = None) -> tuple[list[dict], list[str]]:
    """回傳 (題庫摘要, 錯誤訊息)。壞掉的檔案不會中斷整個列表。"""
    summaries, errors = [], []
    for path in sorted((quiz_dir or QUIZ_DIR).glob("*.json")):
        try:
            quiz = load_quiz(path.stem, quiz_dir)
        except QuizError as e:
            errors.append(f"{path.name}: {e}")
            continue
        chapters = sorted({q["chapter"] for q in quiz["questions"]})
        summaries.append({
            "id": quiz["id"],
            "title": quiz["title"],
            "created": quiz.get("created", ""),
            "chapters": chapters,
            "count": len(quiz["questions"]),
            "description": quiz.get("description", ""),
        })
    summaries.sort(key=lambda s: (s["created"], s["id"]), reverse=True)
    return summaries, errors


# ---------- 作答 ----------

def grade(items: Any, title: Any, duration_sec: Any = 0,
          quiz_dir: Path | None = None) -> dict:
    """依題庫檔重新評分（不信任前端），回傳完整作答紀錄（尚未存檔）。"""
    _require(isinstance(items, list) and items, "作答內容不可為空")
    _require(len(items) <= MAX_ITEMS_PER_ATTEMPT, "作答題數過多")
    _require(isinstance(title, str) and 0 < len(title) <= 200, "標題不合法")
    cache: dict[str, dict] = {}
    graded = []
    for i, item in enumerate(items, 1):
        _require(isinstance(item, dict), f"第 {i} 筆作答格式錯誤")
        quiz_id, qid, choice = item.get("quizId"), item.get("qid"), item.get("choice")
        _require(isinstance(quiz_id, str) and isinstance(qid, str), f"第 {i} 筆缺少 quizId/qid")
        if quiz_id not in cache:
            cache[quiz_id] = {q["id"]: q for q in load_quiz(quiz_id, quiz_dir)["questions"]}
        q = cache[quiz_id].get(qid)
        _require(q is not None, f"第 {i} 筆：題庫「{quiz_id}」沒有題目「{qid}」")
        valid_choice = isinstance(choice, int) and not isinstance(choice, bool) \
            and 0 <= choice < len(q["options"])
        _require(choice is None or valid_choice, f"第 {i} 筆選項不合法")
        graded.append({
            "quizId": quiz_id, "qid": qid,
            "chapter": q["chapter"], "section": q.get("section", ""),
            "question": q["question"], "options": list(q["options"]),
            "answer": q["answer"], "choice": choice,
            "correct": choice == q["answer"],
            "explanation": q.get("explanation", ""),
        })
    correct = sum(1 for g in graded if g["correct"])
    now = datetime.now()
    try:
        duration = max(0, min(int(duration_sec or 0), 24 * 3600))
    except (TypeError, ValueError):
        duration = 0
    return {
        "id": f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}",
        "title": title.strip(),
        "quizIds": sorted(cache),
        "finishedAt": now.isoformat(timespec="seconds"),
        "durationSec": duration,
        "total": len(graded),
        "correct": correct,
        "score": round(correct * 100 / len(graded)),
        "items": graded,
    }


def save_attempt(attempt: dict, history_dir: Path | None = None) -> Path:
    history_dir = history_dir or HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"{attempt['id']}.json"
    path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_attempts(history_dir: Path | None = None) -> list[dict]:
    """依時間由舊到新。壞檔略過。"""
    attempts = []
    for path in sorted((history_dir or HISTORY_DIR).glob("*.json")):
        try:
            attempts.append(_read_json(path))
        except QuizError:
            continue
    return attempts


def load_attempt(attempt_id: str, history_dir: Path | None = None) -> dict:
    _require(bool(ID_RE.match(attempt_id or "")), "紀錄 id 不合法")
    path = (history_dir or HISTORY_DIR) / f"{attempt_id}.json"
    _require(path.is_file(), "找不到這筆紀錄")
    return _read_json(path)


def attempt_summary(a: dict) -> dict:
    return {k: a.get(k) for k in ("id", "title", "finishedAt", "durationSec",
                                  "total", "correct", "score", "quizIds")}


# ---------- 統計 ----------

def question_stats(attempts: list[dict]) -> list[dict]:
    """每一題的累計作答狀況，last 為最近一次是否答對。"""
    stats: dict[tuple[str, str], dict] = {}
    for a in attempts:
        for it in a.get("items", []):
            key = (it["quizId"], it["qid"])
            prev = stats.get(key, {"seen": 0, "wrong": 0})
            stats[key] = {
                **{k: it[k] for k in ("quizId", "qid", "chapter", "section", "question",
                                      "options", "answer", "explanation")},
                "seen": prev["seen"] + 1,
                "wrong": prev["wrong"] + (0 if it["correct"] else 1),
                "lastCorrect": it["correct"],
                "lastChoice": it["choice"],
                "lastAt": a.get("finishedAt", ""),
            }
    return list(stats.values())


def wrong_questions(attempts: list[dict], only_unfixed: bool = False) -> list[dict]:
    rows = [s for s in question_stats(attempts) if s["wrong"] > 0]
    if only_unfixed:
        rows = [s for s in rows if not s["lastCorrect"]]
    return sorted(rows, key=lambda s: (s["lastCorrect"], -s["wrong"], s["chapter"], s["section"]))


def accuracy_by(attempts: list[dict], field: str) -> list[dict]:
    """依 chapter 或 section 統計所有作答的正確率。"""
    acc: dict[Any, list[int]] = {}
    for a in attempts:
        for it in a.get("items", []):
            key = it.get(field) or "-"
            total, ok = acc.get(key, [0, 0])
            acc[key] = [total + 1, ok + (1 if it["correct"] else 0)]
    return [{"key": k, "total": t, "correct": c, "rate": round(c * 100 / t)}
            for k, (t, c) in sorted(acc.items(), key=lambda kv: str(kv[0]))]
