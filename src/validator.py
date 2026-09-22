"""Leitura do estado real do switch e comparação com o estado desejado.

A validação responde a três perguntas, nesta ordem:

1. O hostname ficou igual ao pedido?
2. Todas as VLANs pedidas existem com o nome certo?
3. Existe alguma VLAN no switch que ninguém pediu? (configuração fora do padrão)

Cada divergência vira um alerta com severidade, exibido no frontend e na
saída do script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .models import DesiredState

# VLANs que o IOS cria sozinho e que nunca devem ser tratadas como divergência.
VLANS_DE_SISTEMA = {1, 1002, 1003, 1004, 1005}

SEVERIDADES = ("ok", "aviso", "erro")


@dataclass
class Alerta:
    severidade: str  # ok | aviso | erro
    item: str
    mensagem: str
    esperado: str = ""
    encontrado: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        marca = {"ok": "[OK]   ", "aviso": "[AVISO]", "erro": "[ERRO] "}[self.severidade]
        return f"{marca} {self.item}: {self.mensagem}"


@dataclass
class ResultadoValidacao:
    alertas: list[Alerta]
    hostname_atual: str
    vlans_atuais: dict[int, str]

    @property
    def conforme(self) -> bool:
        return not any(a.severidade == "erro" for a in self.alertas)

    @property
    def tem_fora_do_padrao(self) -> bool:
        return any(a.severidade == "aviso" for a in self.alertas)

    def as_dict(self) -> dict:
        return {
            "conforme": self.conforme,
            "tem_fora_do_padrao": self.tem_fora_do_padrao,
            "hostname_atual": self.hostname_atual,
            "vlans_atuais": {str(k): v for k, v in sorted(self.vlans_atuais.items())},
            "alertas": [a.as_dict() for a in self.alertas],
        }

    def resumo(self) -> str:
        if self.conforme and not self.tem_fora_do_padrao:
            return "Configuração conforme o padrão definido."
        if self.conforme:
            return "Configuração aplicada, mas há itens fora do padrão no switch."
        return "Divergências encontradas: a configuração não corresponde ao esperado."


def parse_vlan_brief(saida: str) -> dict[int, str]:
    """Extrai {id: nome} de `show vlan brief`.

    O formato é posicional, mas a largura da coluna varia entre plataformas,
    então a leitura é feita por tokens: primeiro campo numérico = ID,
    segundo = nome, e o terceiro precisa parecer um status.
    """
    vlans: dict[int, str] = {}
    for linha in saida.splitlines():
        if not linha.strip() or linha.lstrip().startswith(("VLAN", "----")):
            continue
        m = re.match(r"^\s*(\d{1,4})\s+(\S+)\s+(active|act/unsup|suspended|act/lshut)", linha)
        if m:
            vlans[int(m.group(1))] = m.group(2)
    return vlans


def parse_hostname(running_config: str) -> str:
    m = re.search(r"^hostname\s+(\S+)\s*$", running_config, re.MULTILINE)
    return m.group(1) if m else ""


def parse_vlans_from_running_config(running_config: str) -> dict[int, str]:
    """Extrai {id: nome} diretamente de um `show running-config`, a partir dos
    blocos `vlan <id>` / `name <nome>`. Usado pelo rollback, já que um backup
    é um dump de running-config, não de `show vlan brief`."""
    vlans: dict[int, str] = {}
    padrao_bloco = re.compile(r"^vlan (\d+)\s*\n((?:(?!^vlan |^!|^interface ).*\n?)*)", re.MULTILINE)
    for m in padrao_bloco.finditer(running_config):
        vlan_id = int(m.group(1))
        nome_m = re.search(r"name (\S+)", m.group(2))
        if nome_m:
            vlans[vlan_id] = nome_m.group(1)
    return vlans


def coletar_estado(switch) -> tuple[str, dict[int, str], str]:
    """Lê do switch o hostname, as VLANs e a running-config bruta."""
    running = switch.send_command("show running-config")
    vlan_brief = switch.send_command("show vlan brief")
    return parse_hostname(running), parse_vlan_brief(vlan_brief), running


def validar(desejado: DesiredState, hostname_atual: str, vlans_atuais: dict[int, str]) -> ResultadoValidacao:
    alertas: list[Alerta] = []

    # 1. Hostname
    if hostname_atual == desejado.hostname:
        alertas.append(
            Alerta("ok", "hostname", f"Hostname confirmado como '{hostname_atual}'.")
        )
    else:
        alertas.append(
            Alerta(
                "erro",
                "hostname",
                "O hostname no switch não corresponde ao solicitado.",
                esperado=desejado.hostname,
                encontrado=hostname_atual or "(não encontrado)",
            )
        )

    # 2. VLANs pedidas
    for vlan in desejado.vlans:
        nome_real = vlans_atuais.get(vlan.vlan_id)
        if nome_real is None:
            alertas.append(
                Alerta(
                    "erro",
                    f"vlan {vlan.vlan_id}",
                    "VLAN não existe no switch após a aplicação.",
                    esperado=vlan.name,
                    encontrado="(ausente)",
                )
            )
        elif nome_real != vlan.name:
            alertas.append(
                Alerta(
                    "erro",
                    f"vlan {vlan.vlan_id}",
                    "A VLAN existe, mas com outro nome.",
                    esperado=vlan.name,
                    encontrado=nome_real,
                )
            )
        else:
            alertas.append(
                Alerta("ok", f"vlan {vlan.vlan_id}", f"VLAN ativa com o nome '{nome_real}'.")
            )

    # 3. VLANs fora do padrão
    pedidas = {v.vlan_id for v in desejado.vlans}
    for vid in sorted(set(vlans_atuais) - pedidas - VLANS_DE_SISTEMA):
        alertas.append(
            Alerta(
                "aviso",
                f"vlan {vid}",
                "Configuração fora do padrão: VLAN presente no switch e ausente do "
                "padrão informado. Revise antes de remover.",
                esperado="(não prevista)",
                encontrado=vlans_atuais[vid],
            )
        )

    return ResultadoValidacao(alertas, hostname_atual, vlans_atuais)
