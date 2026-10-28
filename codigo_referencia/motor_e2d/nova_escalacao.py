"""
nova_escalacao.py

REGRA PADRÃO (desde 23/10/2026): TROCA DIRETA.
  Cada sainte é substituído, na MESMA posição da fila, pelo entrante do seu slot,
  seguindo a cadeia de slots (sainte -> remanescente que mudou de slot -> ... -> entrante).
  Remanescentes não mudam de posição. Se a cadeia termina num especial, a posição
  do sainte é descartada; entrante sem posição herdada vai para o fim.
  Critério (Rodrigo): quem continua trabalhando deve ter a menor mudança no descanso.
  A regra antiga (substituição indireta) continua disponível com REORD=indireta.

Algoritmo antigo (REORD=indireta):
Para cada posição na ultima_esc (em ordem):
  1. Se permanece: inserir novos cujo q_subst == ele (antes dele), depois ele próprio
  2. Se leaver:
     a. q_entra[leaver] é novo → entra na posição do leaver
     b. q_entra[leaver] é permanece → SKIP (perm mantém própria posição)
     c. q_entra[leaver] é especial → SKIP (especiais gerenciados separado)
"""

def status_valido(st):
    if not st or st in ('ok','P','E'): return st
    if st.startswith('P+'): return st
    try:
        h,m = int(st[:2]), int(st[3:5])
        return 'ok' if h*60+m <= 7*60+30 else st
    except: return 'ok'

def parse_esc(s):
    result = []
    for part in (s or '').split(' > '):
        part = part.strip()
        if not part: continue
        if '(' in part:
            p  = part[:part.index('(')]
            st = part[part.index('(')+1:part.index(')')]
        else:
            p, st = part, 'ok'
        result.append((p, st))
    return result

def fmt_esc(lista):
    return ' > '.join(f'{p}({st})' for p, st in lista)

def nova_escalacao(ultima_esc_str, saindo, entrando):
    ESPECIAIS = set(filter(None, __import__('os').environ.get('ESP_SET','JA,SI,CH').split(',')))
    saindo   = [p for p in saindo   if p and p != '?']
    entrando = [p for p in entrando if p and p != '?']
    n = min(len(saindo), len(entrando))
    saindo, entrando = saindo[:n], entrando[:n]

    saindo_set   = set(saindo)
    entrando_set = set(entrando)

    # q_entra[leaver] = quem entra no slot do leaver
    # q_subst[novo]   = de quem o novo tomou o slot
    q_entra = {saindo[i]: entrando[i] for i in range(n)}
    q_subst = {entrando[i]: saindo[i] for i in range(n)}

    permanece = entrando_set & saindo_set
    novos     = (entrando_set - saindo_set) - ESPECIAIS  # novos não-especiais

    esc = parse_esc(ultima_esc_str)
    if __import__('os').environ.get('REORD', 'direto') == 'direto':
        # TROCA DIRETA: fotografia da fila; cada sainte é substituído, na MESMA posição,
        # pelo entrante do seu slot (seguindo a cadeia de trocas); status mantidos.
        slot_sai = {p: i for i, p in enumerate(saindo)}
        def entra_no_lugar(L):
            seen = set(); j = slot_sai[L]
            while True:
                q = entrando[j] if j < len(entrando) else None
                if q is None or q in seen: return None
                seen.add(q)
                if q in novos: return q
                if q in slot_sai: j = slot_sai[q]
                else: return None
        out = []; usados = set()
        for p, st in esc:
            if p in ESPECIAIS: continue
            if p in saindo_set and p not in entrando_set:
                q = entra_no_lugar(p)
                if q and q not in usados: out.append((q, 'ok')); usados.add(q)
            elif p not in usados:
                out.append((p, st)); usados.add(p)
        for e in entrando:
            if e in novos and e not in usados: out.append((e, 'ok')); usados.add(e)
        return fmt_esc(out[:12])
    if __import__('os').environ.get('REORD') == 'slot':
        # SEM REORDENAR: a fila do novo dia é a própria escalação do dia, na ordem dos slots
        return fmt_esc([(p, 'ok') for p in entrando if p not in ESPECIAIS][:12])

    final    = []
    inseridos = set()

    for p, st in esc:
        if p in ESPECIAIS:
            continue  # especiais gerenciados via next_slot

        if p in permanece:
            # Antes deste perm: inserir novo cujo q_subst == p
            for e in entrando:
                if e not in novos:     continue
                if e in inseridos:     continue
                if q_subst.get(e) == p:
                    final.append((e, 'ok'))
                    inseridos.add(e)
            # Inserir o perm
            if p not in inseridos:
                final.append((p, status_valido(st)))
                inseridos.add(p)

        elif p in saindo_set:
            # Leaver: quem entra no seu slot?
            substituto = q_entra.get(p)
            if substituto and substituto in novos and substituto not in inseridos:
                # Novo toma a posição do leaver
                final.append((substituto, 'ok'))
                inseridos.add(substituto)
            # Se substituto é perm ou especial: skip (perm já aparecerá na própria pos)

        else:
            # Piloto que não é perm nem saindo (ex: já estava e não está em saindo)
            if p not in inseridos:
                final.append((p, status_valido(st)))
                inseridos.add(p)

    # Novos restantes que não encontraram posição → append
    for e in entrando:
        if e in novos and e not in inseridos:
            final.append((e, 'ok'))
            inseridos.add(e)

    # Deduplicar e limitar
    seen = set(); dedup = []
    for item in final:
        if item[0] not in seen:
            seen.add(item[0]); dedup.append(item)

    return fmt_esc(dedup[:12])
