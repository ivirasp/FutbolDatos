# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import difflib
import json
import os
import unicodedata
import re
import time
import random
from datetime import datetime, date
import pytz

# --- 1. CONFIGURACIÓN ---
TZ_MADRID = pytz.timezone('Europe/Madrid')
CALENDAR_FILE = "calendar.json"
STANDINGS_FILE = "standings.json"
RESULTS_FILE = "results.json"

TARGET_URLS_AGENDA = {
    "https://www.futboltv.info/competicion/laliga": "LALIGA",
    "https://www.futboltv.info/competicion/champions-league": "CHAMPIONS",
    "https://www.futboltv.info/competicion/europa-league": "EUROPA",
    "https://www.futboltv.info/competicion/copa-del-rey": "COPA"
}

URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

URLS_RESULTS = [
    ("LALIGA", "https://www.sport.es/resultados/futbol/primera-division/calendario-liga/"),
    ("CHAMPIONS", "https://www.sport.es/resultados/futbol/champions-league/calendario/"),
    ("EUROPA", "https://www.sport.es/resultados/futbol/europa-league/calendario-liga/"),
    ("COPA", "https://www.superdeporte.es/deportes/futbol/copa-rey/calendario/")
]

MONTH_MAP = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

# --- HEADERS MEJORADOS (Para evitar bloqueos anti-bot) ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

# --- 2. FUNCIONES AUXILIARES ---
def calculate_season_year(target_month, today_date):
    curr_year = today_date.year
    curr_month = today_date.month
    if curr_month <= 7:
        if target_month >= 8: return curr_year - 1 
        return curr_year
    else:
        if target_month <= 7: return curr_year + 1 
        return curr_year

def parse_header_text(text, today_date):
    try:
        text = text.lower()
        match = re.search(r"(\d+)\s+de\s+(\w+)", text)
        if match:
            day = int(match.group(1))
            month_txt = match.group(2)
            month = MONTH_MAP.get(month_txt, 0)
            if month > 0:
                year = calculate_season_year(month, today_date)
                return date(year, month, day)
    except: pass
    return None

def load_previous(path, default):
    """Lee el JSON de la ejecución anterior (o 'default' si no existe o está roto)."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def merge_with_previous(new_data, path):
    """Para dicts por competición: si una competición no se pudo extraer, se mantiene la anterior."""
    merged = dict(load_previous(path, {}))
    for key, value in new_data.items():
        if value:
            merged[key] = value
    for key in merged.keys() - new_data.keys():
        print(f"  ♻️ {path}: se conserva {key} de la ejecución anterior", flush=True)
    return merged

def save_json(path, data):
    """Escritura atómica: nunca deja un fichero a medias."""
    tmp = path + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

# --- 2b. FOOTBALL-DATA.ORG (LaLiga y Champions) ---
FD_BASE = "https://api.football-data.org/v4"
FD_COMPS = {"LALIGA": "PD", "CHAMPIONS": "CL"}
FD_LEAGUE_STAGES = {"REGULAR_SEASON", "LEAGUE_STAGE"}
FD_STAGE_TITLES = {
    "PLAYOFFS": "Play-offs", "LAST_16": "Octavos de final", "QUARTER_FINALS": "Cuartos de final",
    "SEMI_FINALS": "Semifinales", "FINAL": "Final", "THIRD_PLACE": "Tercer puesto",
}
# Nombre normalizado de la API -> nombres posibles en nuestros JSON (el que exista se usa).
# Solo hacen falta los casos que el emparejamiento automático no resuelve.
FD_ALIASES = {
    "santander": ["Racing", "Racing de Santander"], "racing santander": ["Racing", "Racing de Santander"],
    "alaves": ["Deportivo Alavés", "Alavés"], "celta": ["Celta", "Celta de Vigo"],
    "deportivo": ["RC Deportivo", "Deportivo de A Coruña"], "deportivo coruna": ["RC Deportivo", "Deportivo de A Coruña"],
    "valencia": ["Valencia", "Valencia CF"],
    "club brugge": ["Brujas"], "brugge": ["Brujas"], "napoli": ["Nápoles"], "inter": ["Inter de Milán"],
    "viking": ["Viking Stavanger"], "lens": ["Lens"], "como 1907": ["Como"], "pae aek": ["AEK Athens"],
    "aek athens": ["AEK Athens"], "bayern": ["Bayern de Munich", "Bayern Múnich"],
    "bayern munchen": ["Bayern de Munich", "Bayern Múnich"], "bodo glimt": ["Bodo Glimt", "Bodø/Glimt"],
    "porto": ["Oporto", "FC Porto"], "leipzig": ["Leipzig", "RB Leipzig"], "shakhtar": ["Shakhtar Donetsk", "Shakhtar"],
    "slavia": ["Slavia de Praga", "Slavia Prague"], "sporting": ["Sporting de Portugal", "Sporting CP"],
    "sporting cp": ["Sporting de Portugal", "Sporting CP"],
    "lyon": ["Olympique de Lyon"], "marseille": ["Olympique de Marsella"],
}

# --- 2c. ESPN (clasificación de Europa League; API pública no oficial, sin clave) ---
ESPN_STANDINGS = {"EUROPA": "uefa.europa"}

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(fc|cf|cd|ud|sc|sk|fk|club|de|del|la|el|rcd|rc|ca|afc|as|ac|sl|bk|ssc|ogc|sv|vfl|vfb|fsv|rb|real club)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def build_name_map(api_teams, existing_names):
    """{id_equipo_api: nombre}, usando el vocabulario de 'existing_names' (el JSON anterior)."""
    existing = list(dict.fromkeys(n for n in existing_names if n))
    ex_norm = {n: _norm(n) for n in existing}
    scored = []
    for t in api_teams:
        cands = [_norm(t.get("shortName")), _norm(t.get("name"))]
        aliases = [a for c in cands for a in FD_ALIASES.get(c, [])]
        for n in existing:
            if n in aliases:
                s = 1.5
            else:
                s = 0
                for c in cands:
                    if not c: continue
                    e = ex_norm[n]
                    r = 1.0 if c == e else difflib.SequenceMatcher(None, c, e).ratio()
                    if e.startswith(c + " ") or c.startswith(e + " "): r = max(r, 0.9)
                    s = max(s, r)
            scored.append((s, t["id"], n))
    scored.sort(key=lambda x: -x[0])
    out, used = {}, set()
    for s, tid, n in scored:
        if s < 0.75: break
        if tid in out or n in used: continue
        out[tid] = n; used.add(n)
    return out

def fd_token():
    tok = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
    if not tok:
        try:
            with open(os.path.expanduser("~/.football-data-token"), encoding="utf-8") as f: tok = f.read().strip()
        except OSError:
            pass
    return tok

def fd_get(path):
    tok = fd_token()
    if not tok:
        print("  ⚠️ Sin FOOTBALL_DATA_TOKEN: se usará el scraping.", flush=True)
        return None
    for _ in range(2):
        try:
            r = requests.get(FD_BASE + path, headers={"X-Auth-Token": tok}, timeout=15)
            if r.status_code == 429:
                time.sleep(15); continue
            if r.status_code != 200:
                print(f"  ❌ football-data HTTP {r.status_code} en {path}", flush=True)
                return None
            return r.json()
        except Exception as e:
            print(f"  ❌ football-data error en {path}: {type(e).__name__}", flush=True)
            return None
    return None

def _name_for(team, names, label):
    if team["id"] in names: return names[team["id"]]
    fallback = team.get("shortName") or team.get("name")
    print(f"  ⚠️ {label}: sin equivalencia para '{fallback}', se usa el nombre de la API", flush=True)
    return fallback

def fetch_standings_fd():
    print("\n📊 Clasificaciones (football-data.org)...", flush=True)
    out = {}
    prev = load_previous(STANDINGS_FILE, {})
    for label, code in FD_COMPS.items():
        d = fd_get(f"/competitions/{code}/standings"); time.sleep(1)
        tables = [s for s in (d or {}).get("standings", []) if s.get("type") == "TOTAL" and s.get("table")]
        if not tables:
            print(f"  ⚠️ {label}: sin tabla en la API", flush=True); continue
        table = tables[0]["table"]
        names = build_name_map([r["team"] for r in table], [r["team"] for r in prev.get(label, [])])
        rows = []
        for i, r in enumerate(table, 1):
            gd = r.get("goalDifference", 0)
            # Posición correlativa (la API repite el puesto en los empates)
            rows.append({"rank": str(i), "team": _name_for(r["team"], names, label),
                         "points": str(r["points"]), "played": str(r["playedGames"]), "won": str(r["won"]),
                         "drawn": str(r["draw"]), "lost": str(r["lost"]), "gf": str(r["goalsFor"]),
                         "ga": str(r["goalsAgainst"]), "dg": f"+{gd}" if gd > 0 else str(gd)})
        out[label] = rows
        print(f"  ✅ {label}: {len(rows)} equipos", flush=True)
    return out

def fetch_standings_espn():
    print("\n📊 Clasificaciones (ESPN)...", flush=True)
    out = {}
    prev = load_previous(STANDINGS_FILE, {})
    for label, slug in ESPN_STANDINGS.items():
        try:
            r = requests.get(f"https://site.api.espn.com/apis/v2/sports/soccer/{slug}/standings", headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f"  ❌ ESPN HTTP {r.status_code} en {slug}", flush=True); continue
            entries = r.json()["children"][0]["standings"]["entries"]
            rows_in = []
            need = ("rank", "points", "gamesPlayed", "wins", "ties", "losses", "pointsFor", "pointsAgainst")
            for e in entries:
                st = {x["name"]: x for x in e["stats"]}
                vals = {k: int(float(st[k].get("value", st[k].get("displayValue", 0)) or 0)) for k in need}
                rows_in.append((vals["rank"], e["team"], vals))
            rows_in.sort(key=lambda x: x[0])
            if len(rows_in) < 10:
                print(f"  ⚠️ {label}: ESPN devolvió solo {len(rows_in)} equipos, se ignora", flush=True); continue
            teams = [{"id": t["id"], "name": t["displayName"], "shortName": t.get("shortDisplayName")} for _, t, _ in rows_in]
            names = build_name_map(teams, [x["team"] for x in prev.get(label, [])])
            rows = []
            for i, (_, t, v) in enumerate(rows_in, 1):
                gf, ga = v["pointsFor"], v["pointsAgainst"]
                tm = {"id": t["id"], "name": t["displayName"], "shortName": t.get("shortDisplayName")}
                rows.append({"rank": str(i), "team": _name_for(tm, names, label), "points": str(v["points"]),
                             "played": str(v["gamesPlayed"]), "won": str(v["wins"]), "drawn": str(v["ties"]),
                             "lost": str(v["losses"]), "gf": str(gf), "ga": str(ga),
                             "dg": f"+{gf - ga}" if gf - ga > 0 else str(gf - ga)})
            out[label] = rows
            print(f"  ✅ {label}: {len(rows)} equipos", flush=True)
        except Exception as e:
            print(f"  ❌ ESPN error en {slug}: {type(e).__name__}", flush=True)
    return out

def fetch_results_fd():
    print("\n⚽ Resultados (football-data.org)...", flush=True)
    out = {}
    prev = load_previous(RESULTS_FILE, {})
    today = datetime.now(TZ_MADRID).date()
    for label, code in FD_COMPS.items():
        d = fd_get(f"/competitions/{code}/matches"); time.sleep(1)
        matches = [m for m in (d or {}).get("matches", []) if m["homeTeam"].get("id") and m["awayTeam"].get("id")]
        if not matches:
            print(f"  ⚠️ {label}: sin partidos en la API", flush=True); continue
        old = [m for rd in prev.get(label, {}).get("rounds", {}).values() for m in rd]
        names = build_name_map({m[s]["id"]: m[s] for m in matches for s in ("homeTeam", "awayTeam")}.values(),
                               [m["home"] for m in old] + [m["away"] for m in old])
        cur_md = matches[0].get("season", {}).get("currentMatchday") or 0
        rounds, upcoming = {}, []
        for m in sorted(matches, key=lambda x: x["utcDate"]):
            local = datetime.strptime(m["utcDate"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc).astimezone(TZ_MADRID)
            league = m.get("stage") in FD_LEAGUE_STAGES
            key = f"Jornada {m['matchday']}" if league and m.get("matchday") else \
                  FD_STAGE_TITLES.get(m.get("stage"), (m.get("stage") or "Jornada").replace("_", " ").title())
            ft = (m.get("score") or {}).get("fullTime") or {}
            played = m["status"] in ("FINISHED", "AWARDED", "IN_PLAY", "PAUSED") and ft.get("home") is not None
            rounds.setdefault(key, []).append({
                "date": local.strftime("%d-%m-%Y"),
                "home": _name_for(m["homeTeam"], names, label), "away": _name_for(m["awayTeam"], names, label),
                "score": f"{ft['home']} - {ft['away']}" if played else "vs",
                "status": "Fin" if m["status"] in ("FINISHED", "AWARDED") else ""})
            if local.date() >= today and m["status"] not in ("CANCELLED", "POSTPONED") and (not league or (m.get("matchday") or 0) >= cur_md):
                upcoming.append(key)
        # Orden: jornadas por número; el resto de fases (eliminatorias) después, por fecha de aparición
        def round_order(item):
            idx, key = item
            mm = re.fullmatch(r"Jornada (\d+)", key)
            return (0, int(mm.group(1))) if mm else (1, idx)
        ordered = [k for _, k in sorted(enumerate(rounds), key=round_order)]
        current = upcoming[0] if upcoming else ordered[-1]
        renamed = {(f"{k} (Actual)" if k == current else k): rounds[k] for k in ordered}
        out[label] = {"rounds": renamed, "current": f"{current} (Actual)"}
        print(f"  ✅ {label}: {len(renamed)} rondas, actual = {current}", flush=True)
    return out

# --- 3. SCRAPERS ---
def scrape_agenda():
    print("🌍 Extrayendo Agenda...", flush=True)
    agenda = []
    seen = set()
    ok_comps = set()  # competiciones extraídas con éxito en esta ejecución
    UTC = pytz.utc

    for url, comp_label in TARGET_URLS_AGENDA.items():
        try:
            print(f"  -> Conectando a Agenda {comp_label}...", flush=True)
            time.sleep(random.uniform(2, 4))
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f"  ❌ Error HTTP {r.status_code} en la agenda: {url}", flush=True)
                continue
            
            soup = BeautifulSoup(r.content, 'html.parser')
            articles = soup.find_all("article", class_="match")
            
            if not articles:
                print(f"  ⚠️ No se encontraron partidos en {url}. ¿La web está vacía hoy?", flush=True)
                continue

            ok_comps.add(comp_label)
            count = 0 # Contador para ver cuántos partidos extraemos
            for art in articles:
                # --- NUEVOS SELECTORES BASADOS EN EL NUEVO HTML ---
                
                # 1. Equipos (Buscamos los dos span con la clase match_teamName)
                teams = art.find_all("span", class_="match_teamName")
                if len(teams) < 2: continue
                title = f"{teams[0].get_text(strip=True)} vs {teams[1].get_text(strip=True)}"
                
                # 2. Fecha y hora (Buscamos la etiqueta <time>)
                time_tag = art.find("time")
                if not time_tag: continue
                
                # El datetime viene como "2026-10-11T12:00:00Z", quitamos la 'Z' para parsear fácil
                date_str = time_tag.get("datetime", "").replace('Z', '')
                
                try:
                    dt_naive = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                    dt_utc = UTC.localize(dt_naive)
                    dt_madrid = dt_utc.astimezone(TZ_MADRID)
                    ts = dt_madrid.timestamp()
                    time_formatted = dt_madrid.strftime("%H:%M")
                except Exception as e:
                    print(f"  ❌ Error procesando fecha {date_str}: {e}")
                    continue
                
                # 3. Canales (Buscamos los botones con clase match_channel)
                # Usamos lambda para que acepte variaciones como "match_channel match_channel--paid"
                channel_buttons = art.find_all("button", class_=lambda c: c and "match_channel" in c)
                if channel_buttons:
                    # Si hay varios canales (ej: DAZN y DAZN LaLiga), los unimos con una barra
                    channel = " / ".join([btn.get_text(strip=True) for btn in channel_buttons])
                else:
                    channel = "TBD"
                
                match_id = f"{title}_{ts}"
                if match_id not in seen:
                    seen.add(match_id)
                    agenda.append({
                        "title": title, "start_ts": ts, 
                        "time_str": time_formatted, "channel": channel, 
                        "competition": comp_label
                    })
                    count += 1
            
            # Imprimimos la cantidad de partidos encontrados con éxito
            print(f"  ✅ Extraídos {count} partidos de {comp_label}.", flush=True)
            
        except Exception as e:
            print(f"  ❌ Error en Agenda ({url}): {e}", flush=True)
            continue
            
    # Si una competición falló, conservamos sus partidos futuros de la ejecución anterior
    now_ts = time.time()
    for m in load_previous(CALENDAR_FILE, []):
        if m.get("competition") not in ok_comps and m.get("start_ts", 0) >= now_ts:
            agenda.append(m)
            print(f"  ♻️ Conservado de la anterior ({m.get('competition')}): {m.get('title')}", flush=True)

    return sorted(agenda, key=lambda x: x['start_ts'])

def scrape_standings(only=None):
    print("\n📊 Extrayendo Clasificaciones (scraping)...", flush=True)
    data_map = {}
    for name, url in URLS_STANDINGS.items():
        if only is not None and name not in only: continue
        try:
            print(f"  -> Conectando a {name}...", flush=True)
            time.sleep(random.uniform(2, 4))
            r = requests.get(url, headers=HEADERS, timeout=15)
            
            if r.status_code != 200:
                print(f"  ❌ BLOQUEO HTTP {r.status_code}: La Vanguardia nos rechaza.", flush=True)
                continue
                
            soup = BeautifulSoup(r.content, 'html.parser')
            tables = soup.find_all('table')
            if not tables: 
                print(f"  ⚠️ No hay tablas de clasificación en {url}", flush=True)
                continue
                
            main_table = max(tables, key=lambda t: len(t.find_all('tr')))
            rows = main_table.find_all('tr')[1:]
            league_data = []
            seen_teams = set()
            for row in rows:
                th = row.find('th')
                if not th: continue
                rank_n = th.find('span', class_='classification-pos')
                team_n = th.find('h2', class_='nombre-equipo')
                if not rank_n or not team_n: continue
                rank = rank_n.get_text(strip=True); team = team_n.get_text(strip=True)
                if team in seen_teams: continue
                seen_teams.add(team)
                tds = row.find_all('td')
                if len(tds) < 7: continue
                pts, pj, pg, pe, pp, gf, gc = [t.get_text(strip=True) for t in tds[:7]]
                try: dg_val = f"+{int(gf)-int(gc)}" if int(gf)-int(gc) > 0 else str(int(gf)-int(gc))
                except: dg_val = "0"
                league_data.append({"rank": rank, "team": team, "points": pts, "played": pj, "won": pg, "drawn": pe, "lost": pp, "gf": gf, "ga": gc, "dg": dg_val})
            if league_data: 
                data_map[name] = league_data
                print(f"  ✅ Extraídos {len(league_data)} equipos.", flush=True)
        except Exception as e:
            print(f"  ❌ Error de código: {e}", flush=True)
            continue
    return data_map

def scrape_results(only=None):
    print("\n⚽ Extrayendo Resultados (scraping)...", flush=True)
    results_map = {}
    today = datetime.now(TZ_MADRID).date()

    for name, url in URLS_RESULTS:
        if only is not None and name not in only: continue
        try:
            print(f"  -> Conectando a {name}...", flush=True)
            time.sleep(random.uniform(2, 4))
            r = requests.get(url, headers=HEADERS, timeout=15)
            
            if r.status_code != 200:
                print(f"  ❌ BLOQUEO HTTP {r.status_code}: Sport.es nos ha bloqueado.", flush=True)
                continue
            
            print(f"  ✅ Conexión exitosa a {name}. Parseando HTML...", flush=True)
            soup = BeautifulSoup(r.content, 'html.parser')
            temp_rounds = []
            current_round_key = ""
            current_found = False

            tables = soup.find_all('table')
            if not tables:
                print(f"  ⚠️ ¡Ojo! No hay etiquetas <table>. Han cambiado el diseño.", flush=True)
                continue

            for table in tables:
                current_header_date = None
                round_match_dates = []
                cap = table.find("caption")
                orig_title = "Jornada"
                if cap and cap.find("h2"):
                    orig_title = cap.find("h2").get_text(strip=True).replace("ª", "")
                else:
                    prev_h2 = table.find_previous("h2", class_="table-caption")
                    if prev_h2: orig_title = prev_h2.get_text(strip=True).replace("ª", "")

                if any(kw in orig_title.upper() for kw in ["FIFA", "WOMEN"]): continue
                final_title = orig_title
                matches = []
                rows = table.find_all('tr')
                
                for row in rows:
                    th_date = row.find("th", class_="textoizda")
                    if th_date:
                        parsed_date = parse_header_text(th_date.get_text(strip=True), today)
                        if parsed_date:
                            current_header_date = parsed_date
                        continue

                    tds = row.find_all('td')
                    if len(tds) < 3: continue

                    status_val = ""
                    time_tag = row.find('time')
                    if time_tag:
                        status_text = time_tag.get_text(strip=True)
                        if ":" not in status_text and status_text: 
                            status_val = status_text

                    if not status_val and len(tds) >= 4:
                        last = tds[-1].get_text(strip=True)
                        if "Fin" in last or "Desc" in last: status_val = last

                    match_date = current_header_date
                    if not match_date:
                        txt_c0 = tds[0].get_text(strip=True)
                        m_d = re.search(r'(\d{2})/(\d{2})', txt_c0)
                        if m_d:
                            d, m = int(m_d.group(1)), int(m_d.group(2))
                            y = calculate_season_year(m, today)
                            match_date = date(y, m, d)

                    date_str = ""
                    if match_date:
                        round_match_dates.append(match_date)
                        date_str = match_date.strftime("%d-%m-%Y")

                    home, away = "", ""
                    home_td = row.find("td", class_="textodcha")
                    if home_td:
                        a = home_td.find("a", class_="geca_enlace_equipo")
                        home = a["title"] if a and a.has_attr("title") else home_td.get_text(strip=True)
                    elif len(tds) > 1: home = tds[1].get_text(strip=True)
                    
                    away_td = row.find("td", class_="textoizda")
                    if away_td:
                        a = away_td.find("a", class_="geca_enlace_equipo")
                        away = a["title"] if a and a.has_attr("title") else away_td.get_text(strip=True)
                    elif len(tds) > 3: away = tds[3].get_text(strip=True)

                    final_score = "vs"
                    candidates = []
                    score_a = row.find('a', class_='geca_enlace_partido')
                    if score_a: candidates.append(score_a.get_text(strip=True))
                    score_span = row.find('span', class_='celdagoles')
                    if score_span: candidates.append(score_span.get_text(strip=True))

                    found_s = False
                    for txt in candidates:
                        if re.search(r'\d+\s*-\s*\d+', txt):
                            final_score = txt; found_s = True; break

                    if not found_s and len(tds) >= 3:
                        center = tds[2].get_text(strip=True)
                        if re.search(r'\d+\s*-\s*\d+', center): final_score = center

                    # Partido sin empezar: la web muestra "0 - 0" y, en lugar del estado, la hora de inicio
                    if time_tag and ":" in time_tag.get_text(strip=True):
                        final_score = "vs"

                    if home and away:
                        matches.append({
                            "date": date_str,
                            "home": home.strip(),
                            "away": away.strip(),
                            "score": final_score,
                            "status": status_val
                        })

                if not matches and len(rows) > 1:
                    print(f"  ⚠️ ALERTA DEBUG: Tabla '{final_title}' procesada pero con 0 partidos.", flush=True)

                if not current_found and round_match_dates:
                    max_d = max(round_match_dates)
                    if max_d >= today:
                        final_title = f"{orig_title} (Actual)"
                        current_round_key = final_title
                        current_found = True

                if matches:
                    temp_rounds.append({"key": final_title, "matches": matches})

            if temp_rounds:
                print(f"  🏆 Extraídas {len(temp_rounds)} jornadas con éxito.", flush=True)
                def_current = current_round_key if current_round_key else temp_rounds[-1]["key"]
                results_map[name] = {
                    "rounds": {r["key"]: r["matches"] for r in temp_rounds},
                    "current": def_current
                }

        except Exception as e:
            print(f"  ❌ Error crítico en {url}: {e}", flush=True)
            continue
    return results_map

if __name__ == "__main__":
    print("Iniciando Actualización...", flush=True)
    save_json(CALENDAR_FILE, scrape_agenda())
    # LaLiga y Champions: API. Si la API falla para alguna, se recurre al scraping.
    # Europa League y Copa: siempre scraping.
    fd_st = {**fetch_standings_fd(), **fetch_standings_espn()}  # football-data (LaLiga, Champions) + ESPN (Europa)
    sc_st = scrape_standings([k for k in URLS_STANDINGS if k not in fd_st])
    save_json(STANDINGS_FILE, merge_with_previous({**sc_st, **fd_st}, STANDINGS_FILE))
    fd_res = fetch_results_fd()
    sc_res = scrape_results([n for n, _ in URLS_RESULTS if n not in fd_res])
    save_json(RESULTS_FILE, merge_with_previous({**sc_res, **fd_res}, RESULTS_FILE))
    print("\n🎉 Datos generados correctamente.", flush=True)
