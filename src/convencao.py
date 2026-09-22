"""Checagem (não bloqueante) da convenção de nomenclatura de hostname usada no
laboratório: CD-<site><nº opcional>-<TIPO><nº>, por exemplo CD-SP1-SW001,
CD-SP1-CSW001, CD-SP1-CR001.

Isso é só um alerta informativo — nunca impede a aplicação da configuração,
porque nomes fora desse padrão (como o "SWITCH_AUTOMATIZADO" do enunciado do
desafio) continuam sendo hostnames válidos para o IOS. Sirva-se deste alerta
como um lembrete de padronização, não como uma regra rígida.
"""

from __future__ import annotations

import re

CONVENCAO_RE = re.compile(r"^CD-[A-Z]{2,3}\d?-(CR|CSW|SW|RT|FW|RTR)\d{2,4}$")


def aviso_convencao_hostname(hostname: str) -> str | None:
    """Retorna uma mensagem de aviso se o hostname não seguir a convenção
    CD-<site>-<TIPO><nº>, ou None se estiver conforme (ou vazio)."""
    if not hostname or CONVENCAO_RE.match(hostname):
        return None
    return (
        f"O hostname {hostname!r} não segue a convenção de nomenclatura "
        "CD-<site><nº>-<TIPO><nº> (ex: CD-SP1-SW001, CD-SP1-CSW001, CD-SP1-CR001). "
        "Isso não impede a aplicação, é só um alerta de padronização."
    )
