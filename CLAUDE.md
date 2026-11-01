# 網路概論 讀書專案

講義：`ch01.pdf`～`ch08.pdf`（8 章）。重點筆記：`ch1.md`～`ch8.md`（出題的主要依據）。小考：`test1.pdf`、`test2.pdf`。
PDF 中文是 Big5 塞在 WinAnsi 字型裡，一般工具抽出來是亂碼；要重抽原文需自訂解碼（pypdf 讀原始位元組 → cp950，CID 字型走 ToUnicode）。

## 出題系統 `quiz/`

- 啟動：`python quiz/server.py` → http://127.0.0.1:8765（純標準函式庫，無需安裝）
- 測試：`python -m pytest quiz/tests -q`
- 題庫：`quiz/quizzes/<id>.json`；作答紀錄：`quiz/history/*.json`（由網頁交卷自動寫入，**不要手動改**）

### 使用者說「出第 N 章 X 題」時
1. 讀 `chN.md`（必要時參考其他章），依重點出單選題；⭐ 考過的點與 📌 數字名詞優先。
2. `python quiz/cli.py next-id chN` 取得 id（如 `ch3-002`）；跨章用 `mix-001`、弱點加強用 `weak-001`。
3. 寫入 `quiz/quizzes/<id>.json`，格式如下，檔名必須等於 id。
4. `python quiz/cli.py validate quiz/quizzes/<id>.json` 驗證，並確認答案分布平均（A/B/C/D 不偏一邊）。
5. 告訴使用者重新整理網頁即可作答。

```json
{
  "id": "ch3-001",
  "title": "第三章 通訊協定和網路模型 — 10 題",
  "created": "YYYY-MM-DD",
  "description": "涵蓋範圍一句話",
  "questions": [
    {
      "id": "q01", "chapter": 3, "section": "3-3",
      "question": "題目",
      "options": ["選項A", "選項B", "選項C", "選項D"],
      "answer": 0,
      "explanation": "為什麼對、其他選項錯在哪（答錯時會顯示，寫具體）",
      "tags": ["OSI"]
    }
  ]
}
```

規則：`answer` 是 0 起算的索引；`chapter` 1～8；`section` 用筆記的小節編號（如 `5-4`）；題庫內 `id` 不可重複；選項 2～6 個且不重複。
出題風格貼近小考：單選、偏記憶（數字、層級、標準編號、名詞定義），干擾選項要合理（用同章其他數字／名詞）。
同一章的新題庫避免與既有題庫重複題目（先看 `quiz/quizzes/` 裡已有的）。
投影片標 ⚠️ 有爭議的點，以投影片說法為準，並在 explanation 註明。

### 使用者說「依我的弱點出題／幫我複習」時
1. `python quiz/cli.py stats` 看各章、各小節正確率與「尚未訂正的錯題」。
2. 針對正確率低的小節與錯題的觀念出**新的**題目（換個問法，不要原題照抄），存成 `weak-NNN.json`。
3. 簡短說明弱點在哪。原錯題本身可直接在網頁「錯題本 → 練習這 N 題」重做。
