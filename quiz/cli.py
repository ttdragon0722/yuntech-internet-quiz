"""出題系統 CLI。

  python quiz/cli.py validate [檔案...]   驗證題庫 JSON（不給檔案則驗證全部）
  python quiz/cli.py stats                 各章／各小節正確率與尚未訂正的錯題
  python quiz/cli.py next-id ch3           建議下一個題庫 id（ch3-001、ch3-002…）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quizlib as ql  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def cmd_validate(files: list[str]) -> int:
    paths = [Path(f) for f in files] or sorted(ql.QUIZ_DIR.glob("*.json"))
    bad = 0
    for p in paths:
        try:
            quiz = json.loads(p.read_text(encoding="utf-8"))
            ql.validate_quiz(quiz, expected_id=p.stem)
            answers = [q["answer"] for q in quiz["questions"]]
            dist = {chr(65 + i): answers.count(i) for i in range(max(answers) + 1)}
            print(f"OK   {p.name}：{len(answers)} 題，答案分布 {dist}")
        except (OSError, json.JSONDecodeError, ql.QuizError) as e:
            bad += 1
            print(f"FAIL {p.name}：{e}")
    return 1 if bad else 0


def cmd_stats() -> int:
    attempts = ql.load_attempts()
    if not attempts:
        print("尚無作答紀錄")
        return 0
    print(f"作答次數：{len(attempts)}\n\n== 各章正確率 ==")
    for r in ql.accuracy_by(attempts, "chapter"):
        print(f"  第 {r['key']} 章  {r['rate']:>3}%  ({r['correct']}/{r['total']})")
    print("\n== 正確率最低的小節 ==")
    worst = sorted(ql.accuracy_by(attempts, "section"), key=lambda r: (r["rate"], -r["total"]))
    for r in worst[:10]:
        print(f"  {r['key']:<8} {r['rate']:>3}%  ({r['correct']}/{r['total']})")
    unfixed = ql.wrong_questions(attempts, only_unfixed=True)
    print(f"\n== 尚未訂正的錯題（{len(unfixed)}）==")
    for w in unfixed:
        mine = w["options"][w["lastChoice"]] if w["lastChoice"] is not None else "（未作答）"
        print(f"  [{w['quizId']}/{w['qid']}] ch{w['chapter']} {w['section']} 錯 {w['wrong']}/{w['seen']}")
        print(f"     {w['question']}")
        print(f"     你選：{mine}｜正解：{w['options'][w['answer']]}")
    return 0


def cmd_next_id(prefix: str) -> int:
    if not ql.ID_RE.match(prefix):
        print("prefix 不合法")
        return 1
    n = 1
    while (ql.QUIZ_DIR / f"{prefix}-{n:03d}.json").exists():
        n += 1
    print(f"{prefix}-{n:03d}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="出題系統 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("files", nargs="*")
    sub.add_parser("stats")
    n = sub.add_parser("next-id")
    n.add_argument("prefix")
    args = parser.parse_args()
    if args.cmd == "validate":
        return cmd_validate(args.files)
    if args.cmd == "stats":
        return cmd_stats()
    return cmd_next_id(args.prefix)


if __name__ == "__main__":
    sys.exit(main())
