"""
agents/log_analyst.py - Agente autônomo que analisa o log do bot em tempo real
e sugere/aplica melhorias automáticas via Gemini API.

Uso:
    python agents/log_analyst.py              # Analisa e mostra sugestões
    python agents/log_analyst.py --apply      # Aplica ajustes automáticos no settings.yaml
    python agents/log_analyst.py --watch      # Modo contínuo (analisa a cada N minutos)
    python agents/log_analyst.py --watch --apply --interval 30
"""

import sys
import os
import re
import time
import json
import yaml
import argparse
import logging
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

LOG_FILE = ROOT / "trading_system.log"
SETTINGS_FILE = ROOT / "config" / "settings.yaml"
REPORT_DIR = ROOT / "agents" / "reports"
REPORT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("LogAnalyst")


# ---------------------------------------------------------------------------
# 1. PARSER DE LOG
# ---------------------------------------------------------------------------

class LogParser:
    """Extrai eventos estruturados do trading_system.log."""

    # Padrões regex
    RE_CYCLE    = re.compile(r"Iniciando Ciclo #(\d+)")
    RE_SYMBOL   = re.compile(r"\[(\w+)\] Iniciando Análise")
    RE_PRICE    = re.compile(r"\[(\w+)\] Preço: ([\d.]+) \| RSI: ([\d.]+)")
    RE_SIGNAL   = re.compile(r"\[(\w+)\] Signal: Signal\(action='(\w+)'")
    RE_TIMESTAMP= re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
    RE_NO_SIGNAL= re.compile(r"\[(\w+)\] Nenhum setup identificado")
    RE_QUALITY  = re.compile(r"\[(\w+)\] Qualidade: Score=(\d+)/100 \| Nota=(\w+) \| Tradeável=(\w+)")
    RE_WARNING  = re.compile(r"\[(\w+)\] ⚠️ (.+)")
    RE_MCP      = re.compile(r"\[(\w+)\] MCP: Aprovado=(\w+) \| Confiança=([\d.]+)")
    RE_BLOCKED  = re.compile(r"\[(\w+)\] Setup bloqueado: Score (\d+) < (\d+)")
    RE_ORDER    = re.compile(r"\[(\w+)\] Executando ordem")
    RE_CLOSE    = re.compile(r"SAÍDA CONFIRMADA: (\w+) \| Trend: (\w+) \| PnL: ([-\d.]+)")
    RE_ERROR    = re.compile(r"ERROR - (.+?) - (.+)")
    RE_SESSION  = re.compile(r"\[(\w+)\] Sessão: (\w+) \| Score: ([\d.]+)")
    RE_CONTEXT  = re.compile(r"\[(\w+)\] Contexto 3m: (.+)")
    RE_SR       = re.compile(r"\[(\w+)\] S/R: Suporte=([\d.N/A]+) \| Resistência=([\d.N/A]+)")

    def parse_tail(self, lines: int = 5000) -> dict:
        """Lê as últimas N linhas do log e extrai métricas."""
        if not LOG_FILE.exists():
            return {}

        # Ler tail eficientemente
        with open(LOG_FILE, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, lines * 200)  # ~200 bytes por linha
            f.seek(max(0, size - chunk))
            raw = f.read().decode("utf-8", errors="replace")

        log_lines = raw.splitlines()

        events = {
            "cycles": 0,
            "symbols_analyzed": Counter(),
            "signals_generated": Counter(),    # sym -> count
            "signals_blocked_score": Counter(), # sym -> count
            "signals_blocked_mcp": Counter(),   # sym -> count
            "orders_executed": Counter(),
            "mcp_approvals": [],               # [{sym, approved, confidence}]
            "quality_scores": defaultdict(list),# sym -> [scores]
            "warnings": defaultdict(list),      # sym -> [warning msgs]
            "errors": [],
            "sessions": Counter(),
            "no_signal": Counter(),
            "closes": [],
            "context_3m": defaultdict(list),
            "near_resistance_blocks": Counter(),
            "volume_blocks": Counter(),
            "rsi_values": defaultdict(list),
            "raw_tail": log_lines[-200:],       # últimas 200 linhas brutas
            # Análise horária (UTC)
            "hourly_signals": defaultdict(int),    # hora -> qtd sinais
            "hourly_scores": defaultdict(list),    # hora -> [scores]
            "hourly_mcp": defaultdict(list),       # hora -> [approved bool]
            "hourly_orders": defaultdict(int),     # hora -> qtd ordens
        }

        current_hour = None

        for line in log_lines:
            # Extrai hora UTC corrente da linha
            if m := self.RE_TIMESTAMP.match(line):
                try:
                    current_hour = int(m.group(1).split(" ")[1].split(":")[0])
                except Exception:
                    pass
            if m := self.RE_CYCLE.search(line):
                events["cycles"] = max(events["cycles"], int(m.group(1)))

            if m := self.RE_PRICE.search(line):
                sym, price, rsi = m.group(1), float(m.group(2)), float(m.group(3))
                events["rsi_values"][sym].append(rsi)

            if m := self.RE_SIGNAL.search(line):
                events["signals_generated"][m.group(1)] += 1
                if current_hour is not None:
                    events["hourly_signals"][current_hour] += 1

            if m := self.RE_NO_SIGNAL.search(line):
                events["no_signal"][m.group(1)] += 1

            if m := self.RE_QUALITY.search(line):
                sym, score = m.group(1), int(m.group(2))
                events["quality_scores"][sym].append(score)
                if current_hour is not None:
                    events["hourly_scores"][current_hour].append(score)

            if m := self.RE_BLOCKED.search(line):
                events["signals_blocked_score"][m.group(1)] += 1

            if m := self.RE_MCP.search(line):
                sym = m.group(1)
                approved = m.group(2) == "True"
                conf = float(m.group(3))
                events["mcp_approvals"].append({"sym": sym, "approved": approved, "confidence": conf})
                if not approved:
                    events["signals_blocked_mcp"][sym] += 1
                if current_hour is not None:
                    events["hourly_mcp"][current_hour].append(approved)

            if m := self.RE_ORDER.search(line):
                events["orders_executed"][m.group(1)] += 1
                if current_hour is not None:
                    events["hourly_orders"][current_hour] += 1

            if m := self.RE_WARNING.search(line):
                sym, msg = m.group(1), m.group(2)
                events["warnings"][sym].append(msg)
                if "resistência" in msg.lower() or "resistance" in msg.lower():
                    events["near_resistance_blocks"][sym] += 1
                if "volume" in msg.lower():
                    events["volume_blocks"][sym] += 1

            if m := self.RE_ERROR.search(line):
                events["errors"].append({"module": m.group(1), "msg": m.group(2)})

            if m := self.RE_SESSION.search(line):
                events["sessions"][m.group(2)] += 1

            if m := self.RE_CLOSE.search(line):
                events["closes"].append({
                    "side": m.group(1), "trend": m.group(2),
                    "pnl": float(m.group(3))
                })

            if m := self.RE_CONTEXT.search(line):
                events["context_3m"][m.group(1)].append(m.group(2))

        return events


# ---------------------------------------------------------------------------
# 2. ANALISADOR
# ---------------------------------------------------------------------------

class BotAnalyzer:
    """Interpreta os eventos e produz um relatório de diagnóstico."""

    def analyze(self, events: dict) -> dict:
        if not events:
            return {"status": "sem_dados"}

        total_analyzed = sum(events["symbols_analyzed"].values()) or sum(events["no_signal"].values()) + sum(events["signals_generated"].values())
        total_signals = sum(events["signals_generated"].values())
        total_blocked_score = sum(events["signals_blocked_score"].values())
        total_blocked_mcp = sum(events["signals_blocked_mcp"].values())
        total_orders = sum(events["orders_executed"].values())
        total_closes = len(events["closes"])
        pnl_list = [c["pnl"] for c in events["closes"]]
        total_pnl = sum(pnl_list)
        wins = sum(1 for p in pnl_list if p > 0)
        losses = sum(1 for p in pnl_list if p <= 0)

        # Taxa de bloqueio por resistência
        resistance_block_rate = (
            sum(events["near_resistance_blocks"].values()) / max(total_signals, 1) * 100
        )

        # Taxa de bloqueio por volume
        volume_block_rate = (
            sum(events["volume_blocks"].values()) / max(total_signals, 1) * 100
        )

        # Scores médios por símbolo
        avg_scores = {
            sym: sum(scores) / len(scores)
            for sym, scores in events["quality_scores"].items()
            if scores
        }

        # RSI médio por símbolo
        avg_rsi = {
            sym: sum(vals) / len(vals)
            for sym, vals in events["rsi_values"].items()
            if vals
        }

        # Sessões dominantes
        top_sessions = events["sessions"].most_common(3)

        # MCP: taxa de aprovação
        mcp_total = len(events["mcp_approvals"])
        mcp_approved = sum(1 for a in events["mcp_approvals"] if a["approved"])
        mcp_approval_rate = (mcp_approved / mcp_total * 100) if mcp_total > 0 else 0
        avg_mcp_confidence = (
            sum(a["confidence"] for a in events["mcp_approvals"]) / mcp_total
            if mcp_total > 0 else 0
        )

        # Análise por hora UTC
        all_hours = set(events["hourly_signals"]) | set(events["hourly_scores"]) | set(events["hourly_mcp"])
        hourly_stats = {}
        for h in sorted(all_hours):
            signals = events["hourly_signals"].get(h, 0)
            scores = events["hourly_scores"].get(h, [])
            mcp_vals = events["hourly_mcp"].get(h, [])
            orders = events["hourly_orders"].get(h, 0)
            hourly_stats[h] = {
                "hour_utc": h,
                "signals": signals,
                "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
                "mcp_approval_rate": round(sum(mcp_vals) / len(mcp_vals) * 100, 1) if mcp_vals else 0,
                "orders": orders,
            }

        # Ranking de melhores horas (por sinais com boa qualidade)
        best_hours = sorted(
            hourly_stats.values(),
            key=lambda x: (x["signals"], x["avg_score"], x["mcp_approval_rate"]),
            reverse=True
        )[:6]

        # Erros recorrentes
        error_counter = Counter(e["msg"][:60] for e in events["errors"])

        # Símbolos sem nenhum sinal
        no_signal_syms = sorted(events["no_signal"].items(), key=lambda x: -x[1])

        # Símbolos mais bloqueados
        most_blocked = (events["signals_blocked_score"] + events["signals_blocked_mcp"]).most_common(5)

        return {
            "cycles": events["cycles"],
            "total_signals": total_signals,
            "total_blocked_score": total_blocked_score,
            "total_blocked_mcp": total_blocked_mcp,
            "total_orders": total_orders,
            "total_closes": total_closes,
            "total_pnl": total_pnl,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0,
            "resistance_block_rate": resistance_block_rate,
            "volume_block_rate": volume_block_rate,
            "avg_scores": avg_scores,
            "avg_rsi": avg_rsi,
            "top_sessions": top_sessions,
            "mcp_approval_rate": mcp_approval_rate,
            "avg_mcp_confidence": avg_mcp_confidence,
            "mcp_total": mcp_total,
            "error_counter": dict(error_counter.most_common(5)),
            "no_signal_syms": no_signal_syms[:5],
            "most_blocked": most_blocked,
            "warnings_summary": {
                sym: Counter(msgs).most_common(2)
                for sym, msgs in events["warnings"].items()
            },
            "hourly_stats": hourly_stats,
            "best_hours": best_hours,
        }


# ---------------------------------------------------------------------------
# 3. AGENTE IA (Gemini)
# ---------------------------------------------------------------------------

class AIAdvisor:
    """Usa Gemini para interpretar o diagnóstico e gerar recomendações."""

    def __init__(self):
        self.client = None
        self._init_gemini()

    def _init_gemini(self):
        try:
            from config.config_loader import load_config
            config = load_config()
            api_key = config.get("mcp", {}).get("gemini_api_key")
            if not api_key:
                return
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.client = genai.GenerativeModel("gemini-2.5-flash")
            logger.info("Gemini inicializado para o agente de análise.")
        except Exception as e:
            logger.warning(f"Gemini não disponível: {e}. Usando análise local.")

    def get_recommendations(self, diagnosis: dict, current_config: dict) -> str:
        """Envia diagnóstico ao Gemini e recebe recomendações estruturadas."""
        if not self.client:
            return self._local_recommendations(diagnosis, current_config)

        prompt = f"""
Você é um especialista em sistemas de trading algorítmico. Analise o diagnóstico abaixo
de um bot de trading de criptomoedas na Bybit e forneça recomendações práticas.

=== DIAGNÓSTICO DO BOT ===
{json.dumps(diagnosis, indent=2, ensure_ascii=False, default=str)}

=== CONFIGURAÇÃO ATUAL ===
{json.dumps(current_config, indent=2, ensure_ascii=False, default=str)}

=== CONTEXTO DO SISTEMA ===
- Estratégia: EMA 20/50 + RSI + Volume para gerar sinais CALL/PUT
- Filtro de qualidade: score 0-100, mínimo {current_config.get('quality', {}).get('min_score', 60)} para entrada
- Validação por IA (MCP/Gemini) antes de executar
- Timeframe: 15m para sinal, 3m para timing de entrada
- Gestão de risco: {current_config.get('risk', {}).get('entry_percent', 0.1)*100:.0f}% do saldo por trade

=== ANALISE POR HORA UTC ===
{json.dumps(diagnosis.get('best_hours', []), indent=2, ensure_ascii=False, default=str)}

=== O QUE ANALISAR ===
1. Por que tantos sinais estão sendo bloqueados? (resistência, volume, score, MCP)
2. A taxa de aprovação do MCP ({diagnosis.get('mcp_approval_rate', 0):.1f}%) está adequada?
3. O score mínimo atual ({current_config.get('quality', {}).get('min_score', 60)}) é muito restritivo?
4. Quais símbolos têm melhor performance e merecem prioridade?
5. Há padrões nos erros que indicam bugs?
6. A sessão de mercado dominante ({diagnosis.get('top_sessions', [])}) afeta a estratégia?
7. Baseado na análise horária, qual janela UTC tem melhor combinação de qualidade+aprovação MCP?

=== FORMATO DE RESPOSTA ===
Retorne APENAS um JSON válido com esta estrutura exata:
{{
  "resumo": "análise em 2-3 frases do estado geral do bot",
  "problemas": [
    {{"prioridade": "ALTA/MEDIA/BAIXA", "problema": "descrição", "causa": "causa raiz", "impacto": "impacto no bot"}}
  ],
  "recomendacoes": [
    {{
      "tipo": "CONFIG/CODIGO/MONITORAR",
      "descricao": "o que fazer",
      "parametro": "nome do parâmetro se aplicável",
      "valor_atual": "valor atual",
      "valor_sugerido": "valor sugerido",
      "justificativa": "por que"
    }}
  ],
  "ajustes_config": {{
    "quality": {{"min_score": numero_ou_null}},
    "risk": {{"entry_percent": numero_ou_null, "stop_loss_percent": numero_ou_null}},
    "mcp": {{"mode": "string_ou_null"}}
  }},
  "alertas": ["alerta 1", "alerta 2"]
}}
"""
        try:
            response = self.client.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json", "temperature": 0.2}
            )
            return response.text
        except Exception as e:
            logger.error(f"Erro ao chamar Gemini: {e}")
            return self._local_recommendations(diagnosis, current_config)

    def _local_recommendations(self, diagnosis: dict, config: dict) -> str:
        """Recomendações baseadas em regras quando Gemini não está disponível."""
        problems = []
        recs = []
        ajustes = {"quality": {}, "risk": {}, "mcp": {}}

        min_score = config.get("quality", {}).get("min_score", 60)
        mcp_rate = diagnosis.get("mcp_approval_rate", 0)
        res_block = diagnosis.get("resistance_block_rate", 0)
        vol_block = diagnosis.get("volume_block_rate", 0)
        total_orders = diagnosis.get("total_orders", 0)
        total_signals = diagnosis.get("total_signals", 0)

        if res_block > 40:
            problems.append({
                "prioridade": "ALTA", "problema": "Muitos sinais bloqueados por resistência próxima",
                "causa": f"{res_block:.0f}% dos sinais gerados perto de resistência",
                "impacto": "Bot perde oportunidades de breakout válidas"
            })
            recs.append({
                "tipo": "CONFIG", "descricao": "Aumentar threshold de S/R para 3%",
                "parametro": "NEAR_THRESHOLD em indicators.py",
                "valor_atual": "2.0%", "valor_sugerido": "3.0%",
                "justificativa": "Resistências próximas em cripto nem sempre bloqueiam"
            })

        if vol_block > 30:
            problems.append({
                "prioridade": "MEDIA", "problema": "Volume baixo bloqueando muitos sinais",
                "causa": f"{vol_block:.0f}% dos sinais com volume insuficiente",
                "impacto": "Sessão ASIAN naturalmente tem volume menor"
            })

        if mcp_rate < 20 and diagnosis.get("mcp_total", 0) > 5:
            problems.append({
                "prioridade": "ALTA", "problema": f"MCP aprovando apenas {mcp_rate:.0f}% dos sinais",
                "causa": "Critérios do MCP muito restritivos ou prompt desalinhado",
                "impacto": "Bot praticamente não executa ordens"
            })
            recs.append({
                "tipo": "CONFIG", "descricao": "Considerar modo mock para testes",
                "parametro": "mcp.mode", "valor_atual": "gemini", "valor_sugerido": "mock",
                "justificativa": "Validar se o problema é no MCP ou na estratégia"
            })

        if total_signals > 0 and total_orders == 0:
            problems.append({
                "prioridade": "ALTA", "problema": "Nenhuma ordem executada",
                "causa": "Pipeline completo bloqueando todos os sinais",
                "impacto": "Bot inativo mesmo com sinais"
            })

        resumo = (
            f"Bot analisou {diagnosis.get('cycles', 0)} ciclos. "
            f"Gerou {total_signals} sinais, {total_orders} ordens executadas. "
            f"MCP aprovou {mcp_rate:.0f}% dos sinais enviados."
        )

        return json.dumps({
            "resumo": resumo,
            "problemas": problems,
            "recomendacoes": recs,
            "ajustes_config": ajustes,
            "alertas": [f"Win rate: {diagnosis.get('win_rate', 0):.1f}%"] if diagnosis.get("total_closes") else []
        }, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 4. APLICADOR DE AJUSTES
# ---------------------------------------------------------------------------

class ConfigAdjuster:
    """Aplica ajustes no settings.yaml com base nas recomendações."""

    def apply(self, ajustes: dict, dry_run: bool = False) -> list:
        applied = []
        if not SETTINGS_FILE.exists():
            logger.error(f"settings.yaml não encontrado: {SETTINGS_FILE}")
            return applied

        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        for section, params in ajustes.items():
            if not isinstance(params, dict):
                continue
            for key, value in params.items():
                if value is None:
                    continue
                old = config.get(section, {}).get(key)
                if old == value:
                    continue
                if not dry_run:
                    config.setdefault(section, {})[key] = value
                applied.append(f"{section}.{key}: {old} → {value}")
                logger.info(f"{'[DRY RUN] ' if dry_run else ''}Ajuste: {section}.{key} = {old} → {value}")

        if applied and not dry_run:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
            logger.info(f"settings.yaml atualizado com {len(applied)} ajuste(s).")

            # Notificar o engine para recarregar config
            try:
                import requests
                requests.post("http://localhost:8502/control/reload-config", timeout=2)
                logger.info("Engine notificado para recarregar configuração.")
            except Exception:
                logger.warning("Não foi possível notificar o engine. Reinicie para aplicar.")

        return applied


# ---------------------------------------------------------------------------
# 5. RELATÓRIO
# ---------------------------------------------------------------------------

def save_report(diagnosis: dict, recommendations_json: str, applied: list):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = REPORT_DIR / f"analysis_{ts}.json"

    try:
        recs = json.loads(recommendations_json)
    except Exception:
        recs = {"raw": recommendations_json}

    report = {
        "timestamp": ts,
        "diagnosis": diagnosis,
        "recommendations": recs,
        "applied_adjustments": applied,
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"Relatório salvo: {report_file}")
    return report_file


def print_report(diagnosis: dict, recs_json: str, applied: list):
    sep = "=" * 65

    print(f"\n{sep}")
    print("  NOVOBOT TRADING - RELATORIO DO AGENTE ANALISADOR")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(sep)

    d = diagnosis
    print(f"\n[METRICAS GERAIS]")
    print(f"  Ciclos analisados : {d.get('cycles', 0)}")
    print(f"  Sinais gerados    : {d.get('total_signals', 0)}")
    print(f"  Bloq. por score   : {d.get('total_blocked_score', 0)}")
    print(f"  Bloq. por MCP     : {d.get('total_blocked_mcp', 0)}")
    print(f"  Ordens executadas : {d.get('total_orders', 0)}")
    print(f"  Trades fechados   : {d.get('total_closes', 0)}")
    print(f"  PnL total         : ${d.get('total_pnl', 0):.2f}")
    if d.get("total_closes"):
        print(f"  Win rate          : {d.get('win_rate', 0):.1f}%")
    print(f"  Taxa aprovc. MCP  : {d.get('mcp_approval_rate', 0):.1f}% ({d.get('mcp_total',0)} enviados)")
    print(f"  Bloq. resistencia : {d.get('resistance_block_rate', 0):.1f}% dos sinais")
    print(f"  Bloq. volume      : {d.get('volume_block_rate', 0):.1f}% dos sinais")

    sessions = d.get("top_sessions", [])
    if sessions:
        print(f"\n[SESSOES DOMINANTES]")
        for sess, count in sessions:
            print(f"  {sess}: {count} analises")

    scores = d.get("avg_scores", {})
    if scores:
        print(f"\n[SCORE MEDIO POR SIMBOLO]")
        for sym, sc in sorted(scores.items(), key=lambda x: -x[1])[:8]:
            bar = "#" * int(sc / 5)
            print(f"  {sym:15s} {sc:5.1f}  {bar}")

    blocked = d.get("most_blocked", [])
    if blocked:
        print(f"\n[MAIS BLOQUEADOS]")
        for sym, count in blocked:
            print(f"  {sym}: {count}x bloqueado")

    errors = d.get("error_counter", {})
    if errors:
        print(f"\n[ERROS RECORRENTES]")
        for msg, count in errors.items():
            print(f"  ({count}x) {msg}")

    try:
        recs = json.loads(recs_json)
    except Exception:
        recs = {}

    if recs.get("resumo"):
        print(f"\n[ANALISE DA IA]")
        print(f"  {recs['resumo']}")

    if recs.get("problemas"):
        print(f"\n[PROBLEMAS IDENTIFICADOS]")
        for p in recs["problemas"]:
            icon = "!!" if p.get("prioridade") == "ALTA" else "! " if p.get("prioridade") == "MEDIA" else "  "
            print(f"  {icon} [{p.get('prioridade','?')}] {p.get('problema','')}")
            print(f"     Causa: {p.get('causa','')}")

    if recs.get("recomendacoes"):
        print(f"\n[RECOMENDACOES]")
        for i, r in enumerate(recs["recomendacoes"], 1):
            print(f"  {i}. [{r.get('tipo','?')}] {r.get('descricao','')}")
            if r.get("parametro"):
                print(f"     {r.get('parametro')}: {r.get('valor_atual')} -> {r.get('valor_sugerido')}")
            print(f"     Por que: {r.get('justificativa','')}")

    if recs.get("alertas"):
        print(f"\n[ALERTAS]")
        for a in recs["alertas"]:
            print(f"  >> {a}")

    # Análise horária
    best_hours = d.get("best_hours", [])
    hourly_stats = d.get("hourly_stats", {})
    if hourly_stats:
        print(f"\n[MELHOR HORARIO PARA OPERAR (UTC)]")
        print(f"  {'Hora':>5} | {'Sinais':>6} | {'Score Med':>9} | {'MCP Aprov%':>10} | {'Ordens':>6} | Sessao")
        print(f"  {'-'*5}-+-{'-'*6}-+-{'-'*9}-+-{'-'*10}-+-{'-'*6}-+--------")
        # Sessões de referência por hora UTC
        SESSION_MAP = {
            **{h: "ASIAN   " for h in range(0, 8)},
            **{h: "LONDON  " for h in range(8, 13)},
            **{h: "OVERLAP " for h in range(13, 16)},
            **{h: "NEW_YORK" for h in range(16, 21)},
            **{h: "OFF_HRS " for h in range(21, 24)},
        }
        # Ordenar por sinais desc
        for stat in sorted(hourly_stats.values(), key=lambda x: (-x["signals"], -x["avg_score"])):
            h = stat["hour_utc"]
            marker = " <-- TOP" if stat in best_hours[:3] else ""
            sess = SESSION_MAP.get(h, "?")
            print(f"  {h:02d}:00 | {stat['signals']:>6} | {stat['avg_score']:>9.1f} | {stat['mcp_approval_rate']:>9.1f}% | {stat['orders']:>6} | {sess}{marker}")

    if applied:
        print(f"\n[AJUSTES APLICADOS]")
        for a in applied:
            print(f"  OK {a}")
    else:
        print(f"\n[AJUSTES] Nenhum ajuste automatico aplicado (use --apply para habilitar)")

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# 6. MAIN
# ---------------------------------------------------------------------------

def run_analysis(apply: bool = False):
    logger.info("Iniciando analise do log...")

    # Parsear log
    parser = LogParser()
    events = parser.parse_tail(lines=8000)

    # Analisar
    analyzer = BotAnalyzer()
    diagnosis = analyzer.analyze(events)

    # Carregar config atual
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            current_config = yaml.safe_load(f)
        # Remover credenciais do contexto enviado à IA
        safe_config = {k: v for k, v in current_config.items()
                       if k not in ("execution", "signals", "mcp") or k == "mcp"}
        if "mcp" in safe_config:
            safe_config["mcp"] = {k: v for k, v in safe_config["mcp"].items()
                                   if "key" not in k.lower()}
    except Exception:
        safe_config = {}
        current_config = {}

    # Obter recomendações da IA
    advisor = AIAdvisor()
    recs_json = advisor.get_recommendations(diagnosis, safe_config)

    # Aplicar ajustes se solicitado
    applied = []
    if apply:
        try:
            recs = json.loads(recs_json)
            ajustes = recs.get("ajustes_config", {})
            adjuster = ConfigAdjuster()
            applied = adjuster.apply(ajustes)
        except Exception as e:
            logger.error(f"Erro ao aplicar ajustes: {e}")

    # Exibir relatório
    print_report(diagnosis, recs_json, applied)

    # Salvar relatório
    save_report(diagnosis, recs_json, applied)

    return diagnosis, recs_json


def main():
    parser = argparse.ArgumentParser(description="Agente Analisador do NovoBotTrading")
    parser.add_argument("--apply", action="store_true",
                        help="Aplica ajustes automaticos no settings.yaml")
    parser.add_argument("--watch", action="store_true",
                        help="Modo continuo - re-analisa periodicamente")
    parser.add_argument("--interval", type=int, default=30,
                        help="Intervalo em minutos para modo --watch (padrao: 30)")
    args = parser.parse_args()

    if args.watch:
        logger.info(f"Modo WATCH ativado. Analisando a cada {args.interval} minutos.")
        while True:
            try:
                run_analysis(apply=args.apply)
                logger.info(f"Proxima analise em {args.interval} minutos...")
                time.sleep(args.interval * 60)
            except KeyboardInterrupt:
                logger.info("Agente encerrado.")
                break
            except Exception as e:
                logger.error(f"Erro na analise: {e}")
                time.sleep(60)
    else:
        run_analysis(apply=args.apply)


if __name__ == "__main__":
    main()
