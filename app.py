"""Frontend web da automação de switch Cisco.

Executar:  python app.py       ->  http://127.0.0.1:5000
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from src.backup import DIRETORIO_PADRAO, listar_backups
from src.device import DeviceConfig
from src.logs import listar_execucoes, registrar_execucao, resumo_para_log
from src.models import DesiredState, ValidationError
from src.rollback import restaurar_router, restaurar_switch
from src.router_models import RouterDesiredState
from src.router_runner import aplicar_configuracao_router, apenas_validar_router
from src.runner import aplicar_configuracao, apenas_validar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

app = Flask(__name__)

# VLANs exigidas pelo desafio, pré-carregadas no formulário.
VLANS_PADRAO = [
    {"id": 10, "name": "VLAN_DADOS"},
    {"id": 20, "name": "VLAN_VOZ"},
    {"id": 50, "name": "VLAN_SEGURANÇA"},
]

PADROES_CONEXAO = {
    "host": os.getenv("SWITCH_HOST", "192.168.10.2"),
    "username": os.getenv("SWITCH_USER", "admin"),
    "port": int(os.getenv("SWITCH_PORT", "22")),
    "hostname": os.getenv("SWITCH_HOSTNAME", "SWITCH_AUTOMATIZADO"),
    "simulate": os.getenv("SWITCH_SIMULATE", "1") == "1",
}

# Subinterfaces exigidas pelo roteador, uma por VLAN do desafio.
SUBINTERFACES_PADRAO = [
    {"vlan_id": 10, "ip": "192.168.10.1", "mascara": "255.255.255.0", "descricao": "VLAN_DADOS"},
    {"vlan_id": 20, "ip": "192.168.20.1", "mascara": "255.255.255.0", "descricao": "VLAN_VOZ"},
    {"vlan_id": 50, "ip": "192.168.50.1", "mascara": "255.255.255.0", "descricao": "VLAN_SEGURANCA"},
]

PADROES_CONEXAO_ROTEADOR = {
    "host": os.getenv("ROUTER_HOST", "192.168.113.10"),
    "username": os.getenv("ROUTER_USER", "admin"),
    "port": int(os.getenv("ROUTER_PORT", "22")),
    "hostname": os.getenv("ROUTER_HOSTNAME", "CD-SP1-CR001"),
    "interface_fisica": os.getenv("ROUTER_INTERFACE", "FastEthernet0/0"),
    "simulate": os.getenv("ROUTER_SIMULATE", "1") == "1",
}


def _device_config(payload: dict) -> DeviceConfig:
    conexao = payload.get("conexao") or {}
    host = (conexao.get("host") or "").strip()
    simulate = bool(conexao.get("simulate"))
    if not simulate and not host:
        raise ValidationError("Informe o IP do switch ou ative o modo simulado.")
    transporte = (conexao.get("transporte") or "ssh").strip().lower()
    if transporte not in ("ssh", "telnet"):
        raise ValidationError(f"Transporte inválido: {transporte!r}. Use 'ssh' ou 'telnet'.")
    porta_informada = conexao.get("port")
    porta = int(porta_informada) if porta_informada else (23 if transporte == "telnet" else 22)
    return DeviceConfig(
        host=host or "simulado",
        username=(conexao.get("username") or "").strip(),
        password=conexao.get("password") or "",
        secret=conexao.get("secret") or "",
        port=porta,
        transporte=transporte,
        simulate=simulate,
    )


@app.get("/")
def index():
    return render_template(
        "index.html",
        vlans_padrao=VLANS_PADRAO,
        padroes=PADROES_CONEXAO,
        subinterfaces_padrao=SUBINTERFACES_PADRAO,
        padroes_roteador=PADROES_CONEXAO_ROTEADOR,
    )


@app.post("/api/aplicar")
def api_aplicar():
    payload = request.get_json(silent=True) or {}
    try:
        desejado = DesiredState.from_payload(payload)
        cfg = _device_config(payload)
    except ValidationError as exc:
        return jsonify({"sucesso": False, "erro": str(exc)}), 400

    resultado = aplicar_configuracao(
        desejado,
        cfg,
        fazer_backup=payload.get("fazer_backup", True),
        salvar_nvram=payload.get("salvar_nvram", True),
    )
    registrar_execucao(resumo_para_log(resultado, "switch", cfg.host, desejado.hostname, "aplicar"))
    return jsonify(resultado)


@app.post("/api/validar")
def api_validar():
    payload = request.get_json(silent=True) or {}
    try:
        desejado = DesiredState.from_payload(payload)
        cfg = _device_config(payload)
    except ValidationError as exc:
        return jsonify({"sucesso": False, "erro": str(exc)}), 400
    resultado = apenas_validar(desejado, cfg)
    resultado["avisos_entrada"] = desejado.avisos
    registrar_execucao(resumo_para_log(resultado, "switch", cfg.host, desejado.hostname, "validar"))
    return jsonify(resultado)


@app.post("/api/previa")
def api_previa():
    """Mostra os comandos que serão enviados, sem tocar no switch."""
    payload = request.get_json(silent=True) or {}
    try:
        desejado = DesiredState.from_payload(payload)
    except ValidationError as exc:
        return jsonify({"sucesso": False, "erro": str(exc)}), 400
    return jsonify(
        {
            "sucesso": True,
            "comandos": desejado.to_config_lines(),
            "avisos_entrada": desejado.avisos,
        }
    )


@app.post("/api/aplicar-roteador")
def api_aplicar_roteador():
    payload = request.get_json(silent=True) or {}
    try:
        desejado = RouterDesiredState.from_payload(payload)
        cfg = _device_config(payload)
    except ValidationError as exc:
        return jsonify({"sucesso": False, "erro": str(exc)}), 400

    resultado = aplicar_configuracao_router(
        desejado,
        cfg,
        fazer_backup=payload.get("fazer_backup", True),
        salvar_nvram=payload.get("salvar_nvram", True),
    )
    resultado["avisos_entrada"] = desejado.avisos
    registrar_execucao(resumo_para_log(resultado, "router", cfg.host, desejado.hostname, "aplicar"))
    return jsonify(resultado)


@app.post("/api/validar-roteador")
def api_validar_roteador():
    payload = request.get_json(silent=True) or {}
    try:
        desejado = RouterDesiredState.from_payload(payload)
        cfg = _device_config(payload)
    except ValidationError as exc:
        return jsonify({"sucesso": False, "erro": str(exc)}), 400
    resultado = apenas_validar_router(desejado, cfg)
    resultado["avisos_entrada"] = desejado.avisos
    registrar_execucao(resumo_para_log(resultado, "router", cfg.host, desejado.hostname, "validar"))
    return jsonify(resultado)


@app.post("/api/previa-roteador")
def api_previa_roteador():
    payload = request.get_json(silent=True) or {}
    try:
        desejado = RouterDesiredState.from_payload(payload)
    except ValidationError as exc:
        return jsonify({"sucesso": False, "erro": str(exc)}), 400
    return jsonify({"sucesso": True, "comandos": desejado.to_config_lines(), "avisos_entrada": desejado.avisos})


@app.post("/api/restaurar")
def api_restaurar():
    payload = request.get_json(silent=True) or {}
    arquivo = (payload.get("arquivo") or "").strip()
    if not arquivo:
        return jsonify({"sucesso": False, "erro": "Informe o arquivo de backup a restaurar."}), 400
    try:
        cfg = _device_config(payload)
        resultado = restaurar_switch(
            arquivo,
            cfg,
            fazer_backup=payload.get("fazer_backup", True),
            salvar_nvram=payload.get("salvar_nvram", True),
        )
    except ValidationError as exc:
        return jsonify({"sucesso": False, "erro": str(exc)}), 400
    registrar_execucao(resumo_para_log(resultado, "switch", cfg.host, f"(restaurado de {arquivo})", "restaurar"))
    return jsonify(resultado)


@app.post("/api/restaurar-roteador")
def api_restaurar_roteador():
    payload = request.get_json(silent=True) or {}
    arquivo = (payload.get("arquivo") or "").strip()
    if not arquivo:
        return jsonify({"sucesso": False, "erro": "Informe o arquivo de backup a restaurar."}), 400
    try:
        cfg = _device_config(payload)
        resultado = restaurar_router(
            arquivo,
            cfg,
            interface_fisica=(payload.get("interface_fisica") or "FastEthernet0/0"),
            fazer_backup=payload.get("fazer_backup", True),
            salvar_nvram=payload.get("salvar_nvram", True),
        )
    except ValidationError as exc:
        return jsonify({"sucesso": False, "erro": str(exc)}), 400
    registrar_execucao(resumo_para_log(resultado, "router", cfg.host, f"(restaurado de {arquivo})", "restaurar"))
    return jsonify(resultado)


@app.get("/api/logs")
def api_logs():
    limite = request.args.get("limite", default=50, type=int)
    return jsonify({"execucoes": listar_execucoes(limite=limite)})


@app.get("/api/backups")
def api_backups():
    return jsonify({"backups": listar_backups()})


@app.get("/backups/<path:nome>")
def baixar_backup(nome: str):
    return send_from_directory(Path(DIRETORIO_PADRAO), nome, as_attachment=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")), debug=True)
