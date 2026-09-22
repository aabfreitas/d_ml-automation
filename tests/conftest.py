"""Configuração compartilhada dos testes.

O dispositivo simulado agora persiste o estado em disco entre execuções
separadas (necessário para o rollback fazer sentido em modo simulado — veja
src/device.py). Sem limpar isso entre testes, um teste "vazaria" estado para
o próximo, já que vários usam o mesmo host fictício ("lab").
"""

import shutil

import pytest

from src.device import DIRETORIO_ESTADO_SIMULADO


@pytest.fixture(autouse=True)
def _estado_simulado_limpo():
    shutil.rmtree(DIRETORIO_ESTADO_SIMULADO, ignore_errors=True)
    yield
    shutil.rmtree(DIRETORIO_ESTADO_SIMULADO, ignore_errors=True)
