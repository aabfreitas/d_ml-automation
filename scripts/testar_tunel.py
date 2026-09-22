"""Teste de conectividade através do túnel IPSec (item opcional da Parte 2).

Executa as três camadas de teste descritas em docs/plano-vpn-ipsec.md:

    1. As duas pontas do /30 do túnel respondem?
    2. Um host da LAN remota responde?
    3. Quanto tempo leva e há perda de pacotes?

Uso:
    python scripts/testar_tunel.py
    python scripts/testar_tunel.py --alvo 10.20.0.10 --alvo 10.20.0.20
    python scripts/testar_tunel.py --json
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, asdict

ALVOS_PADRAO = [
    ("169.255.1.1", "Ponta local do túnel (FortiGate)"),
    ("169.255.1.2", "Ponta remota do túnel (Palo Alto)"),
    ("10.20.0.1", "Gateway da LAN do Site B"),
]


@dataclass
class ResultadoPing:
    alvo: str
    descricao: str
    alcancavel: bool
    perda_pct: float | None
    rtt_medio_ms: float | None
    detalhe: str


def _comando_ping(alvo: str, quantidade: int, timeout: int) -> list[str]:
    if platform.system().lower() == "windows":
        return ["ping", "-n", str(quantidade), "-w", str(timeout * 1000), alvo]
    return ["ping", "-c", str(quantidade), "-W", str(timeout), alvo]


def _extrair_metricas(saida: str) -> tuple[float | None, float | None]:
    perda = None
    if m := re.search(r"(\d+(?:\.\d+)?)%\s*(?:packet\s*)?loss", saida, re.I):
        perda = float(m.group(1))
    elif m := re.search(r"\((\d+)%\s*(?:de\s*)?perda", saida, re.I):
        perda = float(m.group(1))

    rtt = None
    if m := re.search(r"=\s*[\d.]+/([\d.]+)/", saida):  # min/avg/max do Linux
        rtt = float(m.group(1))
    elif m := re.search(r"(?:Average|Média)\s*=\s*(\d+)ms", saida, re.I):
        rtt = float(m.group(1))
    return perda, rtt


def pingar(alvo: str, descricao: str, quantidade: int = 4, timeout: int = 2) -> ResultadoPing:
    try:
        proc = subprocess.run(
            _comando_ping(alvo, quantidade, timeout),
            capture_output=True,
            text=True,
            timeout=quantidade * timeout + 10,
        )
        saida = proc.stdout + proc.stderr
        perda, rtt = _extrair_metricas(saida)
        alcancavel = proc.returncode == 0 and (perda is None or perda < 100)
        detalhe = (
            f"{perda:.0f}% de perda"
            + (f", RTT médio {rtt:.1f} ms" if rtt is not None else "")
            if perda is not None
            else saida.strip().splitlines()[-1][:90] if saida.strip() else "sem saída"
        )
        return ResultadoPing(alvo, descricao, alcancavel, perda, rtt, detalhe)
    except subprocess.TimeoutExpired:
        return ResultadoPing(alvo, descricao, False, 100.0, None, "tempo esgotado")
    except FileNotFoundError:
        return ResultadoPing(alvo, descricao, False, None, None, "comando ping indisponível")


def diagnosticar(resultados: list[ResultadoPing]) -> list[str]:
    """Traduz o padrão de falhas em uma hipótese de causa."""
    por_alvo = {r.alvo: r for r in resultados}
    notas: list[str] = []

    local = por_alvo.get("169.255.1.1")
    remoto = por_alvo.get("169.255.1.2")
    lan = [r for r in resultados if r.alvo not in {"169.255.1.1", "169.255.1.2"}]

    if local and not local.alcancavel:
        notas.append(
            "A ponta local do túnel não responde: a interface de túnel pode estar down "
            "ou sem 'allowaccess ping' / management profile."
        )
    if local and local.alcancavel and remoto and not remoto.alcancavel:
        notas.append(
            "A interface local responde mas a remota não: Phase 1 pode estar UP com a "
            "Phase 2 DOWN. Conferir proxy IDs e as propostas de Phase 2 nos dois lados."
        )
    if remoto and remoto.alcancavel and lan and not any(r.alcancavel for r in lan):
        notas.append(
            "O túnel está de pé mas a LAN remota não responde: verificar a rota estática, "
            "as políticas de firewall nos dois sentidos e se há NAT indevido no tráfego do túnel."
        )
    if all(r.alcancavel for r in resultados):
        notas.append("Todos os alvos responderam. Túnel operacional ponta a ponta.")
    for r in resultados:
        if r.alcancavel and r.perda_pct and r.perda_pct > 0:
            notas.append(
                f"{r.alvo} responde com {r.perda_pct:.0f}% de perda — investigar MTU/fragmentação "
                "(o overhead do ESP costuma exigir ajuste de MSS clamping)."
            )
    return notas


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Testa a conectividade através do túnel IPSec.")
    p.add_argument("--alvo", action="append", help="IP extra a testar; pode repetir")
    p.add_argument("--pacotes", type=int, default=4)
    p.add_argument("--timeout", type=int, default=2)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    alvos = list(ALVOS_PADRAO)
    for extra in args.alvo or []:
        alvos.append((extra, "Alvo informado na linha de comando"))

    resultados = [pingar(ip, desc, args.pacotes, args.timeout) for ip, desc in alvos]
    notas = diagnosticar(resultados)

    if args.json:
        print(
            json.dumps(
                {"resultados": [asdict(r) for r in resultados], "diagnostico": notas},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print("\nTeste de conectividade do túnel IPSec")
        print("=" * 64)
        for r in resultados:
            marca = "[OK]  " if r.alcancavel else "[FALHA]"
            print(f"{marca} {r.alvo:<16} {r.descricao}")
            print(f"        {r.detalhe}")
        print("-" * 64)
        for nota in notas:
            print(f"  → {nota}")
        print()

    return 0 if all(r.alcancavel for r in resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
