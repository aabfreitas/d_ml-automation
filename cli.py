"""Execução da mesma automação pela linha de comando.

Exemplos:
    python cli.py --simular
    python cli.py --host 192.168.10.2 --usuario admin --senha cisco
    python cli.py --simular --somente-validar
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from src.device import DeviceConfig, resetar_estado_simulado
from src.logs import listar_execucoes, registrar_execucao, resumo_para_log
from src.models import DesiredState, ValidationError
from src.rollback import restaurar_router, restaurar_switch
from src.router_models import RouterDesiredState
from src.router_runner import aplicar_configuracao_router, apenas_validar_router
from src.runner import aplicar_configuracao, apenas_validar
from src.validator import Alerta

PADRAO = {
    "hostname": "SWITCH_AUTOMATIZADO",
    "vlans": [
        {"id": 10, "name": "VLAN_DADOS"},
        {"id": 20, "name": "VLAN_VOZ"},
        {"id": 50, "name": "VLAN_SEGURANÇA"},
    ],
}

PADRAO_ROTEADOR = {
    "hostname": "ROTEADOR_AUTOMATIZADO",
    "interface_fisica": "FastEthernet0/0",
    "subinterfaces": [
        {"vlan_id": 10, "ip": "192.168.10.1", "mascara": "255.255.255.0", "descricao": "VLAN_DADOS"},
        {"vlan_id": 20, "ip": "192.168.20.1", "mascara": "255.255.255.0", "descricao": "VLAN_VOZ"},
        {"vlan_id": 50, "ip": "192.168.50.1", "mascara": "255.255.255.0", "descricao": "VLAN_SEGURANCA"},
    ],
}


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Automação de VLANs e hostname em switch Cisco.")
    p.add_argument("--host", default="192.168.10.2", help="IP do switch/roteador")
    p.add_argument("--porta", type=int, default=22)
    p.add_argument("--usuario", default="admin")
    p.add_argument("--senha", default="")
    p.add_argument("--enable", default="", help="senha de enable, se houver")
    p.add_argument(
        "--transporte",
        choices=["ssh", "telnet"],
        default="ssh",
        help="protocolo de conexão. Use telnet se o SSH do dispositivo estiver instável "
        "(comum em algumas imagens IOU) — com telnet, a porta padrão vira 23 "
        "automaticamente, a menos que --porta seja informado.",
    )
    p.add_argument(
        "--dispositivo",
        choices=["switch", "router"],
        default="switch",
        help="tipo de dispositivo a configurar (padrão: switch)",
    )
    p.add_argument("--hostname", default=None, help="hostname a configurar")
    p.add_argument(
        "--vlan",
        action="append",
        metavar="ID:NOME",
        help="[switch] VLAN a configurar; repita a opção. Sem esta opção usa o padrão do desafio.",
    )
    p.add_argument(
        "--interface-fisica",
        default="FastEthernet0/0",
        help="[router] interface física onde as subinterfaces serão criadas",
    )
    p.add_argument(
        "--subinterface",
        action="append",
        metavar="VLAN:IP[:MASCARA[:DESCRICAO]]",
        help="[router] subinterface a configurar; repita a opção. Sem esta opção usa o padrão do desafio.",
    )
    p.add_argument("--simular", action="store_true", help="usa o dispositivo simulado")
    p.add_argument("--sem-backup", action="store_true")
    p.add_argument("--sem-nvram", action="store_true", help="não grava a startup-config")
    p.add_argument("--somente-validar", action="store_true", help="não altera nada")
    p.add_argument(
        "--restaurar",
        metavar="ARQUIVO",
        default=None,
        help="restaura um backup salvo em backups/ (pelo nome do arquivo), em vez de aplicar --vlan/--subinterface",
    )
    p.add_argument(
        "--listar-logs",
        action="store_true",
        help="mostra as últimas execuções registradas e sai (não conecta em nada)",
    )
    p.add_argument(
        "--resetar-simulado",
        action="store_true",
        help="apaga o estado persistido do dispositivo simulado (volta à fábrica) e sai",
    )
    p.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    return p.parse_args(argv)


def montar_desejado(args) -> DesiredState:
    if args.vlan:
        vlans = []
        for item in args.vlan:
            if ":" not in item:
                raise ValidationError(f"Formato inválido em --vlan {item!r}. Use ID:NOME.")
            vid, nome = item.split(":", 1)
            vlans.append({"id": vid, "name": nome})
    else:
        vlans = PADRAO["vlans"]
    hostname = args.hostname or PADRAO["hostname"]
    return DesiredState.from_payload({"hostname": hostname, "vlans": vlans})


def montar_desejado_router(args) -> RouterDesiredState:
    if args.subinterface:
        subs = []
        for item in args.subinterface:
            partes = item.split(":")
            if len(partes) < 2:
                raise ValidationError(
                    f"Formato inválido em --subinterface {item!r}. Use VLAN:IP[:MASCARA[:DESCRICAO]]."
                )
            vlan_id, ip = partes[0], partes[1]
            mascara = partes[2] if len(partes) > 2 else "255.255.255.0"
            descricao = ":".join(partes[3:]) if len(partes) > 3 else ""
            subs.append({"vlan_id": vlan_id, "ip": ip, "mascara": mascara, "descricao": descricao})
    else:
        subs = PADRAO_ROTEADOR["subinterfaces"]
    hostname = args.hostname or PADRAO_ROTEADOR["hostname"]
    return RouterDesiredState.from_payload(
        {"hostname": hostname, "interface_fisica": args.interface_fisica, "subinterfaces": subs}
    )


def imprimir(resultado: dict) -> None:
    print()
    for etapa in resultado.get("etapas", []):
        marca = {"ok": "[OK]   ", "erro": "[ERRO] ", "pulado": "[--]   "}[etapa["status"]]
        print(f"{marca} {etapa['horario']}  {etapa['etapa']}: {etapa['detalhe']}")

    for aviso in resultado.get("avisos_entrada", []) or []:
        print(f"[AVISO] entrada: {aviso}")

    validacao = resultado.get("validacao")
    if validacao:
        print("\n--- Validação ---")
        for dados in validacao["alertas"]:
            print(Alerta(**dados))
            if dados["esperado"] or dados["encontrado"]:
                print(f"        esperado: {dados['esperado']} | encontrado: {dados['encontrado']}")

    if resultado.get("backup"):
        print(f"\nBackup: {resultado['backup']}")
    if resultado.get("erro"):
        print(f"\nErro: {resultado['erro']}")
    print(
        "\nResultado: "
        + ("configuração conforme o padrão." if resultado.get("sucesso") else "há divergências a tratar.")
    )


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    args = parse_args(argv)

    if args.listar_logs:
        for l in listar_execucoes(limite=30):
            marca = "[OK]   " if l.get("sucesso") else "[FALHA]"
            print(
                f"{marca} {l.get('timestamp','')}  {l.get('acao',''):9s} "
                f"[{l.get('dispositivo','')}] {l.get('host','')} — {l.get('hostname_desejado','')}"
                f"  ({l.get('resumo') or l.get('erro') or ''})"
            )
        return 0

    cfg = DeviceConfig(
        host=args.host,
        username=args.usuario,
        password=args.senha,
        secret=args.enable,
        port=args.porta,
        transporte=args.transporte,
        simulate=args.simular,
    )

    if args.resetar_simulado:
        tipo = "router" if args.dispositivo == "router" else "switch"
        apagou = resetar_estado_simulado(cfg.host, tipo)
        print(
            f"Estado simulado de '{cfg.host}' ({tipo}) "
            + ("apagado. Volta à fábrica na próxima conexão." if apagou else "não existia — nada a apagar.")
        )
        return 0

    if args.restaurar:
        try:
            if args.dispositivo == "router":
                resultado = restaurar_router(
                    args.restaurar, cfg,
                    interface_fisica=args.interface_fisica,
                    fazer_backup=not args.sem_backup, salvar_nvram=not args.sem_nvram,
                )
            else:
                resultado = restaurar_switch(
                    args.restaurar, cfg,
                    fazer_backup=not args.sem_backup, salvar_nvram=not args.sem_nvram,
                )
        except ValidationError as exc:
            print(f"Não foi possível restaurar: {exc}", file=sys.stderr)
            return 2
        registrar_execucao(resumo_para_log(resultado, args.dispositivo, cfg.host, f"(restaurado de {args.restaurar})", "restaurar"))
        if args.json:
            print(json.dumps(resultado, indent=2, ensure_ascii=False))
        else:
            print(f"\nRestaurado a partir de: {resultado.get('restaurado_de')}")
            imprimir(resultado)
        return 0 if resultado.get("sucesso") else 1

    try:
        if args.dispositivo == "router":
            desejado = montar_desejado_router(args)
        else:
            desejado = montar_desejado(args)
    except ValidationError as exc:
        print(f"Entrada inválida: {exc}", file=sys.stderr)
        return 2

    if args.dispositivo == "router":
        if args.somente_validar:
            resultado = apenas_validar_router(desejado, cfg)
        else:
            resultado = aplicar_configuracao_router(
                desejado, cfg, fazer_backup=not args.sem_backup, salvar_nvram=not args.sem_nvram
            )
    else:
        if args.somente_validar:
            resultado = apenas_validar(desejado, cfg)
        else:
            resultado = aplicar_configuracao(
                desejado, cfg, fazer_backup=not args.sem_backup, salvar_nvram=not args.sem_nvram
            )

    registrar_execucao(
        resumo_para_log(
            resultado, args.dispositivo, cfg.host, desejado.hostname,
            "validar" if args.somente_validar else "aplicar",
        )
    )

    if args.json:
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    else:
        imprimir(resultado)

    return 0 if resultado.get("sucesso") else 1


if __name__ == "__main__":
    raise SystemExit(main())
