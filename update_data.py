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

URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

# (Mantén aquí tus listas TARGET_URLS_AGENDA y URLS_RESULTS igual que antes)

def scrape_standings():
    print("📊 Extrayendo Clasificaciones Completas...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # Buscamos las filas basándonos en las clases que pusiste (cha, cla, rel)
            rows = soup.find_all('tr', class_=lambda x: x and any(c in x for c in ['cha', 'cla', 'rel']))
            
            league_data = []
            for row in rows:
                th = row.find('th')
                if not th: continue
                
                # Nombre y Posición
                rank = th.find('span', class_='classification-pos').get_text(strip=True)
                team = th.find('h2', class_='nombre-equipo').get_text(strip=True)
                
                # Estadísticas (tds)
                tds = row.find_all('td')
                if len(tds) < 7: continue
                
                # Mapeo según tu código fuente:
                # tds[0] = Puntos, [1] = PJ, [2] = PG, [3] = PE, [4] = PP, [5] = GF, [6] = GC
                pts = tds[0].get_text(strip=True)
                pj  = tds[1].get_text(strip=True)
                pg  = tds[2].get_text(strip=True)
                pe  = tds[3].get_text(strip=True)
                pp  = tds[4].get_text(strip=True)
                gf  = tds[5].get_text(strip=True)
                gc  = tds[6].get_text(strip=True)
                
                # Diferencia de Goles
                try:
                    dg_val = int(gf) - int(gc)
                    dg = f"+{dg_val}" if dg_val > 0 else str(dg_val)
                except: dg = "0"

                # MUY IMPORTANTE: Aquí es donde metemos todos los datos al JSON
                league_data.append({
                    "rank": rank,
                    "team": team,
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
                print(f"   ✅ {name} procesado.")
        except Exception as e:
            print(f"   ❌ Error en {name}: {e}")
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
