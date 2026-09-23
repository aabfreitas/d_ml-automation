"""Checagem (não bloqueante) das convenções de nomenclatura usadas no
laboratório: hostname (CD-<site><nº opcional>-<TIPO><nº>) e nome de
VLAN/subinterface (VLAN_<algo>).

Isso é só um alerta informativo — nunca impede a aplicação da configuração,
porque nomes fora desse padrão (como o "SWITCH_AUTOMATIZADO" do enunciado do
desafio, ou uma VLAN chamada "isolada") continuam sendo valores válidos para
o IOS. Sirva-se deste alerta como um lembrete de padronização, não como uma
regra rígida.
"""

from __future__ import annotations

import re

CONVENCAO_HOSTNAME_RE = re.compile(r"^CD-[A-Z]{2,3}\d?-(CR|CSW|SW|RT|FW|RTR)\d{2,4}$")
CONVENCAO_VLAN_RE = re.compile(r"^VLAN_[A-Z0-9_]+$")


def aviso_convencao_hostname(hostname: str) -> str | None:
    """Retorna uma mensagem de aviso se o hostname não seguir a convenção
    CD-<site>-<TIPO><nº>, ou None se estiver conforme (ou vazio)."""
    if not hostname or CONVENCAO_HOSTNAME_RE.match(hostname):
        return None
    return (
        f"O hostname {hostname!r} não segue a convenção de nomenclatura "
        "CD-<site><nº>-<TIPO><nº> (ex: CD-SP1-SW001, CD-SP1-CSW001, CD-SP1-CR001). "
        "Isso não impede a aplicação, é só um alerta de padronização."
    )


def aviso_convencao_nome_vlan(nome: str, vlan_id: int | None = None, rotulo: str = "VLAN") -> str | None:
    """Retorna uma mensagem de aviso se o nome não seguir a convenção
    VLAN_<algo> (tudo maiúsculo, letras/números/underscore), ou None se
    estiver conforme (ou vazio).

    `rotulo` deixa a mensagem genérica o bastante para servir tanto para uma
    VLAN de switch quanto para a descrição de uma subinterface de roteador.
    """
    if not nome or CONVENCAO_VLAN_RE.match(nome):
        return None
    referencia = f"{rotulo} {vlan_id}" if vlan_id is not None else rotulo
    return (
        f"{referencia}: o nome {nome!r} não segue a convenção de nomenclatura "
        "VLAN_<algo> (ex: VLAN_DADOS, VLAN_VOZ, VLAN_SEGURANCA). Isso não "
        "impede a aplicação, é só um alerta de padronização."
    )

