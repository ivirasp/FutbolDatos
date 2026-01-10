# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import time
from datetime import datetime
import pytz

# --- CONFIGURACIÓN ---
TZ_MADRID = pytz.timezone('Europe/Madrid')
CALENDAR_FILE = "calendar.json"
STANDINGS_FILE = "standings.json"
RESULTS_FILE = "results.json"

# URLs que usabas en tus scripts originales
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

# --- LÓGICA DE TIEMPOS (Igual a la de tu VPS) ---
def check_if_update_needed():
    now_ts = time.time()
    if not os.path.exists(CALENDAR_FILE): return True, "Archivo inicial"

    try:
        with open(CALENDAR_FILE, 'r') as f:
            matches = json.load(f)
        
        # Modo Partido: Si hay algo en vivo o empieza en < 3h (10800s)
        # Basado en tu lógica de scheduler.py
        is_game_near = any(m for m in matches if (m['start_ts'] - 10800) <= now_ts <= m['stop_ts'])
        if is_game_near: return True, "Modo Partido (15 min)"

        # Modo Ahorro: Si han pasado 4h (14400s)
        # Basado en tu lógica de scheduler.py
        if (now_ts - os.path.getmtime(CALENDAR_FILE)) > 14400: return True, "Modo Ahorro (4h)"
    except: return True, "Error lectura"
    return False, "Durmiendo"

# --- SCRAPERS (Tus funciones originales simplificadas para la nube) ---
def run_all_updates():
    print("Iniciando scraping...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 1. Agenda (de scheduler.py)
    agenda = []
    for url in TARGET_URLS_AGENDA:
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.content, 'html.parser')
        for div in soup.find_all("div", class_="match"):
            meta_date = div.find("meta", itemprop="startDate")
            if not meta_date: continue
            ts = TZ_MADRID.localize(datetime.strptime(meta_date.get("content", "").split('+')[0], "%Y-%m-%dT%H:%M:%S")).timestamp()
            name = div.find("meta", itemprop="name").get("content", "")
            chan = div.find("div", class_="m_chan").get_text(strip=True) if div.find("div", class_="m_chan") else "TBD"
            agenda.append({"title": name, "teams": name, "channel": chan, "start_ts": ts, "stop_ts": ts + 7200})
    
    with open(CALENDAR_FILE, 'w') as f: json.dump(sorted(agenda, key=lambda x: x['start_ts']), f, indent=2)

    # 2. Clasificaciones (de standings.py)
    standings = {}
    for name, url in URLS_STANDINGS.items():
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.content, 'html.parser')
        table = max(soup.find_all('table'), key=lambda t: len(t.find_all('tr')))
        league = []
        for row in table.find_all('tr')[1:]:
            c = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
            if len(c) > 5:
                league.append({"rank": c[0], "team": c[1], "points": c[2], "played": c[3], "won": c[4], "drawn": c[5], "lost": c[6]})
        standings[name] = league
    
    with open(STANDINGS_FILE, 'w') as f: json.dump(standings, f, indent=2)

if __name__ == "__main__":
    needed, reason = check_if_update_needed()
    if needed:
        print(f"✅ {reason}")
        run_all_updates()
    else:
        print(f"💤 {reason}")
