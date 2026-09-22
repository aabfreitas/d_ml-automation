"""Orquestração do fluxo completo para o roteador — mesmo padrão do runner.py
do switch: conectar -> backup -> aplicar -> salvar na NVRAM -> reler -> validar.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .backup import salvar_backup
from .device import DeviceConfig, SwitchError, get_router
from .router_models import RouterDesiredState
from .router_validator import coletar_estado_router, validar_router

log = logging.getLogger(__name__)


class EtapasRouter:
    def __init__(self):
        self.itens: list[dict] = []

    def registrar(self, nome: str, status: str, detalhe: str = ""):
        self.itens.append(
            {
                "etapa": nome,
                "status": status,
                "detalhe": detalhe,
                "horario": datetime.now().strftime("%H:%M:%S"),
            }
        )
        log.info("[%s] %s %s", status.upper(), nome, detalhe)


def aplicar_configuracao_router(
    desejado: RouterDesiredState,
    cfg: DeviceConfig,
    fazer_backup: bool = True,
    salvar_nvram: bool = True,
) -> dict:
    etapas = EtapasRouter()
    resultado = {
        "sucesso": False,
        "modo": "simulado" if cfg.simulate else "real",
        "host": cfg.host,
        "comandos": desejado.to_config_lines(),
        "backup": None,
        "saida_config": "",
        "validacao": None,
        "erro": None,
    }

    router = get_router(cfg)
    try:
        router.connect()
        etapas.registrar("Conexão", "ok", f"Sessão aberta com {cfg.host} ({resultado['modo']}).")

        if fazer_backup:
            hostname_antes, _, running_antes = coletar_estado_router(router, desejado.interface_fisica)
            caminho = salvar_backup(running_antes, hostname_antes or "router")
            resultado["backup"] = str(caminho)
            etapas.registrar("Backup", "ok", f"Configuração anterior salva em {caminho.name}.")
        else:
            etapas.registrar("Backup", "pulado", "Backup desativado nesta execução.")

        resultado["saida_config"] = router.send_config(desejado.to_config_lines())
        etapas.registrar(
            "Aplicação",
            "ok",
            f"{len(desejado.subinterfaces)} subinterface(s) e o hostname '{desejado.hostname}' enviados.",
        )

        if salvar_nvram:
            saida = router.save_config()
            etapas.registrar("Gravação na NVRAM", "ok", saida.strip().splitlines()[-1][:80])
        else:
            etapas.registrar(
                "Gravação na NVRAM", "pulado", "A configuração ficou apenas na running-config."
            )

        hostname_atual, subs_atuais, _ = coletar_estado_router(router, desejado.interface_fisica)
        validacao = validar_router(desejado, hostname_atual, subs_atuais)
        resultado["validacao"] = validacao.as_dict()
        etapas.registrar("Validação", "ok" if validacao.conforme else "erro", validacao.resumo())
        resultado["sucesso"] = validacao.conforme

    except SwitchError as exc:
        resultado["erro"] = str(exc)
        etapas.registrar("Conexão", "erro", str(exc))
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha inesperada durante a execução")
        resultado["erro"] = f"Falha inesperada: {exc}"
        etapas.registrar("Execução", "erro", str(exc))
    finally:
        try:
            router.disconnect()
        except Exception:  # noqa: BLE001
            pass

    resultado["etapas"] = etapas.itens
    return resultado


def apenas_validar_router(desejado: RouterDesiredState, cfg: DeviceConfig) -> dict:
    router = get_router(cfg)
    try:
        router.connect()
        hostname_atual, subs_atuais, _ = coletar_estado_router(router, desejado.interface_fisica)
        validacao = validar_router(desejado, hostname_atual, subs_atuais)
        return {"sucesso": validacao.conforme, "validacao": validacao.as_dict(), "erro": None}
    except SwitchError as exc:
        return {"sucesso": False, "validacao": None, "erro": str(exc)}
    finally:
        try:
            router.disconnect()
        except Exception:  # noqa: BLE001
            pass
