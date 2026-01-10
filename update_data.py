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
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12"
}

# --- FUNCIONES ---

def parse_header_date(text):
    """Convierte 'Miércoles, 16 de Septiembre' a '16/09'"""
    try:
        text = text.lower()
        match = re.search(r"(\d+)\s+de\s+(\w+)", text)
        if match:
            day, month_txt = match.groups()
            month_num = MONTH_MAP.get(month_txt, "01")
            return f"{day.zfill(2)}/{month_num}"
    except: pass
    return ""

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
    print("⚽ Extrayendo Resultados (Status separado + Actual)...")
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
                # 1. NOMBRE DE JORNADA
                cap = table.find("caption")
                orig_title = "Jornada"
                if cap and cap.find("h2"):
                    orig_title = cap.find("h2").get_text(strip=True).replace("ª", "")
                else:
                    prev_h2 = table.find_previous("h2", class_="table-caption")
                    if prev_h2: orig_title = prev_h2.get_text(strip=True).replace("ª", "")

                if any(kw in orig_title.upper() for kw in ["FIFA", "WOMEN"]): continue
                
                final_title = orig_title
                
                # --- DETECCIÓN "ACTUAL" (Lógica Híbrida) ---
                is_actual = False
                current_header_date = ""
                thead = table.find("thead")
                
                if thead:
                    th_date = thead.find("th", class_="textoizda")
                    if th_date:
                        raw_txt = th_date.get_text(strip=True)
                        dates_range = re.findall(r'(\d{4}-\d{2}-\d{2})', raw_txt)
                        if len(dates_range) == 2:
                            # TIPO LIGA (Rango)
                            end_date = datetime.strptime(dates_range[1], "%Y-%m-%d").date()
                            if today <= end_date and not current_found:
                                is_actual = True
                        else:
                            # TIPO CHAMPIONS (Texto fecha) - Guardamos contexto
                            parsed = parse_header_date(raw_txt)
                            if parsed: current_header_date = parsed

                # Array para recolectar fechas reales de los partidos de esta tabla
                # para calcular si es la "Actual" en torneos tipo Copa/Champions
                round_dates_objs = [] 

                matches = []
                for row in table.find_all('tr'):
                    # Cabecera intermedia (Champions)
                    th_sub = row.find("th", class_="textoizda")
                    if th_sub:
                        parsed = parse_header_date(th_sub.get_text(strip=True))
                        if parsed: current_header_date = parsed
                        continue

                    tds = row.find_all('td')
                    if len(tds) < 3: continue

                    # A. FECHA & STATUS
                    date_val = ""
                    status_val = ""
                    
                    time_tag = row.find('time')
                    if time_tag:
                        # Extraer estado (Fin, Descanso, Prórroga, Hora)
                        status_text = time_tag.get_text(strip=True)
                        # Si es hora (XX:XX) no es un estado relevante para mostrar abajo, excepto si no hay resultado
                        if ":" not in status_text and status_text:
                            status_val = status_text
                        
                        if time_tag.has_attr('datetime'):
                            dt_s = time_tag['datetime'].split('T')[0]
                            try:
                                do = datetime.strptime(dt_s, "%Y-%m-%d")
                                round_dates_objs.append(do.date())
                                date_val = do.strftime("%d-%m-%Y")
                            except: pass
                    
                    if not date_val:
                        txt_c0 = tds[0].get_text(strip=True)
                        # Intentar formato DD/MM
                        match_d = re.search(r'(\d{2})/(\d{2})', txt_c0)
                        if match_d:
                            date_val = txt_c0
                            try:
                                d, m = int(match_d.group(1)), int(match_d.group(2))
                                y = today.year
                                # Ajuste de año para meses
                                if m < 7 and today.month > 7: y += 1
                                elif m > 7 and today.month < 7: y -= 1
                                round_dates_objs.append(datetime(y, m, d).date())
                            except: pass
                        elif current_header_date:
                            date_val = current_header_date
                            try:
                                d, m = map(int, current_header_date.split('/'))
                                y = today.year
                                round_dates_objs.append(datetime(y, m, d).date())
                            except: pass

                    # B. EQUIPOS
                    home, away = "", ""
                    
                    home_td = row.find("td", class_="textodcha")
                    if home_td:
                        a_tag = home_td.find("a", class_="geca_enlace_equipo")
                        if a_tag and a_tag.has_attr("title"): home = a_tag["title"]
                        else: home = home_td.get_text(strip=True)
                    elif len(tds) > 1: home = tds[1].get_text(strip=True)

                    away_td = row.find("td", class_="textoizda")
                    if away_td:
                        a_tag = away_td.find("a", class_="geca_enlace_equipo")
                        if a_tag and a_tag.has_attr("title"): away = a_tag["title"]
                        else: away = away_td.get_text(strip=True)
                    elif len(tds) > 3: away = tds[3].get_text(strip=True)

                    # C. RESULTADO
                    final_score = "vs"
                    candidates = []
                    
                    score_a = row.find('a', class_='geca_enlace_partido')
                    if score_a: candidates.append(score_a.get_text(strip=True))
                    score_span = row.find('span', class_='celdagoles')
                    if score_span: candidates.append(score_span.get_text(strip=True))
                    for td in tds: candidates.append(td.get_text(strip=True))

                    for txt in candidates:
                        if re.search(r'^\d+\s*-\s*\d+$', txt):
                            final_score = txt
                            break
                    
                    # Limpieza
                    home = home.strip()
                    away = away.strip()

                    if home and away:
                        matches.append({
                            "date": date_val,
                            "home": home,
                            "away": away,
                            "score": final_score,
                            "status": status_val # Campo nuevo
                        })
                
                # CALCULO ACTUAL (Si no fue por rango)
                if not is_actual and not current_found and round_dates_objs:
                    # Si la última fecha de la ronda es hoy o futura -> Actual
                    if max(round_dates_objs) >= today:
                        is_actual = True

                if is_actual:
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

# --- MAIN ---
if __name__ == "__main__":
    with open(CALENDAR_FILE, 'w') as f: json.dump(scrape_agenda(), f, indent=2)
    with open(STANDINGS_FILE, 'w') as f: json.dump(scrape_standings(), f, indent=2)
    with open(RESULTS_FILE, 'w') as f: json.dump(scrape_results(), f, indent=2)
    print("🎉 Datos generados (Status separado).")
