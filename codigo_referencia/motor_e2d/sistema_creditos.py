"""
Sistema de Créditos de Posição para Fila V (Verde).
Pilotos que completam ciclos (i+p) recebem créditos baseado em pontos reais.
"""

from collections import defaultdict
from datetime import datetime

class SistemaCreditos:
    """Gerencia créditos de posição para pilots em fila V."""
    
    def __init__(self):
        self.creditos = {}        # pilot -> credito (0, 1, ou 2)
        self.entrada_ordem = {}   # pilot -> timestamp/sequência (para FIFO)
        self.contador_entrada = 0 # para quebra de empate FIFO
    
    def adicionar_piloto(self, piloto, pts_ciclo, pts_i=None, pts_p=None):
        """
        Pilot completa ciclo e entra na fila V com crédito.

        Regra nova (quando pts_i e pts_p fornecidos):
            1.5 <-> 1.5 = +1
            1.5 <-> 2.0 = +2
            2.0 <-> 2.0 = +3
            qualquer outro par = 0

        Returns: credito 0-3
        """
        if pts_i is not None and pts_p is not None:
            par = tuple(sorted([pts_i, pts_p], reverse=True))
            if par == (2.0, 2.0):   credito = 3
            elif par == (2.0, 1.5): credito = 2
            elif par == (1.5, 1.5): credito = 1
            else:                   credito = 0
        else:
            if pts_ciclo >= 4.0:   credito = 2
            elif pts_ciclo >= 3.5: credito = 1
            else:                  credito = 0

        self.creditos[piloto] = credito
        self.entrada_ordem[piloto] = self.contador_entrada
        self.contador_entrada += 1
        return credito
    
    def consumir_creditos(self, exceto=None):
        """
        Diminui 1 crédito de cada pilot com crédito > 0.
        Retorna set de pilotos cujo crédito chegou a 0 neste ciclo.
        
        Args:
            exceto: pilot a NÃO consumir crédito (acabou de ganhar nesta manobra)
        """
        chegou_zero = set()
        for piloto in self.creditos:
            if piloto == exceto:  # Pular pilot que acabou de ganhar crédito
                continue
            if self.creditos[piloto] > 0:
                self.creditos[piloto] -= 1
                self.entrada_ordem[piloto] = self.contador_entrada
                self.contador_entrada += 1
                if self.creditos[piloto] == 0:
                    chegou_zero.add(piloto)
        return chegou_zero
    
    def obter_sort_key_v(self, piloto):
        """
        Retorna sort key para ordenação da fila V.
        
        Ordem:
        - crédito-2: tier 2 (posição 12, última)
        - crédito-1: tier 1 (posição 11)
        - crédito-0: tier 0 (posição normal, FIFO por entrada_ordem)
        
        FIFO: quem entrou primeiro fica mais atrás (maior sort_key)
        
        Returns:
            (tier, entrada_ordem) onde tier determina posição
            None se piloto não está no sistema de créditos
        """
        if piloto not in self.creditos:
            # Não está no sistema: retorna None
            return None
        
        cred = self.creditos[piloto]
        entrada = self.entrada_ordem[piloto]
        
        # tier 2: crédito-2 (posição 12, mais ao fundo)
        # tier 1: crédito-1 (posição 11)
        # tier 0: crédito-0 (posição normal, FIFO)
        # FIFO: quem entrou PRIMEIRO tem entrada_ordem MENOR, mas queremos que fique MAIS ATRÁS
        # Então invertemos: negativo para ordenar descendente
        
        if cred == 2:
            return (2, -entrada)  # posição 12
        elif cred == 1:
            return (1, -entrada)  # posição 11
        else:  # cred == 0
            return (0, -entrada)  # posição normal, FIFO preservado
    
    def get_credito(self, piloto):
        """Retorna crédito atual do piloto (0 se não tem)."""
        return self.creditos.get(piloto, 0)
    
    def tem_credito(self, piloto):
        """Verifica se piloto tem crédito ativo."""
        return piloto in self.creditos and self.creditos[piloto] > 0
