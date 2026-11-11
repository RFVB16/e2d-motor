"""
vez_e12.py — número dos especiais na fila exibida = posição deles na vez da E12 NAQUELE MOMENTO (regra de 10/11/2026).

A fila exibida mostra os regulares na ordem da E2D. Cada especial aparece com o número de chamadas da E12 que
faltam até a vez dele, contadas no momento da linha (depois do navio daquela linha):
  - os que ficaram para trás (pendentes) vêm primeiro;
  - depois a volta normal a partir da seta, até a posição do especial (pode passar de 12).
Não usa previsão de navio futuro: o especial só aparece "puxado" quando a E12 de fato o chama.
O estado da vez (seta + pendentes + escala do dia) por navio é gravado pelo gerar_2026.py em motor_e2d/_e12_vez.pkl.
"""
import re

ESP = {'JA', 'SI', 'CH'}
N = 12


def numero(estado, sigla):
    """Chamadas da E12 até a vez do especial (1 = é o próximo). None se ele não está na escala do dia."""
    ptr, buf, P = estado
    if sigla not in P:
        return None
    k = P.index(sigla)
    if k in buf:
        return buf.index(k) + 1
    return len(buf) + (k - ptr) % N + 1


def reescrever(esc, estado):
    """Tira os especiais da fila exibida e põe de volta na posição da vez da E12 naquele momento."""
    if not esc or not estado:
        return esc
    toks = [t.strip() for t in str(esc).split(' > ') if t.strip()]
    nome = lambda t: re.sub(r'\(.*?\)', '', t).strip()
    reg = [t for t in toks if nome(t) not in ESP]
    esp = []
    for s in sorted({nome(t) for t in toks if nome(t) in ESP} | {x for x in estado[2] if x in ESP}):
        n = numero(estado, s)
        if n is not None:
            esp.append((n, s))
    out = list(reg)
    for n, s in sorted(esp):
        out.insert(min(n - 1, len(out)), f'{s}({n})')
    return ' > '.join(out)
