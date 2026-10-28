"""
Servidor local EP - porta 7373
GET /collect  -> raspa SPPILOTS e salva pauta_rt.csv
GET /status   -> retorna status atual
POST /pauta   -> recebe CSV do Chrome e salva
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import pathlib, json, subprocess, sys, os, threading

_DIR = pathlib.Path(__file__).parent

def raspar_sppilots():
    """Roda o coletor e retorna n manobras."""
    try:
        import importlib.util, sys
        # Carregar config
        cfg = json.load(open(_DIR / 'config.json'))
        senha = cfg.get('senha_sppilots', '')

        sys.path.insert(0, str(_DIR))
        from coletor_sppilots import coletar_pauta
        df, stats = coletar_pauta(senha=senha)
        if df is not None and len(df) > 0:
            out = _DIR / 'pauta_rt.csv'
            existing_n = 0
            if out.exists():
                import pandas as pd
                existing_n = len(pd.read_csv(out))
            if len(df) > existing_n:
                df.to_csv(out, index=False)
                return len(df), f'Salvo: {len(df)} manobras'
            else:
                return existing_n, f'Mantido: {existing_n} >= {len(df)}'
        return 0, 'Sem dados'
    except Exception as e:
        return 0, f'Erro: {e}'

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == '/collect':
            # Raspar em thread separada para não travar
            print('[Servidor] Coletando SPPILOTS...')
            n, msg = raspar_sppilots()
            print(f'[Servidor] {msg}')
            resp = json.dumps({'ok': n > 0, 'n': n, 'msg': msg})
        elif self.path == '/status':
            out = _DIR / 'pauta_rt.csv'
            n = 0
            if out.exists():
                try:
                    n = sum(1 for _ in open(out, encoding='utf-8')) - 1
                except: pass
            resp = json.dumps({'ok': True, 'n': n})
        else:
            self.send_response(404); self.end_headers(); return

        self.send_response(200)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(resp.encode())

    def do_POST(self):
        if self.path != '/pauta':
            self.send_response(404); self.end_headers(); return
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        try:
            csv = body.decode('utf-8-sig')
            lines = [l for l in csv.splitlines() if l.strip()]
            n = len(lines) - 1
            out = _DIR / 'pauta_rt.csv'
            existing_n = 0
            if out.exists():
                existing_n = sum(1 for _ in open(out, encoding='utf-8')) - 1
            if n > 0:   # sempre grava a pauta mais recente (antes só gravava se tivesse MAIS linhas)
                out.write_text(csv, encoding='utf-8')
                print(f'[Servidor] pauta_rt.csv salvo: {n} manobras')
                resp = json.dumps({'ok': True, 'n': n, 'msg': f'Salvo: {n} manobras'})
            else:
                resp = json.dumps({'ok': False, 'n': existing_n, 'msg': f'Mantido: {existing_n} >= {n}'})
        except Exception as e:
            resp = json.dumps({'ok': False, 'msg': str(e)})

        self.send_response(200)
        self._cors()
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(resp.encode())

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

if __name__ == '__main__':
    port = 7373
    server = HTTPServer(('localhost', port), Handler)
    print(f'[Servidor EP] Rodando em http://localhost:{port}')
    print(f'  GET /collect -> raspa SPPILOTS')
    print(f'  GET /status  -> status atual')
    print(f'  POST /pauta  -> recebe CSV')
    server.serve_forever()
