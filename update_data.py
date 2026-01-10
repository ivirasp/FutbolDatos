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

def scrape_standings():
    print("📊 Extrayendo Clasificaciones Completas...")
    data_map = {}
    headers = {'User-Agent': 'Mozilla/5.0'}
    for name, url in URLS_STANDINGS.items():
        try:
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.content, 'html.parser')
            table = max(soup.find_all('table'), key=lambda t: len(t.find_all('tr')))
            rows = table.find_all('tr')
            
            league_data = []
            rank_counter = 0
            seen_teams = set()
            
            for row in rows:
                cells = row.find_all(['th', 'td'])
                texts = [c.get_text(strip=True) for c in cells if c.get_text(strip=True)]
                if len(texts) < 4: continue
                if any(t.upper() in ["EQUIPO", "PTS"] for t in texts): continue
                
                # Buscamos el nombre del equipo y su posición
                team = ""; team_idx = -1
                for i, t in enumerate(texts):
                    if len(t) > 2 and not t.isdigit(): 
                        team = t; team_idx = i; break
                
                if not team: continue
                team = re.sub(r'^\d+\.?\s*', '', team)
                if team in seen_teams: continue
                seen_teams.add(team)
                
                # Extraemos todas las estadísticas numéricas tras el nombre del equipo
                stats = texts[team_idx+1:]
                nums = [s for s in stats if s.replace('-','').isdigit()]
                
                if len(nums) >= 5: # PJ, G, E, P, Puntos...
                    rank_counter += 1
                    # Diferencia de goles manual por si no viene
                    dg = "0"
                    if len(nums) >= 7:
                        dg_val = int(nums[5]) - int(nums[6])
                        dg = f"+{dg_val}" if dg_val > 0 else str(dg_val)

                    league_data.append({
                        "rank": str(rank_counter),
                        "team": team,
                        "points": nums[0],
                        "played": nums[1],
                        "won": nums[2],
                        "drawn": nums[3],
                        "lost": nums[4],
                        "gf": nums[5] if len(nums)>5 else "0",
                        "ga": nums[6] if len(nums)>6 else "0",
                        "dg": dg
                    })
            if league_data: data_map[name] = league_data
        except: continue
    return data_map

# ... (Mantén aquí tus funciones scrape_agenda y scrape_results de la versión anterior) ...

if __name__ == "__main__":
    # Ejecuta las tres funciones y guarda los archivos
    with open(CALENDAR_FILE, 'w') as f: json.dump(scrape_agenda(), f, indent=2)
    with open(STANDINGS_FILE, 'w') as f: json.dump(scrape_standings(), f, indent=2)
    with open(RESULTS_FILE, 'w') as f: json.dump(scrape_results(), f, indent=2)
    print("✅ Actualización completa.")
