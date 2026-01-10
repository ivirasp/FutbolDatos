# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import re
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

def scrape_standings():
    print("📊 Extrayendo Clasificaciones...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.content, 'html.parser')
            tables = soup.find_all('table')
            if not tables: continue
            
            # Buscamos la tabla con más filas (la de la liga)
            table = max(tables, key=lambda t: len(t.find_all('tr')))
            rows = table.find_all('tr')
            
            league_data = []
            rank_counter = 0
            seen_teams = set()
            
            for row in rows:
                cells = row.find_all(['th', 'td'])
                texts = [c.get_text(strip=True) for c in cells if c.get_text(strip=True)]
                if len(texts) < 4: continue
                
                # Evitar cabeceras
                if any(t.upper() in ["EQUIPO", "PTS", "POS"] for t in texts): continue
                
                # Buscar nombre del equipo y puntos (Lógica de tu standings.py original)
                team = ""
                stats = []
                for t in texts:
                    if len(t) > 2 and not t.isdigit(): team = t
                    elif t.isdigit() or (len(t) <= 2 and t.isdigit()): stats.append(t)
                
                if not team: continue
                team = re.sub(r'^\d+\.?\s*', '', team) # Limpiar número inicial si existe
                
                if team in seen_teams: continue
                seen_teams.add(team)
                
                if len(stats) >= 2:
                    rank_counter += 1
                    league_data.append({
                        "rank": str(rank_counter),
                        "team": team,
                        "points": stats[0] # El primer número suelen ser los puntos
                    })
            if league_data:
                data_map[name] = league_data
                print(f"   ✅ {name}: {len(league_data)} equipos.")
        except Exception as e: print(f"   ❌ Error en {name}: {e}")
    return data_map

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
                if f"{name}_{ts}" not in seen:
                    seen.add(f"{name}_{ts}")
                    agenda.append({"title": name, "start_ts": ts, "channel": chan})
        except: continue
    return sorted(agenda, key=lambda x: x['start_ts'])

def scrape_results():
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
                title = caption.find("h2").get_text(strip=True) if caption and caption.find("h2") else "Jornada"
                matches = []
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) < 4: continue
                    matches.append({
                        "date": cols[0].get_text(strip=True),
                        "home": cols[1].get_text(strip=True),
                        "away": cols[3].get_text(strip=True),
                        "score": cols[2].get_text(strip=True)
                    })
                if matches: temp_rounds.append({"key": title, "matches": matches})
            results_map[name] = {"rounds": {r["key"]: r["matches"] for r in temp_rounds}, "current": temp_rounds[-1]["key"] if temp_rounds else ""}
        except: continue
    return results_map

if __name__ == "__main__":
    # Ejecutamos todo
    agenda_data = scrape_agenda()
    with open(CALENDAR_FILE, 'w') as f: json.dump(agenda_data, f, indent=2)

    standings_data = scrape_standings()
    with open(STANDINGS_FILE, 'w') as f: json.dump(standings_data, f, indent=2)

    results_data = scrape_results()
    with open(RESULTS_FILE, 'w') as f: json.dump(results_data, f, indent=2)
    
    print("🎉 ¡Todo listo!")
