// ==UserScript==
// @name         E2D - Salvar Pauta Automatica
// @namespace    e2d-santos
// @version      1.5
// @description  Na pagina da pauta do SPPILOTS: salva a pauta no ep_server (porta 7373), recarrega a cada 5 min e refaz o login se a sessao cair (v1.5: login por formulario, nova tentativa a cada 3 min).
// @match        https://sts.sppilots.com.br/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      localhost
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';
  const RECARREGAR_MIN = 5;      // recarrega a pagina a cada 5 min
  const ESPERA_MS = 5000;        // espera a tabela carregar

  function aviso(txt, cor) {
    let d = document.getElementById('e2d-aviso');
    if (!d) {
      d = document.createElement('div');
      d.id = 'e2d-aviso';
      d.style.cssText = 'position:fixed;top:6px;right:6px;z-index:99999;padding:6px 10px;' +
        'font:12px Arial;border-radius:4px;color:#fff;box-shadow:0 1px 4px #0006';
      document.body.appendChild(d);
    }
    d.style.background = cor;
    d.textContent = txt;
  }

  function extrair() {
    const rows = document.querySelectorAll('tr');
    // amarelo (#ffff00) = manobra sem prático: ignorada. Verde (#66cc66) = CANCELADA depois da escalação:
    // enviada (v1.4, 29/10/2026) para o painel pôr o prático escalado na frente da fila.
    const CI = new Set(['#ffff00']);
    const SM = {'#66cc66': 'CANCELADA', '#ff4a4a': 'AGENDADO', '#33ccff': 'PROXIMO', '#b7b7ff': 'BREVE', '#ffffff': 'FUTURO', '#ff0099': 'ESPECIAL', '#000000': 'ESPECIAL'};
    const hoje = new Date();
    const m = [];
    for (const r of rows) {
      const tds = r.querySelectorAll('td');
      if (tds.length < 7) continue;
      const es = (tds[3]?.textContent?.trim() || '').toUpperCase();
      if (!['E', 'S', 'M'].includes(es)) continue;
      const st = r.getAttribute('style') || '';
      const bg = st.match(/background\s*:\s*(#[0-9a-fA-F]{6})/i);
      const cor = bg ? bg[1].toLowerCase() : '#ffffff';
      if (CI.has(cor)) continue;
      const sta = SM[cor] || 'FUTURO';
      const vr = tds[2]?.textContent?.trim() || '';
      const vTem2 = /\(\s*2\s*PR[A-Za-zÀ-ÿ]TICOS?\s*\)/i.test(vr);
      const v = vr.replace(/\s*\(\s*2\s*PR[A-Za-zÀ-ÿ]TICOS?\s*\)\s*/gi, '').trim();
      const b = (tds[4]?.textContent?.trim() || '').replace(/\s+/g, ' ');
      const b2 = tds[5]?.textContent?.trim() || '';
      const h = tds[6]?.textContent?.trim() || '';
      const pra = tds[11]?.textContent?.trim() || '';
      // Calado e bordo pelo conteúdo (a posição das colunas mudou no SPPILOTS):
      //   calado = "12,75" ou "12,75 | 12,95"; bordo = BB ou BE
      const txt = [...tds].map(td => (td.textContent || '').trim());
      const cal = txt.slice(7).find(x => /^\d{1,2}[,.]\d{1,2}(\s*\|\s*\d{1,2}[,.]\d{1,2})?$/.test(x)) || '';
      const brd = txt.slice(7).find(x => /^(BB|BE)$/i.test(x)) || '';
      const cels = txt.slice(7).join(' ¦ ');   // diagnóstico: todas as colunas a partir da 8ª
      const ag = tds[15]?.textContent?.trim() || '';
      const ob = (tds[16]?.textContent?.trim() || '').replace(/[\n\r]/g, ' ');
      const mm = h.match(/(\d{2})\/(\d{2})\s+(\d{2}):(\d{2})/);
      if (!mm) continue;
      // Ano: o do dia de hoje; na virada do ano (pauta de janeiro vista em dezembro) usa o seguinte
      let ano = hoje.getFullYear();
      const mes = parseInt(mm[2], 10);
      if (mes - (hoje.getMonth() + 1) < -6) ano += 1;
      if (mes - (hoje.getMonth() + 1) > 6) ano -= 1;
      const dt = `${ano}-${mm[2]}-${mm[1]}T${mm[3]}:${mm[4]}:00`;
      const da = `${mm[1]}/${mm[2]}/${ano}`;
      const hh = `${mm[3]}:${mm[4]}`;
      let fr, to;
      if (es === 'E') { fr = 'FB'; to = b; } else if (es === 'S') { fr = b; to = 'FB'; } else { fr = b; to = b2 || b; }
      const pp = pra.split(/\s+/).filter(p => p.length >= 2);
      const bi = pp.filter(p => /^[A-Z]{2}$/.test(p));
      const dois = vTem2 || bi.length >= 2 || /2\s*PLT/i.test(ob);
      if (dois && pp.length >= 2) {
        for (const p of pp.slice(0, 2)) m.push([dt, da, hh, '', v, fr, to, es, b, cal, brd, ag, ob, sta, 'true', p, cels]);
      } else m.push([dt, da, hh, '', v, fr, to, es, b, cal, brd, ag, ob, sta, String(dois), pp[0] || '', cels]);
    }
    const hd = 'datetime,Data,Hora,Termino,Vessel,From,To,ES,Berco,Calado,Bordo,Agente,OBS,Status,dois_prat,Pratico,Celulas';
    const csv = hd + '\n' + m.map(r => r.map(x => '"' + String(x).replace(/"/g, '""') + '"').join(',')).join('\n');
    return {n: m.length, csv};
  }

  function enviar() {
    const {n, csv} = extrair();
    const hora = new Date().toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});
    if (n === 0) {
      aviso(`E2D ${hora}: nenhuma manobra na página (sessão expirou?) — nada enviado`, '#c0392b');
      return;
    }
    GM_xmlhttpRequest({
      method: 'POST',
      url: 'http://localhost:7373/pauta',
      headers: {'Content-Type': 'text/csv; charset=utf-8'},
      data: csv,
      onload: r => {
        let msg = '';
        try { msg = JSON.parse(r.responseText).msg; } catch (e) { msg = r.status; }
        aviso(`E2D ${hora}: ${n} manobras → ${msg}`, '#27ae60');
      },
      onerror: () => aviso(`E2D ${hora}: ep_server.py não respondeu (está aberto?)`, '#c0392b'),
    });
  }

  // ── Login automático quando a sessão cai ────────────────────────────────
  // A senha fica guardada só no Tampermonkey deste computador (pedida uma vez).
  const USUARIO = 'villasboas';
  const URL_PAUTA_PADRAO = 'https://sts.sppilots.com.br/sources/manobra/psh.asp';

  function logado() {
    return /\bSAIR\b/.test(document.body.innerText || '') || document.body.innerText.includes('NOME DO NAVIO');
  }

  // v1.5 (03/11/2026): o login automático pelo fetch dizia "ok", mas a pauta continuava sem sessão e a página
  // ficava parada em "nova tentativa". Agora o login é feito como na tela (formulário de verdade, o navegador grava
  // o cookie da sessão nova), depois abre o contexto OPR e a pauta padrão. Nova tentativa a cada 3 min, sem limite.
  // A senha nunca é apagada sozinha, e só é pedida com a página visível (um prompt escondido travaria tudo).
  const ESPERA_RELOGIN = 3 * 60 * 1000;
  const hhmm = t => new Date(t).toLocaleTimeString('pt-BR', {hour: '2-digit', minute: '2-digit'});

  function relogar() {
    const ult = GM_getValue('ult_relogin', 0);
    if (Date.now() - ult < ESPERA_RELOGIN) {
      const prox = ult + ESPERA_RELOGIN;
      aviso(`E2D: sessão caiu; nova tentativa de login às ${hhmm(prox)}`, '#c0392b');
      setTimeout(() => { location.href = URL_PAUTA_PADRAO; }, prox - Date.now() + 2000);
      return;
    }
    GM_setValue('ult_relogin', Date.now());
    let senha = GM_getValue('senha', '');
    if (!senha && document.visibilityState === 'visible') {
      senha = prompt('E2D: senha do SPPILOTS para refazer o login automático (fica salva só neste computador):') || '';
      if (senha) GM_setValue('senha', senha);
    }
    if (!senha) {
      aviso('E2D: falta a senha do SPPilots para o login automático. Recarregue esta página com ela na tela.', '#c0392b');
      setTimeout(() => { location.href = URL_PAUTA_PADRAO; }, ESPERA_RELOGIN);
      return;
    }
    aviso('E2D: sessão caiu — refazendo login...', '#e67e22');
    GM_setValue('pos_login', Date.now());
    const f = document.createElement('form');
    f.method = 'POST'; f.action = '/default.asp'; f.style.display = 'none';
    for (const [k, v] of Object.entries({userid: USUARIO, password: senha, cmd: 'LOG', act: ''})) {
      const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.appendChild(i);
    }
    document.body.appendChild(f);
    f.submit();
  }

  const naPauta = location.pathname.toLowerCase().includes('/sources/manobra/psh.asp');
  setTimeout(() => {
    if (naPauta) {
      if (document.body.innerText.includes('NOME DO NAVIO')) {
        GM_setValue('url_pauta', location.href);
        GM_setValue('ativo', true);
        enviar();
        setTimeout(() => location.reload(), RECARREGAR_MIN * 60 * 1000);
      } else {
        relogar();                                     // pauta sem tabela = sessão caiu
      }
    } else if (GM_getValue('ativo', false)) {
      // Caiu em outra página do SPPILOTS (ex.: tela de login) enquanto rodava sozinho
      if (!logado()) relogar();
      else if (Date.now() - GM_getValue('pos_login', 0) < 5 * 60 * 1000) {   // acabou de refazer o login
        GM_setValue('pos_login', 0);
        aviso('E2D: login refeito — abrindo a pauta', '#27ae60');
        fetch('/default.asp?ctx=OPR', {credentials: 'same-origin'}).catch(() => {}).finally(() => { location.href = URL_PAUTA_PADRAO; });
      }
      else setTimeout(() => { location.href = GM_getValue('url_pauta', URL_PAUTA_PADRAO); }, 60 * 1000);
    }
  }, ESPERA_MS);
})();
