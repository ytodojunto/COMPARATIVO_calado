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
obs = {}; ALL_OBS = {}
cut = now_art - timedelta(hours=OBS_HORAS)
last_cap = None
for l in open(os.path.join(SHN, 'data/historico_alturas.jsonl')):
    try: r = json.loads(l)
    except: continue
    last_cap = r.get('capturado_en', last_cap)
    for m in r.get('mediciones', []):
        try: t = datetime.strptime(m['fecha_hora'], '%d/%m/%Y %H:%M'); h = float(m['altura_m'])
        except: continue
        ALL_OBS.setdefault(m['estacion'], {})[t] = h
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

# ================= HISTORIAL: un json por dia (docs/data/hist/AAAA-MM-DD.json) =================
HIST = os.path.join(OUT, 'hist'); os.makedirs(HIST, exist_ok=True)
dias_all = sorted({t.date() for v in ALL_OBS.values() for t in v})
# pronosticos SHN (todos los boletines)
fc = []
for l in open(os.path.join(SHN, 'data/historico.jsonl')):
    try: r = json.loads(l)
    except: continue
    try: iss = datetime.strptime(r['valido_desde'], '%d/%m/%Y %H:%M')
    except: continue
    for p in r['puertos']:
        if '---' in p['hora'] + p['fecha'] + str(p['altura_m']): continue
        try: t = datetime.strptime(p['fecha'] + ' ' + p['hora'], '%d/%m/%Y %H:%M'); h = float(p['altura_m'])
        except: continue
        fc.append((p['lugar'], p['estado'], t, h, iss))
shn_key = {'CANAL PUNTA INDIO': 'Oyarvide', 'PUERTO LA PLATA': 'La Plata', 'PUERTO DE BUENOS AIRES': 'Buenos Aires', 'SAN FERNANDO': 'San Fernando'}
def shn_estacion(lugar):
    for k, v in shn_key.items():
        if k in lugar: return v
# observado INA (todos los slugs, desde el primer dia con datos SHN)
ina_obs_all = {}
if dias_all:
    d0 = dias_all[0].strftime('%Y-%m-%d')
    for f in glob.glob(os.path.join(INA, 'data/series/*.csv')):
        slug = os.path.basename(f)[:-4]; m = {}
        for row in csv.DictReader(open(f)):
            if row['timestart'][:10] >= d0:
                try: m[row['timestart'][:16]] = float(row['valor'])
                except ValueError: pass
        ina_obs_all[slug] = m
# snapshots INA y ciclos de viento
from datetime import timezone
def to_naive_utc(s):
    c = datetime.fromisoformat(s.replace('Z', '+00:00'))
    return c.astimezone(timezone.utc).replace(tzinfo=None) if c.tzinfo else c
snap_list = []
for f in snaps:
    try: dd = json.load(open(f)); snap_list.append((to_naive_utc(dd['capturado_en']), dd))
    except Exception: pass
wind_list = []
for l in open(os.path.join(SMN, 'data/historico_viento.jsonl')):
    try: r = json.loads(l); wind_list.append((to_naive_utc(r['capturado_en']), r))
    except Exception: pass
hoy = now_art.date(); existentes = {os.path.basename(p)[:-5] for p in glob.glob(os.path.join(HIST, '*.json'))}
hechos = []
for D in dias_all:
    ds = D.isoformat(); hechos.append(ds)
    if ds in existentes and (hoy - D).days > 2: continue
    ini = datetime(D.year, D.month, D.day); fin = ini + timedelta(days=1); ini_utc = ini + timedelta(hours=3)
    day = {'fecha': ds}
    day['shn_obs'] = {k: [[t.strftime('%H:%M'), h] for t, h in sorted(v.items()) if ini <= t < fin] for k, v in ALL_OBS.items() if k not in ('Ushuaia', 'Puerto Belgrano')}
    day['shn_obs'] = {k: v for k, v in day['shn_obs'].items() if v}
    ev = {}
    for lugar, est, t, h, iss in fc:
        if ini <= t < fin and iss <= t:
            k = (lugar, est, t)
            if k not in ev or iss > ev[k][1]: ev[k] = (h, iss)
    day['shn_pron'] = [{'est': shn_estacion(l), 'estado': e, 't': t.strftime('%H:%M'), 'h': h} for (l, e, t), (h, iss) in sorted(ev.items(), key=lambda x: x[0][2])]
    day['ina_obs'] = {}
    for slug, m in ina_obs_all.items():
        pts = [[k[11:16], v] for k, v in sorted(m.items()) if ini.strftime('%Y-%m-%dT%H:%M') <= k < fin.strftime('%Y-%m-%dT%H:%M')]
        if pts: day['ina_obs'][slug] = pts
    prev = [x for x in snap_list if x[0] <= ini_utc]
    day['ina_pron'] = {}
    if prev:
        for slug, e in prev[-1][1]['estaciones'].items():
            pts = [[p['timestart'][11:16], p['central']] for p in e['serie'] if ini.strftime('%Y-%m-%dT%H:%M') <= p['timestart'][:16] < fin.strftime('%Y-%m-%dT%H:%M')]
            if pts: day['ina_pron'][slug] = {'corrida': e.get('corrida_forecastdate'), 'pts': pts}
    pw = [x for x in wind_list if x[0] <= ini_utc]
    day['viento'] = {}
    if pw:
        r = pw[-1][1]; day['viento_ciclo'] = r['ciclo_init']
        for k, v in r['estaciones'].items():
            pts = [[p['valido_para'], round(p['viento_10m_ms'], 2), round(p['direccion_10m_deg'])] for p in v]
            pts = [p for p in pts if ini_utc <= to_naive_utc(p[0]) < ini_utc + timedelta(days=1)]
            if pts: day['viento'][k] = pts
    json.dump(day, open(os.path.join(HIST, ds + '.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
json.dump({'dias': hechos}, open(os.path.join(HIST, 'index.json'), 'w'))
print('historial:', len(hechos), 'dias')
print('site.json', os.path.getsize(os.path.join(OUT, 'site.json')) // 1024, 'KB')
