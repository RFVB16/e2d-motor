"""
escala_grafica.py — Lê a escala gráfica (escalas anuais) do SPPilots e diz quem está
realmente de serviço em cada dia (D1/D2), slot a slot.

Regras de leitura (validadas com o Rodrigo, out/2026):
  - 6 blocos de 12 colunas; bloco = grupo. Bloco do D1 = ((dias desde 01/01)/2 + 2) mod 6.
  - Linha do D1/D2 = dono do slot. Dono riscado (\\) = não trabalha.
  - Substitutos: acima da linha do D1 (para o D1) e abaixo da linha do D2 (para o D2),
    empilhados. Quem trabalha = o primeiro NÃO riscado, do dono para fora.

Depende só de numpy e Pillow (sem OCR externo): as siglas são reconhecidas por
comparação com o banco de modelos 'escala_grafica_modelos.npz'.
"""
import numpy as np, calendar, datetime as dt, json, re, base64, io
from pathlib import Path
from PIL import Image

D0 = dt.date(2026, 1, 1)

# ── grade ────────────────────────────────────────────────────────────────────
def _grp(v):
    out = []
    for x in v:
        if out and x - out[-1][-1] <= 2: out[-1].append(x)
        else: out.append([x])
    return [int(round(np.mean(o))) for o in out]

def _longest_run(v, lo, hi):
    best = []; cur = [v[0]]
    for a, b in zip(v, v[1:]):
        if lo <= b - a <= hi: cur.append(b)
        else:
            if len(cur) > len(best): best = cur
            cur = [b]
    return cur if len(cur) > len(best) else best

def _cols(xs):
    w = np.diff(xs)
    k = next((i for i in range(60, len(w)) if w[i] <= 19), None)
    if k is None: k = len(xs) - 1
    left = k - 72
    assert left >= 0, 'grade: colunas não encontradas'
    return xs[left:k + 1]

def carregar(img, ano, mes):
    """img: caminho ou bytes do JPEG. Devolve (rgb, xs[73], ys[nd+1], nd)."""
    im = Image.open(io.BytesIO(img) if isinstance(img, (bytes, bytearray)) else img).convert('RGB')
    rgb = np.asarray(im).astype(np.int16)
    g = np.asarray(im.convert('L')).astype(np.int16)
    H, W = g.shape
    dark = (g < 100)
    cs = dark.sum(0); rs = dark.sum(1)
    vx = _grp([x for x in range(W) if cs[x] > H * 0.45])
    hy = _grp([y for y in range(H) if rs[y] > W * 0.5])
    xs = _cols(_longest_run(vx, 17, 32))
    nd = calendar.monthrange(ano, mes)[1]
    sep = [x for x in vx if xs[-1] + 10 <= x <= xs[-1] + 26]
    if sep:
        sx = sep[0]; d = []
        for a, b in zip(hy, hy[1:]):
            if 22 <= b - a <= 31 and dark[a + 3:b - 2, sx - 1:sx + 2].max(1).mean() > 0.9: d.append(a)
        y0 = d[0]
    else:
        y0 = next(hy[i + 1] for i in range(len(hy) - 2) if 17 <= hy[i + 1] - hy[i] <= 24 and 24 <= hy[i + 2] - hy[i + 1] <= 30)
    best = None
    for s in np.arange(24, 31, 0.05):
        sc = sum(any(abs(h - (y0 + k * s)) <= 2 for h in hy) for k in range(nd + 1))
        if best is None or sc > best[0]: best = (sc, s)
    ys = [y0 + k * best[1] for k in range(nd + 1)]
    return rgb, xs, ys, nd

# ── célula ───────────────────────────────────────────────────────────────────
def _crop(rgb, x0, x1, y0, y1):
    return rgb[int(round(y0)) + 2:int(round(y1)) - 1, int(x0) + 2:int(x1) - 1]

def _textmask(c):
    r, g_, b = c[..., 0], c[..., 1], c[..., 2]
    gray = (0.299 * r + 0.587 * g_ + 0.114 * b)
    return (gray < 105) | ((r > 110) & (g_ < 90) & (b < 90))   # preto ou vermelho

def riscado(c):
    """Traço diagonal do canto superior esquerdo ao inferior direito (cantos fora do texto)."""
    h, w = c.shape[:2]
    if h < 8 or w < 8: return False
    gray = 0.299 * c[..., 0] + 0.587 * c[..., 1] + 0.114 * c[..., 2]
    bg = np.median(gray)
    m = (bg - gray) > 55
    def seg(ts):
        n = 0
        for t in ts:
            x = int(round(t * (w - 1))); y = int(round(t * (h - 1)))
            n += m[max(0, y - 2):y + 3, max(0, x - 2):x + 3].any()
        return n / len(ts)
    sup = seg(np.linspace(0.03, 0.24, 9)); inf = seg(np.linspace(0.76, 0.97, 9))
    # o traço às vezes não chega ao canto inferior (célula mais larga): o canto superior basta
    return (sup + inf) / 2 >= 0.75 or sup >= 0.99

def tem_texto(c):
    m = _textmask(c); h, w = m.shape
    core = m[int(h * .2):int(h * .85), int(w * .12):int(w * .88)]
    return core.mean() > 0.06

def vetor(c):
    """Sigla normalizada (sem o risco diagonal) -> vetor 16x32."""
    m = _textmask(c).astype(np.uint8); h, w = m.shape
    yy, xx = np.mgrid[0:h, 0:w]
    diag = np.abs(yy / max(h - 1, 1) - xx / max(w - 1, 1)) < 0.09
    m[diag] = 0
    m[:2, :] = 0; m[-2:, :] = 0; m[:, :2] = 0; m[:, -2:] = 0
    # remove pixels isolados
    nb = sum(np.roll(np.roll(m, i, 0), j, 1) for i in (-1, 0, 1) for j in (-1, 0, 1))
    m = ((m == 1) & (nb >= 3)).astype(np.uint8)
    ys_, xs_ = np.nonzero(m)
    if len(ys_) < 8: return None
    s = m[ys_.min():ys_.max() + 1, xs_.min():xs_.max() + 1] * 255
    v = np.asarray(Image.fromarray(s.astype(np.uint8)).resize((32, 16), Image.BILINEAR)).astype(np.float32).ravel()
    v -= v.mean(); n = np.linalg.norm(v)
    return v / n if n > 0 else None

class Banco:
    def __init__(self, path, extra=None):
        z = np.load(path, allow_pickle=False)
        self.V = z['V'].astype(np.float32); self.L = z['L']
        if extra is not None and Path(extra).exists():
            try:
                e = np.load(extra, allow_pickle=False)
                self.V = np.vstack([self.V, e['V'].astype(np.float32)]); self.L = np.concatenate([self.L, e['L']])
            except Exception:
                pass
    def ler(self, c):
        v = vetor(c)
        if v is None: return None, 0.0
        s = self.V @ v; i = int(np.argmax(s))
        return str(self.L[i]), float(s[i])

# ── leitura de um dia ────────────────────────────────────────────────────────
def bloco_do_d1(d1):
    return ((d1 - D0).days // 2 + 2) % 6

def _celula(imgs, data, c):
    g = imgs.get((data.year, data.month))
    if g is None: return None
    rgb, xs, ys, nd = g; r = data.day - 1
    return _crop(rgb, xs[c], xs[c + 1], ys[r], ys[r + 1])

def pilhas(imgs, dia, d1):
    """Por slot: [dono, substitutos...] — acima do D1 / abaixo do D2 (atravessa a virada do mês)."""
    b = bloco_do_d1(d1); sent = -1 if dia == d1 else 1; out = []
    for p in range(12):
        c = b * 12 + p; seq = [_celula(imgs, dia, c)]
        for k in range(1, 8):
            cc = _celula(imgs, dia + dt.timedelta(days=sent * k), c)
            if cc is None or not tem_texto(cc): break
            seq.append(cc)
        out.append([x for x in seq if x is not None])
    return out

def quem_trabalha(seq, banco):
    """Primeiro não riscado, do dono para fora. Devolve (sigla, semelhança) ou (None, 0)."""
    for c in seq:
        if not tem_texto(c) or riscado(c): continue
        return banco.ler(c)
    return None, 0.0

def escala_do_turno(imgs, d1, banco):
    """{D1: [12 siglas], D2: [12 siglas]}. Slot sem leitura num dia usa o do outro dia do turno."""
    d2 = d1 + dt.timedelta(days=1)
    r1 = [quem_trabalha(s, banco) for s in pilhas(imgs, d1, d1)]
    r2 = [quem_trabalha(s, banco) for s in pilhas(imgs, d2, d1)]
    w1 = [a[0] if a[0] else b[0] for a, b in zip(r1, r2)]
    w2 = [b[0] if b[0] else a[0] for a, b in zip(r1, r2)]
    sim = min([x[1] for x in r1 + r2 if x[0]] or [0])
    return {d1: w1, d2: w2}, sim

# ── download ────────────────────────────────────────────────────────────────
URL = 'https://sts.sppilots.com.br/sources/escala/escalas_anuais.asp'
def baixar(session, ano, mes):
    pad = r'data:image/[a-zA-Z]+;base64,([A-Za-z0-9+/=\s]+)'
    for dados in ({'mes': str(mes), 'ano': str(ano)}, {'mes': f'{mes:02d}', 'ano': str(ano)}):
        r = session.post(URL, data=dados, timeout=60)
        m = re.search(pad, r.text)
        if m: return base64.b64decode(re.sub(r'\s+', '', m.group(1)))
    r = session.get(URL, params={'mes': str(mes), 'ano': str(ano)}, timeout=60)
    m = re.search(pad, r.text)
    if m: return base64.b64decode(re.sub(r'\s+', '', m.group(1)))
    raise RuntimeError('imagem não encontrada na resposta do SPPilots')

def _dias_d1(ano, mes):
    nd = calendar.monthrange(ano, mes)[1]
    return [dt.date(ano, mes, d) for d in range(1, nd + 1) if (dt.date(ano, mes, d) - D0).days % 2 == 0]

def atualizar(senha, pasta, max_idade_min=50, hoje=None):
    """Baixa a escala gráfica do mês (e do vizinho perto da virada), lê quem trabalha em
    cada D1/D2 e grava inputs/escala_grafica.json. Usa a senha só para o login (não grava)."""
    import time
    pasta = Path(pasta); hoje = hoje or dt.date.today()
    cache = pasta / 'dados' / 'escala_grafica'; cache.mkdir(parents=True, exist_ok=True)
    meses = {(hoje.year, hoje.month)}
    ant = hoje.replace(day=1) - dt.timedelta(days=1); prox = (hoje.replace(day=28) + dt.timedelta(days=5)).replace(day=1)
    if hoje.day <= 8: meses.add((ant.year, ant.month))
    if hoje.day >= 22: meses.add((prox.year, prox.month))
    sess = None; imgs = {}
    for (a, m) in sorted(meses):
        f = cache / f'{a}-{m:02d}.jpg'
        if not f.exists() or (time.time() - f.stat().st_mtime) / 60 > max_idade_min:
            try:
                if sess is None:
                    from raspar_historico import fazer_login, BASE_URL
                    sess = fazer_login(senha); sess.get(f'{BASE_URL}/default.asp?ctx=OPR', timeout=30)
                f.write_bytes(baixar(sess, a, m))
                print(f'[Escala gráfica] {m:02d}/{a} baixada')
            except Exception as e:
                print(f'[Escala gráfica] ERRO ao baixar {m:02d}/{a}: {e}')
        if f.exists():
            try: imgs[(a, m)] = carregar(str(f), a, m)
            except Exception as e: print(f'[Escala gráfica] ERRO ao ler {f.name}: {e}')
    if not imgs: return None
    extra = pasta / 'dados' / 'escala_grafica_aprendido.npz'
    try:
        aprender(imgs, Banco(Path(__file__).parent / 'escala_grafica_modelos.npz', extra), pasta, extra, hoje)
    except Exception as e:
        print(f'[Escala gráfica] aprendizado não feito: {e}')
    banco = Banco(Path(__file__).parent / 'escala_grafica_modelos.npz', extra)
    saida = pasta / 'inputs' / 'escala_grafica.json'
    res = json.loads(saida.read_text(encoding='utf-8')) if saida.exists() else {}
    for (a, m) in imgs:
        for d1 in _dias_d1(a, m):
            try:
                E, sim = escala_do_turno(imgs, d1, banco)
            except Exception as e:
                print(f'[Escala gráfica] ERRO no turno {d1}: {e}'); continue
            for d, w in E.items():
                if (d.year, d.month) in imgs: res[d.isoformat()] = w
    saida.write_text(json.dumps(res, ensure_ascii=False, indent=0), encoding='utf-8')
    for d in (hoje, hoje + dt.timedelta(days=1)):
        print(f'[Escala gráfica] {d:%d/%m}: {" ".join(x or "??" for x in res.get(d.isoformat(), []))}')
    return res


def aprender(imgs, banco, pasta, extra, hoje):
    """Confere os dias já trabalhados com o histórico real (historico_2026.csv) e guarda as siglas
    confirmadas como novos modelos (melhora a leitura de estilos novos, ex.: células rosa)."""
    import pandas as pd
    hist = Path(pasta) / 'historico_2026.csv'
    if not hist.exists(): return
    h = pd.read_csv(hist); h['t'] = pd.to_datetime(h['datetime'], errors='coerce')
    h = h[h['Pratico'].notna()]
    real_dia = {}
    for t, p in zip(h['t'], h['Pratico']):
        if pd.isna(t): continue
        d = (t - pd.Timedelta(hours=7, minutes=30)).date()
        real_dia.setdefault(d, set()).update(x.strip().upper() for x in str(p).replace('/', ' ').split())
    novosV, novosL = [], []
    for (a, m) in imgs:
        for d1 in _dias_d1(a, m):
            for dia in (d1, d1 + dt.timedelta(days=1)):
                if dia >= hoje or dia not in real_dia or (dia.year, dia.month) not in imgs: continue
                real = real_dia[dia]; cel = []
                for seq in pilhas(imgs, dia, d1):
                    c = next((c for c in seq if tem_texto(c) and not riscado(c)), None)
                    v = vetor(c) if c is not None else None
                    cel.append((v, banco.ler(c)[0] if c is not None else None))
                lidos = [l for v, l in cel if v is not None]
                sobra = [i for i, (v, l) in enumerate(cel) if v is not None and l not in real]
                falta = sorted(real - set(lidos))
                for i, (v, l) in enumerate(cel):
                    if v is not None and l in real: novosV.append(v); novosL.append(l)
                if len(sobra) == 1 and len(falta) == 1:
                    novosV.append(cel[sobra[0]][0]); novosL.append(falta[0])
    if not novosV: return
    V = np.stack(novosV).astype(np.float16); L = np.array(novosL, dtype='U2')
    if Path(extra).exists():
        try:
            e = np.load(extra, allow_pickle=False); V = np.vstack([e['V'], V]); L = np.concatenate([e['L'], L])
        except Exception:
            pass
    # remove repetidos (mesmo vetor)
    _, idx = np.unique(np.round(V.astype(np.float32), 3), axis=0, return_index=True)
    idx = np.sort(idx)[-20000:]
    np.savez_compressed(extra, V=V[idx], L=L[idx])
