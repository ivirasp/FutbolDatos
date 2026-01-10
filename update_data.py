# -*- coding: utf-8 -*-
import requests
from bs4 import BeautifulSoup
import json
import os
import re
import time
from datetime import datetime, date
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

MONTH_MAP = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

# --- 2. FUNCIONES AUXILIARES ---

def calculate_season_year(target_month, today_date):
    """
    Calcula el año correcto basándose en la temporada de fútbol (Agosto-Mayo).
    Si estamos en 2026 (Ene-Jul) y leemos 'Noviembre', debe ser 2025.
    """
    current_year = today_date.year
    current_month = today_date.month
    
    # Si estamos en la segunda mitad de la temporada (Ene-Jul)
    if current_month <= 7:
        # Y la fecha leída es de la primera mitad (Ago-Dic) -> Es del año pasado
        if target_month >= 8:
            return current_year - 1
        # Si la fecha leída es Ene-Jul -> Es de este año
        return current_year
    
    # Si estamos en la primera mitad de la temporada (Ago-Dic)
    else:
        # Y la fecha leída es Ene-Jul -> Es del año que viene
        if target_month <= 7:
            return current_year + 1
        # Si la fecha leída es Ago-Dic -> Es de este año
        return current_year

def parse_header_date_obj(text, today_date):
    """
    Parsea 'Miércoles, 16 de Septiembre' devolviendo un objeto DATE con el año corregido.
    """
    try:
        text = text.lower()
        match = re.search(r"(\d+)\s+de\s+(\w+)", text)
        if match:
            day = int(match.group(1))
            month_txt = match.group(2)
            month = MONTH_MAP.get(month_txt, 0)
            
            if month > 0:
                year = calculate_season_year(month, today_date)
                return date(year, month, day)
    except: pass
    return None

# --- 3. SCRAPERS ---

def scrape_agenda():
    print("🌍 Extrayendo Agenda...")
    agenda = []
    seen = set()
    headers = {'User-Agent': 'Mozilla/5.0'}
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
                    agenda.append({"title": title, "start_ts": ts, "channel": channel, "competition": comp_label})
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
    print("⚽ Extrayendo Resultados (Lógica de Temporada)...")
    results_map = {}
    today = datetime.now(TZ_MADRID).date()
    
    for name, url in URLS_RESULTS:
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            temp_rounds = []
            current_round_key = ""
            current_found = False
            
            # Recorremos cada tabla (Jornada)
            for table in soup.find_all('table'):
                current_header_date_obj = None
                round_dates_objs = [] # Fechas reales de los partidos de ESTA jornada
                
                # 1. Nombre Jornada
                cap = table.find("caption")
                orig_title = "Jornada"
                if cap and cap.find("h2"):
                    orig_title = cap.find("h2").get_text(strip=True).replace("ª", "")
                else:
                    prev_h2 = table.find_previous("h2", class_="table-caption")
                    if prev_h2: orig_title = prev_h2.get_text(strip=True).replace("ª", "")

                if any(kw in orig_title.upper() for kw in ["FIFA", "WOMEN"]): continue
                final_title = orig_title
                
                # 2. Detección Fecha en Cabecera (THEAD)
                thead = table.find("thead")
                if thead:
                    th_date = thead.find("th", class_="textoizda")
                    if th_date:
                        raw_txt = th_date.get_text(strip=True)
                        # Intento Rango (Liga: "2025-08-15 - 2025-08-19")
                        dates_range = re.findall(r'(\d{4}-\d{2}-\d{2})', raw_txt)
                        if len(dates_range) == 2:
                            # En Liga la fecha ya viene con año, es fácil
                            end_date = datetime.strptime(dates_range[1], "%Y-%m-%d").date()
                            round_dates_objs.append(end_date)
                        else:
                            # Intento Texto (Champions: "Miércoles, 16 de Septiembre")
                            # Aquí aplicamos la lógica del AÑO
                            dt_obj = parse_header_date_obj(raw_txt, today)
                            if dt_obj: current_header_date_obj = dt_obj

                matches = []
                for row in table.find_all('tr'):
                    # Cabeceras intermedias (Múltiples días en una jornada Champions)
                    th_sub = row.find("th", class_="textoizda")
                    if th_sub:
                        dt_obj = parse_header_date_obj(th_sub.get_text(strip=True), today)
                        if dt_obj: current_header_date_obj = dt_obj
                        continue

                    tds = row.find_all('td')
                    if len(tds) < 3: continue

                    # A. FECHA & STATUS
                    match_date_obj = None
                    date_display = ""
                    status_val = ""
                    
                    time_tag = row.find('time')
                    if time_tag:
                        status_text = time_tag.get_text(strip=True)
                        if ":" not in status_text and status_text: status_val = status_text
                        if time_tag.has_attr('datetime'):
                            dt_s = time_tag['datetime'].split('T')[0]
                            try:
                                match_date_obj = datetime.strptime(dt_s, "%Y-%m-%d").date()
                            except: pass
                    
                    # Fallback status en última columna
                    if not status_val and len(tds) >= 4:
                        last = tds[-1].get_text(strip=True)
                        if "Fin" in last or "Desc" in last: status_val = last

                    # Si no tenemos fecha por <time>, buscamos en celdas o cabecera
                    if not match_date_obj:
                        txt_c0 = tds[0].get_text(strip=True)
                        match_d = re.search(r'(\d{2})/(\d{2})', txt_c0)
                        if match_d:
                            d, m = int(match_d.group(1)), int(match_d.group(2))
                            # Calcular año según mes vs hoy
                            y = calculate_season_year(m, today)
                            match_date_obj = date(y, m, d)
                        elif current_header_date_obj:
                            match_date_obj = current_header_date_obj

                    # Si logramos calcular fecha real, la guardamos para la lógica de "Actual"
                    if match_date_obj:
                        round_dates_objs.append(match_date_obj)
                        date_display = match_date_obj.strftime("%d-%m-%Y")

                    # B. EQUIPOS
                    home, away = "", ""
                    home_td = row.find("td", class_="textodcha")
                    if home_td:
                        a = home_td.find("a", class_="geca_enlace_equipo")
                        home = a["title"] if a and a.has_attr("title") else home_td.get_text(strip=True)
                    elif len(tds) > 1: home = tds[1].get_text(strip=True)

                    away_td = row.find("td", class_="textoizda")
                    if away_td:
                        a = away_td.find("a", class_="geca_enlace_equipo")
                        away = a["title"] if a and a.has_attr("title") else away_td.get_text(strip=True)
                    elif len(tds) > 3: away = tds[3].get_text(strip=True)

                    # C. RESULTADO
                    final_score = "vs"
                    candidates = []
                    score_a = row.find('a', class_='geca_enlace_partido')
                    if score_a: candidates.append(score_a.get_text(strip=True))
                    score_span = row.find('span', class_='celdagoles')
                    if score_span: candidates.append(score_span.get_text(strip=True))
                    
                    found_score = False
                    for txt in candidates:
                        if re.search(r'\d+\s*-\s*\d+', txt):
                            final_score = txt; found_score = True; break
                    
                    if not found_score and len(tds) >= 3:
                        center = tds[2].get_text(strip=True)
                        if re.search(r'\d+\s*-\s*\d+', center): final_score = center

                    if home and away:
                        matches.append({
                            "date": date_display,
                            "home": home.strip(),
                            "away": away.strip(),
                            "score": final_score,
                            "status": status_val
                        })
                
                # --- CÁLCULO DE JORNADA ACTUAL ---
                # Si la fecha MÁS TARDÍA de esta jornada es HOY o FUTURA -> Esta es la Actual
                if not current_found and round_dates_objs:
                    max_date_in_round = max(round_dates_objs)
                    if max_date_in_round >= today:
                        final_title = f"{orig_title} (Actual)"
                        current_round_key = final_title
                        current_found = True

                if matches:
                    temp_rounds.append({"key": final_title, "matches": matches})
            
            if temp_rounds:
                def_current = current_round_key if current_round_key else temp_rounds[-1]["key"]
                results_map[name] = {
                    "rounds": {r["key"]: r["matches"] for r in temp_rounds},
                    "current": def_current
                }
        except: continue
    return results_map

if __name__ == "__main__":
    with open(CALENDAR_FILE, 'w') as f: json.dump(scrape_agenda(), f, indent=2)
    with open(STANDINGS_FILE, 'w') as f: json.dump(scrape_standings(), f, indent=2)
    with open(RESULTS_FILE, 'w') as f: json.dump(scrape_results(), f, indent=2)
    print("🎉 Datos generados.")
