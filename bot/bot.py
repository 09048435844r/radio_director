"""Discord bot エントリーポイント。

スマートフォンの Discord アプリから /run <theme> を叩くと、
research_pipeline → radio_director を順次実行し進捗を投稿する。

セキュリティ: ALLOWED_USER_ID のみ /run /status を実行可能。
並列実行は排他: 1 タスク実行中は新しい /run を弾く。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import traceback
from pathlib import Path

# bot/ ディレクトリを sys.path に追加 (config / runner を相対 import)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import discord
from discord import app_commands

from config import BotConfig, load_config
from runner import RunResult, run_full_pipeline


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("bot")


RECOMMENDED_THEMES = [
    "腸内細菌と免疫力の関係",
    "良質な睡眠を得るための科学的方法",
    "マインドフルネス瞑想の効果",
    "コラーゲンペプチドの効果と科学的根拠",
    "発酵食品が健康に与える影響",
    "プロテイン摂取と筋肉合成のメカニズム",
    "ビタミンDと免疫機能",
    "コーヒーの健康効果と注意点",
]


class RadioBot(discord.Client):
    def __init__(self, cfg: BotConfig) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.cfg = cfg
        self.tree = app_commands.CommandTree(self)
        self._current_task: asyncio.Task | None = None
        self._current_theme: str | None = None

    async def setup_hook(self) -> None:
        # スラッシュコマンドをグローバル登録 (反映に最大 1 時間)。
        # 開発中の即時反映が必要なら、ギルド単位で sync する手もあるが
        # ここではシンプルにグローバル sync に揃える。
        synced = await self.tree.sync()
        log.info("slash commands synced: %d", len(synced))

    async def on_ready(self) -> None:
        log.info("logged in as %s (id=%s)", self.user, getattr(self.user, "id", "?"))
        log.info("allowed_user_id=%s", self.cfg.allowed_user_id)

    @property
    def is_running_task(self) -> bool:
        return self._current_task is not None and not self._current_task.done()


# ─── helpers ──────────────────────────────────────────────────

# citation タグ ([src=3] 等) を読み上げ用テキストから除去する (backlog §14.4)
_SRC_TAG_RE = re.compile(r"\s*\[src=\d+\]")


def _strip_src_tags(text: str) -> str:
    return _SRC_TAG_RE.sub("", text)


def _load_verified_script(result: RunResult) -> dict | None:
    """run_dir/verified_script.json を読み込む。無ければ None (gate fail 等)。"""
    if not result.run_dir:
        return None
    vs_path = result.run_dir / "verified_script.json"
    if not vs_path.is_file():
        return None
    try:
        return json.loads(vs_path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("verified_script.json 読込失敗: %s", vs_path)
        return None


def _quality_check_value(result: RunResult, script: dict | None) -> str:
    """matched_ratio / fp_candidates / citation 整合性を信号機判定する。

    matched_ratio・false_positive_candidates は RunResult.metrics から、
    citation_tags_inconsistent は runner._extract_metrics が拾わないため
    verified_script.json の metrics ブロックから直接読む。
    """
    m = result.metrics or {}
    ratio = float(m.get("matched_ratio", 0.0) or 0.0)
    fp = int(m.get("false_positive_candidates", 0) or 0)
    cit_inc = 0
    if script:
        cit_inc = int((script.get("metrics") or {}).get("citation_tags_inconsistent", 0) or 0)

    lines: list[str] = []
    statuses: list[str] = []

    if ratio >= 0.50:
        lines.append("✅ matched_ratio 良好")
        statuses.append("ok")
    elif ratio >= 0.35:
        lines.append("⚠️ matched_ratio やや低め (目視推奨)")
        statuses.append("warn")
    else:
        lines.append("❌ matched_ratio 低 (要確認)")
        statuses.append("ng")

    if fp <= 15:
        lines.append("✅ 数値の信頼性 良好")
        statuses.append("ok")
    elif fp <= 30:
        lines.append(f"⚠️ 数値警告 {fp}件 (放送前に目視推奨)")
        statuses.append("warn")
    else:
        lines.append(f"❌ 数値警告 {fp}件 (要目視確認)")
        statuses.append("ng")

    if cit_inc == 0:
        lines.append("✅ 引用構造 正常")
        statuses.append("ok")
    else:
        lines.append(f"❌ 引用エラー {cit_inc}件")
        statuses.append("ng")

    if "ng" in statuses:
        verdict = "🔴 要確認"
    elif "warn" in statuses:
        verdict = "🟡 放送前に確認を"
    else:
        verdict = "🟢 品質良好"
    lines.append(f"\n→ **{verdict}**")
    return "\n".join(lines)[:1024]


def _script_sample_message(script: dict) -> str | None:
    """segments[1] の turns[0:3] を [src=N] 除去してサンプル表示する。"""
    segments = ((script.get("script") or {}).get("segments")) or []
    if len(segments) < 2:
        return None
    seg = segments[1]
    seg_title = seg.get("title") or "(no title)"
    turns = seg.get("turns") or []
    if not turns:
        return None
    lines = [f"📄 台本サンプル ({seg_title})"]
    for turn in turns[:3]:
        spk = turn.get("speaker", "?")
        txt = _strip_src_tags(turn.get("text", "")).strip()
        lines.append(f"[{spk}] {txt[:100]}...")
    return "\n".join(lines)[:2000]


def _result_embed(result: RunResult, script: dict | None = None) -> discord.Embed:
    if result.success:
        title = "✅ パイプライン完了"
        color = discord.Color.green()
    else:
        title = "❌ パイプライン失敗"
        color = discord.Color.red()

    minutes, seconds = divmod(int(result.elapsed_sec), 60)
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="theme", value=result.theme[:1024] or "(unknown)", inline=False)
    embed.add_field(name="elapsed", value=f"{minutes}分{seconds}秒", inline=True)

    if result.brief_path:
        embed.add_field(name="brief", value=f"`{result.brief_path.name}`", inline=False)
    if result.run_dir:
        embed.add_field(name="run_dir", value=f"`{result.run_dir.name}`", inline=False)

    if result.success and result.metrics:
        m = result.metrics
        ratio = m.get("matched_ratio", 0.0)
        pct = f"{ratio * 100:.1f}%"
        embed.add_field(name="title", value=m.get("title", "")[:256], inline=False)
        embed.add_field(
            name="matched_ratio",
            value=f"**{pct}** ({m.get('matched_to_structured_facts',0)}/"
                  f"{m.get('total_numbers_extracted',0)})",
            inline=True,
        )
        embed.add_field(
            name="citations",
            value=f"{m.get('citation_tags_normalized',0)}/{m.get('citation_tags_total',0)}",
            inline=True,
        )
        embed.add_field(
            name="warnings",
            value=str(m.get("warnings_count", 0)),
            inline=True,
        )
        embed.add_field(
            name="references",
            value=str(m.get("references_count", 0)),
            inline=True,
        )
        embed.add_field(
            name="chapters",
            value=str(m.get("chapters_count", 0)),
            inline=True,
        )
        embed.add_field(
            name="fp_candidates",
            value=str(m.get("false_positive_candidates", 0)),
            inline=True,
        )
        embed.add_field(
            name="🔍 品質チェック",
            value=_quality_check_value(result, script),
            inline=False,
        )

    if result.error:
        embed.add_field(name="error", value=result.error[:1024], inline=False)

    return embed


async def _pipeline_worker(
    bot: RadioBot,
    channel: discord.abc.Messageable,
    theme: str,
    mode: str,
) -> None:
    """バックグラウンドでパイプラインを回し、進捗と結果を channel に投稿する。"""
    try:
        async for kind, payload in run_full_pipeline(bot.cfg, theme, mode=mode):
            if kind == "progress":
                await channel.send(payload["message"][:2000])
            elif kind == "complete":
                result: RunResult = payload["result"]
                files: list[discord.File] = []
                if result.brief_path and result.brief_path.is_file():
                    files.append(
                        discord.File(str(result.brief_path), filename="research_brief.json")
                    )
                if result.run_dir:
                    script_ok = result.run_dir / "verified_script.json"
                    script_failed = result.run_dir / "verified_script.failed.json"
                    if script_ok.is_file():
                        files.append(
                            discord.File(str(script_ok), filename="verified_script.json")
                        )
                    elif script_failed.is_file():
                        files.append(
                            discord.File(str(script_failed), filename="verified_script.failed.json")
                        )
                script = _load_verified_script(result)
                await channel.send(
                    embed=_result_embed(result, script), files=files
                )
                if result.success and script is not None:
                    sample = _script_sample_message(script)
                    if sample:
                        await channel.send(sample)
    except Exception:
        tb = traceback.format_exc()
        log.exception("pipeline worker crashed")
        # Discord メッセージ上限を考慮して短く切る
        await channel.send(
            f"❌ 内部例外でパイプライン中断:\n```\n{tb[-1500:]}\n```"
        )
    finally:
        bot._current_theme = None


# ─── commands ─────────────────────────────────────────────────

def _is_allowed(interaction: discord.Interaction, cfg: BotConfig) -> bool:
    return interaction.user.id == cfg.allowed_user_id


def register_commands(bot: RadioBot) -> None:
    cfg = bot.cfg

    @bot.tree.command(
        name="run",
        description="リサーチパイプラインを実行 (35〜55 分かかります)",
    )
    @app_commands.describe(
        theme="テーマ (30〜100 文字推奨)",
        mode="リサーチモード (lecture/debate/voices/trivia/weekly_digest)",
    )
    async def run_cmd(
        interaction: discord.Interaction,
        theme: str,
        mode: str = "lecture",
    ) -> None:
        if not _is_allowed(interaction, cfg):
            await interaction.response.send_message(
                "🔒 権限がありません。", ephemeral=True
            )
            return

        valid_modes = {"lecture", "debate", "voices", "trivia", "weekly_digest"}
        if mode not in valid_modes:
            await interaction.response.send_message(
                f"❌ mode は次から選択: {', '.join(sorted(valid_modes))}",
                ephemeral=True,
            )
            return

        if bot.is_running_task:
            await interaction.response.send_message(
                f"⏳ 既に実行中です (theme=「{bot._current_theme}」)。"
                " 終わるまでお待ちください。",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"🚀 開始: 「{theme}」 (mode={mode})\n"
            f"進捗はこのチャンネルに順次投稿します。"
        )

        bot._current_theme = theme
        channel = interaction.channel
        if channel is None:
            await interaction.followup.send(
                "❌ チャンネルが取得できないため中止します。", ephemeral=True
            )
            bot._current_theme = None
            return

        bot._current_task = asyncio.create_task(
            _pipeline_worker(bot, channel, theme, mode)
        )

    @bot.tree.command(name="status", description="実行中のパイプラインを確認")
    async def status_cmd(interaction: discord.Interaction) -> None:
        if not _is_allowed(interaction, cfg):
            await interaction.response.send_message(
                "🔒 権限がありません。", ephemeral=True
            )
            return
        if bot.is_running_task:
            await interaction.response.send_message(
                f"⏳ 実行中: theme=「{bot._current_theme}」", ephemeral=True
            )
        else:
            await interaction.response.send_message("💤 アイドル中", ephemeral=True)

    @bot.tree.command(name="myid", description="自分の Discord User ID を返す (権限チェックなし)")
    async def myid_cmd(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"あなたのUser ID: {interaction.user.id}", ephemeral=True
        )

    @bot.tree.command(name="themes", description="推奨テーマ一覧を表示")
    async def themes_cmd(interaction: discord.Interaction) -> None:
        lines = "\n".join(f"• {t}" for t in RECOMMENDED_THEMES)
        await interaction.response.send_message(
            f"**推奨テーマ (Step 7-10b 安全象限 §11.5):**\n{lines}",
            ephemeral=True,
        )


def main() -> int:
    try:
        cfg = load_config()
    except RuntimeError as e:
        print(f"設定エラー: {e}", file=sys.stderr)
        return 1

    bot = RadioBot(cfg)
    register_commands(bot)

    try:
        bot.run(cfg.discord_token, log_handler=None)
    except discord.LoginFailure:
        print("❌ Discord ログイン失敗 (token を確認)", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("⏹ 停止 (Ctrl+C)", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
