# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime
import pytz

# --- CONFIGURACIÓN GLOBAL ---
TZ_MADRID = pytz.timezone('Europe/Madrid')
CALENDAR_FILE = "calendar.json"
STANDINGS_FILE = "standings.json"
RESULTS_FILE = "results.json"

# URLs para la Agenda
TARGET_URLS_AGENDA = {
    "https://www.futboltv.info/competicion/laliga": "LALIGA",
    "https://www.futboltv.info/competicion/champions-league": "CHAMPIONS",
    "https://www.futboltv.info/competicion/europa-league": "EUROPA",
    "https://www.futboltv.info/competicion/copa-del-rey": "COPA"
}

# URLs para Clasificaciones
URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

# URLs para Resultados (Orden: La liga, Champions, Europa y Copa)
URLS_RESULTS = [
    ("LALIGA", "https://www.sport.es/resultados/futbol/primera-division/calendario-liga/"),
    ("CHAMPIONS", "https://www.sport.es/resultados/futbol/champions-league/calendario/"),
    ("EUROPA", "https://www.sport.es/resultados/futbol/europa-league/calendario-liga/"),
    ("COPA", "https://www.superdeporte.es/deportes/futbol/copa-rey/calendario/")
]

def scrape_agenda():
    print("🌍 Extrayendo Agenda...")
    agenda = []
    seen = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for url, comp_label in TARGET_URLS_AGENDA.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            articles = soup.find_all("article", class_="match")
            for art in articles:
                name_tag = art.find("meta", itemprop="name")
                date_tag = art.find("meta", itemprop="startDate")
                if not name_tag or not date_tag: continue
                title = name_tag.get("content", "").strip()
                date_str = date_tag.get("content", "").split('+')[0]
                dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                ts = TZ_MADRID.localize(dt).timestamp()
                chan_span = art.find("span", itemprop="name")
                channel = chan_span.get_text(strip=True) if chan_span else "TBD"
                match_id = f"{title}_{ts}"
                if match_id not in seen:
                    seen.add(match_id)
                    agenda.append({
                        "title": title,
                        "start_ts": ts,
                        "channel": channel,
                        "competition": comp_label
                    })
        except: continue
    return sorted(agenda, key=lambda x: x['start_ts'])

def scrape_standings():
    print("📊 Extrayendo Clasificaciones...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
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
                rank = rank_n.get_text(strip=True)
                team = team_n.get_text(strip=True)
                if team in seen_teams: continue
                seen_teams.add(team)
                tds = row.find_all('td')
                if len(tds) < 7: continue
                pts, pj, pg, pe, pp, gf, gc = [t.get_text(strip=True) for t in tds[:7]]
                dg = f"+{int(gf)-int(gc)}" if int(gf)-int(gc) > 0 else str(int(gf)-int(gc))
                league_data.append({"rank": rank, "team": team, "points": pts, "played": pj, "won": pg, "drawn": pe, "lost": pp, "gf": gf, "ga": gc, "dg": dg})
            if league_data: data_map[name] = league_data
        except: continue
    return data_map

def scrape_results():
    print("⚽ Extrayendo Resultados (Detección Champions/Copa)...")
    results_map = {}
    today = datetime.now(TZ_MADRID).date()
    for name, url in URLS_RESULTS:
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            temp_rounds = []
            current_round_name = ""; current_found = False
            for table in soup.find_all('table'):
                cap = table.find("caption")
                orig_title = cap.find("h2").get_text(strip=True).replace("ª", "") if cap else "Jornada"
                if any(kw in orig_title.upper() for kw in ["FIFA", "WOMEN"]): continue
                final_title = orig_title
                if not current_found:
                    date_th = table.find("th", class_="textoizda")
                    if date_th:
                        dates = re.findall(r'(\d{4}-\d{2}-\d{2})', date_th.get_text())
                        if len(dates) == 2 and today <= datetime.strptime(dates[1], "%Y-%m-%d").date():
                            final_title = f"{orig_title} (Actual)"
                            current_round_name = final_title; current_found = True
                matches = []
                for row in table.find_all('tr'):
                    # 1. Fecha (Prioridad etiqueta <time>)
                    time_tag = row.find('time')
                    if time_tag:
                        dt_s = time_tag.get('datetime', '').split('T')[0]
                        date_v = datetime.strptime(dt_s, "%Y-%m-%d").strftime("%d-%m-%Y")
                    else:
                        tds = row.find_all('td')
                        date_v = tds[0].get_text(strip=True) if tds else ""
                    # 2. Equipos (Prioridad clase Champions)
                    team_spans = row.find_all('span', class_='geca_enlace_equipo__name')
                    if len(team_spans) >= 2:
                        home = team_spans[0].get_text(strip=True)
                        away = team_spans[1].get_text(strip=True)
                    else:
                        tds = row.find_all('td')
                        if len(tds) < 4: continue
                        home = tds[1].get_text(strip=True)
                        away = tds[3].get_text(strip=True)
                    # 3. Marcador
                    score_a = row.find('a', class_='geca_enlace_partido')
                    score = score_a.get_text(strip=True) if score_a else "vs"
                    if score == "vs" and row.find('span', class_='celdagoles'):
                        score = row.find('span', class_='celdagoles').get_text(strip=True)
                    if home and away:
                        matches.append({"date": date_v, "home": home, "away": away, "score": score})
                if matches: temp_rounds.append({"key": final_title, "matches": matches})
            if temp_rounds:
                results_map[name] = {"rounds": {r["key"]: r["matches"] for r in temp_rounds}, "current": current_round_name if current_round_name else temp_rounds[-1]["key"]}
        except: continue
    return results_map

if __name__ == "__main__":
    with open(CALENDAR_FILE, 'w') as f: json.dump(scrape_agenda(), f, indent=2)
    with open(STANDINGS_FILE, 'w') as f: json.dump(scrape_standings(), f, indent=2)
    with open(RESULTS_FILE, 'w') as f: json.dump(scrape_results(), f, indent=2)
    print("🎉 Archivos grabados íntegramente.")
