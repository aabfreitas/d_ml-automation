"""Testes do parsing, da normalização de nomes e da validação."""

import pytest

from src.device import DeviceConfig, SimulatedSwitch
from src.models import DesiredState, ValidationError, normalize_vlan_name
from src.runner import aplicar_configuracao
from src.validator import parse_hostname, parse_vlan_brief, validar

PAYLOAD = {
    "hostname": "SWITCH_AUTOMATIZADO",
    "vlans": [
        {"id": 10, "name": "VLAN_DADOS"},
        {"id": 20, "name": "VLAN_VOZ"},
        {"id": 50, "name": "VLAN_SEGURANÇA"},
    ],
}


def cfg_simulado():
    return DeviceConfig(host="lab", username="admin", password="x", simulate=True)


# --- normalização -----------------------------------------------------------

def test_cedilha_vira_nome_valido_para_o_ios():
    nome, aviso = normalize_vlan_name("VLAN_SEGURANÇA")
    assert nome == "VLAN_SEGURANCA"
    assert aviso is not None


def test_nome_valido_passa_sem_aviso():
    nome, aviso = normalize_vlan_name("VLAN_DADOS")
    assert (nome, aviso) == ("VLAN_DADOS", None)


def test_espacos_viram_underscore():
    assert normalize_vlan_name("rede de voz")[0] == "rede_de_voz"


# --- validação de entrada ---------------------------------------------------

@pytest.mark.parametrize("vid", [0, 4095, 1002])
def test_ids_invalidos_sao_recusados(vid):
    with pytest.raises(ValidationError):
        DesiredState.from_payload({"hostname": "SW1", "vlans": [{"id": vid, "name": "X"}]})


def test_vlan_duplicada_e_recusada():
    with pytest.raises(ValidationError):
        DesiredState.from_payload(
            {"hostname": "SW1", "vlans": [{"id": 10, "name": "A"}, {"id": 10, "name": "B"}]}
        )


def test_hostname_com_acento_e_recusado():
    with pytest.raises(ValidationError):
        DesiredState.from_payload({"hostname": "SWÍTCH", "vlans": [{"id": 10, "name": "A"}]})


def test_comandos_gerados_na_ordem_certa():
    linhas = DesiredState.from_payload(PAYLOAD).to_config_lines()
    assert linhas[0] == "hostname SWITCH_AUTOMATIZADO"
    assert "vlan 10" in linhas and " name VLAN_SEGURANCA" in linhas


# --- parsing ----------------------------------------------------------------

def test_parse_vlan_brief_ignora_cabecalho_e_reservadas_ficam_visiveis():
    saida = SimulatedSwitch(cfg_simulado()).connect().send_command("show vlan brief")
    vlans = parse_vlan_brief(saida)
    assert vlans[1] == "default"
    assert 1002 in vlans


def test_parse_hostname():
    assert parse_hostname("!\nhostname SW-CORE-01\n!\n") == "SW-CORE-01"


# --- fluxo completo ---------------------------------------------------------

def test_fluxo_completo_fica_conforme_e_alerta_a_vlan_legado():
    desejado = DesiredState.from_payload(PAYLOAD)
    res = aplicar_configuracao(desejado, cfg_simulado())

    assert res["sucesso"] is True
    assert res["backup"]  # backup do estado anterior foi gerado
    validacao = res["validacao"]
    assert validacao["hostname_atual"] == "SWITCH_AUTOMATIZADO"
    # a VLAN 99 do simulador não está no padrão -> deve virar aviso
    avisos = [a for a in validacao["alertas"] if a["severidade"] == "aviso"]
    assert any("99" in a["item"] for a in avisos)


def test_divergencia_gera_erro():
    desejado = DesiredState.from_payload(PAYLOAD)
    # o switch tem só a VLAN 10, com outro nome
    resultado = validar(desejado, "OUTRO_NOME", {1: "default", 10: "DADOS"})
    assert resultado.conforme is False
    # hostname errado + vlan 10 com nome errado + vlans 20 e 50 ausentes
    itens_com_erro = {a.item for a in resultado.alertas if a.severidade == "erro"}
    assert itens_com_erro == {"hostname", "vlan 10", "vlan 20", "vlan 50"}


def test_nvram_e_gravada():
    switch = SimulatedSwitch(cfg_simulado()).connect()
    switch.send_config(["hostname TESTE"])
    assert switch.saved is False
    switch.save_config()
    assert switch.saved is True
