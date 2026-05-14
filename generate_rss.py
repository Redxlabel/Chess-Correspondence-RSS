#!/usr/bin/env python3
"""
Chess Correspondence RSS Generator
chess.com + lichess.org → RSS feed
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

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


def fen_active_color(fen: str) -> str:
    """Второе поле FEN — цвет активного игрока: 'w' или 'b'."""
    parts = fen.split()
    return parts[1] if len(parts) > 1 else ""


def username_from_url(url: str) -> str:
    """https://api.chess.com/pub/player/erik → 'erik'"""
    return url.rstrip("/").split("/")[-1].lower()


# ─── chess.com ────────────────────────────────
def get_chesscom_games(username: str) -> list[dict]:
    """
    Используем /games/to-move — специальный endpoint chess.com,
    который возвращает ТОЛЬКО партии где сейчас ход игрока.
    Затем для каждой партии получаем детали (FEN, PGN, противника)
    из /games.
    """
    if not username:
        return []

    # Шаг 1: получаем список партий где наш ход
    to_move = fetch_json(f"https://api.chess.com/pub/player/{username}/games/to-move")
    if not to_move:
        return []

    to_move_urls = {
        g["url"] for g in to_move.get("games", [])
        if g.get("move_by", 0) != 0  # move_by=0 означает draw offer, не наш ход
    }
    if not to_move_urls:
        return []

    # Шаг 2: получаем полные данные всех текущих партий
    all_games = fetch_json(f"https://api.chess.com/pub/player/{username}/games")
    if not all_games:
        return []

    me     = username.lower()
    result = []

    for g in all_games.get("games", []):
        # Только daily (correspondence)
        if g.get("time_class") != "daily":
            continue
        # Только партии где наш ход
        if g.get("url") not in to_move_urls:
            continue
        # Нужен FEN и PGN
        if not g.get("fen") or not g.get("pgn"):
            continue

        # white и black — строки-URL: "https://api.chess.com/pub/player/username"
        white = username_from_url(str(g.get("white", "")))
        black = username_from_url(str(g.get("black", "")))
        my_color      = "white" if white == me else "black"
        opponent_name = black if my_color == "white" else white

        pgn      = g.get("pgn", "")
        game_url = g.get("url", "")
        result.append({
            "source":    "chess.com",
            "game_id":   game_url.rstrip("/").split("/")[-1],
            "url":       game_url,
            "opponent":  opponent_name or "opponent",
            "my_color":  my_color,
            "last_move": extract_last_move_pgn(pgn),
            "pgn":       pgn,
        })

    return result


def extract_last_move_pgn(pgn: str) -> str:
    text   = re.sub(r"\{[^}]*\}", "", pgn)
    text   = re.sub(r"\[[^\]]*\]", "", text)
    tokens = [
        t for t in text.split()
        if not re.match(r"^\d+\.+$", t)
        and not t.startswith("$")
        and t not in ("1-0", "0-1", "1/2-1/2", "*")
    ]
    return tokens[-1].rstrip("+-#") if tokens else "?"


# ─── lichess ──────────────────────────────────
def get_lichess_games(username: str) -> list[dict]:
    """
    Используем lastFen=true — FEN последней позиции.
    Второе поле FEN указывает чей ход ('w' или 'b').
    Это самый надёжный способ определить чей ход.
    """
    if not username:
        return []

    url = (
        f"https://lichess.org/api/games/user/{username}"
        f"?ongoing=true&finished=false&moves=true"
        f"&clocks=false&evals=false&opening=false"
        f"&perfType=correspondence&lastFen=true"
    )
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "chess-rss-bot/1.0")
    req.add_header("Accept", "application/x-ndjson")

    games = []
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if not line:
                    continue
                try:
                    g = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if g.get("status") not in ("started", "created"):
                    continue

                players       = g.get("players", {})
                # Согласно схеме: players.white.user.name
                white_name    = players.get("white", {}).get("user", {}).get("name", "")
                black_name    = players.get("black", {}).get("user", {}).get("name", "")
                me            = username.lower()
                my_color      = "white" if white_name.lower() == me else "black"
                opponent_name = black_name if my_color == "white" else white_name

                # lastFen: "rnbqkbnr/pp... b KQkq - 0 1"
                #                        ^ 'w'=белые ходят, 'b'=чёрные
                last_fen     = g.get("lastFen", "")
                active_color = fen_active_color(last_fen)
                whos_turn    = "white" if active_color == "w" else "black"

                moves_list = g.get("moves", "").split() if g.get("moves", "").strip() else []

                if whos_turn == my_color and moves_list:
                    games.append({
                        "source":    "lichess",
                        "game_id":   g.get("id", ""),
                        "url":       f"https://lichess.org/{g.get('id', '')}",
                        "opponent":  opponent_name or "opponent",
                        "my_color":  my_color,
                        "last_move": moves_list[-1],
                        "pgn":       g.get("moves", ""),
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
def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def build_rss(games: list[dict], new_keys: set) -> str:
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = []

    for g in games:
        key        = game_key(g)
        badge      = "🆕 " if key in new_keys else ""
        move_count = len(g["pgn"].split()) if g["pgn"] else "?"
        title      = (
            f"{badge}{g['source']} | vs {g['opponent']} "
            f"(ты {g['my_color']}) → {g['last_move']}"
        )
        desc = (
            f"Противник <b>{esc(g['opponent'])}</b> сделал ход: "
            f"<b>{esc(g['last_move'])}</b>.<br/>"
            f"Ходов в партии: {move_count}. Твой цвет: {g['my_color']}. Твой ход!"
        )
        items.append(f"""  <item>
    <title>{esc(title)}</title>
    <link>{esc(g['url'])}</link>
    <guid isPermaLink="false">{esc(key)}:{esc(g['last_move'])}</guid>
    <pubDate>{now}</pubDate>
    <description><![CDATA[{desc}]]></description>
  </item>""")

    if not items:
        items.append(f"""  <item>
    <title>Нет партий, ожидающих твоего хода</title>
    <link>https://lichess.org</link>
    <guid isPermaLink="false">no-games-{now}</guid>
    <pubDate>{now}</pubDate>
    <description><![CDATA[Все противники думают, или активных партий нет.]]></description>
  </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>♟ Шахматы по переписке</title>
    <link>https://lichess.org</link>
    <description>Ходы противников на chess.com и lichess.org</description>
    <language>ru</language>
    <lastBuildDate>{now}</lastBuildDate>
    <ttl>60</ttl>
{chr(10).join(items)}
  </channel>
</rss>
"""


# ─── Main ─────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching games...")

    cc = get_chesscom_games(CHESSCOM_USERNAME)
    print(f"  chess.com: {len(cc)} game(s) awaiting your move")

    li = get_lichess_games(LICHESS_USERNAME)
    print(f"  lichess:   {len(li)} game(s) awaiting your move")

    all_games = cc + li
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
