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

def scrape_agenda():
    print("🌍 Extrayendo Agenda...")
    agenda = []
    seen = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for url in TARGET_URLS_AGENDA:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            # Cambio clave: Buscamos <article class="match">
            articles = soup.find_all("article", class_="match")
            for art in articles:
                name_tag = art.find("meta", itemprop="name")
                date_tag = art.find("meta", itemprop="startDate")
                if not name_tag or not date_tag: continue

                title = name_tag.get("content", "").strip()
                date_str = date_tag.get("content", "").split('+')[0]
                dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                ts = TZ_MADRID.localize(dt).timestamp()

                # Canal: Buscamos el span con itemprop="name" dentro de match_channels
                chan_span = art.find("span", itemprop="name")
                channel = chan_span.get_text(strip=True) if chan_span else "TBD"

                match_id = f"{title}_{ts}"
                if match_id not in seen:
                    seen.add(match_id)
                    agenda.append({"title": title, "start_ts": ts, "channel": channel})
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
            rows = main_table.find_all('tr')
            league_data = []; seen_teams = set()
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
                # Pts, PJ, PG, PE, PP, GF, GC
                pts, pj, pg, pe, pp, gf, gc = [t.get_text(strip=True) for t in tds[:7]]
                dg = f"+{int(gf)-int(gc)}" if int(gf)-int(gc) > 0 else str(int(gf)-int(gc))
                league_data.append({"rank": rank, "team": team, "points": pts, "played": pj, "won": pg, "drawn": pe, "lost": pp, "gf": gf, "ga": gc, "dg": dg})
            if league_data: data_map[name] = league_data
        except: continue
    return data_map

def scrape_results():
    print("⚽ Extrayendo Resultados...")
    results_map = {}
    for name, url in URLS_RESULTS.items():
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            temp_rounds = []
            for table in soup.find_all('table'):
                cap = table.find("caption")
                title = cap.find("h2").get_text(strip=True).replace("ª", "") if cap else "Jornada"
                matches = []
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) < 4: continue
                    matches.append({"date": cols[0].get_text(strip=True), "home": cols[1].get_text(strip=True), "away": cols[3].get_text(strip=True), "score": cols[2].get_text(strip=True)})
                if matches: temp_rounds.append({"key": title, "matches": matches})
            if temp_rounds: results_map[name] = {"rounds": {r["key"]: r["matches"] for r in temp_rounds}, "current": temp_rounds[-1]["key"]}
        except: continue
    return results_map

if __name__ == "__main__":
    with open(CALENDAR_FILE, 'w') as f: json.dump(scrape_agenda(), f, indent=2)
    with open(STANDINGS_FILE, 'w') as f: json.dump(scrape_standings(), f, indent=2)
    with open(RESULTS_FILE, 'w') as f: json.dump(scrape_results(), f, indent=2)
    print("🎉 ¡Datos actualizados!")
