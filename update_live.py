# -*- coding: utf-8 -*-
"""Marcador en vivo de LaLiga, Champions, Europa League y Copa del Rey.

Fuente: api-sports.io (plan gratuito: 100 llamadas/día, solo ayer/hoy/mañana).
Una única llamada por ejecución (`fixtures?date=hoy`) devuelve todos los partidos del día
con su estado, y solo se hace cuando hay algo que seguir:
  - 1ª llamada del día: 15 min antes del primer partido de la agenda (calendar.json).
  - Después, solo mientras haya partidos en juego o a punto de empezar.
  - Si todos los partidos en juego están en el descanso, se pausa unos 11 min.
  - Con partidos terminados no se vuelve a llamar por ellos.
Escribe live.json solo si algo cambia (menos commits).
"""
import json
import os
import re
import sys
from datetime import datetime

import pytz
import requests

from update_data import (TZ_MADRID, CALENDAR_FILE, RESULTS_FILE, STANDINGS_FILE,
                         build_name_map, load_previous, save_json)

# Rondas que no cuentan para la clasificación (eliminatorias, previas...)
KNOCKOUT = re.compile(r"play-?off|round of|quarter|semi|final|knockout|preliminary|qualif", re.I)

LIVE_FILE = "live.json"
API_BASE = "https://v3.football.api-sports.io"
LEAGUES = {140: "LALIGA", 2: "CHAMPIONS", 3: "EUROPA", 143: "COPA"}

LIVE_STATUS = {"1H", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"}   # en juego
DONE_STATUS = {"FT", "AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"}  # no hay nada más que seguir
HT_PAUSE = 11 * 60        # segundos sin llamar tras detectar el descanso
PRE_MARGIN = 15 * 60      # 1ª llamada: 15 min antes del primer partido del día
STALE_NS = 60 * 60        # un partido "no empezado" 1 h después de su hora se deja de esperar
LOW_BUDGET = 10           # con menos llamadas restantes, solo 1 de cada 3 ejecuciones


def api_key():
    key = os.environ.get("API_SPORTS_KEY", "").strip()
    if not key:
        try:
            with open(os.path.expanduser("~/.api-sports-token"), encoding="utf-8") as f:
                key = f.read().strip()
        except OSError:
            pass
    return key


def decide(now_ts, today, prev, calendar):
    """Devuelve (llamar, motivo) sin gastar ninguna llamada a la API."""
    if prev.get("date") != today or not prev.get("fetched"):
        starts = [m["start_ts"] for m in calendar
                  if m.get("competition") in LEAGUES.values()
                  and datetime.fromtimestamp(m["start_ts"], TZ_MADRID).strftime("%d-%m-%Y") == today]
        if not starts:
            return False, "no hay partidos hoy en la agenda"
        if now_ts >= min(starts) - PRE_MARGIN:
            return True, "primera llamada del día"
        return False, "aún no es la hora del primer partido"

    pending = []
    for m in prev.get("matches", []):
        st = m["status"]
        if st in DONE_STATUS:
            continue
        if st in LIVE_STATUS:
            pending.append(("live", m))
        elif st == "HT":
            pending.append(("ht", m))
        elif now_ts >= m["kickoff_ts"] - 60 and now_ts <= m["kickoff_ts"] + STALE_NS:
            pending.append(("ns", m))
    if not pending:
        return False, "nada en juego ni a punto de empezar"
    if all(k == "ht" and now_ts - (m.get("ht_since") or 0) < HT_PAUSE for k, m in pending):
        return False, "todos los partidos en juego están en el descanso"
    return True, f"{len(pending)} partido(s) en juego o a punto de empezar"


def fetch_fixtures(day_iso, key):
    try:
        r = requests.get(f"{API_BASE}/fixtures?date={day_iso}", headers={"x-apisports-key": key}, timeout=30)
    except Exception as e:
        print(f"  ❌ api-sports: error de conexión ({type(e).__name__})", flush=True)
        return None, None
    remaining = None
    try:
        remaining = int(r.headers.get("x-ratelimit-requests-remaining"))
    except (TypeError, ValueError, AttributeError):
        pass
    if r.status_code != 200:
        print(f"  ❌ api-sports: HTTP {r.status_code}", flush=True)
        return None, remaining
    data = r.json()
    if data.get("errors"):
        print(f"  ❌ api-sports: {data['errors']}", flush=True)
        return None, remaining
    return data.get("response", []), remaining


def build_matches(fixtures, prev_matches, now_ts):
    results = load_previous(RESULTS_FILE, {})
    prev_by_id = {m["id"]: m for m in prev_matches}
    by_comp = {}
    for x in fixtures:
        comp = LEAGUES.get(x["league"]["id"])
        if comp:
            by_comp.setdefault(comp, []).append(x)

    standings = load_previous(STANDINGS_FILE, {})
    out = []
    for comp, items in by_comp.items():
        old = [m for rd in results.get(comp, {}).get("rounds", {}).values() for m in rd]
        teams = {t["id"]: {"id": t["id"], "name": t["name"]}
                 for x in items for t in (x["teams"]["home"], x["teams"]["away"])}
        names = build_name_map(list(teams.values()), [m["home"] for m in old] + [m["away"] for m in old])
        # Nombres según standings.json (vocabulario distinto al de results.json) y partidos jugados de cada equipo
        st_rows = standings.get(comp, [])
        st_names = build_name_map(list(teams.values()), [r["team"] for r in st_rows]) if st_rows else {}
        played = {r["team"]: int(r["played"]) for r in st_rows}
        for x in items:
            fx, goals = x["fixture"], x["goals"]
            st = fx["status"]["short"]
            before = prev_by_id.get(fx["id"], {})
            ht_since = (before.get("ht_since") or now_ts) if st == "HT" else None
            home, away = x["teams"]["home"], x["teams"]["away"]
            for t in (home, away):
                if t["id"] not in names:
                    print(f"  ⚠️ {comp}: sin equivalencia para '{t['name']}', se usa el nombre de la API", flush=True)
            has_score = goals["home"] is not None and goals["away"] is not None
            h_st, a_st = st_names.get(home["id"]), st_names.get(away["id"])
            # Partidos jugados de cada equipo según la clasificación base ANTES de que empiece su partido:
            # se refresca mientras no ha empezado y se congela después (para no contar el partido dos veces)
            if before.get("base") and st not in ("NS", "TBD"):
                base = before["base"]
            else:
                base = {"home": played.get(h_st), "away": played.get(a_st)}
            out.append({
                "home_st": h_st, "away_st": a_st, "base": base,
                "id": fx["id"], "competition": comp, "round": x["league"].get("round"),
                "date": datetime.fromtimestamp(fx["timestamp"], TZ_MADRID).strftime("%d-%m-%Y"),
                "kickoff_ts": fx["timestamp"],
                "home": names.get(home["id"], home["name"]), "away": names.get(away["id"], away["name"]),
                "home_api": home["name"], "away_api": away["name"],
                "score": f"{goals['home']} - {goals['away']}" if has_score else "vs",
                "status": st, "minute": fx["status"].get("elapsed"), "ht_since": ht_since,
            })
    return sorted(out, key=lambda m: (m["kickoff_ts"], m["id"]))


def compute_standings(matches, standings):
    """Clasificación provisional: standings.json + partidos en juego (o recién terminados y aún no
    reflejados en la clasificación base). Solo competiciones con algún partido aplicado."""
    out = {}
    for comp in LEAGUES.values():
        base = standings.get(comp)
        if not base:
            continue
        rows = {r["team"]: dict(r) for r in base}
        base_played = {r["team"]: int(r["played"]) for r in base}
        touched = set()
        for m in matches:
            if m["competition"] != comp or m["status"] not in LIVE_STATUS | {"HT", "FT"}:
                continue
            if KNOCKOUT.search(m.get("round") or ""):
                continue
            h, a = m.get("home_st"), m.get("away_st")
            if h not in rows or a not in rows or h in touched or a in touched:
                continue
            try:
                gh, ga = (int(x) for x in m["score"].split(" - "))
            except (ValueError, AttributeError):
                continue
            b = m.get("base") or {}
            if (b.get("home") is not None and base_played[h] > b["home"]) or \
               (b.get("away") is not None and base_played[a] > b["away"]):
                continue  # la clasificación base ya incluye este partido
            for team, gf, gc in ((h, gh, ga), (a, ga, gh)):
                r = rows[team]
                pts = 3 if gf > gc else 1 if gf == gc else 0
                r["points"] = str(int(r["points"]) + pts)
                r["played"] = str(int(r["played"]) + 1)
                r["won"] = str(int(r["won"]) + (gf > gc))
                r["drawn"] = str(int(r["drawn"]) + (gf == gc))
                r["lost"] = str(int(r["lost"]) + (gf < gc))
                r["gf"] = str(int(r["gf"]) + gf)
                r["ga"] = str(int(r["ga"]) + gc)
                d = int(r["gf"]) - int(r["ga"])
                r["dg"] = f"+{d}" if d > 0 else str(d)
                touched.add(team)
        if not touched:
            continue
        # Orden provisional: puntos, diferencia de goles, goles a favor (desempates oficiales más complejos)
        order = sorted(rows.values(), key=lambda r: (-int(r["points"]), -(int(r["gf"]) - int(r["ga"])),
                                                    -int(r["gf"]), int(r["rank"])))
        out[comp] = [{**r, "base_rank": int(r["rank"]), "rank": str(i), "live": r["team"] in touched}
                     for i, r in enumerate(order, 1)]
    return out


def main():
    # UPDATE_LIVE_NOW solo se usa para pruebas (timestamp UNIX)
    now_ts = float(os.environ.get("UPDATE_LIVE_NOW") or datetime.now(pytz.utc).timestamp())
    now = datetime.fromtimestamp(now_ts, pytz.utc)
    today = now.astimezone(TZ_MADRID).strftime("%d-%m-%Y")
    prev = load_previous(LIVE_FILE, {})
    calendar = load_previous(CALENDAR_FILE, [])
    iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    call, why = decide(now_ts, today, prev, calendar)
    remaining = prev.get("requests_remaining")
    if call and prev.get("date") == today and remaining is not None and remaining < LOW_BUDGET:
        if int(now_ts // 300) % 3 != 0:
            call, why = False, f"quedan solo {remaining} llamadas: se espacian"
    standings_base = load_previous(STANDINGS_FILE, {})
    if not call:
        print(f"⏸️ Sin llamada: {why}", flush=True)
        if prev.get("date") != today:  # al empezar el día se limpia el marcador de ayer
            save_json(LIVE_FILE, {"date": today, "fetched": False, "updated": iso, "updated_ts": now_ts,
                                  "requests_remaining": remaining, "matches": [], "standings": {}})
            print("  🧹 live.json reiniciado para hoy", flush=True)
            return
        # Sin llamada, pero la clasificación base puede haberse actualizado (ya incluye el partido):
        # se recalcula la provisional para que no cuente dos veces
        overlay = compute_standings(prev.get("matches", []), standings_base)
        if overlay != prev.get("standings", {}):
            save_json(LIVE_FILE, {**prev, "standings": overlay, "updated": iso, "updated_ts": now_ts})
            print(f"📊 Clasificación provisional actualizada ({', '.join(overlay) or 'ninguna'})", flush=True)
        return

    key = api_key()
    if not key:
        print("⚠️ Sin API_SPORTS_KEY: no se actualiza el marcador.", flush=True)
        return
    print(f"📡 Llamando a api-sports: {why}", flush=True)
    fixtures, remaining_now = fetch_fixtures(now.strftime("%Y-%m-%d"), key)
    if fixtures is None:
        return
    same_day = prev.get("date") == today
    matches = build_matches(fixtures, prev.get("matches", []) if same_day else [], now_ts)
    overlay = compute_standings(matches, standings_base)
    out = {"date": today, "fetched": True, "updated": iso, "updated_ts": now_ts,
           "requests_remaining": remaining_now, "matches": matches, "standings": overlay}
    if same_day and prev.get("fetched") and prev.get("matches") == matches and prev.get("standings", {}) == overlay:
        print(f"✅ Sin cambios ({len(matches)} partidos). Llamadas restantes: {remaining_now}", flush=True)
        return
    save_json(LIVE_FILE, out)
    live = sum(1 for m in matches if m["status"] in LIVE_STATUS or m["status"] == "HT")
    print(f"✅ live.json: {len(matches)} partidos ({live} en juego). Llamadas restantes: {remaining_now}", flush=True)


if __name__ == "__main__":
    main()
    sys.exit(0)
