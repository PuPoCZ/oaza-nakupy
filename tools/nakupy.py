#!/usr/bin/env python3
"""Správa aplikace Nákupy Oáza klidu z příkazové řádky (přes REST API Firestore).

Klíč se bere z proměnné NAKUPY_KLIC, ze souboru ~/.config/oaza-nakupy/klic nebo z --klic.
Jen standardní knihovna Pythonu.

  nakupy.py souhrn                         útrata k cíli a podle kategorií
  nakupy.py seznam [--kat K] [--stav S]    nákupy (S: plan, run, fak)
  nakupy.py detail ID                      jeden nákup jako JSON
  nakupy.py export [SOUBOR]                záloha všeho (stejný formát jako v aplikaci)
  nakupy.py uloz SOUBOR.json               založí nebo přepíše nákup(y) z JSON
  nakupy.py stav ID obj|zap|fak DATUM|ano|zrusit
  nakupy.py doklad ID --cislo C --datum RRRR-MM-DD --castka N [--typ Faktura]
  nakupy.py smaz ID --ano
"""
import argparse, json, os, random, signal, string, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime

API_KEY = 'AIzaSyDowhduH6_0zkbfVn_VDKVS3Ztz6XJqjto'
BASE = 'https://firestore.googleapis.com/v1/projects/oaza-luzka/databases/(default)/documents'
ROOT = 'oaza_nakupy'
P_KEYS = ['nazev', 'dodavatel', 'kat', 'obj', 'zap', 'fak', 'pozn', 'pol', 'dok', 'vytv', 'upr']
ITEM_KEYS = ['id', 'kat', 'nazev', 'prov', 'kod', 'pocet', 'jed', 'cena', 'odkaz', 'pozn', 'zrus']
DOC_KEYS = ['id', 'typ', 'cislo', 'datum', 'castka']
STAVBA = 'Stavební práce'


def rid():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))


def now():
    return datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def klic(args):
    k = args.klic or os.environ.get('NAKUPY_KLIC')
    if not k:
        p = os.path.expanduser('~/.config/oaza-nakupy/klic')
        if os.path.exists(p):
            k = open(p).read().strip()
    if not k:
        sys.exit('Chybí klíč: nastavte NAKUPY_KLIC, soubor ~/.config/oaza-nakupy/klic nebo --klic.')
    return k


# ---------- převod hodnot Firestore <-> JSON ----------
def dec(v):
    if 'stringValue' in v: return v['stringValue']
    if 'integerValue' in v: return int(v['integerValue'])
    if 'doubleValue' in v: return float(v['doubleValue'])
    if 'booleanValue' in v: return v['booleanValue']
    if 'nullValue' in v: return None
    if 'arrayValue' in v: return [dec(x) for x in v['arrayValue'].get('values', [])]
    if 'mapValue' in v: return {k: dec(x) for k, x in v['mapValue'].get('fields', {}).items()}
    raise ValueError(v)


def enc(v):
    if isinstance(v, bool): return {'booleanValue': v}
    if isinstance(v, int): return {'integerValue': str(v)}
    if isinstance(v, float): return {'integerValue': str(int(v))} if v.is_integer() else {'doubleValue': v}
    if isinstance(v, str): return {'stringValue': v}
    if v is None: return {'nullValue': None}
    if isinstance(v, list): return {'arrayValue': {'values': [enc(x) for x in v]}}
    if isinstance(v, dict): return {'mapValue': {'fields': {k: enc(x) for k, x in v.items()}}}
    raise ValueError(v)


def req(method, path, body=None, params=None):
    q = {'key': API_KEY, **(params or {})}
    url = f'{BASE}/{path}?{urllib.parse.urlencode(q, doseq=True)}'
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors='replace')
        if e.code == 403:
            sys.exit('Přístup odepřen: klíč neplatí, nebo data neodpovídají pravidlům.\n' + msg[:400])
        sys.exit(f'Chyba {e.code}: {msg[:600]}')


# ---------- data ----------
def load_all(k):
    out, token = {}, None
    while True:
        params = {'pageSize': 300}
        if token: params['pageToken'] = token
        r = req('GET', f'{ROOT}/{k}/nakupy', params=params)
        for d in r.get('documents', []):
            pid = d['name'].rsplit('/', 1)[1]
            out[pid] = {'id': pid, **{f: dec(v) for f, v in d.get('fields', {}).items()}}
        token = r.get('nextPageToken')
        if not token: return out


def load_cfg(k):
    r = req('GET', f'{ROOT}/{k}')
    return {f: dec(v) for f, v in r.get('fields', {}).items()}


def clean(p):
    o = {}
    for key in P_KEYS:
        o[key] = p.get(key, [] if key in ('pol', 'dok') else '')
    o['pol'] = [{**{'id': rid(), 'kat': '', 'nazev': '', 'prov': '', 'kod': '', 'pocet': 1, 'jed': 'ks', 'cena': 0, 'odkaz': '', 'pozn': '', 'zrus': False},
                 **{kk: i[kk] for kk in ITEM_KEYS if kk in i}} for i in o['pol'] or []]
    o['dok'] = [{**{'id': rid(), 'typ': 'Faktura', 'cislo': '', 'datum': '', 'castka': 0},
                 **{kk: d[kk] for kk in DOC_KEYS if kk in d}} for d in o['dok'] or []]
    for key in ('obj', 'zap', 'fak'):
        o[key] = str(o[key] or '')
    if not o['vytv']: o['vytv'] = now()
    return o


def save(k, pid, p):
    body = {'fields': {f: enc(v) for f, v in clean(p).items()}}
    req('PATCH', f'{ROOT}/{k}/nakupy/{pid}', body)


# ---------- výpočty (stejné jako v aplikaci) ----------
num = lambda v: float(v or 0)
item_total = lambda i: 0 if i.get('zrus') else num(i.get('pocet')) * num(i.get('cena'))
items_sum = lambda p: sum(item_total(i) for i in p.get('pol', []))
docs_sum = lambda p: sum(num(d.get('castka')) for d in p.get('dok', []))
amount = lambda p: docs_sum(p) if p.get('dok') else items_sum(p)
state = lambda p: 'fak' if p.get('fak') else 'zap' if p.get('zap') else 'obj' if p.get('obj') else 'plan'


def shares(p):
    tot, a, out = items_sum(p), amount(p), {}
    if tot > 0:
        for i in p.get('pol', []):
            v = item_total(i)
            if v:
                kk = i.get('kat') or p.get('kat') or 'Bez kategorie'
                out[kk] = out.get(kk, 0) + v / tot * a
    elif a:
        out[p.get('kat') or 'Bez kategorie'] = a
    return out


kc = lambda n: f'{round(n):,} Kč'.replace(',', ' ')


def cmd_souhrn(a):
    k = klic(a); cfg = load_cfg(k); ps = load_all(k)
    t = {'fak': 0, 'zap': 0, 'obj': 0, 'plan': 0}; cats = {}
    for p in ps.values():
        s = state(p); t[s] += amount(p)
        for kk, v in shares(p).items():
            c = cats.setdefault(kk, [0, 0]); c[1 if s == 'plan' else 0] += v
    spent = t['fak'] + t['zap'] + t['obj']; cil = num(cfg.get('cil', 1200000))
    print(f'Utraceno {kc(spent)} z cíle {kc(cil)} ({spent / cil * 100:.1f} %), zbývá {kc(cil - spent)}')
    print(f'  vyfakturováno {kc(t["fak"])}, zaplaceno bez faktury {kc(t["zap"])}, objednáno nezaplaceno {kc(t["obj"])}')
    st = cats.get(STAVBA, [0, 0])[0]
    print(f'  stavební práce {kc(st)}, vybavení a ostatní {kc(spent - st)}')
    print(f'V plánu {kc(t["plan"])}, nenaplánováno {kc(cil - spent - t["plan"])}')
    print('\nKategorie: utraceno / v plánu')
    for kk in list(cfg.get('kat', [])) + [x for x in cats if x not in cfg.get('kat', [])]:
        c = cats.get(kk, [0, 0]); print(f'  {kk}: {kc(c[0])} / {kc(c[1])}')


def cmd_seznam(a):
    k = klic(a); ps = load_all(k)
    for p in sorted(ps.values(), key=lambda p: (state(p), p.get('nazev', ''))):
        s = state(p)
        if a.stav and not (s == a.stav or (a.stav == 'run' and s in ('obj', 'zap'))): continue
        if a.kat and a.kat not in shares(p) and p.get('kat') != a.kat: continue
        marks = ''.join(x if p.get(f) else '·' for x, f in (('O', 'obj'), ('Z', 'zap'), ('F', 'fak')))
        print(f"{p['id']}  {marks}  {kc(amount(p)):>14}  {p.get('nazev', '')}  [{p.get('dodavatel', '')}]")


def cmd_detail(a):
    k = klic(a); r = req('GET', f'{ROOT}/{k}/nakupy/{a.id}')
    print(json.dumps({'id': a.id, **{f: dec(v) for f, v in r.get('fields', {}).items()}}, ensure_ascii=False, indent=1))


def cmd_export(a):
    k = klic(a); data = {'config': load_cfg(k), 'nakupy': list(load_all(k).values())}
    s = json.dumps(data, ensure_ascii=False, indent=1)
    if a.soubor: open(a.soubor, 'w').write(s); print(f'Uloženo {len(data["nakupy"])} nákupů do {a.soubor}')
    else: print(s)


def cmd_uloz(a):
    k = klic(a); data = json.load(open(a.soubor))
    lst = data['nakupy'] if isinstance(data, dict) and 'nakupy' in data else data if isinstance(data, list) else [data]
    for p in lst:
        pid = p.get('id') or rid(); p['upr'] = now(); save(k, pid, p)
        print(f'Uloženo {pid}  {p.get("nazev", "")}  {kc(amount(clean(p)))}')


def cmd_stav(a):
    k = klic(a); p = load_one(k, a.id)
    v = {'ano': '1', 'zrusit': ''}.get(a.hodnota, a.hodnota)
    if v and v != '1' and not (len(v) == 10 and v[4] == '-' and v[7] == '-'): sys.exit('Datum ve tvaru RRRR-MM-DD, nebo ano / zrusit.')
    p[a.krok] = v; p['upr'] = now(); save(k, a.id, p); print(f'{p.get("nazev")}: {a.krok} = {v or "(zrušeno)"}')


def cmd_doklad(a):
    k = klic(a); p = load_one(k, a.id)
    p.setdefault('dok', []).append({'id': rid(), 'typ': a.typ, 'cislo': a.cislo, 'datum': a.datum, 'castka': float(a.castka.replace(',', '.').replace(' ', ''))})
    p['upr'] = now(); save(k, a.id, p); print(f'{p.get("nazev")}: přidán doklad {a.typ} {a.cislo}, nákup teď {kc(amount(p))}')


def cmd_smaz(a):
    if not a.ano: sys.exit('Smazání potvrďte přepínačem --ano.')
    k = klic(a); p = load_one(k, a.id); req('DELETE', f'{ROOT}/{k}/nakupy/{a.id}'); print(f'Smazáno: {p.get("nazev")}')


def load_one(k, pid):
    r = req('GET', f'{ROOT}/{k}/nakupy/{pid}')
    return {f: dec(v) for f, v in r.get('fields', {}).items()}


def main():
    ap = argparse.ArgumentParser(description='Správa aplikace Nákupy Oáza klidu')
    ap.add_argument('--klic')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('souhrn').set_defaults(f=cmd_souhrn)
    s = sub.add_parser('seznam'); s.add_argument('--kat'); s.add_argument('--stav', choices=['plan', 'run', 'obj', 'zap', 'fak']); s.set_defaults(f=cmd_seznam)
    s = sub.add_parser('detail'); s.add_argument('id'); s.set_defaults(f=cmd_detail)
    s = sub.add_parser('export'); s.add_argument('soubor', nargs='?'); s.set_defaults(f=cmd_export)
    s = sub.add_parser('uloz'); s.add_argument('soubor'); s.set_defaults(f=cmd_uloz)
    s = sub.add_parser('stav'); s.add_argument('id'); s.add_argument('krok', choices=['obj', 'zap', 'fak']); s.add_argument('hodnota'); s.set_defaults(f=cmd_stav)
    s = sub.add_parser('doklad'); s.add_argument('id'); s.add_argument('--typ', default='Faktura'); s.add_argument('--cislo', required=True)
    s.add_argument('--datum', required=True); s.add_argument('--castka', required=True); s.set_defaults(f=cmd_doklad)
    s = sub.add_parser('smaz'); s.add_argument('id'); s.add_argument('--ano', action='store_true'); s.set_defaults(f=cmd_smaz)
    a = ap.parse_args(); a.f(a)


if __name__ == '__main__':
    if hasattr(signal, 'SIGPIPE'): signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    main()
