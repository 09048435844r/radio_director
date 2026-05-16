#!/usr/bin/env bash
# Discord bot 起動スクリプト。
# bot/.venv が無ければ作って discord.py を install してから bot.py を起動する。
#
# 使い方:
#   ./start_bot.sh          # フォアグラウンド起動 (Ctrl+C で停止)
#   ./start_bot.sh --setup  # venv 作成と pip install のみ実行して終了

set -euo pipefail

BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${BOT_DIR}/.venv"
VENV_PYTHON="${VENV_DIR}/bin/python"
REQUIREMENTS="${BOT_DIR}/requirements_bot.txt"

# LaunchAgent から起動された場合のログディレクトリ確保 (手動起動でも害なし)
mkdir -p "${BOT_DIR}/logs"

# 1) venv セットアップ (初回 or --setup 指定時)
if [[ ! -x "${VENV_PYTHON}" ]]; then
    echo "🔧 bot 用 venv を作成: ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
    "${VENV_PYTHON}" -m pip install --upgrade pip
    "${VENV_PYTHON}" -m pip install -r "${REQUIREMENTS}"
fi

# --setup のみで終了
if [[ "${1:-}" == "--setup" ]]; then
    echo "✅ セットアップ完了。次に bot/.env を作成して ./start_bot.sh を実行してください。"
    exit 0
fi

# 2) .env 存在チェック
if [[ ! -f "${BOT_DIR}/.env" ]]; then
    echo "❌ ${BOT_DIR}/.env が見つかりません。" >&2
    echo "   bot/.env.example をコピーして DISCORD_TOKEN / ALLOWED_USER_ID を設定してください。" >&2
    exit 1
fi

# 3) bot 起動
cd "${BOT_DIR}"
exec "${VENV_PYTHON}" bot.py
