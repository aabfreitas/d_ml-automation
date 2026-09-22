"""Camada de acesso ao switch.

Duas implementações com a mesma interface:

- `CiscoSwitch`    -> conexão SSH real via Netmiko (Packet Tracer, GNS3, EVE-NG
                      ou hardware físico).
- `SimulatedSwitch` -> switch em memória que reproduz a saída de `show vlan brief`
                      e `show running-config`. Serve para desenvolver e testar a
                      aplicação inteira (inclusive a validação e os alertas) sem
                      um laboratório ligado.

O frontend nunca fala com o Netmiko diretamente: ele usa `get_switch()`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
import json

log = logging.getLogger(__name__)

# Onde o estado do(s) dispositivo(s) simulado(s) fica persistido entre
# execuções separadas (cada chamada de `python cli.py --simular` ou cada
# requisição do frontend cria um processo/objeto novo — sem isso, o
# simulado "esquece" tudo a cada chamada, o que inviabiliza demonstrar um
# rollback de verdade em modo simulado).
DIRETORIO_ESTADO_SIMULADO = Path(__file__).resolve().parent.parent / ".estado_simulado"


def _chave_simulado(host: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", host or "simulado") or "simulado"


def _carregar_estado_simulado(host: str, tipo: str) -> dict | None:
    caminho = DIRETORIO_ESTADO_SIMULADO / f"{tipo}_{_chave_simulado(host)}.json"
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _salvar_estado_simulado(host: str, tipo: str, dados: dict) -> None:
    DIRETORIO_ESTADO_SIMULADO.mkdir(parents=True, exist_ok=True)
    caminho = DIRETORIO_ESTADO_SIMULADO / f"{tipo}_{_chave_simulado(host)}.json"
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def resetar_estado_simulado(host: str, tipo: str) -> bool:
    """Apaga o estado persistido de um dispositivo simulado, voltando-o à
    fábrica na próxima conexão. Devolve True se havia algo para apagar."""
    caminho = DIRETORIO_ESTADO_SIMULADO / f"{tipo}_{_chave_simulado(host)}.json"
    if caminho.exists():
        caminho.unlink()
        return True
    return False


@dataclass
class DeviceConfig:
    host: str
    username: str
    password: str
    secret: str = ""
    port: int = 22
    device_type: str = "cisco_ios"
    simulate: bool = False
    conn_timeout: int = 20


class SwitchError(RuntimeError):
    """Falha de conexão ou de execução de comando no switch."""


class BaseSwitch:
    def connect(self):  # pragma: no cover - interface
        raise NotImplementedError

    def disconnect(self):  # pragma: no cover - interface
        raise NotImplementedError

    def send_config(self, linhas: list[str]) -> str:  # pragma: no cover
        raise NotImplementedError

    def send_command(self, comando: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def save_config(self) -> str:
        """Grava a running-config na NVRAM (startup-config)."""
        return self.send_command_timing("write memory")

    def send_command_timing(self, comando: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.disconnect()
        return False


class CiscoSwitch(BaseSwitch):
    """Switch Cisco real, acessado por SSH com Netmiko."""

    def __init__(self, cfg: DeviceConfig):
        self.cfg = cfg
        self._conn = None

    def connect(self):
        from netmiko import ConnectHandler
        from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

        params = {
            "device_type": self.cfg.device_type,
            "host": self.cfg.host,
            "username": self.cfg.username,
            "password": self.cfg.password,
            "port": self.cfg.port,
            "conn_timeout": self.cfg.conn_timeout,
            "fast_cli": False,  # Packet Tracer/IOSvL2 não gostam de fast_cli
        }
        if self.cfg.secret:
            params["secret"] = self.cfg.secret

        log.info("Conectando em %s:%s", self.cfg.host, self.cfg.port)
        try:
            self._conn = ConnectHandler(**params)
            if self.cfg.secret:
                self._conn.enable()
        except NetmikoAuthenticationException as exc:
            raise SwitchError(
                f"Autenticação recusada em {self.cfg.host}. Verifique usuário e senha."
            ) from exc
        except NetmikoTimeoutException as exc:
            raise SwitchError(
                f"Sem resposta de {self.cfg.host}:{self.cfg.port}. "
                "Confirme o IP, se o SSH está habilitado e se há rota até o switch."
            ) from exc
        except Exception as exc:  # paramiko e afins
            raise SwitchError(f"Falha ao conectar em {self.cfg.host}: {exc}") from exc
        return self

    def disconnect(self):
        if self._conn:
            self._conn.disconnect()
            self._conn = None

    def _require(self):
        if not self._conn:
            raise SwitchError("Nenhuma sessão aberta com o switch.")
        return self._conn

    def send_config(self, linhas: list[str]) -> str:
        return self._require().send_config_set(linhas, cmd_verify=False)

    def send_command(self, comando: str) -> str:
        return self._require().send_command(comando, read_timeout=60)

    def send_command_timing(self, comando: str) -> str:
        conn = self._require()
        saida = conn.send_command_timing(comando, read_timeout=60)
        # "write memory" e "copy run start" pedem confirmação em alguns IOS.
        if "?" in saida or "confirm" in saida.lower() or "filename" in saida.lower():
            saida += conn.send_command_timing("\n", read_timeout=60)
        return saida


class SimulatedSwitch(BaseSwitch):
    """Switch fictício em memória, com saídas no formato do IOS.

    Começa com um estado "sujo" de propósito — hostname de fábrica e uma VLAN
    99 fora do padrão — para que a etapa de validação tenha algo real a
    reportar antes e depois da aplicação.
    """

    def __init__(self, cfg: DeviceConfig):
        self.cfg = cfg
        estado = _carregar_estado_simulado(cfg.host, "switch")
        if estado:
            self.hostname = estado["hostname"]
            self.vlans = {int(k): v for k, v in estado["vlans"].items()}
        else:
            self.hostname = "Switch"
            self.vlans = {
                1: "default",
                99: "VLAN_LEGADO_NAO_DOCUMENTADA",
            }
        self.saved = False
        self._conectado = False

    def _persistir(self):
        _salvar_estado_simulado(self.cfg.host, "switch", {"hostname": self.hostname, "vlans": self.vlans})

    def connect(self):
        self._conectado = True
        log.info("Switch simulado ativo (nenhuma conexão de rede foi aberta).")
        return self

    def disconnect(self):
        self._conectado = False

    def _require(self):
        if not self._conectado:
            raise SwitchError("Nenhuma sessão aberta com o switch simulado.")

    def send_config(self, linhas: list[str]) -> str:
        self._require()
        eco, vlan_atual = [], None
        for linha in linhas:
            texto = linha.strip()
            eco.append(f"{self.hostname}(config)#{texto}")
            if m := re.match(r"^hostname\s+(\S+)$", texto):
                self.hostname = m.group(1)
            elif m := re.match(r"^no vlan\s+(\d+)$", texto):
                self.vlans.pop(int(m.group(1)), None)
                vlan_atual = None
            elif m := re.match(r"^vlan\s+(\d+)$", texto):
                vlan_atual = int(m.group(1))
                self.vlans.setdefault(vlan_atual, f"VLAN{vlan_atual:04d}")
            elif m := re.match(r"^name\s+(\S+)$", texto):
                if vlan_atual is not None:
                    self.vlans[vlan_atual] = m.group(1)
            elif texto == "exit":
                vlan_atual = None
        self.saved = False
        self._persistir()
        return "\n".join(eco)

    def send_command(self, comando: str) -> str:
        self._require()
        cmd = comando.strip().lower()
        if cmd.startswith("show vlan"):
            return self._show_vlan_brief()
        if cmd.startswith("show run") or cmd.startswith("show start"):
            return self._show_running_config()
        if cmd.startswith("show version"):
            return (
                "Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE4\n"
                f"{self.hostname} uptime is 1 hour, 4 minutes\n"
            )
        return f"% Comando ignorado pelo simulador: {comando}"

    def send_command_timing(self, comando: str) -> str:
        if comando.strip().lower() in {"write memory", "wr", "copy running-config startup-config"}:
            self.saved = True
            return "Building configuration...\n[OK]"
        return self.send_command(comando)

    def _show_vlan_brief(self) -> str:
        cab = (
            "VLAN Name                             Status    Ports\n"
            "---- -------------------------------- --------- "
            "-------------------------------\n"
        )
        linhas = []
        for vid in sorted(self.vlans):
            portas = "Fa0/1, Fa0/2, Fa0/3" if vid == 1 else ""
            linhas.append(f"{vid:<4} {self.vlans[vid]:<32} active    {portas}")
        for vid, nome in (
            (1002, "fddi-default"),
            (1003, "token-ring-default"),
            (1004, "fddinet-default"),
            (1005, "trnet-default"),
        ):
            linhas.append(f"{vid:<4} {nome:<32} act/unsup")
        return cab + "\n".join(linhas)

    def _show_running_config(self) -> str:
        blocos = [
            "Building configuration...",
            "",
            "Current configuration : 1428 bytes",
            "!",
            "version 15.0",
            "service timestamps debug datetime msec",
            "no service password-encryption",
            "!",
            f"hostname {self.hostname}",
            "!",
        ]
        for vid in sorted(v for v in self.vlans if v != 1):
            blocos += [f"vlan {vid}", f" name {self.vlans[vid]}", "!"]
        blocos += [
            "interface Vlan1",
            " ip address 192.168.10.2 255.255.255.0",
            "!",
            "line vty 0 4",
            " transport input ssh",
            "!",
            "end",
        ]
        return "\n".join(blocos)


class SimulatedRouter(BaseSwitch):
    """Roteador fictício com subinterfaces 802.1Q, para desenvolver sem laboratório.

    Mesma ideia do SimulatedSwitch: começa com um estado "sujo" de propósito
    (uma subinterface legada fora do padrão) para que a validação tenha algo
    real a reportar.
    """

    def __init__(self, cfg: DeviceConfig):
        self.cfg = cfg
        estado = _carregar_estado_simulado(cfg.host, "router")
        if estado:
            self.hostname = estado["hostname"]
            self.interface_fisica = estado["interface_fisica"]
            self.subinterfaces = {int(k): v for k, v in estado["subinterfaces"].items()}
        else:
            self.hostname = "Router"
            self.interface_fisica = "FastEthernet0/0"
            self.subinterfaces = {
                99: {"ip": "10.99.99.1", "mascara": "255.255.255.0", "descricao": "LEGADO_NAO_DOCUMENTADO"},
            }
        self.saved = False
        self._conectado = False

    def _persistir(self):
        _salvar_estado_simulado(
            self.cfg.host,
            "router",
            {
                "hostname": self.hostname,
                "interface_fisica": self.interface_fisica,
                "subinterfaces": self.subinterfaces,
            },
        )

    def connect(self):
        self._conectado = True
        log.info("Roteador simulado ativo (nenhuma conexão de rede foi aberta).")
        return self

    def disconnect(self):
        self._conectado = False

    def _require(self):
        if not self._conectado:
            raise SwitchError("Nenhuma sessão aberta com o roteador simulado.")

    def send_config(self, linhas: list[str]) -> str:
        self._require()
        eco: list[str] = []
        sub_atual: int | None = None
        for linha in linhas:
            texto = linha.strip()
            eco.append(f"{self.hostname}(config)#{texto}")
            if m := re.match(r"^hostname\s+(\S+)$", texto):
                self.hostname = m.group(1)
            elif m := re.match(rf"^interface\s+{re.escape(self.interface_fisica)}\.(\d+)$", texto):
                sub_atual = int(m.group(1))
                self.subinterfaces.setdefault(sub_atual, {"ip": None, "mascara": None, "descricao": ""})
            elif texto == f"interface {self.interface_fisica}":
                sub_atual = None
            elif m := re.match(r"^ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)$", texto):
                if sub_atual is not None:
                    self.subinterfaces[sub_atual]["ip"] = m.group(1)
                    self.subinterfaces[sub_atual]["mascara"] = m.group(2)
            elif m := re.match(r"^description\s+(.+)$", texto):
                if sub_atual is not None:
                    self.subinterfaces[sub_atual]["descricao"] = m.group(1)
            elif texto == "exit":
                sub_atual = None
        self.saved = False
        self._persistir()
        return "\n".join(eco)

    def send_command(self, comando: str) -> str:
        self._require()
        cmd = comando.strip().lower()
        if cmd.startswith("show run") or cmd.startswith("show start"):
            return self._show_running_config()
        if cmd.startswith("show ip interface brief"):
            return self._show_ip_interface_brief()
        return f"% Comando ignorado pelo simulador: {comando}"

    def send_command_timing(self, comando: str) -> str:
        if comando.strip().lower() in {"write memory", "wr", "copy running-config startup-config"}:
            self.saved = True
            return "Building configuration...\n[OK]"
        return self.send_command(comando)

    def _show_running_config(self) -> str:
        blocos = [
            "Building configuration...",
            "",
            f"hostname {self.hostname}",
            "!",
            f"interface {self.interface_fisica}",
            " no ip address",
            "!",
        ]
        for vid in sorted(self.subinterfaces):
            dados = self.subinterfaces[vid]
            blocos.append(f"interface {self.interface_fisica}.{vid}")
            blocos.append(f" encapsulation dot1Q {vid}")
            if dados.get("descricao"):
                blocos.append(f" description {dados['descricao']}")
            if dados.get("ip"):
                blocos.append(f" ip address {dados['ip']} {dados['mascara']}")
            blocos.append("!")
        blocos.append("end")
        return "\n".join(blocos)

    def _show_ip_interface_brief(self) -> str:
        linhas = ["Interface                  IP-Address      OK? Method Status                Protocol"]
        for vid in sorted(self.subinterfaces):
            ip = self.subinterfaces[vid].get("ip") or "unassigned"
            nome = f"{self.interface_fisica}.{vid}"
            linhas.append(f"{nome:<27} {ip:<15} YES manual up                    up")
        return "\n".join(linhas)


def get_switch(cfg: DeviceConfig) -> BaseSwitch:
    """Devolve o driver certo conforme `cfg.simulate`."""
    return SimulatedSwitch(cfg) if cfg.simulate else CiscoSwitch(cfg)


def get_router(cfg: DeviceConfig) -> BaseSwitch:
    """Devolve o driver certo para o roteador conforme `cfg.simulate`.

    Em conexão real, é o mesmo driver Netmiko do switch — SSH genérico não
    muda entre plataformas Cisco. Só o simulador é diferente, porque modela
    subinterfaces em vez de VLAN database.
    """
    return SimulatedRouter(cfg) if cfg.simulate else CiscoSwitch(cfg)
