"""Restaura um backup salvo anteriormente.

A ideia é simples: um backup é um dump de `show running-config` de uma
execução passada. Para restaurar, extraímos dele o hostname e as
VLANs/subinterfaces, montamos um `DesiredState`/`RouterDesiredState` como se
o usuário tivesse digitado aqueles valores no frontend, e mandamos pelo MESMO
fluxo de aplicação normal (`aplicar_configuracao`/`aplicar_configuracao_router`).

Isso dá o rollback "de graça" duas proteções que já existem no fluxo normal:
o backup do estado atual é feito automaticamente ANTES de restaurar (uma
segunda rede de segurança sobre a primeira), e a validação roda no final,
confirmando se a restauração realmente bateu com o que estava no backup.
"""

from __future__ import annotations

from pathlib import Path

from .backup import DIRETORIO_PADRAO
from .device import DeviceConfig
from .models import DesiredState, ValidationError
from .router_models import RouterDesiredState
from .router_runner import aplicar_configuracao_router
from .router_validator import parse_subinterfaces
from .runner import aplicar_configuracao
from .validator import parse_hostname, parse_vlans_from_running_config


def ler_backup(nome_arquivo: str, diretorio: Path | str | None = None) -> str:
    """Lê o conteúdo de um arquivo de backup pelo nome, dentro da pasta de
    backups — nunca por caminho arbitrário, para não permitir escapar do
    diretório (ex: `../../etc/passwd`)."""
    destino = Path(diretorio) if diretorio else DIRETORIO_PADRAO
    caminho = destino / Path(nome_arquivo).name  # .name descarta qualquer parte de diretório
    if not caminho.exists():
        raise ValidationError(f"Backup não encontrado: {nome_arquivo}")
    return caminho.read_text(encoding="utf-8")


def restaurar_switch(nome_arquivo: str, cfg: DeviceConfig, **kwargs) -> dict:
    conteudo = ler_backup(nome_arquivo)
    hostname = parse_hostname(conteudo)
    vlans = parse_vlans_from_running_config(conteudo)
    if not hostname:
        raise ValidationError(f"Não foi possível extrair o hostname do backup {nome_arquivo!r}.")
    if not vlans:
        raise ValidationError(f"Não foi possível extrair VLANs do backup {nome_arquivo!r}.")

    payload = {
        "hostname": hostname,
        "vlans": [{"id": vid, "name": nome} for vid, nome in vlans.items()],
    }
    desejado = DesiredState.from_payload(payload)
    resultado = aplicar_configuracao(desejado, cfg, **kwargs)
    resultado["restaurado_de"] = nome_arquivo
    return resultado


def restaurar_router(nome_arquivo: str, cfg: DeviceConfig, interface_fisica: str = "FastEthernet0/0", **kwargs) -> dict:
    conteudo = ler_backup(nome_arquivo)
    hostname = parse_hostname(conteudo)
    subs = parse_subinterfaces(conteudo, interface_fisica)
    subs_validas = {vid: dados for vid, dados in subs.items() if dados.get("ip")}
    if not hostname:
        raise ValidationError(f"Não foi possível extrair o hostname do backup {nome_arquivo!r}.")
    if not subs_validas:
        raise ValidationError(
            f"Não foi possível extrair subinterfaces com IP do backup {nome_arquivo!r} "
            f"(interface física considerada: {interface_fisica})."
        )

    payload = {
        "hostname": hostname,
        "interface_fisica": interface_fisica,
        "subinterfaces": [
            {
                "vlan_id": vid,
                "ip": dados["ip"],
                "mascara": dados["mascara"],
                "descricao": dados.get("descricao", ""),
            }
            for vid, dados in subs_validas.items()
        ],
    }
    desejado = RouterDesiredState.from_payload(payload)
    resultado = aplicar_configuracao_router(desejado, cfg, **kwargs)
    resultado["restaurado_de"] = nome_arquivo
    return resultado
