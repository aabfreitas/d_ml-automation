"""Estado desejado do roteador: hostname + subinterfaces 802.1Q (uma por VLAN).

O roteador não tem "VLAN com nome" como o switch — cada VLAN vira uma
subinterface roteada, com encapsulamento dot1Q e um IP que serve de gateway
para aquela VLAN. É a mesma ideia de "estado desejado" do models.py, adaptada
para a topologia L3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from .models import ValidationError
from .convencao import aviso_convencao_hostname, aviso_convencao_nome_vlan

SUBINTERFACE_ID_MIN, SUBINTERFACE_ID_MAX = 1, 4094
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _validar_ip(valor: str, rotulo: str) -> str:
    valor = (valor or "").strip()
    if not IP_RE.match(valor):
        raise ValidationError(f"{rotulo} inválido: {valor!r}.")
    partes = valor.split(".")
    if any(not 0 <= int(p) <= 255 for p in partes):
        raise ValidationError(f"{rotulo} fora da faixa 0-255: {valor!r}.")
    return valor


@dataclass
class Subinterface:
    vlan_id: int
    ip: str
    mascara: str = "255.255.255.0"
    descricao: str = ""

    @classmethod
    def from_input(cls, vlan_id, ip, mascara=None, descricao="") -> "Subinterface":
        try:
            vid = int(str(vlan_id).strip())
        except (TypeError, ValueError):
            raise ValidationError(f"ID de VLAN/subinterface inválido: {vlan_id!r}.")
        if not SUBINTERFACE_ID_MIN <= vid <= SUBINTERFACE_ID_MAX:
            raise ValidationError(
                f"ID {vid} fora da faixa permitida ({SUBINTERFACE_ID_MIN}-{SUBINTERFACE_ID_MAX})."
            )
        ip_validado = _validar_ip(ip, f"IP da subinterface {vid}")
        mascara_validada = _validar_ip(mascara or "255.255.255.0", f"Máscara da subinterface {vid}")
        return cls(vlan_id=vid, ip=ip_validado, mascara=mascara_validada, descricao=(descricao or "").strip())


@dataclass
class RouterDesiredState:
    hostname: str
    interface_fisica: str = "FastEthernet0/0"
    subinterfaces: list[Subinterface] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict) -> "RouterDesiredState":
        hostname = (payload.get("hostname") or "").strip()
        if not hostname:
            raise ValidationError("Informe o hostname do roteador.")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_\-]{0,62}$", hostname):
            raise ValidationError(
                "Hostname inválido. Use de 1 a 63 caracteres, começando por letra, "
                "sem acentos ou espaços."
            )

        interface_fisica = (payload.get("interface_fisica") or "FastEthernet0/0").strip()
        if not re.match(r"^[A-Za-z]+[A-Za-z0-9/]*\d$", interface_fisica):
            raise ValidationError(f"Nome de interface física inválido: {interface_fisica!r}.")

        entradas = payload.get("subinterfaces") or []
        if not entradas:
            raise ValidationError("Adicione pelo menos uma subinterface.")

        subs: list[Subinterface] = []
        vistos: set[int] = set()
        for item in entradas:
            sub = Subinterface.from_input(
                item.get("vlan_id"), item.get("ip"), item.get("mascara"), item.get("descricao", "")
            )
            if sub.vlan_id in vistos:
                raise ValidationError(f"A subinterface para a VLAN {sub.vlan_id} aparece mais de uma vez.")
            vistos.add(sub.vlan_id)
            subs.append(sub)

        subs.sort(key=lambda s: s.vlan_id)

        avisos = []
        aviso_nome = aviso_convencao_hostname(hostname)
        if aviso_nome:
            avisos.append(aviso_nome)

        for sub in subs:
            if not sub.descricao:
                avisos.append(
                    f"subinterface .{sub.vlan_id}: sem descrição — a convenção esperada é "
                    "VLAN_<algo> (ex: VLAN_DADOS, VLAN_VOZ). Isso não impede a aplicação, "
                    "é só um alerta de padronização."
                )
            else:
                aviso_nome_sub = aviso_convencao_nome_vlan(sub.descricao, sub.vlan_id, rotulo="subinterface")
                if aviso_nome_sub:
                    avisos.append(aviso_nome_sub)

        return cls(hostname=hostname, interface_fisica=interface_fisica, subinterfaces=subs, avisos=avisos)

    def to_config_lines(self) -> list[str]:
        """Gera os comandos na ordem em que serão enviados: hostname, interface
        física ativa, e uma subinterface 802.1Q por VLAN."""
        linhas = [
            f"hostname {self.hostname}",
            f"interface {self.interface_fisica}",
            " no shutdown",
            " exit",
        ]
        for sub in self.subinterfaces:
            nome_sub = f"{self.interface_fisica}.{sub.vlan_id}"
            linhas.append(f"interface {nome_sub}")
            linhas.append(f" encapsulation dot1Q {sub.vlan_id}")
            linhas.append(f" ip address {sub.ip} {sub.mascara}")
            if sub.descricao:
                linhas.append(f" description {sub.descricao}")
            linhas.append(" exit")
        return linhas

    def as_dict(self) -> dict:
        return asdict(self)
