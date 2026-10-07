# 小1 さんすう れんしゅう（MVP）

Python + Streamlit の、10問ずつ学習するローカルWebアプリです。
たし算・ひき算・ミックス、10まで・20まで、結果表示、間違い問題の再練習に対応します。

## 外出先のiPhone・iPadから使う（クラウド）

Streamlit Community Cloudへ公開し、履歴はSupabaseに保存する構成を用意しています。
クラウドURLをSafariで開けば、PCが停止しているときや別のWi-Fiでも利用できます。
ローカルの `127.0.0.1` URLはiPhoneからは使えません。

1. `supabase_attempts.sql` をSupabaseプロジェクトのSQL Editorで実行します。
   心電図appと同じプロジェクトでも専用の `math_attempts` テーブルに保存します。
2. GitHubの算数appリポジトリをStreamlit Community Cloudからデプロイします。
   ブランチは `main`、起動ファイルは `app.py`、Pythonは3.12を指定します。
3. Advanced settings / Secrets に `secrets.example.toml` の4項目を設定します。
   `MATH_REQUIRE_PASSWORD = true` にし、家族用の長めのパスワードを設定します。
   Supabase URLとサーバー用 `sb_secret_...` キーも入力します。
   本物のキーとパスワードはチャットやGitHubへ貼らないでください。
4. 発行されたHTTPS URLをSafariで開き、家族用パスワードを入力します。
   名前をタップして学習し、必要ならSafariの共有メニューからホーム画面へ追加します。

数字入力欄はタッチ端末の数字キーボードに対応し、「こたえる」「つぎへ」のボタンでも操作できます。
iPhone幅390pxとiPad幅768pxで表示を検証しています。実機Safariとソフトキーボードの挙動は
公開後に実機で確認してください。ホーム画面へ追加しても、ネット接続が必要です。

公開時は家族用パスワードの設定が必要です。必須モードでパスワードが未設定なら学習画面を開きません。
Supabase設定の片方だけがある場合はエラーで止まり、クラウド保存に失敗してもSQLiteへ切り替えません。
Supabase未設定時だけローカルSQLiteを使います。クラウド運用では必ず両項目を設定してください。
既存のローカル履歴は自動移行しません。

Streamlit Cloudのローカルファイル保存は永続性が保証されないため、外部DBを使用します。
参考：[Streamlitのデータ接続](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data)

## 起動方法（Windows / PowerShell）

Python 3.10以上を用意し、このフォルダーで次を実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

ブラウザーで http://localhost:8501 を開いてください。
この作業で作成済みの `.venv` があれば、最後のコマンドだけで起動できます。

## 操作

1. なまえのボタンを押し、学習モードと数の範囲を選びます。
2. 数字キー・テンキーで答えを入力し、Enterで回答します。Backspaceで修正できます。
3. 正誤表示後、Enterまたはボタンで次に進みます。
4. 終了画面で正答数・正答率を確認し、間違えた問題だけ再練習できます。

入力欄は問題表示時に自動でフォーカスされます。別の場所をクリックしてから
キー操作する場合は、答えの欄または次へボタンをクリックしてください。
空欄は回答として記録しません。数字以外は入力欄から除き、全角数字は半角に変換します。
不正解時には答えを表示せず、セット終了後にもう一度解きます。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `app.py` | 学習者選択、設定、問題、正誤、結果の画面と進行 |
| `learning.py` | 問題生成、分析属性、SQLiteへの保存 |
| `keyboard/index.html` | 入力欄のフォーカス、数字入力、Enter操作 |
| `requirements.txt` | Python依存ライブラリー |
| `test_learning.py` | 問題の範囲と履歴保存の自動検証 |
| `data/history.sqlite3` | 起動時に作られる履歴DB |

名前は `learning.py` の `USERS` で変更できます。履歴は名前ではなく `user_id` に紐づきます。
既存の学習者の履歴を引き継ぐ場合は、そのIDを変更しないでください。

## 履歴とデータの意味

SQLiteの `attempts` テーブルへ回答ごとにコミットし、既存の回答を上書きしません。
保存に失敗した場合は次へ進まず、確定した回答を表示します。
「ほぞんを やりなおす」ボタンで、同じ回答・日時・回答時間のレコードを再保存できます。
同じ `attempt_id` の通信再送は重複保存しません。

- `session_id`：通常10問、または再練習1回のセットID。再練習ごとに新しく作ります。
- `question_order`：そのセット内の出題順。再練習も1から始まります。
- `problem_id`：演算・範囲・左右の数からなる問題ID。再練習でも同じIDです。
- `selection_type`：通常は `normal`、再練習は `retry`。`weak_area` は将来用です。
- `attempt_count`：通常セットから連続する再練習における、その問題の回答回数。
  新しい通常セットでは1から始めます。初回正答率は `selection_type=normal` で抽出できます。
- `datetime`：日本時間（UTC+09:00）を含むISO形式の回答日時。
- `response_time_sec`：ブラウザーに入力欄を表示してから確定するまでの時間。
  通信やDB保存の待ち時間は含みません。

全保存項目と型は `learning.py` の `COLUMNS` に定義しています。
SQLiteで真偽値は0/1、未使用属性はNULLとして保存します。
`calculation_correct` は計算結果の正誤、文章問題用の演算選択・式作成の正誤はNULLです。
穴埋め用の `blank_position` は現在 `answer`、`story_type` と `unknown_type` はNULLです。
`hint_used`、`dont_know_used` はfalseです。

将来拡張時の値の候補（画面・出題は未実装）：

| 項目 | 候補 |
|---|---|
| `selection_type` | `normal`, `retry`, `weak_area` |
| `problem_format` | `calculation`, `fill_blank`, `word_problem` |
| `blank_position` | `answer`, `left_operand`, `right_operand` |
| `story_type` | `increase`, `decrease`, `combine`, `separate`, `compare`, `difference` |
| `unknown_type` | `result`, `start`, `change`, `difference` |

### 計算属性のルール

- たし算は左右の数と答えが選択範囲内、ひき算は左右の数が範囲内で答えが0以上。
- 0を含む問題も出題します。同じセット内の問題は重複しません。
- ミックス10問はたし算5問・ひき算5問をシャッフルします。
- `carry`：一の位の和が10以上。ひき算ではNULL。
- `borrowing`：引かれる数の一の位が引く数の一の位より小さい。たし算ではNULL。
- `crosses_10`：たし算は両方10未満で答えが10超、ひき算は10超の数から引いて答えが10未満。
  ちょうど10になる計算はfalseで、`answer_is_10` で別に分類します。
- `zero_included`：左右の数のどちらかが0。
- `doubles`：同じ数同士のたし算。
- `near_10`：MVPでは8または9を含み、答えが10超のたし算と定義します。
- `commutative_pair`：左右を小さい順にしたたし算の識別文字列。ひき算ではNULL。

履歴確認例（Python）：

```python
import sqlite3
with sqlite3.connect("data/history.sqlite3") as db:
    rows = db.execute(
        "SELECT user_id, session_id, question_order, selection_type, "
        "question_text, user_answer, is_correct, attempt_count "
        "FROM attempts WHERE user_id = ? ORDER BY datetime", ("user_001",)
    ).fetchall()
    print(rows)
```

## 検証

```powershell
.\.venv\Scripts\python.exe -m unittest -v
```

## MVPの範囲と制約

文章問題、穴埋め、ヒント、苦手分析、自動調整、詳細レポートは未実装です。
学習者選択は認証ではありません。家庭内で使う前提で、外部公開用のアクセス制御はありません。
履歴はユーザーIDで分離し、画面では選択した学習者の現在のセットだけを表示します。
ページを再読み込みすると進行中のセットはリセットされますが、保存済み回答は残ります。
DBは起動場所ではなく、このプロジェクトの `data` に保存されます。
DBのバックアップはアプリを停止してからファイルをコピーしてください。
開発時のブラウザー検証11回答は `data/mvp-verification.sqlite3` に保管し、
実際の学習に使う `data/history.sqlite3` は空の履歴から始められる状態にしています。
