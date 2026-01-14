import requests
import xml.etree.ElementTree as ET
import re
import os
import logging
import sys
import json
import time

# --- 1. CONFIGURACIÓN ---
URL_XMLTV = "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/master/guiatv.xml"
URL_M3U_PRIVADA = "http://vd5yk8ep.k3ane.xyz:80/get.php?username=Ivan1129X&password=Awypyfedm121&type=m3u_plus&output=mpegts"
THREADFIN_URL = "http://10.0.0.51:34400"

# Directorio base dentro del Docker
DIR_BASE = "/opt/threadfin/conf/scripts/"
RUTA_SALIDA = os.path.join(DIR_BASE, "lista_filtrada.m3u")
RUTA_LOG = os.path.join(DIR_BASE, "historial_actualizaciones.log")

# --- 2. CONFIGURACIÓN DE LOGGING ---
logging.basicConfig(
    filename=RUTA_LOG,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

console = logging.StreamHandler(sys.stdout)
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(levelname)s - %(message)s')
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)

# --- 3. FUNCIONES DE LÓGICA ---

def obtener_calidad(nombre_canal):
    nombre = nombre_canal.upper()
    if 'FHD HEVC' in nombre: return 5
    if 'FHD' in nombre: return 4
    if 'HD' in nombre: return 3
    if 'SD' in nombre: return 2
    return 1

def descargar_y_parsear_xml(url):
    logging.info("1. Descargando guía XMLTV...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        response.raw.decode_content = True
        
        mapa_canales = {}
        orden_contador = 0 
        
        context = ET.iterparse(response.raw, events=("start", "end"))
        
        for event, elem in context:
            if event == "start" and elem.tag == "programme":
                break
                
            if event == "end" and elem.tag == "channel":
                orden_contador += 1
                channel_id = elem.get("id")
                
                icon_elem = elem.find("icon")
                logo_src = icon_elem.get("src") if icon_elem is not None else ""
                
                nombres = [dn.text for dn in elem.findall("display-name")]
                
                if nombres:
                    nombre_oficial = nombres[0]
                    datos_canal = {
                        "id": channel_id,
                        "logo": logo_src,
                        "nombre_oficial": nombre_oficial,
                        "orden_xml": orden_contador
                    }
                    for nombre in nombres:
                        if nombre:
                            mapa_canales[nombre.strip().upper()] = datos_canal
                elem.clear()
        
        logging.info("    XML procesado correctamente.")
        return mapa_canales

    except Exception as e:
        logging.error(f"    ERROR descargando XML: {e}")
        return None

def descargar_lista_m3u(url):
    logging.info("2. Descargando lista M3U personal...")
    try:
        response = requests.get(url)
        response.raise_for_status()
        response.encoding = 'utf-8'
        
        contenido = response.text
        lineas = contenido.splitlines()
        
        logging.info(f"    Lista descargada. Total líneas: {len(lineas)}")
        return lineas
    except Exception as e:
        logging.error(f"    ERROR descargando M3U: {e}")
        return None

def procesar_datos(lineas, mapa_xml):
    logging.info("3. Analizando y filtrando canales...")
    canales_seleccionados = {} 
    fallos = []
    
    total_ignorados_no_es = 0
    total_procesados = 0
    last_processed_id = None
    
    for linea in lineas:
        linea = linea.strip()
        
        if linea.startswith("#EXTINF:"):
            total_procesados += 1
            match_name = re.search(r'tvg-name="([^"]+)"', linea)
            if match_name:
                raw_name = match_name.group(1) 
                
                if not raw_name.startswith("ES: "):
                    total_ignorados_no_es += 1
                    last_processed_id = None
                    continue 
                
                clean_m3u_name = raw_name[4:].strip() 
                if "VAMOS" in clean_m3u_name.upper():
                    clean_m3u_name = clean_m3u_name.replace("#", "").strip()
                
                key_busqueda = clean_m3u_name.upper()
                
                if key_busqueda in mapa_xml:
                    datos_xml = mapa_xml[key_busqueda]
                    xml_id = datos_xml['id']
                    calidad_nueva = obtener_calidad(clean_m3u_name)
                    
                    if xml_id not in canales_seleccionados or \
                       calidad_nueva >= canales_seleccionados[xml_id]['calidad']:
                        
                        canales_seleccionados[xml_id] = {
                            "id": xml_id,
                            "nombre_mostrar": datos_xml['nombre_oficial'],
                            "logo": datos_xml['logo'],
                            "orden": datos_xml['orden_xml'],
                            "calidad": calidad_nueva,
                            "url": "" 
                        }
                        last_processed_id = xml_id
                    else:
                        last_processed_id = None
                else:
                    fallos.append(clean_m3u_name)
                    last_processed_id = None
            else:
                total_ignorados_no_es += 1
                last_processed_id = None

        elif linea and not linea.startswith("#"):
            if last_processed_id:
                canales_seleccionados[last_processed_id]['url'] = linea

    logging.info(f"    Ignorados (No ES:): {total_ignorados_no_es}")
    logging.info(f"    Encontrados y Guardados: {len(canales_seleccionados)}")
    logging.info(f"    NO ENCONTRADOS en XML: {len(fallos)}")
    
    return list(canales_seleccionados.values())

def generar_m3u_final(canales, archivo_salida):
    logging.info(f"4. Guardando en {archivo_salida}...")
    canales_ordenados = sorted(canales, key=lambda x: x['orden'])
    
    try:
        with open(archivo_salida, 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n')
            for c in canales_ordenados:
                linea = f'#EXTINF:-1 tvg-id="{c["id"]}" tvg-name="{c["nombre_mostrar"]}" tvg-logo="{c["logo"]}" group-title="TV", {c["nombre_mostrar"]}\n'
                f.write(linea)
                f.write(f'{c["url"]}\n')
        return True
    except Exception as e:
        logging.error(f"Error guardando archivo: {e}")
        return False

def enviar_comando_api(cmd_name):
    """Función auxiliar para enviar comandos a la API"""
    api_endpoint = f"{THREADFIN_URL}/api/"
    payload = {'cmd': cmd_name}
    
    try:
        logging.info(f"    -> Enviando comando: {cmd_name}...")
        response = requests.post(api_endpoint, json=payload, timeout=15)
        
        if response.status_code == 200:
            # Parseamos la respuesta para ver si status es true
            try:
                resp_json = response.json()
                if resp_json.get('status') is True:
                    logging.info(f"       OK: Comando {cmd_name} ejecutado correctamente.")
                    return True
                else:
                    logging.warning(f"       ADVERTENCIA: API devolvió status false: {resp_json}")
            except:
                logging.info(f"       OK: (Respuesta 200 recibida).")
                return True
        else:
            logging.warning(f"       FALLO: Código HTTP {response.status_code}. Respuesta: {response.text}")
            return False
            
    except Exception as e:
        logging.error(f"       ERROR de conexión: {e}")
        return False

def actualizar_threadfin():
    logging.info("5. Contactando con Threadfin para recargar...")
    
    # 1. Actualizar Playlist M3U (Lee el archivo nuevo)
    if enviar_comando_api('update.m3u'):
        # Esperamos 2 segundos para dar tiempo a procesar
        time.sleep(2)
        
        # 2. Actualizar XMLTV (Opcional, pero bueno para asegurar sincronía)
        enviar_comando_api('update.xmltv')
        time.sleep(1)
        
        # 3. Actualizar XEPG (Mapeo de canales y generación final)
        enviar_comando_api('update.xepg')
        
        logging.info("    --- Secuencia de actualización completada ---")
    else:
        logging.error("    No se pudo actualizar la lista M3U, abortando siguientes pasos.")

# --- 4. EJECUCIÓN PRINCIPAL ---

def main():
    logging.info("--- INICIO DEL PROCESO AUTOMÁTICO ---")
    
    if not os.path.exists(DIR_BASE):
        try:
            os.makedirs(DIR_BASE)
        except OSError as e:
            logging.error(f"No se pudo crear el directorio {DIR_BASE}: {e}")
            return

    # Paso 1: XML
    mapa_xml = descargar_y_parsear_xml(URL_XMLTV)
    if not mapa_xml:
        logging.error("Abortando por fallo en XML.")
        return

    # Paso 2: M3U
    lineas_m3u = descargar_lista_m3u(URL_M3U_PRIVADA)
    if not lineas_m3u:
        logging.error("Abortando por fallo en M3U.")
        return

    # Paso 3: Procesar
    canales_finales = procesar_datos(lineas_m3u, mapa_xml)

    # Paso 4: Guardar
    if canales_finales:
        guardado = generar_m3u_final(canales_finales, RUTA_SALIDA)
        # Paso 5: Actualizar Threadfin
        if guardado:
            actualizar_threadfin()
    else:
        logging.error("No se generaron canales finales. Revisa los filtros.")

    logging.info("--- FIN DEL PROCESO ---")

if __name__ == "__main__":
    main()
