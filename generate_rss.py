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
        # Только дейли-партии (correspondence) — отсекаем задачи, тренера и пр.
        if g.get("time_class") != "daily":
            continue
        # Должны быть оба игрока и поле fen (признак настоящей партии)
        if not g.get("fen") or not g.get("pgn"):
            continue
        # Поле turn должно быть "white" или "black"
        turn = g.get("turn", "")
        if turn not in ("white", "black"):
            continue
 
        white = extract_username(g.get("white", {}))
        black = extract_username(g.get("black", {}))
        me    = username.lower()
 
        # Если нас нет ни среди белых, ни среди чёрных — пропускаем
        if me not in (white, black):
            continue
 
        my_color      = "white" if white == me else "black"
        opponent_name = black   if my_color == "white" else white
 
        # Наш ход → противник только что походил
        if turn == my_color:
            pgn       = g.get("pgn", "")
            last_move = extract_last_move_pgn(pgn)
            games.append({
                "source":    "chess.com",
                "game_id":   str(g.get("url", "")).split("/")[-1],
                "url":       g.get("url", ""),
                "opponent":  opponent_name or "opponent",
                "my_color":  my_color,
                "last_move": last_move,
                "pgn":       pgn,
            })
 
    return games
 
 
def extract_last_move_pgn(pgn: str) -> str:
    moves_text  = re.sub(r"\{[^}]*\}", "", pgn)
    moves_text  = re.sub(r"\[[^\]]*\]", "", moves_text)
    tokens      = moves_text.split()
    move_tokens = [
        t for t in tokens
        if not re.match(r"^\d+\.+$", t)
        and not t.startswith("$")
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
        f"&opening=false&perfType=correspondence&lastFen=true"
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
 
                # Только незавершённые партии
                if g.get("status") not in ("started", "created"):
                    continue
 
                players       = g.get("players", {})
                white_name    = players.get("white", {}).get("user", {}).get("name", "")
                black_name    = players.get("black", {}).get("user", {}).get("name", "")
                me            = username.lower()
                my_color      = "white" if white_name.lower() == me else "black"
                opponent_name = black_name if my_color == "white" else white_name
 
                # Определяем чей ход по количеству ходов:
                # чётное число ходов → ходят белые, нечётное → ходят чёрные
                moves_str  = g.get("moves", "")
                moves_list = moves_str.split() if moves_str.strip() else []
                move_count = len(moves_list)
                whites_turn = (move_count % 2 == 0)
                its_my_turn = (my_color == "white" and whites_turn) or \
                              (my_color == "black" and not whites_turn)
 
                if its_my_turn and move_count > 0:
                    last_move = moves_list[-1]
                    games.append({
                        "source":    "lichess",
                        "game_id":   g.get("id", ""),
                        "url":       f"https://lichess.org/{g.get('id', '')}",
                        "opponent":  opponent_name or "opponent",
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
