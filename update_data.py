# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime, timedelta
import pytz

# --- CONFIGURACIÓN ---
TZ_MADRID = pytz.timezone('Europe/Madrid')
CALENDAR_FILE = "calendar.json"
STANDINGS_FILE = "standings.json"
RESULTS_FILE = "results.json"

# URLs de Origen
TARGET_URLS_AGENDA = [
    "https://www.futboltv.info/competicion/laliga",
    "https://www.futboltv.info/competicion/champions-league",
    "https://www.futboltv.info/competicion/europa-league",
    "https://www.futboltv.info/competicion/copa-del-rey"
]

URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

URLS_RESULTS = {
    "LALIGA": "https://www.sport.es/resultados/futbol/primera-division/calendario-liga/",
    "CHAMPIONS": "https://www.sport.es/resultados/futbol/champions-league/calendario/",
    "EUROPA": "https://www.sport.es/resultados/futbol/europa-league/calendario-liga/",
    "COPA": "https://www.superdeporte.es/deportes/futbol/copa-rey/calendario/"
}

# Reglas de Clasificación e Indicadores
RULES = {
    "LALIGA": { "champions": (1, 4), "europa": (5, 5), "conference": (6, 6), "relegation": (18, 20) },
    "CHAMPIONS": { "knockout_direct": (1, 8), "playoff": (9, 24) },
    "EUROPA": { "knockout_direct": (1, 8), "playoff": (9, 24) }
}
INDICATORS = {
    "champions": "🟢 ", "europa": "🔵 ", "conference": "🟡 ", "relegation": "🔴 ", 
    "knockout_direct": "✅ ", "playoff": "⚔️ ", "midtable": "⚫ "
}

def get_prefix(competition, rank_str):
    """ Determina el emoji de estatus según la posición """
    try:
        rank = int(rank_str)
        comp_rules = RULES.get(competition)
        if not comp_rules: return INDICATORS["midtable"]
        for status_name, (start, end) in comp_rules.items():
            if start <= rank <= end: return INDICATORS.get(status_name, "")
        return INDICATORS["midtable"]
    except: return INDICATORS["midtable"]

def scrape_standings():
    """ Extrae la tabla detallada con PJ, G, E, P, GF, GC, DG y PTS """
    print("📊 Extrayendo Clasificaciones Detalladas...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            table = max(soup.find_all('table'), key=lambda t: len(t.find_all('tr')))
            rows = table.find_all('tr')
            
            league_data = []
            seen_teams = set()
            rank_counter = 0
            
            for row in rows:
                cells = row.find_all(['th', 'td'])
                texts = [c.get_text(strip=True) for c in cells if c.get_text(strip=True)]
                if len(texts) < 5 or any(t.upper() in ["EQUIPO", "PTS"] for t in texts): continue
                
                # Identificar equipo y estadísticas numéricas
                team = ""
                stats = []
                for t in texts:
                    if len(t) > 2 and not t.isdigit(): team = t
                    elif t.replace('-','').isdigit(): stats.append(t)
                
                if not team or team in seen_teams: continue
                seen_teams.add(team)
                team = re.sub(r'^\d+\.?\s*', '', team)
                
                if len(stats) >= 5:
                    rank_counter += 1
                    prefix = get_prefix(name, str(rank_counter))
                    # Cálculo de Diferencia de Goles (DG)
                    dg = "0"
                    if len(stats) >= 7:
                        dg_val = int(stats[5]) - int(stats[6])
                        dg = f"+{dg_val}" if dg_val > 0 else str(dg_val)

                    league_data.append({
                        "rank": str(rank_counter),
                        "team": f"{prefix}{team}",
                        "points": stats[0],
                        "played": stats[1], "won": stats[2], "drawn": stats[3], "lost": stats[4],
                        "gf": stats[5] if len(stats)>5 else "0",
                        "ga": stats[6] if len(stats)>6 else "0",
                        "dg": dg
                    })
            if league_data: data_map[name] = league_data
        except: continue
    return data_map

def scrape_agenda():
    """ Extrae la agenda de partidos próximos """
    print("🌍 Extrayendo Agenda...")
    agenda = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for url in TARGET_URLS_AGENDA:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            for div in soup.find_all("div", class_="match"):
                meta_date = div.find("meta", itemprop="startDate")
                if not meta_date: continue
                ts = TZ_MADRID.localize(datetime.strptime(meta_date.get("content", "").split('+')[0], "%Y-%m-%dT%H:%M:%S")).timestamp()
                name = div.find("meta", itemprop="name").get("content", "").strip()
                chan = div.find("div", class_="m_chan").get_text(strip=True) if div.find("div", class_="m_chan") else "TBD"
                agenda.append({"title": name, "start_ts": ts, "channel": chan, "stop_ts": ts + 7200})
        except: continue
    return sorted(agenda, key=lambda x: x['start_ts'])

def scrape_results():
    """ Extrae resultados históricos por jornada """
    print("⚽ Extrayendo Resultados...")
    results_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_RESULTS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            temp_rounds = []
            for table in soup.find_all('table'):
                caption = table.find("caption")
                title = caption.find("h2").get_text(strip=True).replace("ª", "") if caption and caption.find("h2") else "Jornada"
                if any(kw in title.upper() for kw in ["FIFA", "WOMEN"]): continue
                matches = []
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) < 4: continue
                    matches.append({
                        "date": cols[0].get_text(strip=True),
                        "home": cols[1].get_text(strip=True),
                        "away": cols[3].get_text(strip=True),
                        "score": cols[2].get_text(strip=True),
                        "status": "FT" if "-" in cols[2].get_text() else "Pending"
                    })
                if matches: temp_rounds.append({"key": title, "matches": matches})
            if temp_rounds:
                results_map[name] = {"rounds": {r["key"]: r["matches"] for r in temp_rounds}, "current": temp_rounds[-1]["key"]}
        except: continue
    return results_map

if __name__ == "__main__":
    # Lógica de decisión de ejecución
    now = time.time()
    update = False
    if not os.path.exists(CALENDAR_FILE):
        update = True
    else:
        with open(CALENDAR_FILE, 'r') as f:
            m = json.load(f)
            # Modo partido (cada 15 min) o ahorro (cada 4h)
            if any(x for x in m if (x['start_ts'] - 10800) <= now <= x['stop_ts']) or (now - os.path.getmtime(CALENDAR_FILE)) > 14400:
                update = True

    if update:
        with open(CALENDAR_FILE, 'w') as f: json.dump(scrape_agenda(), f, indent=2)
        with open(STANDINGS_FILE, 'w') as f: json.dump(scrape_standings(), f, indent=2)
        with open(RESULTS_FILE, 'w') as f: json.dump(scrape_results(), f, indent=2)
        print("🎉 Datos actualizados en GitHub.")
    else:
        print("💤 No hay partidos cerca. Saltando actualización.")
