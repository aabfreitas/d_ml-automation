"""Backup da running-config em arquivo local.

Nome do arquivo: <hostname>_<AAAAMMDD-HHMMSS>.cfg — pedido do desafio e
também o que torna o diretório de backups legível em ordem alfabética.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

DIRETORIO_PADRAO = Path(__file__).resolve().parent.parent / "backups"


def _slug(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", texto or "switch")[:40]


def salvar_backup(conteudo: str, hostname: str, diretorio: Path | str | None = None) -> Path:
    destino = Path(diretorio) if diretorio else DIRETORIO_PADRAO
    destino.mkdir(parents=True, exist_ok=True)

    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    caminho = destino / f"{_slug(hostname)}_{carimbo}.cfg"

    cabecalho = (
        f"! Backup gerado em {datetime.now():%d/%m/%Y %H:%M:%S}\n"
        f"! Dispositivo: {hostname}\n"
        f"! Origem: show running-config\n!\n"
    )
    caminho.write_text(cabecalho + conteudo + "\n", encoding="utf-8")
    log.info("Backup salvo em %s", caminho)
    return caminho


def listar_backups(diretorio: Path | str | None = None) -> list[dict]:
    destino = Path(diretorio) if diretorio else DIRETORIO_PADRAO
    if not destino.exists():
        return []
    arquivos = sorted(destino.glob("*.cfg"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "nome": p.name,
            "tamanho_bytes": p.stat().st_size,
            "modificado_em": datetime.fromtimestamp(p.stat().st_mtime).strftime(
                "%d/%m/%Y %H:%M:%S"
            ),
        }
        for p in arquivos
    ]
