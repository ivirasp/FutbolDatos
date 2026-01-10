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
    print("📊 Extrayendo Clasificaciones con precisión HTML...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            # Buscamos las filas de la tabla
            rows = soup.find_all('tr', class_=lambda x: x and ('cha' in x or 'cla' in x or 'rel' in x))
            
            league_data = []
            for row in rows:
                # 1. Extraer del <th> (Rango y Nombre)
                th = row.find('th')
                if not th: continue
                rank = th.find('span', class_='classification-pos').get_text(strip=True)
                team_name = th.find('h2', class_='nombre-equipo').get_text(strip=True)
                
                # 2. Extraer de los <td> (Stats)
                tds = row.find_all('td')
                if len(tds) < 7: continue
                
                # Siguiendo tu código fuente:
                pts = tds[0].get_text(strip=True)
                pj  = tds[1].get_text(strip=True)
                pg  = tds[2].get_text(strip=True)
                pe  = tds[3].get_text(strip=True)
                pp  = tds[4].get_text(strip=True)
                gf  = tds[5].get_text(strip=True)
                gc  = tds[6].get_text(strip=True)
                
                # Calcular Diferencia de Goles (DG)
                try:
                    dg_val = int(gf) - int(gc)
                    dg = f"+{dg_val}" if dg_val > 0 else str(dg_val)
                except: dg = "0"

                prefix = get_prefix(name, rank)
                
                league_data.append({
                    "rank": rank,
                    "team": f"{prefix}{team_name}",
                    "points": pts,
                    "played": pj,
                    "won": pg,
                    "drawn": pe,
                    "lost": pp,
                    "gf": gf,
                    "ga": gc,
                    "dg": dg
                })
            
            if league_data: 
                data_map[name] = league_data
                print(f"   ✅ {name} ok")
        except Exception as e: print(f"Error en {name}: {e}")
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
