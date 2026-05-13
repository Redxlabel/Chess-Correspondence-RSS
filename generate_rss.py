#!/usr/bin/env python3
"""
Chess Correspondence RSS Generator
Fetches ongoing games from chess.com and lichess.org,
generates an RSS feed with opponent moves.
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Никнеймы берутся из GitHub Secrets.
# Settings → Secrets and variables → Actions → New repository secret
CHESSCOM_USERNAME = os.environ.get("CHESSCOM_USERNAME", "")
LICHESS_USERNAME  = os.environ.get("LICHESS_USERNAME", "")

OUTPUT_FILE = Path("docs/feed.xml")
STATE_FILE  = Path("state.json")


def fetch_json(url: str, headers: dict = None) -> dict | list | None:
    req = urllib.request.Request(url, headers=headers or {})
    req.add_header("User-Agent", "chess-rss-bot/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"  Warning: could not fetch {url}: {e}")
        return None


def extract_username(player) -> str:
    """Safely extract username whether player is a string or a dict."""
    if isinstance(player, str):
        return player.lower()
    if isinstance(player, dict):
        return player.get("username", "").lower()
    return ""


# ─── chess.com ────────────────────────────────
def get_chesscom_games(username: str) -> list[dict]:
    if not username:
        return []

    data = fetch_json(
        f"https://api.chess.com/pub/player/{username}/games",
        headers={"Accept": "application/json"},
    )
    if not data:
        return []

    games = []
    for g in data.get("games", []):
        if g.get("time_class") not in ("daily",):
            continue

        turn  = g.get("turn", "")
        white = extract_username(g.get("white", {}))
        black = extract_username(g.get("black", {}))
        me    = username.lower()

        my_color       = "white" if white == me else "black"
        opponent_color = "black" if my_color == "white" else "white"
        opponent_name  = black   if my_color == "white" else white

        # It's your turn → opponent just moved
        if turn == my_color:
            pgn       = g.get("pgn", "")
            last_move = extract_last_move_pgn(pgn)
            games.append({
                "source":    "chess.com",
                "game_id":   str(g.get("url", "")).split("/")[-1],
                "url":       g.get("url", ""),
                "opponent":  opponent_name or opponent_color,
                "my_color":  my_color,
                "last_move": last_move,
                "pgn":       pgn,
            })

    return games


def extract_last_move_pgn(pgn: str) -> str:
    """Extract the last move notation from a PGN string."""
    moves_text = re.sub(r"\{[^}]*\}", "", pgn)
    moves_text = re.sub(r"\[[^\]]*\]", "", moves_text)
    tokens     = moves_text.split()
    move_tokens = [
        t for t in tokens
        if not re.match(r"^\d+\.+$", t) and not t.startswith("$")
        and t not in ("1-0", "0-1", "1/2-1/2", "*")
    ]
    return move_tokens[-1].rstrip("+-#") if move_tokens else "?"


# ─── lichess ──────────────────────────────────
def get_lichess_games(username: str) -> list[dict]:
    if not username:
        return []

    url = (
        f"https://lichess.org/api/games/user/{username}"
        f"?ongoing=true&moves=true&clocks=false&evals=false"
        f"&opening=false&perfType=correspondence"
    )
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "chess-rss-bot/1.0")
    req.add_header("Accept", "application/x-ndjson")

    games = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if not line:
                    continue
                try:
                    g = json.loads(line)
                except json.JSONDecodeError:
                    continue

                players      = g.get("players", {})
                white_name   = players.get("white", {}).get("user", {}).get("name", "")
                black_name   = players.get("black", {}).get("user", {}).get("name", "")
                me           = username.lower()
                my_color     = "white" if white_name.lower() == me else "black"
                opponent_name = black_name if my_color == "white" else white_name

                if g.get("isMyTurn", False):
                    moves_str = g.get("moves", "")
                    last_move = moves_str.split()[-1] if moves_str.strip() else "?"
                    games.append({
                        "source":    "lichess",
                        "game_id":   g.get("id", ""),
                        "url":       f"https://lichess.org/{g.get('id', '')}",
                        "opponent":  opponent_name or ("black" if my_color == "white" else "white"),
                        "my_color":  my_color,
                        "last_move": last_move,
                        "pgn":       moves_str,
                    })
    except Exception as e:
        print(f"  Warning: lichess fetch failed: {e}")

    return games


# ─── State ────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def game_key(game: dict) -> str:
    return f"{game['source']}:{game['game_id']}"


# ─── RSS ──────────────────────────────────────
def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )


def build_rss(games: list[dict], new_game_keys: set) -> str:
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for g in games:
        key        = game_key(g)
        badge      = "🆕 " if key in new_game_keys else ""
        move_count = len(g["pgn"].split()) if g["pgn"] else "?"
        title      = (
            f"{badge}{g['source']} | vs {g['opponent']} "
            f"(ты {g['my_color']}) → {g['last_move']}"
        )
        description = (
            f"Противник {g['opponent']} сделал ход: <b>{escape_xml(g['last_move'])}</b>. "
            f"Всего ходов в партии: {move_count}. "
            f"Твой цвет: {g['my_color']}. Твой ход!"
        )
        items.append(f"""  <item>
    <title>{escape_xml(title)}</title>
    <link>{escape_xml(g['url'])}</link>
    <guid isPermaLink="false">{escape_xml(key)}:{escape_xml(g['last_move'])}</guid>
    <pubDate>{now}</pubDate>
    <description><![CDATA[{description}]]></description>
  </item>""")

    if not items:
        items.append(f"""  <item>
    <title>Нет партий, ожидающих твоего хода</title>
    <link>https://lichess.org</link>
    <guid isPermaLink="false">no-games-{now}</guid>
    <pubDate>{now}</pubDate>
    <description><![CDATA[Все противники думают, или активных партий нет.]]></description>
  </item>""")

    items_xml = "\n".join(items)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>♟ Шахматы по переписке</title>
    <link>https://lichess.org</link>
    <description>Ходы противников на chess.com и lichess.org</description>
    <language>ru</language>
    <lastBuildDate>{now}</lastBuildDate>
    <ttl>60</ttl>
{items_xml}
  </channel>
</rss>
"""


# ─── Main ─────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching games...")

    chesscom_games = get_chesscom_games(CHESSCOM_USERNAME)
    print(f"  chess.com: {len(chesscom_games)} game(s) awaiting your move")

    lichess_games = get_lichess_games(LICHESS_USERNAME)
    print(f"  lichess:   {len(lichess_games)} game(s) awaiting your move")

    all_games = chesscom_games + lichess_games

    state     = load_state()
    new_keys  = set()
    new_state = {}
    for g in all_games:
        k = game_key(g)
        new_state[k] = g["last_move"]
        if state.get(k) != g["last_move"]:
            new_keys.add(k)

    save_state(new_state)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(build_rss(all_games, new_keys), encoding="utf-8")
    print(f"  RSS written → {OUTPUT_FILE} ({len(all_games)} items, {len(new_keys)} new)")


if __name__ == "__main__":
    main()
