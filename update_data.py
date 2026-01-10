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

# URLs de Agenda (de scheduler.py)
TARGET_URLS_AGENDA = [
    "https://www.futboltv.info/competicion/laliga",
    "https://www.futboltv.info/competicion/champions-league",
    "https://www.futboltv.info/competicion/europa-league",
    "https://www.futboltv.info/competicion/copa-del-rey"
]

# URLs de Resultados/Calendario (de standings.py)
URLS_RESULTS = {
    "LALIGA": "https://www.sport.es/resultados/futbol/primera-division/calendario-liga/",
    "CHAMPIONS": "https://www.sport.es/resultados/futbol/champions-league/calendario/",
    "EUROPA": "https://www.sport.es/resultados/futbol/europa-league/calendario-liga/",
    "COPA": "https://www.superdeporte.es/deportes/futbol/copa-rey/calendario/"
}

URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

# --- LÓGICA DE TIEMPOS (Intervalo Dinámico) ---
def check_if_update_needed():
    now_ts = time.time()
    if not os.path.exists(CALENDAR_FILE): return True, "Iniciando: Archivos no existen"

    try:
        with open(CALENDAR_FILE, 'r') as f:
            matches = json.load(f)
        
        # Modo Partido: Evento próximo (< 3h) o en vivo
        is_game_near = any(m for m in matches if (m['start_ts'] - 10800) <= now_ts <= m['stop_ts'])
        if is_game_near: return True, "Modo Partido (Prioridad 15 min)"

        # Modo Ahorro: Han pasado 4 horas
        if (now_ts - os.path.getmtime(CALENDAR_FILE)) > 14400: return True, "Modo Ahorro (Han pasado 4h)"
    except: return True, "Error lectura, reintentando"
    return False, "Durmiendo... No hay eventos cerca"

# --- FUNCIONES DE EXTRACCIÓN ---

def scrape_agenda():
    print("🌍 Extrayendo Agenda...")
    agenda = []
    seen = set()
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
                
                uid = f"{name}_{ts}"
                if uid not in seen:
                    seen.add(uid)
                    agenda.append({"title": name, "teams": name, "channel": chan, "start_ts": ts, "stop_ts": ts + 7200})
        except: continue
    return sorted(agenda, key=lambda x: x['start_ts'])

def scrape_standings():
    print("📊 Extrayendo Clasificaciones...")
    standings = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            table = max(soup.find_all('table'), key=lambda t: len(t.find_all('tr')))
            league = []
            rank = 1
            for row in table.find_all('tr')[1:]:
                c = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                if len(c) > 5 and c[0].isdigit():
                    league.append({"rank": str(rank), "team": c[1], "points": c[2], "played": c[3], "won": c[4], "drawn": c[5], "lost": c[6]})
                    rank += 1
            standings[name] = league
        except: continue
    return standings

def scrape_results():
    print("⚽ Extrayendo Resultados y Calendario...")
    results_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    today = datetime.now(TZ_MADRID).date()

    for name, url in URLS_RESULTS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            comp_data = { "current": "", "rounds": {} }
            temp_rounds = []

            for table in soup.find_all('table'):
                caption = table.find("caption")
                round_title = caption.find("h2").get_text(strip=True).replace("ª", "") if caption and caption.find("h2") else "Jornada"
                
                # Filtrar ruidos
                if any(kw in round_title.upper() for kw in ["FIFA", "WOMEN", "FEDERACIÓN"]): continue

                matches = []
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) < 4: continue
                    score = cols[2].get_text(strip=True)
                    matches.append({
                        "date": cols[0].get_text(strip=True),
                        "home": cols[1].get_text(strip=True),
                        "away": cols[3].get_text(strip=True),
                        "score": score,
                        "status": "FT" if ("-" in score and any(i.isdigit() for i in score)) else "Pending"
                    })
                
                if matches:
                    temp_rounds.append({"key": round_title, "matches": matches})

            comp_data["rounds"] = {r["key"]: r["matches"] for r in temp_rounds}
            comp_data["current"] = temp_rounds[-1]["key"] if temp_rounds else ""
            results_map[name] = comp_data
        except: continue
    return results_map

# --- EJECUCIÓN ---
if __name__ == "__main__":
    run, reason = check_if_update_needed()
    if run:
        print(f"✅ {reason}")
        # 1. Agenda
        agenda_data = scrape_agenda()
        with open(CALENDAR_FILE, 'w') as f: json.dump(agenda_data, f, indent=2)
        
        # 2. Clasificaciones
        standings_data = scrape_standings()
        with open(STANDINGS_FILE, 'w') as f: json.dump(standings_data, f, indent=2)
        
        # 3. Resultados
        results_data = scrape_results()
        with open(RESULTS_FILE, 'w') as f: json.dump(results_data, f, indent=2)
        
        print("🎉 Proceso completado. Archivos generados.")
    else:
        print(f"💤 {reason}")
