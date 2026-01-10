# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime
import pytz

TZ_MADRID = pytz.timezone('Europe/Madrid')
CALENDAR_FILE = "calendar.json"
STANDINGS_FILE = "standings.json"
RESULTS_FILE = "results.json"

URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

def get_prefix(competition, rank_str):
    """ Mantenemos los indicadores visuales para los puestos especiales """
    try:
        rank = int(rank_str)
        if competition == "LALIGA":
            if rank <= 4: return "🟢 "
            if rank == 5: return "🔵 "
            if rank == 6: return "🟡 "
            if rank >= 18: return "🔴 "
        elif rank <= 8: return "✅ "
        elif rank <= 24: return "⚔️ "
    except: pass
    return ""

def scrape_standings():
    print("📊 Extrayendo Clasificaciones COMPLETAS...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # Buscamos específicamente la tabla de clasificación para evitar duplicados de Casa/Fuera
            # En La Vanguardia, la tabla principal suele estar dentro de un div específico
            tables = soup.find_all('table')
            if not tables: continue
            
            # Seleccionamos la tabla con más filas (la clasificación general tiene más datos)
            main_table = max(tables, key=lambda t: len(t.find_all('tr')))
            rows = main_table.find_all('tr')
            
            league_data = []
            for row in rows:
                th = row.find('th')
                if not th: continue
                
                # Intentamos sacar el rango y el equipo
                rank_node = th.find('span', class_='classification-pos')
                team_node = th.find('h2', class_='nombre-equipo')
                
                if not rank_node or not team_node: continue
                
                rank = rank_node.get_text(strip=True)
                team = team_node.get_text(strip=True)
                
                tds = row.find_all('td')
                if len(tds) < 7: continue
                
                # Mapeo: Puntos, PJ, PG, PE, PP, GF, GC
                pts, pj, pg, pe, pp, gf, gc = [t.get_text(strip=True) for t in tds[:7]]
                
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
    # Guardar standings.json con todos los datos
    standings = scrape_standings()
    with open(STANDINGS_FILE, 'w') as f:
        json.dump(standings, f, indent=2)
