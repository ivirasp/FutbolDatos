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

# Reglas de Clasificación e Indicadores
RULES = {
    "LALIGA": { "champions": (1, 4), "europa": (5, 5), "conference": (6, 6), "relegation": (18, 20) },
    "CHAMPIONS": { "knockout_direct": (1, 8), "playoff": (9, 24) },
    "EUROPA": { "knockout_direct": (1, 8), "playoff": (9, 24) }
}
INDICATORS = {
    "champions": "🟢 ", "europa": "🔵 ", "conference": "🟡 ", "relegation": "🔴 ", 
    "knockout_direct": "✅ ", "playoff": "⚔️ ", "midtable": ""
}

def get_prefix(competition, rank_str):
    try:
        rank = int(rank_str)
        comp_rules = RULES.get(competition)
        if not comp_rules: return INDICATORS["midtable"]
        for status_name, (start, end) in comp_rules.items():
            if start <= rank <= end: return INDICATORS.get(status_name, "")
        return INDICATORS["midtable"]
    except: return INDICATORS["midtable"]

def scrape_standings():
    print("📊 Extrayendo Clasificaciones COMPLETAS...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # Buscamos la tabla que más filas tenga (la principal)
            tables = soup.find_all('table')
            if not tables: continue
            table = max(tables, key=lambda t: len(t.find_all('tr')))
            rows = table.find_all('tr')
            
            league_data = []
            seen_teams = set() # <--- Esto evita que se repitan Barça, Madrid, etc.

            for row in rows:
                # Buscamos el rango y el nombre del equipo según tu código fuente
                rank_span = row.find('span', class_='classification-pos')
                team_h2 = row.find('h2', class_='nombre-equipo')
                
                if not rank_span or not team_h2: continue
                
                rank = rank_span.get_text(strip=True)
                team = team_h2.get_text(strip=True)
                
                # Si el equipo ya lo hemos procesado en esta liga, lo saltamos (evita Casa/Fuera)
                if team in seen_teams: continue
                seen_teams.add(team)
                
                tds = row.find_all('td')
                if len(tds) < 7: continue
                
                # Mapeo exacto de tu fuente: 0=Pts, 1=PJ, 2=PG, 3=PE, 4=PP, 5=GF, 6=GC
                pts = tds[0].get_text(strip=True)
                pj  = tds[1].get_text(strip=True)
                pg  = tds[2].get_text(strip=True)
                pe  = tds[3].get_text(strip=True)
                pp  = tds[4].get_text(strip=True)
                gf  = tds[5].get_text(strip=True)
                gc  = tds[6].get_text(strip=True)
                
                try:
                    dg_val = int(gf) - int(gc)
                    dg = f"+{dg_val}" if dg_val > 0 else str(dg_val)
                except: dg = "0"

                prefix = get_prefix(name, rank)
                league_data.append({
                    "rank": rank,
                    "team": f"{prefix}{team}",
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
                print(f"   ✅ {name} ok: {len(league_data)} equipos.")
        except Exception as e:
            print(f"   ❌ Error en {name}: {e}")
    return data_map

def scrape_agenda():
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
    # Forzamos la actualización eliminando el IF para probar
    print("🚀 Iniciando actualización forzada...")
    with open(CALENDAR_FILE, 'w') as f: json.dump(scrape_agenda(), f, indent=2)
    with open(STANDINGS_FILE, 'w') as f: json.dump(scrape_standings(), f, indent=2)
    with open(RESULTS_FILE, 'w') as f: json.dump(scrape_results(), f, indent=2)
    print("🎉 ¡Datos actualizados con éxito!")
