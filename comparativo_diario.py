"""
Comparativo diario: SHN pronostico vs INA pronostico vs modelo (Norden) vs real.
Corre sobre el dia anterior (ART) o el dia dado: python comparativo_diario.py [AAAA-MM-DD]
Lee los repos hermanos (checkout en shn/, ina/, smn/, carp/ o BASE=<dir>).
Escribe data/comparativo_mareas.csv, data/comparativo_parana.csv y data/resumen.json
Convenciones: horas ART naive. error = real - pronostico. Sin dato = vacio ('sin dato'), nunca se estima.
"""
import csv, glob, json, math, os, sys, collections
from datetime import datetime, timedelta
import numpy as np, pandas as pd

BASE = os.environ.get('BASE', '.')
SHN, INA, SMN, CARP = [os.path.join(BASE, d) for d in ('shn', 'ina', 'smn', 'carp')]
OUT = 'data'; os.makedirs(OUT, exist_ok=True)
MIN_AMPL = 0.20   # se descartan oscilaciones menores (m)
TOL_H = 3         # tolerancia para emparejar evento (h)

if len(sys.argv) > 1: DAY0 = pd.Timestamp(sys.argv[1])
else: DAY0 = pd.Timestamp((datetime.utcnow() - timedelta(hours=3)).date()) - pd.Timedelta(days=1)
DAY1 = DAY0 + pd.Timedelta(days=1)
PAD = pd.Timedelta(hours=8)

# ---------- extremos ----------
def extrema(s):
    s = s.sort_index(); t = s.index; v = s.values; ev = []
    for i in range(1, len(v) - 1):
        if (t[i]-t[i-1]) > pd.Timedelta(hours=1.6) or (t[i+1]-t[i]) > pd.Timedelta(hours=1.6): continue
        if (v[i] >= v[i-1] and v[i] > v[i+1]) or (v[i] > v[i-1] and v[i] >= v[i+1]): k = 'PLEAMAR'
        elif (v[i] <= v[i-1] and v[i] < v[i+1]) or (v[i] < v[i-1] and v[i] <= v[i+1]): k = 'BAJAMAR'
        else: continue
        a, b, c = v[i-1], v[i], v[i+1]; den = a - 2*b + c
        off = 0.5*(a-c)/den if abs(den) > 1e-9 else 0; off = max(-1, min(1, off))
        ev.append((t[i] + pd.Timedelta(hours=off*(t[i+1]-t[i]).total_seconds()/3600), b - 0.25*(a-c)*off, k))
    out = []
    for e in ev:
        if out and out[-1][2] == e[2]:
            if (e[2] == 'PLEAMAR' and e[1] > out[-1][1]) or (e[2] == 'BAJAMAR' and e[1] < out[-1][1]): out[-1] = e
        else: out.append(e)
    while len(out) >= 4:
        d = [abs(out[i][1]-out[i+1][1]) for i in range(len(out)-1)]; i = int(np.argmin(d))
        if d[i] >= MIN_AMPL: break
        if i == 0 or i == len(out)-2:
            if len(out) > 4: del out[i:i+2]; continue
            break
        del out[i:i+2]
    return out

def match(ev, ref):
    best = None
    for r in ref:
        if r[2] != ev[2]: continue
        dt = abs((r[0]-ev[0]).total_seconds())/3600
        if dt <= TOL_H and (best is None or dt < best[0]): best = (dt, r)
    return best[1] if best else None

# ---------- SHN ----------
obs = collections.defaultdict(dict)
for l in open(os.path.join(SHN, 'data/historico_alturas.jsonl')):
    try: r = json.loads(l)
    except: continue
    for m in r.get('mediciones', []):
        try: obs[m['estacion']][pd.Timestamp(datetime.strptime(m['fecha_hora'], '%d/%m/%Y %H:%M'))] = float(m['altura_m'])
        except: pass
fc = []
for l in open(os.path.join(SHN, 'data/historico.jsonl')):
    try: r = json.loads(l)
    except: continue
    try: fc.append((pd.Timestamp(datetime.strptime(r['valido_desde'], '%d/%m/%Y %H:%M')), r))
    except: pass

def shn_fc_events(key):
    d = collections.defaultdict(list)
    for iss, r in fc:
        for p in r['puertos']:
            if key in p['lugar']:
                if '---' in p['hora'] + p['fecha'] + str(p['altura_m']): continue
                try: t = pd.Timestamp(datetime.strptime(p['fecha']+' '+p['hora'], '%d/%m/%Y %H:%M')); h = float(p['altura_m'])
                except: continue
                d[(t, p['estado'])].append((iss, h))
    out = []
    for (t, k), lst in d.items():
        if DAY0-pd.Timedelta(hours=6) <= t < DAY1+pd.Timedelta(hours=6):
            l2 = [x for x in lst if x[0] <= t]     # ultimo boletin emitido antes del evento
            if l2: out.append((t, max(l2)[1], k))
    return out

# ---------- INA ----------
def ina_series(slug):
    f = os.path.join(INA, 'data/series/%s.csv' % slug); s = {}
    if not os.path.exists(f): return pd.Series(dtype=float)
    for row in csv.DictReader(open(f)): s[pd.Timestamp(row['timestart'])] = float(row['valor'])
    return pd.Series(s).sort_index()

def ina_fc(slug, before):
    best = None
    for f in sorted(glob.glob(os.path.join(INA, 'data/historico_prono/*.json'))):
        d = json.load(open(f)); c = pd.Timestamp(d['capturado_en'])
        cap = c.tz_convert(None) if c.tzinfo else c
        if cap <= before and slug in d['estaciones']: best = (cap, d['estaciones'][slug])
    if not best: return None
    e = best[1]
    return best[0], e.get('corrida_forecastdate'), pd.Series({pd.Timestamp(p['timestart']): p['central'] for p in e['serie']}).sort_index()

# ---------- Modelo Norden ----------
SPEEDS = {'M2':28.9841042,'S2':30.0,'N2':28.4397295,'K1':15.0410686,'O1':13.9430356,'P1':14.9589314,'K2':30.0821373}
def design(th):
    cols = [np.ones_like(th)]
    for v in SPEEDS.values():
        w = np.radians(v); cols += [np.cos(w*th), np.sin(w*th)]
    return np.column_stack(cols)
T0 = pd.Timestamp('2015-11-04')
def build_model():
    tide = pd.read_csv(os.path.join(CARP, 'data/norden_tide.csv'), parse_dates=['date_time']).dropna()
    th = (tide['date_time']-T0).dt.total_seconds().values/3600.0
    beta, *_ = np.linalg.lstsq(design(th), tide['tide_height'].values, rcond=None)
    astro = lambda ts: design((ts-T0).total_seconds().values/3600.0) @ beta
    snaps = []
    for l in open(os.path.join(SMN, 'data/historico_viento.jsonl')):
        try: r = json.loads(l)
        except: continue
        key = [k for k in r['estaciones'] if 'Norden' in k]
        if not key: continue
        init = pd.Timestamp(r['ciclo_init']).tz_convert('UTC').tz_localize(None)
        cap = pd.Timestamp(r['capturado_en']).tz_convert('UTC').tz_localize(None)
        w = {pd.Timestamp(p['valido_para']).tz_convert('UTC').tz_localize(None): (p['viento_10m_ms'], p['direccion_10m_deg']) for p in r['estaciones'][key[0]]}
        snaps.append((init, cap, w))
    snaps.sort(key=lambda x: x[0])
    use = lambda sp, dr: sp*math.cos(math.radians(dr-135))
    def wind(tutc, cap_limit=None):
        t0 = tutc.floor('h'); t1 = t0 + pd.Timedelta(hours=1); f = (tutc-t0).total_seconds()/3600; best = None
        for init, cap, w in snaps:
            if cap_limit is not None and cap > cap_limit: continue
            if init <= t0 and t0 in w and t1 in w: best = (w[t0], w[t1])
        if not best: return None
        a, b = use(*best[0]), use(*best[1]); return a + (b-a)*f
    s = pd.Series(obs['Pilote Norden']).sort_index()
    tr = s[s.index < DAY0].to_frame('obs'); tr['res'] = tr['obs'] - astro(tr.index)
    tr['u'] = [wind(t + pd.Timedelta(hours=3)) for t in tr.index]; tr = tr.dropna()
    if len(tr) < 50: return None
    A = np.column_stack([np.ones(len(tr)), tr['u'].values]); c, *_ = np.linalg.lstsq(A, tr['res'].values, rcond=None)
    idx = pd.date_range(DAY0 - pd.Timedelta(hours=6), DAY1 + pd.Timedelta(hours=6), freq='10min')
    cap_limit = DAY0 + pd.Timedelta(hours=3)
    hrs = pd.date_range(idx[0].floor('h'), idx[-1].ceil('h'), freq='1h')
    uh = pd.Series([wind(t + pd.Timedelta(hours=3), cap_limit) for t in hrs], index=hrs, dtype=float)
    if uh.isna().all(): return None
    uh = uh.interpolate(limit_direction='both'); u10 = uh.reindex(uh.index.union(idx)).interpolate('time').reindex(idx)
    m = pd.Series(astro(idx) + c[0] + c[1]*u10.values, index=idx)
    ev = []
    for i in range(1, len(m)-1):
        a, b, cc = m.iloc[i-1], m.iloc[i], m.iloc[i+1]
        if b > a and b >= cc: ev.append((m.index[i], b, 'PLEAMAR'))
        elif b < a and b <= cc: ev.append((m.index[i], b, 'BAJAMAR'))
    return ev, dict(n_calibracion=len(tr), c0=round(c[0], 3), c1=round(c[1], 3))

STN = [('Mar del Plata','Mar del Plata',None,None),('San Clemente','San Clemente',None,None),('Atalaya','Atalaya',None,None),
       ('Oyarvide (Punta Indio)','Oyarvide','CANAL PUNTA INDIO',None),('La Plata','La Plata','PUERTO LA PLATA','la_plata'),
       ('Buenos Aires','Buenos Aires','PUERTO DE BUENOS AIRES','buenos_aires'),('San Fernando','San Fernando','SAN FERNANDO','san_fernando'),
       ('Martín García','Martín García',None,'martin_garcia'),('Pilote Norden','Pilote Norden',None,None)]

def main():
    print('Dia:', DAY0.date())
    try: mod = build_model()
    except Exception as e: print('[WARN] modelo Norden fallo:', e); mod = None
    mev, minfo = mod if mod else ([], {})
    rows = []
    for name, key, shnkey, ina in STN:
        s = pd.Series(obs[key]).sort_index(); s = s[(s.index >= DAY0-PAD) & (s.index < DAY1+PAD)]
        real = [e for e in extrema(s) if DAY0 <= e[0] < DAY1] if len(s) else []
        if len(s[(s.index >= DAY0) & (s.index < DAY1)]) < 18: real = []   # dia incompleto
        shl = shn_fc_events(shnkey) if shnkey else []
        inaev = []
        if ina:
            r = ina_fc(ina, DAY0 + pd.Timedelta(hours=3))
            if r and len(r[2]) > 20:
                sf = r[2]; inaev = extrema(sf[(sf.index >= DAY0-PAD) & (sf.index < DAY1+PAD)])
        for n, e in enumerate(real):
            sh = match(e, shl) if shnkey else None; ia = match(e, inaev) if ina else None
            mo = match(e, mev) if key == 'Pilote Norden' else None
            def f(x):
                return (x[0].strftime('%H:%M'), round(x[1], 2), round((e[0]-x[0]).total_seconds()/60), round(e[1]-x[1], 2)) if x else ('sin dato', '', '', '')
            row = [DAY0.date(), name, e[2], e[0].strftime('%H:%M'), round(e[1], 2)]
            row += list(f(sh)) if shnkey else ['no pronostica', '', '', '']
            row += list(f(ia)) if ina else ['no pronostica', '', '', '']
            row += list(f(mo)) if key == 'Pilote Norden' else ['no disponible', '', '', '']
            rows.append(row)
    hdr = ['fecha','estacion','evento','real_hora','real_alt','shn_hora','shn_alt','shn_err_min','shn_err_m','ina_hora','ina_alt','ina_err_min','ina_err_m','mod_hora','mod_alt','mod_err_min','mod_err_m']
    path = os.path.join(OUT, 'comparativo_mareas.csv')
    old = []
    if os.path.exists(path): old = [r for r in csv.reader(open(path, encoding='utf-8')) ][1:]
    old = [r for r in old if r[0] != str(DAY0.date())]      # idempotente
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(hdr); w.writerows(old); w.writerows(rows)
    # Parana: valor diario 00:00 vs ultima corrida previa
    prow = []
    for slug, name in [('campana','Campana'),('baradero','Baradero'),('san_pedro','San Pedro'),('ramallo','Ramallo'),('san_nicolas','San Nicolás'),
                       ('villa_constitucion','Villa Constitución'),('rosario','Rosario'),('san_lorenzo_san_martin','San Lorenzo')]:
        so = ina_series(slug); o = so.get(DAY0); r = ina_fc(slug, DAY0 + pd.Timedelta(hours=3)); p = None
        if r: p = r[2].get(DAY0)
        prow.append([DAY0.date(), name, '' if o is None else o, '' if p is None else round(p, 3), '' if (o is None or p is None) else round(o-p, 3)])
    pp = os.path.join(OUT, 'comparativo_parana.csv'); oldp = []
    if os.path.exists(pp): oldp = [r for r in csv.reader(open(pp, encoding='utf-8'))][1:]
    oldp = [r for r in oldp if r[0] != str(DAY0.date())]
    with open(pp, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(['fecha','estacion','ina_obs','ina_pron','err']); w.writerows(oldp); w.writerows(prow)
    # resumen acumulado
    all_rows = [dict(zip(hdr, r)) for r in csv.reader(open(path, encoding='utf-8'))][1:]
    res = {'actualizado': datetime.utcnow().isoformat()+'Z', 'dias': sorted({r['fecha'] for r in all_rows}), 'modelo_norden': minfo, 'por_estacion': {}}
    for src in ('shn', 'ina', 'mod'):
        agg = collections.defaultdict(lambda: {'h': [], 't': []})
        for r in all_rows:
            try: agg[r['estacion']]['h'].append(float(r[src+'_err_m'])); agg[r['estacion']]['t'].append(float(r[src+'_err_min']))
            except ValueError: pass
        for est, d in agg.items():
            if d['h']:
                h = np.array(d['h']); t = np.array(d['t'])
                res['por_estacion'].setdefault(est, {})[src] = {'n': len(h), 'mae_alt_m': round(float(np.mean(abs(h))), 3), 'sesgo_alt_m': round(float(np.mean(h)), 3), 'mae_hora_min': round(float(np.mean(abs(t))), 1), 'sesgo_hora_min': round(float(np.mean(t)), 1)}
    json.dump(res, open(os.path.join(OUT, 'resumen.json'), 'w'), indent=2, ensure_ascii=False)
    print('eventos:', len(rows), '| modelo:', minfo or 'no disponible')

if __name__ == '__main__':
    main()
