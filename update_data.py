# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime
import pytz

# --- 1. CONFIGURACIÓN ---
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

# Mapa de meses para traducir Champions "Septiembre" -> "09"
MONTH_MAP = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12"
}

# --- 2. FUNCIONES AUXILIARES ---

def parse_spanish_date(text):
    """Convierte 'Miércoles, 16 de Septiembre' a '16/09'"""
    try:
        text = text.lower()
        # Buscar patrón "16 de mes"
        match = re.search(r"(\d+)\s+de\s+(\w+)", text)
        if match:
            day, month_txt = match.groups()
            month_num = MONTH_MAP.get(month_txt, "01")
            return f"{day.zfill(2)}/{month_num}"
    except:
        pass
    return ""

# --- 3. FUNCIONES DE EXTRACCIÓN ---

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
                rank = rank_n.get_text(strip=True); team = team_n.get_text(strip=True)
                if team in seen_teams: continue
                seen_teams.add(team)
                tds = row.find_all('td')
                if len(tds) < 7: continue
                pts, pj, pg, pe, pp, gf, gc = [t.get_text(strip=True) for t in tds[:7]]
                try: dg_val = f"+{int(gf)-int(gc)}" if int(gf)-int(gc) > 0 else str(int(gf)-int(gc))
                except: dg_val = "0"
                league_data.append({"rank": rank, "team": team, "points": pts, "played": pj, "won": pg, "drawn": pe, "lost": pp, "gf": gf, "ga": gc, "dg": dg_val})
            if league_data: data_map[name] = league_data
        except: continue
    return data_map

def scrape_results():
    print("⚽ Extrayendo Resultados (Unificado Champions/Liga)...")
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
                # 1. Nombre de Jornada
                # A veces el caption está dentro de la tabla, a veces es un H2 previo
                cap = table.find("caption")
                orig_title = "Jornada"
                if cap and cap.find("h2"):
                    orig_title = cap.find("h2").get_text(strip=True).replace("ª", "")
                else:
                    # Intento fallback para estructura rara
                    prev_h2 = table.find_previous("h2", class_="table-caption")
                    if prev_h2: orig_title = prev_h2.get_text(strip=True).replace("ª", "")

                if any(kw in orig_title.upper() for kw in ["FIFA", "WOMEN"]): continue
                
                final_title = orig_title
                
                # 2. Contexto de Fecha (Header de Champions)
                # Buscamos si hay un TH con fecha en el THEAD (ej: "Miércoles, 16 de Septiembre")
                current_header_date = ""
                thead = table.find("thead")
                if thead:
                    th_date = thead.find("th", class_="textoizda")
                    if th_date:
                        # Si es un rango (Liga): "2025-08-15 - 2025-08-19"
                        raw_txt = th_date.get_text(strip=True)
                        dates_range = re.findall(r'(\d{4}-\d{2}-\d{2})', raw_txt)
                        
                        if len(dates_range) == 2:
                            # Es Liga, usamos rango para "Actual"
                            if not current_found:
                                end_date = datetime.strptime(dates_range[1], "%Y-%m-%d").date()
                                if today <= end_date:
                                    final_title = f"{orig_title} (Actual)"
                                    current_round_key = final_title
                                    current_found = True
                        else:
                            # Es Champions/Copa, es una fecha única texto: "Miércoles, 16 de Septiembre"
                            # Intentamos parsear para tener una fecha por defecto para las filas
                            parsed = parse_spanish_date(raw_txt)
                            if parsed: current_header_date = parsed

                matches = []
                # Recorremos filas (TR)
                for row in table.find_all('tr'):
                    # Si es una fila de cabecera intermedia (Champions tiene varias fechas en una tabla)
                    th_sub = row.find("th", class_="textoizda")
                    if th_sub:
                        # Actualizamos la fecha contexto
                        raw_txt = th_sub.get_text(strip=True)
                        parsed = parse_spanish_date(raw_txt)
                        if parsed: current_header_date = parsed
                        continue

                    tds = row.find_all('td')
                    if len(tds) < 3: continue

                    # A. FECHA
                    date_val = ""
                    # 1. Mirar si la primera celda tiene formato DD/MM (La Liga)
                    txt_col0 = tds[0].get_text(strip=True)
                    if re.search(r'\d{2}/\d{2}', txt_col0):
                        date_val = txt_col0
                    # 2. Si no, usar la fecha de cabecera (Champions)
                    elif current_header_date:
                        date_val = current_header_date
                    
                    # B. EQUIPOS (Prioridad Title)
                    # La Liga: td.textodcha > a[title]
                    # Champions: td.textodcha > div > a > span (o title)
                    home = ""
                    away = ""
                    
                    # Local
                    home_node = row.find("td", class_="textodcha")
                    if home_node:
                        # Buscamos enlace con title
                        a_tag = home_node.find("a", class_="geca_enlace_equipo")
                        if a_tag and a_tag.has_attr("title"):
                            home = a_tag["title"]
                        elif a_tag:
                            home = a_tag.get_text(strip=True) # Fallback al texto
                        else:
                            home = home_node.get_text(strip=True)

                    # Visitante
                    away_node = row.find("td", class_="textoizda") # Ojo, en champions a veces comparten clase
                    # Truco: el visitante es el último td con clase textoizda o el td siguiente al resultado
                    if away_node:
                         a_tag = away_node.find("a", class_="geca_enlace_equipo")
                         if a_tag and a_tag.has_attr("title"):
                            away = a_tag["title"]
                         elif a_tag:
                            away = a_tag.get_text(strip=True)
                         else:
                            away = away_node.get_text(strip=True)
                    
                    # Si falló la extracción por clases específicas, fallback a índices
                    if not home and len(tds) > 1: home = tds[1].get_text(strip=True)
                    if not away and len(tds) > 3: away = tds[3].get_text(strip=True)

                    # C. RESULTADO
                    final_score = "vs"
                    
                    # 1. Buscar enlace de partido
                    score_a = row.find('a', class_='geca_enlace_partido')
                    if score_a:
                        txt = score_a.get_text(strip=True)
                        if re.search(r'^\d+\s*-\s*\d+$', txt): final_score = txt
                    
                    # 2. Buscar celdagoles
                    if final_score == "vs":
                        score_span = row.find('span', class_='celdagoles')
                        if score_span:
                            txt = score_span.get_text(strip=True)
                            if re.search(r'^\d+\s*-\s*\d+$', txt): final_score = txt
                    
                    # 3. Fuerza bruta columnas (La Liga suele tenerlo en col 2, pero validamos)
                    if final_score == "vs":
                        for td in tds:
                            txt = td.get_text(strip=True)
                            if re.search(r'^\d+\s*-\s*\d+$', txt):
                                final_score = txt
                                break

                    # Limpieza final de nombres
                    home = home.strip()
                    away = away.strip()

                    if home and away:
                        matches.append({
                            "date": date_val,
                            "home": home,
                            "away": away,
                            "score": final_score
                        })
                
                if matches:
                    temp_rounds.append({"key": final_title, "matches": matches})
            
            # Ordenamos Champions/Copa para que la última jornada sea la "Actual" por defecto si no detectamos fecha
            if temp_rounds:
                # Si no encontramos "Actual" por fecha (Champions), cogemos la última del array
                def_current = current_round_key if current_round_key else temp_rounds[-1]["key"]
                
                # Hack: En Champions/Copa, si no hemos detectado fecha fin, marcamos la última como actual
                if "Actual" not in def_current and name in ["CHAMPIONS", "COPA"]:
                     # Simplemente usamos la última disponible como la que se muestra
                     pass 

                results_map[name] = {
                    "rounds": {r["key"]: r["matches"] for r in temp_rounds},
                    "current": def_current
                }
        except Exception as e: print(f"Error {name}: {e}")
            
    return results_map

# --- 4. MAIN ---

if __name__ == "__main__":
    agenda_data = scrape_agenda()
    with open(CALENDAR_FILE, 'w') as f: json.dump(agenda_data, f, indent=2)
    
    standings_data = scrape_standings()
    with open(STANDINGS_FILE, 'w') as f: json.dump(standings_data, f, indent=2)
    
    results_data = scrape_results()
    with open(RESULTS_FILE, 'w') as f: json.dump(results_data, f, indent=2)
    print("🎉 Datos generados (Unificación Liga/Champions completa).")
