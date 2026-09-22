"""Testes do modelo, parsing e validação do roteador."""

import pytest

from src.device import DeviceConfig
from src.models import ValidationError
from src.router_models import RouterDesiredState
from src.router_runner import aplicar_configuracao_router
from src.router_validator import parse_subinterfaces, validar_router

PAYLOAD = {
    "hostname": "CD-SP1-CR001",
    "interface_fisica": "FastEthernet0/0",
    "subinterfaces": [
        {"vlan_id": 10, "ip": "192.168.10.1", "mascara": "255.255.255.0", "descricao": "VLAN_DADOS"},
        {"vlan_id": 20, "ip": "192.168.20.1", "mascara": "255.255.255.0", "descricao": "VLAN_VOZ"},
        {"vlan_id": 50, "ip": "192.168.50.1", "mascara": "255.255.255.0", "descricao": "VLAN_SEGURANCA"},
    ],
}

RUNNING_CONFIG_EXEMPLO = """\
hostname CD-SP1-CR001
!
interface FastEthernet0/0
 no ip address
!
interface FastEthernet0/0.10
 encapsulation dot1Q 10
 ip address 192.168.10.1 255.255.255.0
!
interface FastEthernet0/0.20
 encapsulation dot1Q 20
 ip address 192.168.20.1 255.255.255.0
!
interface FastEthernet1/0
 no ip address
!
end
"""


def cfg_simulado():
    return DeviceConfig(host="lab", username="admin", password="x", simulate=True)


# --- validação de entrada ---------------------------------------------------

def test_ip_invalido_e_recusado():
    payload = dict(PAYLOAD, subinterfaces=[{"vlan_id": 10, "ip": "999.1.1.1"}])
    with pytest.raises(ValidationError):
        RouterDesiredState.from_payload(payload)


def test_subinterface_duplicada_e_recusada():
    payload = dict(
        PAYLOAD,
        subinterfaces=[
            {"vlan_id": 10, "ip": "192.168.10.1"},
            {"vlan_id": 10, "ip": "192.168.10.2"},
        ],
    )
    with pytest.raises(ValidationError):
        RouterDesiredState.from_payload(payload)


def test_comandos_gerados_incluem_encapsulamento_e_ip():
    linhas = RouterDesiredState.from_payload(PAYLOAD).to_config_lines()
    assert "interface FastEthernet0/0.10" in linhas
    assert " encapsulation dot1Q 10" in linhas
    assert " ip address 192.168.10.1 255.255.255.0" in linhas


# --- parsing ------------------------------------------------------------

def test_parse_subinterfaces_le_ip_e_ignora_interface_sem_endereco():
    subs = parse_subinterfaces(RUNNING_CONFIG_EXEMPLO, "FastEthernet0/0")
    assert subs[10] == {"ip": "192.168.10.1", "mascara": "255.255.255.0", "descricao": ""}
    assert subs[20]["ip"] == "192.168.20.1"
    assert 0 not in subs  # a interface física em si não é uma subinterface


# --- validação ------------------------------------------------------------

def test_validacao_detecta_ausencia_e_divergencia():
    desejado = RouterDesiredState.from_payload(PAYLOAD)
    subs_atuais = {
        10: {"ip": "192.168.10.1", "mascara": "255.255.255.0", "descricao": ""},  # ok
        20: {"ip": "10.0.0.1", "mascara": "255.255.255.0", "descricao": ""},  # divergente
        # 50 ausente
    }
    resultado = validar_router(desejado, "CD-SP1-CR001", subs_atuais)
    assert resultado.conforme is False
    itens_erro = {a.item for a in resultado.alertas if a.severidade == "erro"}
    assert itens_erro == {"subinterface .20", "subinterface .50"}


# --- fluxo completo ---------------------------------------------------------

def test_fluxo_completo_no_roteador_simulado():
    desejado = RouterDesiredState.from_payload(PAYLOAD)
    res = aplicar_configuracao_router(desejado, cfg_simulado())

    assert res["sucesso"] is True
    assert res["backup"]
    validacao = res["validacao"]
    assert validacao["hostname_atual"] == "CD-SP1-CR001"
    # a subinterface .99 do simulador não está no padrão -> deve virar aviso
    avisos = [a for a in validacao["alertas"] if a["severidade"] == "aviso"]
    assert any("99" in a["item"] for a in avisos)
