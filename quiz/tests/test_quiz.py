"""python -m pytest quiz/tests -q"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quizlib as ql  # noqa: E402
import server  # noqa: E402


def make_quiz(qid: str = "ch1-001") -> dict:
    return {
        "id": qid, "title": "測試題庫", "created": "2026-11-01",
        "questions": [
            {"id": "q1", "chapter": 1, "section": "1-4", "question": "ARPANET 哪年建立？",
             "options": ["1969", "1973", "1983", "1993"], "answer": 0, "explanation": "1969"},
            {"id": "q2", "chapter": 2, "section": "2-5", "question": "對講機是？",
             "options": ["單工", "半雙工", "全雙工"], "answer": 1},
        ],
    }


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    qdir, hdir = tmp_path / "quizzes", tmp_path / "history"
    qdir.mkdir()
    hdir.mkdir()
    (qdir / "ch1-001.json").write_text(json.dumps(make_quiz(), ensure_ascii=False), encoding="utf-8")
    return qdir, hdir


# ---------- 驗證 ----------

def test_valid_quiz_passes() -> None:
    ql.validate_quiz(make_quiz(), expected_id="ch1-001")


@pytest.mark.parametrize("mutate, msg", [
    (lambda q: q["questions"][0].update(answer=4), "answer"),
    (lambda q: q["questions"][0].update(answer=True), "answer"),
    (lambda q: q["questions"][0].update(chapter=9), "chapter"),
    (lambda q: q["questions"][0].update(options=["a"]), "options"),
    (lambda q: q["questions"][0].update(options=["a", "a"]), "重複"),
    (lambda q: q["questions"][1].update(id="q1"), "重複"),
    (lambda q: q.update(questions=[]), "questions"),
    (lambda q: q.update(id="../x"), "id"),
])
def test_invalid_quiz_rejected(mutate, msg: str) -> None:
    quiz = make_quiz()
    mutate(quiz)
    with pytest.raises(ql.QuizError, match=msg):
        ql.validate_quiz(quiz)


def test_id_must_match_filename() -> None:
    with pytest.raises(ql.QuizError, match="檔名"):
        ql.validate_quiz(make_quiz("ch1-002"), expected_id="ch1-001")


def test_load_quiz_rejects_path_traversal(dirs) -> None:
    with pytest.raises(ql.QuizError):
        ql.load_quiz("../secret", dirs[0])


def test_list_quizzes_reports_broken_file(dirs) -> None:
    (dirs[0] / "bad.json").write_text("{not json", encoding="utf-8")
    quizzes, errors = ql.list_quizzes(dirs[0])
    assert [q["id"] for q in quizzes] == ["ch1-001"]
    assert quizzes[0]["chapters"] == [1, 2]
    assert len(errors) == 1 and "bad.json" in errors[0]


# ---------- 評分與紀錄 ----------

def test_grade_uses_server_answers(dirs) -> None:
    items = [{"quizId": "ch1-001", "qid": "q1", "choice": 0},
             {"quizId": "ch1-001", "qid": "q2", "choice": None}]
    a = ql.grade(items, "測試", 30, dirs[0])
    assert (a["correct"], a["total"], a["score"]) == (1, 2, 50)
    assert a["items"][1]["correct"] is False
    assert a["items"][0]["question"].startswith("ARPANET")


@pytest.mark.parametrize("items", [
    [], [{"quizId": "ch1-001", "qid": "nope", "choice": 0}],
    [{"quizId": "ch1-001", "qid": "q1", "choice": 9}],
    [{"quizId": "missing", "qid": "q1", "choice": 0}],
    "not-a-list",
])
def test_grade_rejects_bad_items(dirs, items) -> None:
    with pytest.raises(ql.QuizError):
        ql.grade(items, "測試", 0, dirs[0])


def test_wrong_questions_tracks_fixes(dirs) -> None:
    qdir, hdir = dirs
    first = ql.grade([{"quizId": "ch1-001", "qid": "q1", "choice": 2},
                      {"quizId": "ch1-001", "qid": "q2", "choice": 0}], "第一次", 0, qdir)
    second = ql.grade([{"quizId": "ch1-001", "qid": "q1", "choice": 0}], "第二次", 0, qdir)
    first, second = {**first, "id": "20260101-000000-aaaa"}, {**second, "id": "20260101-000001-aaaa"}
    ql.save_attempt(first, hdir)
    ql.save_attempt(second, hdir)
    attempts = ql.load_attempts(hdir)
    wrong = ql.wrong_questions(attempts)
    assert {w["qid"]: w["lastCorrect"] for w in wrong} == {"q1": True, "q2": False}
    assert [w["qid"] for w in ql.wrong_questions(attempts, only_unfixed=True)] == ["q2"]
    by_ch = {r["key"]: r["rate"] for r in ql.accuracy_by(attempts, "chapter")}
    assert by_ch == {1: 50, 2: 0}


# ---------- HTTP API ----------

@pytest.fixture
def base_url(dirs, monkeypatch):
    monkeypatch.setattr(ql, "QUIZ_DIR", dirs[0])
    monkeypatch.setattr(ql, "HISTORY_DIR", dirs[1])
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def call(url: str, data: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, method="POST" if data is not None else "GET",
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_api_flow(base_url, dirs) -> None:
    status, body = call(f"{base_url}/api/quizzes")
    assert status == 200 and body["data"]["quizzes"][0]["id"] == "ch1-001"
    status, body = call(f"{base_url}/api/attempts", {
        "title": "API 測試", "durationSec": 12,
        "items": [{"quizId": "ch1-001", "qid": "q1", "choice": 1}]})
    assert status == 200 and body["data"]["score"] == 0
    attempt_id = body["data"]["id"]
    assert (dirs[1] / f"{attempt_id}.json").is_file()
    _, body = call(f"{base_url}/api/attempts/{attempt_id}")
    assert body["data"]["title"] == "API 測試"
    _, body = call(f"{base_url}/api/wrong?unfixed=1")
    assert [w["qid"] for w in body["data"]] == ["q1"]


def test_api_saves_each_answer_into_same_attempt(base_url, dirs) -> None:
    q1_wrong = {"quizId": "ch1-001", "qid": "q1", "choice": 2}
    q2_right = {"quizId": "ch1-001", "qid": "q2", "choice": 1}
    status, body = call(f"{base_url}/api/attempts",
                        {"title": "逐題", "items": [q1_wrong], "finished": False})
    assert status == 200 and body["data"]["finished"] is False
    attempt_id = body["data"]["id"]
    _, body = call(f"{base_url}/api/wrong?unfixed=1")
    assert [w["qid"] for w in body["data"]] == ["q1"]  # 答完第一題錯題本就更新

    status, body = call(f"{base_url}/api/attempts", {
        "id": attempt_id, "title": "逐題", "items": [q1_wrong, q2_right], "finished": True})
    assert status == 200 and body["data"]["id"] == attempt_id
    assert body["data"]["finished"] is True and body["data"]["total"] == 2
    assert [p.name for p in dirs[1].glob("*.json")] == [f"{attempt_id}.json"]

    status, body = call(f"{base_url}/api/attempts", {
        "id": attempt_id, "title": "逐題", "items": [q2_right], "finished": False})
    assert status == 400 and "交卷" in body["error"]


def test_api_rejects_update_of_unknown_attempt(base_url) -> None:
    item = {"quizId": "ch1-001", "qid": "q1", "choice": 0}
    status, _ = call(f"{base_url}/api/attempts", {"id": "nope-1", "title": "x", "items": [item]})
    assert status == 400
    status, _ = call(f"{base_url}/api/attempts", {"id": "../x", "title": "x", "items": [item]})
    assert status == 400
    status, _ = call(f"{base_url}/api/attempts", {"title": "x", "items": [item], "finished": "no"})
    assert status == 400


def test_old_attempt_without_finished_flag_counts_as_finished(dirs) -> None:
    qdir, hdir = dirs
    old = ql.grade([{"quizId": "ch1-001", "qid": "q1", "choice": 0}], "舊", 0, qdir)
    old = {k: v for k, v in old.items() if k != "finished"}
    ql.save_attempt(old, hdir)
    assert ql.attempt_summary(ql.load_attempt(old["id"], hdir))["finished"] is True
    with pytest.raises(ql.QuizError, match="交卷"):
        ql.save_attempt({**old, "finished": False}, hdir, update=True)


def test_api_errors(base_url) -> None:
    status, body = call(f"{base_url}/api/quizzes/nope")
    assert status == 400 and body["success"] is False and "找不到" in body["error"]
    status, _ = call(f"{base_url}/api/unknown")
    assert status == 404
    status, body = call(f"{base_url}/api/attempts", {"title": "x", "items": []})
    assert status == 400 and body["error"]
