"""Leitura das subinterfaces do roteador e comparação com o estado desejado.

Espelha o validator.py do switch: mesma ideia de severidades (ok/aviso/erro),
mesmo formato de Alerta — só a fonte dos dados muda (subinterfaces 802.1Q em
vez de VLAN database).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .router_models import RouterDesiredState
from .validator import Alerta, parse_hostname


def parse_subinterfaces(running_config: str, interface_fisica: str) -> dict[int, dict]:
    """Extrai {vlan_id: {"ip", "mascara", "descricao"}} das subinterfaces de
    uma interface física, a partir de um `show running-config`."""
    resultado: dict[int, dict] = {}
    prefixo = re.escape(interface_fisica)
    padrao_bloco = re.compile(
        rf"^interface {prefixo}\.(\d+)\s*\n((?:(?!^interface |^!).*\n?)*)",
        re.MULTILINE,
    )
    for m in padrao_bloco.finditer(running_config):
        vlan_id = int(m.group(1))
        bloco = m.group(2)
        ip_m = re.search(r"ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)", bloco)
        desc_m = re.search(r"description (.+)", bloco)
        resultado[vlan_id] = {
            "ip": ip_m.group(1) if ip_m else None,
            "mascara": ip_m.group(2) if ip_m else None,
            "descricao": desc_m.group(1).strip() if desc_m else "",
        }
    return resultado


@dataclass
class ResultadoValidacaoRouter:
    alertas: list[Alerta]
    hostname_atual: str
    subinterfaces_atuais: dict[int, dict]

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
            "subinterfaces_atuais": {str(k): v for k, v in sorted(self.subinterfaces_atuais.items())},
            "alertas": [a.as_dict() for a in self.alertas],
        }

    def resumo(self) -> str:
        if self.conforme and not self.tem_fora_do_padrao:
            return "Configuração do roteador conforme o padrão definido."
        if self.conforme:
            return "Configuração aplicada, mas há subinterfaces fora do padrão no roteador."
        return "Divergências encontradas no roteador: a configuração não corresponde ao esperado."


def coletar_estado_router(router, interface_fisica: str) -> tuple[str, dict[int, dict], str]:
    running = router.send_command("show running-config")
    return parse_hostname(running), parse_subinterfaces(running, interface_fisica), running


def validar_router(
    desejado: RouterDesiredState, hostname_atual: str, subs_atuais: dict[int, dict]
) -> ResultadoValidacaoRouter:
    alertas: list[Alerta] = []

    if hostname_atual == desejado.hostname:
        alertas.append(Alerta("ok", "hostname", f"Hostname confirmado como '{hostname_atual}'."))
    else:
        alertas.append(
            Alerta(
                "erro",
                "hostname",
                "O hostname no roteador não corresponde ao solicitado.",
                esperado=desejado.hostname,
                encontrado=hostname_atual or "(não encontrado)",
            )
        )

    for sub in desejado.subinterfaces:
        item = f"subinterface .{sub.vlan_id}"
        atual = subs_atuais.get(sub.vlan_id)
        esperado = f"{sub.ip} {sub.mascara}"

        if atual is None:
            alertas.append(
                Alerta("erro", item, "Subinterface não existe no roteador.", esperado=esperado, encontrado="(ausente)")
            )
        elif atual.get("ip") is None:
            alertas.append(
                Alerta(
                    "erro", item, "Subinterface existe, mas sem IP configurado.",
                    esperado=esperado, encontrado="(sem IP)",
                )
            )
        elif atual["ip"] != sub.ip or atual["mascara"] != sub.mascara:
            alertas.append(
                Alerta(
                    "erro", item, "IP/máscara da subinterface divergem do esperado.",
                    esperado=esperado, encontrado=f"{atual['ip']} {atual['mascara']}",
                )
            )
        else:
            alertas.append(Alerta("ok", item, f"IP confirmado como {atual['ip']}/{atual['mascara']}."))

    pedidas = {s.vlan_id for s in desejado.subinterfaces}
    for vid in sorted(set(subs_atuais) - pedidas):
        dados = subs_atuais[vid]
        alertas.append(
            Alerta(
                "aviso",
                f"subinterface .{vid}",
                "Configuração fora do padrão: subinterface presente no roteador e ausente "
                "do padrão informado. Revise antes de remover.",
                esperado="(não prevista)",
                encontrado=f"{dados.get('ip') or '(sem IP)'} {dados.get('mascara') or ''}".strip(),
            )
        )

    return ResultadoValidacaoRouter(alertas, hostname_atual, subs_atuais)
