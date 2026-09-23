"""Estruturas de dados do estado desejado e normalização de nomes de VLAN."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict

from .convencao import aviso_convencao_hostname, aviso_convencao_nome_vlan

# IOS aceita 1..32 caracteres em nomes de VLAN, sem espaços e sem acentos.
VLAN_NAME_MAX = 32
VLAN_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")
VLAN_ID_MIN, VLAN_ID_MAX = 1, 4094
RESERVED_VLAN_IDS = range(1002, 1006)  # 1002-1005 são reservadas pelo IOS


class ValidationError(ValueError):
    """Entrada inválida vinda do frontend."""


def normalize_vlan_name(raw: str) -> tuple[str, str | None]:
    """Converte um nome digitado pelo usuário em um nome aceito pelo IOS.

    Retorna (nome_normalizado, aviso). O aviso é preenchido quando o nome
    precisou ser alterado — o caso mais comum é "VLAN_SEGURANÇA", que o
    desafio pede mas que o IOS não aceita por causa do cedilha.
    """
    original = (raw or "").strip()
    if not original:
        raise ValidationError("O nome da VLAN não pode ficar vazio.")

    # NFKD separa o caractere base do acento; o encode descarta os acentos.
    sem_acento = (
        unicodedata.normalize("NFKD", original)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    limpo = re.sub(r"\s+", "_", sem_acento)
    limpo = re.sub(r"[^A-Za-z0-9_\-]", "", limpo)[:VLAN_NAME_MAX]

    if not limpo:
        raise ValidationError(
            f"O nome {original!r} não possui caracteres válidos para o IOS."
        )

    aviso = None
    if limpo != original:
        aviso = (
            f"O nome {original!r} foi normalizado para {limpo!r}: o Cisco IOS "
            "aceita apenas letras sem acento, números, '_' e '-'."
        )
    return limpo, aviso


@dataclass
class Vlan:
    vlan_id: int
    name: str
    aviso: str | None = None

    @classmethod
    def from_input(cls, vlan_id, name: str) -> "Vlan":
        try:
            vid = int(str(vlan_id).strip())
        except (TypeError, ValueError):
            raise ValidationError(f"ID de VLAN inválido: {vlan_id!r}.")
        if not VLAN_ID_MIN <= vid <= VLAN_ID_MAX:
            raise ValidationError(
                f"ID {vid} fora da faixa permitida ({VLAN_ID_MIN}-{VLAN_ID_MAX})."
            )
        if vid in RESERVED_VLAN_IDS:
            raise ValidationError(f"A VLAN {vid} é reservada pelo IOS e não pode ser criada.")
        nome, aviso = normalize_vlan_name(name)
        return cls(vlan_id=vid, name=nome, aviso=aviso)


@dataclass
class DesiredState:
    """O que o usuário pediu no frontend: hostname + lista de VLANs."""

    hostname: str
    vlans: list[Vlan] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: dict) -> "DesiredState":
        hostname = (payload.get("hostname") or "").strip()
        if not hostname:
            raise ValidationError("Informe o hostname do switch.")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_\-]{0,62}$", hostname):
            raise ValidationError(
                "Hostname inválido. Use de 1 a 63 caracteres, começando por letra, "
                "sem acentos ou espaços."
            )

        entradas = payload.get("vlans") or []
        if not entradas:
            raise ValidationError("Adicione pelo menos uma VLAN.")

        vlans, avisos, vistos = [], [], set()
        for item in entradas:
            vlan = Vlan.from_input(item.get("id"), item.get("name", ""))
            if vlan.vlan_id in vistos:
                raise ValidationError(f"A VLAN {vlan.vlan_id} aparece mais de uma vez.")
            vistos.add(vlan.vlan_id)
            if vlan.aviso:
                avisos.append(vlan.aviso)
            aviso_nome_vlan = aviso_convencao_nome_vlan(vlan.name, vlan.vlan_id, rotulo="VLAN")
            if aviso_nome_vlan:
                avisos.append(aviso_nome_vlan)
            vlans.append(vlan)

        vlans.sort(key=lambda v: v.vlan_id)

        aviso_nome = aviso_convencao_hostname(hostname)
        if aviso_nome:
            avisos.append(aviso_nome)

        return cls(hostname=hostname, vlans=vlans, avisos=avisos)

    def to_config_lines(self) -> list[str]:
        """Gera os comandos de configuração na ordem em que serão enviados."""
        linhas = [f"hostname {self.hostname}"]
        for vlan in self.vlans:
            linhas += [f"vlan {vlan.vlan_id}", f" name {vlan.name}", " exit"]
        return linhas

    def as_dict(self) -> dict:
        return asdict(self)
