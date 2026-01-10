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

TARGET_URLS_AGENDA = {
    "https://www.futboltv.info/competicion/laliga": "LALIGA",
    "https://www.futboltv.info/competicion/champions-league": "CHAMPIONS",
    "https://www.futboltv.info/competicion/europa-league": "EUROPA",
    "https://www.futboltv.info/competicion/copa-del-rey": "COPA"
}

URLS_STANDINGS = {
    "LALIGA": "https://www.lavanguardia.com/deportes/resultados/laliga-primera-division/clasificacion",
    "CHAMPIONS": "https://www.lavanguardia.com/deportes/resultados/champions-league/clasificacion",
    "EUROPA": "https://www.lavanguardia.com/deportes/resultados/europa-league/clasificacion"
}

URLS_RESULTS = [
    ("LALIGA", "https://www.sport.es/resultados/futbol/primera-division/calendario-liga/"),
    ("CHAMPIONS", "https://www.sport.es/resultados/futbol/champions-league/calendario/"),
    ("EUROPA", "https://www.sport.es/resultados/futbol/europa-league/calendario-liga/"),
    ("COPA", "https://www.superdeporte.es/deportes/futbol/copa-rey/calendario/")
]

# --- 2. FUNCIONES DE EXTRACCIÓN ---

def scrape_agenda():
    print("🌍 Extrayendo Agenda...")
    agenda = []
    seen = set()
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    for url, comp_label in TARGET_URLS_AGENDA.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            articles = soup.find_all("article", class_="match")
            for art in articles:
                name_tag = art.find("meta", itemprop="name")
                date_tag = art.find("meta", itemprop="startDate")
                if not name_tag or not date_tag: continue

                title = name_tag.get("content", "").strip()
                date_str = date_tag.get("content", "").split('+')[0]
                dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                ts = TZ_MADRID.localize(dt).timestamp()

                chan_span = art.find("span", itemprop="name")
                channel = chan_span.get_text(strip=True) if chan_span else "TBD"

                match_id = f"{title}_{ts}"
                if match_id not in seen:
                    seen.add(match_id)
                    agenda.append({
                        "title": title,
                        "start_ts": ts,
                        "channel": channel,
                        "competition": comp_label
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
            tables = soup.find_all('table')
            if not tables: continue
            main_table = max(tables, key=lambda t: len(t.find_all('tr')))
            rows = main_table.find_all('tr')[1:]
            league_data = []
            seen_teams = set()
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
                pts, pj, pg, pe, pp, gf, gc = [t.get_text(strip=True) for t in tds[:7]]
                try:
                    dg_val = int(gf) - int(gc)
                    dg = f"+{dg_val}" if dg_val > 0 else str(dg_val)
                except: dg = "0"
                league_data.append({
                    "rank": rank, "team": team, "points": pts, 
                    "played": pj, "won": pg, "drawn": pe, "lost": pp,
                    "gf": gf, "ga": gc, "dg": dg
                })
            if league_data: data_map[name] = league_data
        except: continue
    return data_map

def scrape_results():
    print("⚽ Extrayendo Resultados (Búsqueda por clases)...")
    results_map = {}
    today = datetime.now(TZ_MADRID).date()
    
    for name, url in URLS_RESULTS:
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            temp_rounds = []
            current_round_key = ""
            current_found = False
            
            for table in soup.find_all('table'):
                # 1. Nombre de la Jornada
                cap = table.find("caption")
                orig_title = cap.find("h2").get_text(strip=True).replace("ª", "") if cap else "Jornada"
                if any(kw in orig_title.upper() for kw in ["FIFA", "WOMEN"]): continue
                
                final_title = orig_title
                # 2. Identificar Jornada Actual
                date_th = table.find("th", class_="textoizda")
                if date_th and not current_found:
                    dates = re.findall(r'(\d{4}-\d{2}-\d{2})', date_th.get_text())
                    if len(dates) == 2:
                        end_date = datetime.strptime(dates[1], "%Y-%m-%d").date()
                        if today <= end_date:
                            final_title = f"{orig_title} (Actual)"
                            current_round_key = final_title
                            current_found = True

                matches = []
                for row in table.find_all('tr'):
                    tds = row.find_all('td')
                    if not tds: continue

                    # A. EXTRACCIÓN DEL RESULTADO (Prioritaria)
                    score = ""
                    # 1. Buscar enlace o span con clase específica (Champions/Copa/LaLiga moderna)
                    score_container = row.find('a', class_='geca_enlace_partido') or \
                                      row.find('span', class_='celdagoles') or \
                                      row.find('td', class_='resultado')
                    
                    if score_container:
                        score = score_container.get_text(strip=True)
                    else:
                        # 2. Búsqueda manual: escanear celdas buscando patrón "N - N"
                        for td in tds:
                            txt = td.get_text(strip=True)
                            # Si encontramos "numero - numero", es el marcador seguro
                            if re.search(r'^\d+\s*-\s*\d+$', txt):
                                score = txt
                                break
                    
                    # Si después de todo score está vacío o es raro, marcamos "vs"
                    if not score or ":" in score or "/" in score or score == "-":
                        score = "vs"

                    # B. EXTRACCIÓN DE FECHA
                    time_tag = row.find('time')
                    if time_tag:
                        dt_s = time_tag.get('datetime', '').split('T')[0]
                        date_val = datetime.strptime(dt_s, "%Y-%m-%d").strftime("%d-%m-%Y")
                    else:
                        # Buscamos celda con formato fecha DD/MM o fecha completa
                        date_val = ""
                        for td in tds:
                            txt = td.get_text(strip=True)
                            if re.search(r'\d{2}/\d{2}', txt) or re.search(r'\d{2}-\d{2}', txt):
                                date_val = txt
                                break
                        # Fallback: primera columna si no se encontró nada
                        if not date_val: date_val = tds[0].get_text(strip=True)

                    # C. EXTRACCIÓN DE EQUIPOS
                    team_links = row.find_all('a', class_='geca_enlace_equipo')
                    if len(team_links) >= 2:
                        home = team_links[0].get('title', team_links[0].get_text(strip=True))
                        away = team_links[1].get('title', team_links[1].get_text(strip=True))
                    elif len(tds) >= 4:
                        # Asumimos estructura estándar si no hay enlaces geca
                        # Evitamos coger la columna que identificamos como fecha o score
                        home = tds[1].get_text(strip=True)
                        away = tds[3].get_text(strip=True)
                    else:
                        continue # Fila inválida

                    if home and away:
                        matches.append({
                            "date": date_val,
                            "home": home,
                            "away": away,
                            "score": score
                        })
                
                if matches:
                    temp_rounds.append({"key": final_title, "matches": matches})
            
            if temp_rounds:
                results_map[name] = {
                    "rounds": {r["key"]: r["matches"] for r in temp_rounds},
                    "current": current_round_key if current_round_key else temp_rounds[-1]["key"]
                }
        except: continue
    return results_map

# --- 3. EJECUCIÓN ---

if __name__ == "__main__":
    # Agenda
    agenda_data = scrape_agenda()
    with open(CALENDAR_FILE, 'w') as f:
        json.dump(agenda_data, f, indent=2)
    
    # Standings
    standings_data = scrape_standings()
    with open(STANDINGS_FILE, 'w') as f:
        json.dump(standings_data, f, indent=2)
    
    # Resultados
    results_data = scrape_results()
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results_data, f, indent=2)
    
    print("🎉 Datos generados (Búsqueda selectiva de marcador).")
