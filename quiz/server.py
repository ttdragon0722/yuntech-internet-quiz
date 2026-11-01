"""本機出題系統伺服器：python quiz/server.py → http://127.0.0.1:8765"""
from __future__ import annotations

import json
import logging
import os
import sys
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quizlib as ql  # noqa: E402

HOST = "127.0.0.1"
PORT = int(os.environ.get("QUIZ_PORT", "8765"))
STATIC_DIR = ql.ROOT / "static"
MAX_BODY = 1_000_000

log = logging.getLogger("quiz")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:  # 安靜一點
        log.debug(fmt, *args)

    # ----- helpers -----
    def _json(self, data, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data) -> None:
        self._json({"success": True, "data": data, "error": None})

    def _err(self, msg: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"success": False, "data": None, "error": msg}, status)

    def _route(self, method: str) -> None:
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            if method == "GET":
                self._get(parts, parse_qs(url.query))
            else:
                self._post(parts)
        except ql.QuizError as e:
            self._err(str(e))
        except Exception:  # 最後防線：記錄細節、回傳通用訊息
            log.exception("處理 %s %s 時發生錯誤", method, self.path)
            self._err("伺服器發生錯誤，請看終端機訊息", HTTPStatus.INTERNAL_SERVER_ERROR)

    # ----- routes -----
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._route("GET")
        else:
            super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")

    def _get(self, parts: list[str], query: dict) -> None:
        match parts:
            case ["api", "quizzes"]:
                quizzes, errors = ql.list_quizzes()
                self._ok({"quizzes": quizzes, "errors": errors})
            case ["api", "quizzes", quiz_id]:
                self._ok(ql.load_quiz(quiz_id))
            case ["api", "attempts"]:
                attempts = ql.load_attempts()
                self._ok([ql.attempt_summary(a) for a in reversed(attempts)])
            case ["api", "attempts", attempt_id]:
                self._ok(ql.load_attempt(attempt_id))
            case ["api", "wrong"]:
                only = query.get("unfixed", ["0"])[0] == "1"
                self._ok(ql.wrong_questions(ql.load_attempts(), only_unfixed=only))
            case ["api", "stats"]:
                attempts = ql.load_attempts()
                self._ok({"chapters": ql.accuracy_by(attempts, "chapter"),
                          "sections": ql.accuracy_by(attempts, "section"),
                          "attempts": len(attempts)})
            case _:
                self._err("找不到此 API", HTTPStatus.NOT_FOUND)

    def _post(self, parts: list[str]) -> None:
        if parts != ["api", "attempts"]:
            self._err("找不到此 API", HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            self._err("請求內容大小不合法")
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._err("請求內容不是合法 JSON")
            return
        if not isinstance(body, dict):
            self._err("請求內容格式錯誤")
            return
        attempt = ql.grade(body.get("items"), body.get("title"), body.get("durationSec"))
        ql.save_attempt(attempt)
        self._ok(attempt)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ql.QUIZ_DIR.mkdir(exist_ok=True)
    ql.HISTORY_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    log.info("出題系統已啟動：%s（Ctrl+C 結束）", url)
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("已關閉")


if __name__ == "__main__":
    main()
