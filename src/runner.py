"""Orquestração do fluxo completo, usada tanto pelo frontend quanto pela CLI.

Ordem de execução:

    conectar -> backup do estado atual -> aplicar -> salvar na NVRAM
             -> reler o switch -> validar -> desconectar

O backup vem antes da aplicação de propósito: o arquivo mais útil em uma
reversão é o que descreve como o equipamento estava antes da mudança.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .backup import salvar_backup
from .device import DeviceConfig, SwitchError, get_switch
from .models import DesiredState
from .validator import coletar_estado, validar

log = logging.getLogger(__name__)


class Etapas:
    """Registra o andamento para exibir no frontend."""

    def __init__(self):
        self.itens: list[dict] = []

    def registrar(self, nome: str, status: str, detalhe: str = ""):
        self.itens.append(
            {
                "etapa": nome,
                "status": status,  # ok | erro | pulado
                "detalhe": detalhe,
                "horario": datetime.now().strftime("%H:%M:%S"),
            }
        )
        log.info("[%s] %s %s", status.upper(), nome, detalhe)


def aplicar_configuracao(
    desejado: DesiredState,
    cfg: DeviceConfig,
    fazer_backup: bool = True,
    salvar_nvram: bool = True,
) -> dict:
    etapas = Etapas()
    resultado = {
        "sucesso": False,
        "modo": "simulado" if cfg.simulate else "real",
        "host": cfg.host,
        "comandos": desejado.to_config_lines(),
        "avisos_entrada": desejado.avisos,
        "backup": None,
        "saida_config": "",
        "validacao": None,
        "erro": None,
    }

    switch = get_switch(cfg)
    try:
        switch.connect()
        etapas.registrar(
            "Conexão", "ok", f"Sessão aberta com {cfg.host} ({resultado['modo']})."
        )

        if fazer_backup:
            hostname_antes, _, running_antes = coletar_estado(switch)
            caminho = salvar_backup(running_antes, hostname_antes or "switch")
            resultado["backup"] = str(caminho)
            etapas.registrar("Backup", "ok", f"Configuração anterior salva em {caminho.name}.")
        else:
            etapas.registrar("Backup", "pulado", "Backup desativado nesta execução.")

        resultado["saida_config"] = switch.send_config(desejado.to_config_lines())
        etapas.registrar(
            "Aplicação",
            "ok",
            f"{len(desejado.vlans)} VLAN(s) e o hostname '{desejado.hostname}' enviados.",
        )

        if salvar_nvram:
            saida = switch.save_config()
            etapas.registrar("Gravação na NVRAM", "ok", saida.strip().splitlines()[-1][:80])
        else:
            etapas.registrar(
                "Gravação na NVRAM", "pulado", "A configuração ficou apenas na running-config."
            )

        hostname_atual, vlans_atuais, _ = coletar_estado(switch)
        validacao = validar(desejado, hostname_atual, vlans_atuais)
        resultado["validacao"] = validacao.as_dict()
        etapas.registrar(
            "Validação",
            "ok" if validacao.conforme else "erro",
            validacao.resumo(),
        )
        resultado["sucesso"] = validacao.conforme

    except SwitchError as exc:
        resultado["erro"] = str(exc)
        etapas.registrar("Conexão", "erro", str(exc))
    except Exception as exc:  # noqa: BLE001 - o frontend precisa exibir qualquer falha
        log.exception("Falha inesperada durante a execução")
        resultado["erro"] = f"Falha inesperada: {exc}"
        etapas.registrar("Execução", "erro", str(exc))
    finally:
        try:
            switch.disconnect()
        except Exception:  # noqa: BLE001
            pass

    resultado["etapas"] = etapas.itens
    return resultado


def apenas_validar(desejado: DesiredState, cfg: DeviceConfig) -> dict:
    """Lê o switch e compara com o padrão, sem alterar nada."""
    switch = get_switch(cfg)
    try:
        switch.connect()
        hostname_atual, vlans_atuais, _ = coletar_estado(switch)
        validacao = validar(desejado, hostname_atual, vlans_atuais)
        return {"sucesso": validacao.conforme, "validacao": validacao.as_dict(), "erro": None}
    except SwitchError as exc:
        return {"sucesso": False, "validacao": None, "erro": str(exc)}
    finally:
        try:
            switch.disconnect()
        except Exception:  # noqa: BLE001
            pass
