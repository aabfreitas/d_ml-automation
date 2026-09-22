"""Log persistente de execuções, para servir de trilha de auditoria e evidência.

Cada linha do arquivo é um registro JSON de uma execução (aplicar, validar ou
restaurar). É intencionalmente simples (JSON Lines) para poder ser lido,
filtrado ou até versionado no Git sem ferramentas extras — cada linha é
independente, então um `tail -f` ou um `git diff` continuam legíveis.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "logs" / "execucoes.jsonl"


def registrar_execucao(registro: dict, caminho: Path | str | None = None) -> Path:
    destino = Path(caminho) if caminho else CAMINHO_PADRAO
    destino.parent.mkdir(parents=True, exist_ok=True)

    linha = dict(registro)
    linha.setdefault("timestamp", datetime.now().strftime("%d/%m/%Y %H:%M:%S"))

    with destino.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return destino


def listar_execucoes(limite: int = 50, caminho: Path | str | None = None) -> list[dict]:
    """Devolve as últimas `limite` execuções, mais recente primeiro."""
    destino = Path(caminho) if caminho else CAMINHO_PADRAO
    if not destino.exists():
        return []

    linhas = destino.read_text(encoding="utf-8").splitlines()
    registros = []
    for linha in linhas[-limite:]:
        linha = linha.strip()
        if not linha:
            continue
        try:
            registros.append(json.loads(linha))
        except json.JSONDecodeError:
            continue  # uma linha corrompida não derruba a listagem inteira
    registros.reverse()
    return registros


def resumo_para_log(resultado: dict, dispositivo: str, host: str, hostname_desejado: str, acao: str) -> dict:
    """Monta o registro de log a partir do dict retornado por um runner
    (aplicar/validar/restaurar), sem expor a saída bruta do switch inteira —
    só o essencial para auditoria."""
    validacao = resultado.get("validacao") or {}
    alertas = validacao.get("alertas", [])
    contagem = {"ok": 0, "aviso": 0, "erro": 0}
    for a in alertas:
        contagem[a.get("severidade", "ok")] = contagem.get(a.get("severidade", "ok"), 0) + 1

    if validacao.get("conforme") is False:
        resumo = "divergências encontradas"
    elif validacao.get("tem_fora_do_padrao"):
        resumo = "conforme, com itens fora do padrão"
    elif validacao:
        resumo = "conforme"
    else:
        resumo = None

    return {
        "acao": acao,  # aplicar | validar | restaurar
        "dispositivo": dispositivo,  # switch | router
        "host": host,
        "hostname_desejado": hostname_desejado,
        "modo": resultado.get("modo"),
        "sucesso": resultado.get("sucesso"),
        "erro": resultado.get("erro"),
        "backup": resultado.get("backup"),
        "restaurado_de": resultado.get("restaurado_de"),
        "alertas": contagem,
        "resumo": resumo,
    }
