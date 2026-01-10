# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime
import pytz

# --- 1. CONFIGURACIÓN GLOBAL ---
TZ_MADRID = pytz.timezone('Europe/Madrid')
CALENDAR_FILE = "calendar.json"
STANDINGS_FILE = "standings.json"
RESULTS_FILE = "results.json"

# URLs para la Agenda
TARGET_URLS_AGENDA = [
    "https://www.futboltv.info/competicion/laliga",
    "https://www.futboltv.info/competicion/champions-league",
    "https://www.futboltv.info/competicion/europa-league",
    "https://www.futboltv.info/competicion/copa-del-rey"
]

# URLs para Clasificaciones
URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

# URLs para Resultados
URLS_RESULTS = {
    "LALIGA": "https://www.sport.es/resultados/futbol/primera-division/calendario-liga/",
    "CHAMPIONS": "https://www.sport.es/resultados/futbol/champions-league/calendario/",
    "EUROPA": "https://www.sport.es/resultados/futbol/europa-league/calendario-liga/",
    "COPA": "https://www.superdeporte.es/deportes/futbol/copa-rey/calendario/"
}

# --- 2. FUNCIONES DE EXTRACCIÓN ---

def scrape_agenda():
    print("🌍 Extrayendo Agenda...")
    agenda = []
    seen = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    
    for url in TARGET_URLS_AGENDA:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200: continue
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # Buscamos bloques de partidos
            matches = soup.find_all("div", class_="match")
            for div in matches:
                meta_date = div.find("meta", itemprop="startDate")
                meta_name = div.find("meta", itemprop="name")
                if not meta_date or not meta_name: continue
                
                # Procesar fecha y título
                date_str = meta_date.get("content", "").split('+')[0]
                dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                ts = TZ_MADRID.localize(dt).timestamp()
                title = meta_name.get("content", "").strip()
                
                # Canal
                chan_div = div.find("div", class_="m_chan") or div.find("div", class_="channels")
                channel = chan_div.get_text(strip=True) if chan_div else "TBD"
                
                match_id = f"{title}_{ts}"
                if match_id not in seen:
                    seen.add(match_id)
                    agenda.append({
                        "title": title,
                        "start_ts": ts,
                        "channel": channel,
                        "stop_ts": ts + 7200
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
            # Buscamos las filas con clases de competición o descenso
            rows = soup.find_all('tr', class_=lambda x: x and any(c in x for c in ['cha', 'cla', 'rel']))
            
            league_data = []
            seen_teams = set()
            for row in rows:
                th = row.find('th')
                if not th: continue
                rank = th.find('span', class_='classification-pos').get_text(strip=True)
                team = th.find('h2', class_='nombre-equipo').get_text(strip=True)
                
                if team in seen_teams: continue
                seen_teams.add(team)

                tds = row.find_all('td')
                if len(tds) < 7: continue
                
                # Orden: Pts, PJ, PG, PE, PP, GF, GC
                pts, pj, pg, pe, pp, gf, gc = [t.get_text(strip=True) for t in tds[:7]]
                
                try:
                    dg_val = int(gf) - int(gc)
                    dg = f"+{dg_val}" if dg_val > 0 else str(dg_val)
                except: dg = "0"

                league_data.append({
                    "rank": rank,
                    "team": team,  # Nombre limpio (sin iconos)
                    "points": pts,
                    "played": pj, "won": pg, "drawn": pe, "lost": pp,
                    "gf": gf, "ga": gc, "dg": dg
                })
            if league_data: data_map[name] = league_data
        except: continue
    return data_map

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
                title = caption.find("h2").get_text(strip=True).replace("ª", "") if caption else "Jornada"
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
            if temp_rounds:
                results_map[name] = {"rounds": {r["key"]: r["matches"] for r in temp_rounds}, "current": temp_rounds[-1]["key"]}
        except: continue
    return results_map

# --- 3. BLOQUE DE EJECUCIÓN ---

if __name__ == "__main__":
    print("🚀 Iniciando actualización forzada...")
    
    # 1. Agenda
    agenda_data = scrape_agenda()
    with open(CALENDAR_FILE, 'w') as f:
        json.dump(agenda_data, f, indent=2)
    print(f"✅ Agenda: {len(agenda_data)} partidos guardados.")

    # 2. Clasificación
    standings_data = scrape_standings()
    with open(STANDINGS_FILE, 'w') as f:
        json.dump(standings_data, f, indent=2)
    print(f"✅ Clasificación: {len(standings_data)} ligas guardadas.")

    # 3. Resultados
    results_data = scrape_results()
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results_data, f, indent=2)
    
    print("🎉 ¡Proceso completado con éxito!")
