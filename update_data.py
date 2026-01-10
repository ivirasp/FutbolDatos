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

TARGET_URLS_AGENDA = [
    "https://www.futboltv.info/competicion/laliga",
    "https://www.futboltv.info/competicion/champions-league",
    "https://www.futboltv.info/competicion/europa-league",
    "https://www.futboltv.info/competicion/copa-del-rey"
]

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

def check_if_update_needed():
    now_ts = time.time()
    # Si no existen los archivos, ACTUALIZAR SÍ O SÍ
    if not os.path.exists(CALENDAR_FILE):
        return True, "Archivos no existen en el repositorio"

    try:
        with open(CALENDAR_FILE, 'r') as f:
            matches = json.load(f)
        
        # Modo Partido: Evento próximo (< 3h) o en vivo
        is_game_near = any(m for m in matches if (m['start_ts'] - 10800) <= now_ts <= m['stop_ts'])
        if is_game_near: return True, "Modo Partido (Prioridad 15 min)"

        # Modo Ahorro: Han pasado 4 horas
        if (now_ts - os.path.getmtime(CALENDAR_FILE)) > 14400:
            return True, "Modo Ahorro (Han pasado 4h)"
    except:
        return True, "Error lectura, forzando"
        
    return False, "Durmiendo... No hay eventos cerca"

def scrape_all():
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 1. Agenda
    print("🌍 Extrayendo Agenda...")
    agenda = []
    seen = set()
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
                if f"{name}_{ts}" not in seen:
                    seen.add(f"{name}_{ts}")
                    agenda.append({"title": name, "teams": name, "channel": chan, "start_ts": ts, "stop_ts": ts + 7200})
        except: continue
    with open(CALENDAR_FILE, 'w') as f: json.dump(sorted(agenda, key=lambda x: x['start_ts']), f, indent=2)

    # 2. Clasificaciones
    print("📊 Extrayendo Clasificaciones...")
    standings = {}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            table = max(soup.find_all('table'), key=lambda t: len(t.find_all('tr')))
            league = []
            for row in table.find_all('tr')[1:]:
                c = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                if len(c) > 5 and c[0].isdigit():
                    league.append({"rank": c[0], "team": c[1], "points": c[2], "played": c[3], "won": c[4], "drawn": c[5], "lost": c[6]})
            standings[name] = league
        except: continue
    with open(STANDINGS_FILE, 'w') as f: json.dump(standings, f, indent=2)

    # 3. Resultados
    print("⚽ Extrayendo Resultados...")
    results_map = {}
    for name, url in URLS_RESULTS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            temp_rounds = []
            for table in soup.find_all('table'):
                caption = table.find("caption")
                round_title = caption.find("h2").get_text(strip=True).replace("ª", "") if caption and caption.find("h2") else "Jornada"
                if any(kw in round_title.upper() for kw in ["FIFA", "WOMEN", "FEDERACIÓN"]): continue
                matches = []
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) < 4: continue
                    score = cols[2].get_text(strip=True)
                    matches.append({"date": cols[0].get_text(strip=True), "home": cols[1].get_text(strip=True), "away": cols[3].get_text(strip=True), "score": score, "status": "FT" if "-" in score else "Pending"})
                if matches: temp_rounds.append({"key": round_title, "matches": matches})
            results_map[name] = {"rounds": {r["key"]: r["matches"] for r in temp_rounds}, "current": temp_rounds[-1]["key"] if temp_rounds else ""}
        except: continue
    with open(RESULTS_FILE, 'w') as f: json.dump(results_map, f, indent=2)

if __name__ == "__main__":
    run, reason = check_if_update_needed()
    if run:
        print(f"✅ {reason}")
        scrape_all()
        print("🎉 Proceso completado.")
    else:
        print(f"💤 {reason}")
        # Aseguramos que los archivos existan aunque no actualicemos para que GIT no de error
        for f in [CALENDAR_FILE, STANDINGS_FILE, RESULTS_FILE]:
            if not os.path.exists(f): 
                with open(f, 'w') as out: out.write("[]")
