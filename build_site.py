"""Arma docs/data/site.json (liviano) para la pagina. Lee shn/, ina/, smn/ (BASE). Horas ART naive salvo 'viento' (UTC con Z)."""
import csv, glob, json, os, shutil
from datetime import datetime, timedelta
BASE = os.environ.get('BASE', '.')
SHN, INA, SMN = [os.path.join(BASE, d) for d in ('shn', 'ina', 'smn')]
OUT = 'docs/data'; os.makedirs(OUT, exist_ok=True)
now = datetime.utcnow(); now_art = now - timedelta(hours=3)
OBS_HORAS = 96

site = {'generado_utc': now.isoformat() + 'Z'}

# --- SHN alturas observadas (ultimas 96 h) ---
obs = {}
cut = now_art - timedelta(hours=OBS_HORAS)
last_cap = None
for l in open(os.path.join(SHN, 'data/historico_alturas.jsonl')):
    try: r = json.loads(l)
    except: continue
    last_cap = r.get('capturado_en', last_cap)
    for m in r.get('mediciones', []):
        try: t = datetime.strptime(m['fecha_hora'], '%d/%m/%Y %H:%M'); h = float(m['altura_m'])
        except: continue
        if t >= cut: obs.setdefault(m['estacion'], {})[t.strftime('%Y-%m-%dT%H:%M')] = h
site['shn_obs'] = {k: sorted(v.items()) for k, v in obs.items() if k not in ('Ushuaia', 'Puerto Belgrano')}
site['shn_obs_capturado'] = last_cap

# --- SHN pronostico: ultimo boletin ---
last = None
for l in open(os.path.join(SHN, 'data/historico.jsonl')):
    try: last = json.loads(l)
    except: pass
if last:
    ev = []
    for p in last['puertos']:
        if '---' in p['hora'] + p['fecha'] + str(p['altura_m']): continue
        ev.append({'lugar': p['lugar'], 'estado': p['estado'], 't': datetime.strptime(p['fecha'] + ' ' + p['hora'], '%d/%m/%Y %H:%M').strftime('%Y-%m-%dT%H:%M'), 'h': float(p['altura_m'])})
    site['shn_pron'] = {'capturado_utc': last['capturado_en'], 'valido_desde': last['valido_desde'], 'valido_hasta': last['valido_hasta'], 'eventos': ev}

# --- INA: ultimo snapshot de pronostico + observado reciente ---
snaps = sorted(glob.glob(os.path.join(INA, 'data/historico_prono/*.json')))
ina = {}
if snaps:
    d = json.load(open(snaps[-1])); site['ina_capturado_utc'] = d['capturado_en']
    for slug, e in d['estaciones'].items():
        ser = [[p['timestart'][:16], p['central'], p.get('min'), p.get('max')] for p in e['serie']]
        o = []
        f = os.path.join(INA, 'data/series/%s.csv' % slug)
        if os.path.exists(f):
            c2 = (now_art - timedelta(days=10)).strftime('%Y-%m-%dT%H:%M')
            for row in csv.DictReader(open(f)):
                if row['timestart'] >= c2: o.append([row['timestart'][:16], float(row['valor'])])
            o = sorted({x[0]: x for x in o}.values())
        ina[slug] = {'corrida': e.get('corrida_forecastdate'), 'pron': ser, 'obs': o}
site['ina'] = ina

# --- SMN viento: ultimo ciclo (UTC) ---
lw = None
for l in open(os.path.join(SMN, 'data/historico_viento.jsonl')):
    try: lw = json.loads(l)
    except: pass
if lw:
    site['viento'] = {'ciclo_init': lw['ciclo_init'], 'capturado_utc': lw['capturado_en'],
                      'estaciones': {k: [[p['valido_para'], round(p['viento_10m_ms'], 2), round(p['direccion_10m_deg'])] for p in v[:73]] for k, v in lw['estaciones'].items()}}

json.dump(site, open(os.path.join(OUT, 'site.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
for f in ('comparativo_mareas.csv', 'comparativo_parana.csv', 'resumen.json'):
    if os.path.exists(os.path.join('data', f)): shutil.copy(os.path.join('data', f), os.path.join(OUT, f))
print('site.json', os.path.getsize(os.path.join(OUT, 'site.json')) // 1024, 'KB')
