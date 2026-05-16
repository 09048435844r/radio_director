# Discord Bot — スマホからパイプライン実行

Mac Studio 上に常駐する Discord bot。スマートフォンの Discord アプリから
`/run <theme>` を叩くと、`research_pipeline → radio_director` を順次実行し、
進捗と最終メトリクス (matched_ratio / citations / warnings 等) を Discord
チャンネルに返す。

既存パイプライン (`~/research_pipeline`, `~/radio_director`) のコードには
一切手を入れず、外側のラッパーとして動く。

---

## アーキテクチャ

```
[iPhone / Discord App]
        │  /run "テーマ"
        ▼
[Mac Studio: bot.py (discord.py)]
        │  asyncio.subprocess
        ├─→ research_pipeline/venv/bin/python main.py --theme ... --mode lecture
        │     stdout/stderr を行単位で解析 → 進捗を Discord に送信
        │     最後に research_brief_<TS>.json のパスを抽出
        │
        └─→ radio_director/.venv/bin/python -m radio_director <brief>
              stderr のログを解析、stdout の run_dir を捕捉
              完了後 verified_script.json からメトリクスを抽出
                  │
                  ▼
            [Discord: Embed で最終結果 (matched_ratio 等) を表示]
```

bot 専用の venv (`bot/.venv`) を切って discord.py を入れる。
本体の `radio_director/.venv` には触らない。

---

## 初期セットアップ

### 1. Discord 側で bot を作る

1. https://discord.com/developers/applications で `New Application`
2. `Bot` タブで `Add Bot` → `TOKEN` を `Reset Token` で生成しコピー
3. `Privileged Gateway Intents` は **不要** (デフォルト Intents のみ使用)
4. `OAuth2` → `URL Generator`:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Read Message History`
   - 生成された URL を開いて自分の Discord サーバーに招待
5. 自分の **ユーザー ID** を取得:
   - Discord 設定 → 詳細設定 → 開発者モード ON
   - 自分のアイコン右クリック → ユーザー ID をコピー

### 2. .env を用意

```bash
cd ~/radio_director/bot
cp .env.example .env
# エディタで開いて DISCORD_TOKEN と ALLOWED_USER_ID を入れる
```

`.env` は `.gitignore` 済 (commit されない)。

### 3. venv セットアップ

```bash
cd ~/radio_director/bot
./start_bot.sh --setup    # bot/.venv を作って discord.py を install するだけ
```

### 4. 手動起動 (フォアグラウンド)

```bash
cd ~/radio_director/bot
./start_bot.sh
```

ターミナルにログが流れ、`logged in as ...` が出たら接続成功。
スマホの Discord アプリから `/run` を叩いてみる。
Ctrl+C で停止。

### 5. macOS 自動起動 (任意)

```bash
mkdir -p ~/radio_director/bot/logs    # launchd の StandardOutPath/StandardErrorPath が要求
cp ~/radio_director/bot/com.tada.radio-bot.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.tada.radio-bot.plist

# 状態確認
launchctl list | grep radio-bot

# 再起動 (推奨)
launchctl kickstart -k gui/$(id -u)/com.tada.radio-bot

# 停止
launchctl unload ~/Library/LaunchAgents/com.tada.radio-bot.plist
```

ログは `~/radio_director/bot/logs/stdout.log` / `stderr.log`。

---

## コマンド

| コマンド | 説明 |
|---|---|
| `/run <theme> [mode]` | パイプライン実行。`mode` は `lecture`/`debate`/`voices`/`trivia`/`weekly_digest`、省略時 `lecture` |
| `/status` | 現在実行中かどうかを返す |
| `/themes` | 推奨テーマ一覧 (§11.5 安全象限) |

`ALLOWED_USER_ID` 以外のユーザーが叩いた場合は `🔒 権限がありません。` で
拒否する。並列実行は禁止 (1 タスク実行中は新しい `/run` を弾く)。

### 進捗イベント

実行中、以下のような行がチャンネルに投稿される (代表例):

- `🚀 パイプライン開始: 「<theme>」 (mode=lecture)`
- `📋 STAGE 1: クエリ・アウトライン生成中...`
- `🔍 STAGE 2: 記事を収集中 (約10分)...`
- `📖 STAGE 3: 記事を要約・統合中 (約20-30分、最も時間がかかります)...`
- `🔧 STAGE 4: ブリーフを組み立て中...`
- `✅ research_brief 生成完了: research_brief_<TS>.json`
- `🎙️ radio_director 起動: brief=...`
- `🧠 Phase A: ブリーフを読み込み中...`
- `✅ Phase A 完了: sources=20 key_numbers=18`
- `📝 Phase B: 番組構成を作成中...`
- `✅ Phase B 完了: title=「...」 topics=3`
- `🎙️ Phase C: 対話セグメントを生成中 (約5-7分)...`
- `✅ Phase C 完了: segments=5 total_chars=6571`
- `🔍 Phase D: 数値・引用の検証中...`
- `🔁 Phase D gate fail (...) → retry 1/1` (gate fail 時のみ)
- `✅ Phase D 完了: title=「...」 hashtags=10 chapters=5 references=5 warnings=15`
- 最後に Embed で **matched_ratio / citations / warnings / references** を表示

所要時間目安: 35〜55 分 (リサーチ 30-40 分 + 台本生成 5-15 分)。

---

## トラブルシューティング

### Bot がオンラインにならない

```bash
cd ~/radio_director/bot
./start_bot.sh
```

をフォアグラウンドで実行してエラーを目視。よくある原因:
- `DISCORD_TOKEN` が未設定 / 古い (`Reset Token` で再発行)
- `ALLOWED_USER_ID` が整数でない
- bot をサーバーに招待していない

### `/run` がコマンドリストに出ない

スラッシュコマンドはグローバル登録で**反映に最大 1 時間**かかる。
すぐ試したい場合は Discord アプリを再起動する。

### パイプラインがすぐ失敗する

- `~/research_pipeline/venv/bin/python` が無い → 本体側の venv 未作成
- `~/radio_director/.venv/bin/python` が無い → 本体側の venv 未作成
- Mac Studio Proxy (port 11435) が死んでいる:
  ```bash
  launchctl kickstart -k gui/$(id -u)/com.tada.ollama-proxy
  ```

### 失敗時の再走

`/run` は同テーマで複数回叩いて OK。Stage1 JSON 抽出失敗などの確率的失敗は
再走で復帰するケースが多い (backlog §11.6 参照、コラーゲンテーマは 3 回目で
通過した事例)。

---

## ファイル一覧

```
bot/
├── README.md               # このファイル
├── .env.example            # 環境変数テンプレ (git 管理対象)
├── .env                    # 実際のトークン (git ignored)
├── bot.py                  # Discord 接続 / slash コマンド
├── config.py               # .env ローダー + パス解決
├── runner.py               # サブプロセス起動 + ログ解析 + 進捗 yield
├── requirements_bot.txt    # discord.py のみ
├── start_bot.sh            # venv 作成 + 起動 (フォアグラウンド)
└── com.tada.radio-bot.plist  # macOS LaunchAgent (任意で ~/Library/LaunchAgents/ へ)
```

既存パイプラインのコードへの変更は **`.gitignore` への `bot/.env` 追記の 1 行のみ**。
