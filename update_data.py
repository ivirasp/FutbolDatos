# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
import random
from datetime import datetime, date
import pytz
import traceback

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

# --- 3. SCRAPERS ---

def scrape_agenda():
    print("🌍 Extrayendo Agenda...")
    agenda = []
    seen = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    UTC = pytz.utc

    for url, comp_label in TARGET_URLS_AGENDA.items():
        try:
            time.sleep(random.uniform(2, 5))
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200: continue
            
            soup = BeautifulSoup(r.content, 'html.parser')
            articles = soup.find_all("article", class_="match")
            
            if not articles:
                print(f"⚠️ No se encontraron 'article.match' en {url}. ¿Cambió el HTML?")
                
            for art in articles:
                name_tag = art.find("meta", itemprop="name")
                date_tag = art.find("meta", itemprop="startDate")
                if not name_tag or not date_tag: continue
                title = name_tag.get("content", "").strip()
                date_str = date_tag.get("content", "").split('+')[0]
                
                dt_naive = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                dt_utc = UTC.localize(dt_naive)
                dt_madrid = dt_utc.astimezone(TZ_MADRID)
                ts = dt_madrid.timestamp()
                time_formatted = dt_madrid.strftime("%H:%M")
                
                chan_span = art.find("span", itemprop="name")
                channel = chan_span.get_text(strip=True) if chan_span else "TBD"
                
                match_id = f"{title}_{ts}"
                if match_id not in seen:
                    seen.add(match_id)
                    agenda.append({
                        "title": title, 
                        "start_ts": ts, 
                        "time_str": time_formatted,
                        "channel": channel, 
                        "competition": comp_label
                    })
        except Exception as e:
            traceback.print_exc()
            continue
    return sorted(agenda, key=lambda x: x['start_ts'])

def scrape_standings():
    print("📊 Extrayendo Clasificaciones...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            time.sleep(random.uniform(2, 5))
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            tables = soup.find_all('table')
            if not tables: continue
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
            if league_data: data_map[name] = league_data
        except: continue
    return data_map

def scrape_results():
    print("⚽ Extrayendo Resultados...")
    results_map = {}
    today = datetime.now(TZ_MADRID).date()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

    for name, url in URLS_RESULTS:
        try:
            time.sleep(random.uniform(2, 5))
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200: continue
            
            soup = BeautifulSoup(r.content, 'html.parser')
            temp_rounds = []
            current_round_key = ""
            current_found = False

            tables = soup.find_all('table')
            if not tables:
                print(f"⚠️ ¡Ojo! No hay etiquetas <table> en {url}. Han cambiado el diseño por completo.")
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

                    if home and away:
                        matches.append({
                            "date": date_str,
                            "home": home.strip(),
                            "away": away.strip(),
                            "score": final_score,
                            "status": status_val
                        })

                # --- DOCUMENTACIÓN DE CÓDIGO: DEEP DEBUGGING ---
                # Si hemos iterado por toda la tabla, hay filas (len > 1), pero no logramos extraer partidos, 
                # imprimimos el código fuente para investigarlo.
                if not matches and len(rows) > 1:
                    print(f"\n⚠️ ALERTA DEBUG: Tabla '{final_title}' procesada pero con 0 partidos.")
                    print("Aquí tienes el HTML de la primera fila de datos para adaptar los selectores:")
                    # Imprimimos los primeros 500 caracteres de la fila 1 (la 0 suele ser cabecera) para no saturar la consola
                    print(rows[1].prettify()[:500])
                    print("-" * 50)
                # ------------------------------------------------

                if not current_found and round_match_dates:
                    max_d = max(round_match_dates)
                    if max_d >= today:
                        final_title = f"{orig_title} (Actual)"
                        current_round_key = final_title
                        current_found = True

                if matches:
                    temp_rounds.append({"key": final_title, "matches": matches})

            if temp_rounds:
                def_current = current_round_key if current_round_key else temp_rounds[-1]["key"]
                results_map[name] = {
                    "rounds": {r["key"]: r["matches"] for r in temp_rounds},
                    "current": def_current
                }

        except Exception as e:
            traceback.print_exc()
            continue
    return results_map

if __name__ == "__main__":
    with open(CALENDAR_FILE, 'w', encoding='utf-8') as f: json.dump(scrape_agenda(), f, indent=2, ensure_ascii=False)
    with open(STANDINGS_FILE, 'w', encoding='utf-8') as f: json.dump(scrape_standings(), f, indent=2, ensure_ascii=False)
    with open(RESULTS_FILE, 'w', encoding='utf-8') as f: json.dump(scrape_results(), f, indent=2, ensure_ascii=False)
    print("🎉 Datos generados.")
