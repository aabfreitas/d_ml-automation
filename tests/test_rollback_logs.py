"""Testes do rollback, da persistência do dispositivo simulado, da convenção
de nomenclatura e do log de execuções."""

import pytest

from src.convencao import aviso_convencao_hostname
from src.device import DeviceConfig, resetar_estado_simulado
from src.logs import listar_execucoes, registrar_execucao, resumo_para_log
from src.models import DesiredState, ValidationError
from src.rollback import ler_backup, restaurar_router, restaurar_switch
from src.router_models import RouterDesiredState
from src.router_runner import aplicar_configuracao_router
from src.runner import aplicar_configuracao


def cfg_simulado(host="lab-rollback"):
    return DeviceConfig(host=host, username="admin", password="x", simulate=True)


# --- convenção de nome -------------------------------------------------

def test_hostname_conforme_nao_gera_aviso():
    assert aviso_convencao_hostname("CD-SP1-SW001") is None
    assert aviso_convencao_hostname("CD-SP1-CSW001") is None
    assert aviso_convencao_hostname("CD-SP1-CR001") is None


def test_hostname_fora_da_convencao_gera_aviso():
    aviso = aviso_convencao_hostname("SWITCH_AUTOMATIZADO")
    assert aviso is not None
    assert "convenção" in aviso


def test_avisos_entrada_incluem_convencao_no_switch_e_no_router():
    desejado_switch = DesiredState.from_payload(
        {"hostname": "SWITCH_AUTOMATIZADO", "vlans": [{"id": 10, "name": "VLAN_DADOS"}]}
    )
    assert any("convenção" in a for a in desejado_switch.avisos)

    desejado_router = RouterDesiredState.from_payload(
        {"hostname": "ROTEADOR_X", "subinterfaces": [{"vlan_id": 10, "ip": "192.168.10.1"}]}
    )
    assert any("convenção" in a for a in desejado_router.avisos)


# --- persistência do simulado ----------------------------------------------

def test_estado_simulado_persiste_entre_chamadas_separadas():
    cfg = cfg_simulado("persist-teste")
    d1 = DesiredState.from_payload({"hostname": "CD-SP1-SW001", "vlans": [{"id": 10, "name": "VLAN_DADOS"}]})
    aplicar_configuracao(d1, cfg)

    # uma "nova chamada" (novo objeto de device por baixo) deve enxergar o que a primeira aplicou
    d2 = DesiredState.from_payload(
        {"hostname": "CD-SP1-SW001", "vlans": [{"id": 10, "name": "VLAN_DADOS"}, {"id": 20, "name": "VLAN_VOZ"}]}
    )
    r2 = aplicar_configuracao(d2, cfg)
    itens_ok = {a["item"] for a in r2["validacao"]["alertas"] if a["severidade"] == "ok"}
    assert "vlan 10" in itens_ok  # se não tivesse persistido, a vlan 10 nem apareceria como "já lá"


def test_resetar_estado_simulado_volta_a_fabrica():
    cfg = cfg_simulado("reset-teste")
    d1 = DesiredState.from_payload({"hostname": "CD-SP1-SW001", "vlans": [{"id": 10, "name": "VLAN_DADOS"}]})
    aplicar_configuracao(d1, cfg)

    apagou = resetar_estado_simulado(cfg.host, "switch")
    assert apagou is True

    d2 = DesiredState.from_payload({"hostname": "CD-SP1-SW001", "vlans": [{"id": 10, "name": "VLAN_DADOS"}]})
    r2 = aplicar_configuracao(d2, cfg)
    # depois do reset, o estado voltou à fábrica: só a vlan 99 legada deveria
    # já estar lá além da que acabamos de aplicar
    nomes_vlans = {a["item"] for a in r2["validacao"]["alertas"]}
    assert "vlan 99" in nomes_vlans


# --- rollback: switch --------------------------------------------------

def test_rollback_switch_reaplica_estado_do_backup_e_alerta_o_que_mudou_depois():
    cfg = cfg_simulado("rollback-switch")
    d1 = DesiredState.from_payload({"hostname": "CD-SP1-SW001", "vlans": [{"id": 10, "name": "VLAN_DADOS"}]})
    aplicar_configuracao(d1, cfg)

    d2 = DesiredState.from_payload(
        {"hostname": "CD-SP1-SW001", "vlans": [{"id": 10, "name": "VLAN_DADOS"}, {"id": 20, "name": "VLAN_VOZ"}]}
    )
    r2 = aplicar_configuracao(d2, cfg)
    backup_pre_r2 = r2["backup"].split("/")[-1]  # captura o estado só com a VLAN 10

    r3 = restaurar_switch(backup_pre_r2, cfg)
    assert r3["sucesso"] is True
    assert r3["restaurado_de"] == backup_pre_r2

    alertas = {a["item"]: a["severidade"] for a in r3["validacao"]["alertas"]}
    assert alertas["vlan 10"] == "ok"
    assert alertas["vlan 20"] == "aviso"  # sobrou da 2ª aplicação, não fazia parte do backup restaurado


def test_rollback_de_arquivo_inexistente_falha_com_clareza():
    cfg = cfg_simulado("rollback-inexistente")
    with pytest.raises(ValidationError):
        restaurar_switch("nao_existe_20260101-000000.cfg", cfg)


def test_ler_backup_ignora_caminho_com_travessia_de_diretorio(tmp_path):
    # nome_arquivo com "../" não deve escapar da pasta de backups
    with pytest.raises(ValidationError):
        ler_backup("../../etc/passwd", diretorio=tmp_path)


# --- rollback: router --------------------------------------------------

def test_rollback_router_reaplica_subinterfaces_do_backup():
    cfg = cfg_simulado("rollback-router")
    d1 = RouterDesiredState.from_payload(
        {"hostname": "CD-SP1-CR001", "subinterfaces": [{"vlan_id": 10, "ip": "192.168.10.1"}]}
    )
    aplicar_configuracao_router(d1, cfg)

    d2 = RouterDesiredState.from_payload(
        {
            "hostname": "CD-SP1-CR001",
            "subinterfaces": [
                {"vlan_id": 10, "ip": "192.168.10.1"},
                {"vlan_id": 20, "ip": "192.168.20.1"},
            ],
        }
    )
    r2 = aplicar_configuracao_router(d2, cfg)
    backup_pre_r2 = r2["backup"].split("/")[-1]

    r3 = restaurar_router(backup_pre_r2, cfg)
    assert r3["sucesso"] is True
    alertas = {a["item"]: a["severidade"] for a in r3["validacao"]["alertas"]}
    assert alertas["subinterface .10"] == "ok"
    assert alertas["subinterface .20"] == "aviso"


# --- log de execuções ----------------------------------------------------

def test_log_registra_e_lista_execucoes(tmp_path):
    caminho = tmp_path / "execucoes.jsonl"
    cfg = cfg_simulado("log-teste")
    d1 = DesiredState.from_payload({"hostname": "CD-SP1-SW001", "vlans": [{"id": 10, "name": "VLAN_DADOS"}]})
    r1 = aplicar_configuracao(d1, cfg)

    registrar_execucao(resumo_para_log(r1, "switch", cfg.host, d1.hostname, "aplicar"), caminho)
    registros = listar_execucoes(limite=10, caminho=caminho)

    assert len(registros) == 1
    assert registros[0]["acao"] == "aplicar"
    assert registros[0]["dispositivo"] == "switch"
    assert registros[0]["sucesso"] is True
    assert registros[0]["alertas"]["aviso"] >= 1  # a vlan 99 legada


def test_log_lida_com_linha_corrompida_sem_quebrar(tmp_path):
    caminho = tmp_path / "execucoes.jsonl"
    caminho.write_text('{"acao": "aplicar", "sucesso": true}\nlinha corrompida sem ser json\n', encoding="utf-8")
    registros = listar_execucoes(limite=10, caminho=caminho)
    assert len(registros) == 1
