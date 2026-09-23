# Automação de rede — Desafio Networking Mercado Livre

Automação de configuração de switch Cisco com frontend web, mais o plano de automação
de uma VPN IPSec entre FortiGate e Palo Alto.

| Parte | Entrega | Onde |
|---|---|---|
| 1 | Script Python + frontend que configura VLANs e hostname no switch, salva na NVRAM, faz backup e valida o resultado | `app.py`, `cli.py`, `src/` |
| 1 (extra) | O mesmo fluxo aplicado ao roteador: subinterfaces 802.1Q (uma por VLAN) em vez de VLAN database | os mesmos `app.py`/`cli.py`, módulos `src/router_*.py` |
| 2 | Plano de automação da VPN IPSec FortiGate ↔ Palo Alto | [`docs/plano-vpn-ipsec.md`](docs/plano-vpn-ipsec.md) |

O desafio pede automação de "um switch Cisco". A topologia usada aqui tem também um
roteador fazendo roteamento entre as VLANs (inter-VLAN routing via subinterfaces), então
o mesmo padrão de automação — aplicar, salvar, fazer backup, reler e validar — foi
estendido para configurá-lo também. É um adicional além do mínimo exigido, não uma
substituição da Parte 1.

---

## Parte 1 — Automação do switch Cisco

### O que faz

1. Recebe hostname e VLANs pelo frontend web (ou pela CLI).
2. Abre sessão SSH com o switch via Netmiko.
3. **Faz backup** da configuração atual em `backups/<hostname>_<data-hora>.cfg`.
4. Aplica as VLANs e o hostname.
5. **Grava na NVRAM** (`write memory`).
6. Relê o switch com `show running-config` e `show vlan brief`.
7. **Valida** o que está no equipamento contra o que foi pedido e emite alertas por divergência.

O backup é feito **antes** de aplicar de propósito: em uma reversão, o arquivo útil é o
que descreve como o equipamento estava antes da mudança.

### Instalação

```bash
git clone <URL-DO-REPOSITORIO>
cd ml-net-automation

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Python 3.10 ou superior.

### Executar o frontend

```bash
python app.py
```

Abra <http://127.0.0.1:5000>. No topo da página, o campo **Tipo de dispositivo** alterna
entre **Switch (VLANs)** e **Roteador (subinterfaces 802.1Q)** — os painéis de resultado
(Execução, Validação, Saída, Backups) são os mesmos para os dois.

O **modo simulado** vem ligado. Nele a aplicação inteira roda contra um dispositivo
fictício em memória, sem abrir conexão de rede — dá para ver o fluxo completo, inclusive
os alertas de validação, sem laboratório ligado. Para usar um equipamento de verdade,
desmarque a opção, preencha IP, usuário e senha, e clique em **Aplicar**.

### Como usar a interface

| Elemento | O que faz |
|---|---|
| **Switch** | IP, porta SSH, usuário, senha e senha de enable. Desativado no modo simulado |
| **Usar switch simulado** | Executa tudo em memória, sem tocar na rede |
| **Hostname do switch** | Valor que será aplicado. Padrão: `SWITCH_AUTOMATIZADO` |
| **VLANs** | Lista editável, já preenchida com as três VLANs do desafio. Dá para adicionar, editar e remover linhas |
| **Ver comandos** | Mostra os comandos que seriam enviados, sem enviar nada |
| **Só validar** | Lê o switch e compara com o padrão, sem alterar nada |
| **Aplicar no switch** | Executa o fluxo completo |
| **Execução** | Andamento etapa por etapa, com horário |
| **Validação** | Um alerta por item: conforme, fora do padrão ou divergente |
| **Saída do switch** | Comandos enviados e resposta bruta do equipamento |
| **Backups** | Arquivos gerados, com link para download |

### Executar pela linha de comando

```bash
# fluxo completo contra o switch simulado
python cli.py --simular

# switch real
python cli.py --host 192.168.10.2 --usuario admin --senha cisco

# só conferir, sem alterar nada
python cli.py --host 192.168.10.2 --usuario admin --senha cisco --somente-validar

# VLANs personalizadas
python cli.py --simular --vlan 30:VLAN_GESTAO --vlan 40:VLAN_WIFI

# saída em JSON, para encadear em pipeline
python cli.py --simular --json
```

Código de retorno: `0` se a configuração está conforme, `1` se há divergências, `2` se a
entrada é inválida. Isso permite usar o script como gate em um pipeline de CI.

### Executar contra o roteador

Mesmo `cli.py`, com `--dispositivo router`. As subinterfaces substituem as VLANs — cada
uma leva o ID da VLAN, o IP e, opcionalmente, a máscara e uma descrição:

```bash
# fluxo completo contra o roteador simulado
python cli.py --dispositivo router --simular

# roteador real
python cli.py --dispositivo router \
  --host 192.168.113.10 --usuario admin --senha cisco123 --enable cisco123 \
  --hostname CD-SP1-CR001

# subinterfaces personalizadas (VLAN:IP[:MASCARA[:DESCRICAO]])
python cli.py --dispositivo router --simular \
  --subinterface 10:192.168.10.1 \
  --subinterface 20:192.168.20.1:255.255.255.0:VLAN_VOZ \
  --interface-fisica FastEthernet0/0

# só validar, sem alterar nada
python cli.py --dispositivo router --host 192.168.113.10 --usuario admin --senha cisco123 --somente-validar
```

### Testes

```bash
pytest -v
```

20 testes: 14 cobrindo o switch (normalização de nomes, validação de entrada, parsing das
saídas do IOS, fluxo completo) e 6 cobrindo o roteador (parsing de subinterfaces,
validação de IP/máscara, fluxo completo).

---

## Decisões de implementação

**`VLAN_SEGURANÇA` não existe no IOS.** O desafio pede esse nome, mas o Cisco IOS não aceita
cedilha em nome de VLAN. Em vez de falhar na hora de aplicar, o sistema normaliza para
`VLAN_SEGURANCA` e exibe um aviso explicando o que mudou e por quê. Mesmo tratamento para
espaços e outros caracteres inválidos.

**O switch simulado não é um mock de teste.** É um driver de verdade, com a mesma interface
do driver Netmiko, que reproduz a saída de `show vlan brief` e `show running-config`. Ele
começa com um estado "sujo" de propósito — hostname de fábrica e uma VLAN 99 sem
documentação — para que a validação tenha algo real a reportar. Sem isso, a etapa de
validação seria sempre verde e não provaria nada.

**A validação distingue três severidades.** `erro` é algo que foi pedido e não está no
equipamento (o script falha). `aviso` é algo que está no equipamento e ninguém pediu — é a
"configuração não padrão" que o desafio menciona, e ela não invalida a execução, só precisa
ser vista por alguém. `ok` é conformidade.

**O parsing de `show vlan brief` é por regex sobre tokens, não por posição de coluna.** A
largura das colunas varia entre plataformas (2960, IOSvL2, Packet Tracer); cortar por índice
fixo quebra silenciosamente.

**VLANs 1 e 1002–1005 nunca viram alerta.** São criadas pelo próprio IOS e reportá-las como
divergência geraria ruído em toda execução.

**O roteador reaproveita quase toda a base do switch.** A camada de conexão (`device.py`)
é a mesma — SSH genérico não muda entre um switch e um roteador Cisco, então
`CiscoSwitch` atende aos dois em conexão real. Só o simulador ganhou uma classe própria
(`SimulatedRouter`), porque o que ele modela é diferente: subinterfaces 802.1Q com IP em
vez de VLAN database. A validação também segue o mesmo formato de `Alerta` (severidade +
esperado/encontrado), então o frontend usa os mesmos painéis de Execução e Validação para
os dois tipos de dispositivo — só troca o formulário de entrada.

**Convenção de nomenclatura do hostname (`CD-<site>-<TIPO><nº>`).** Além da validação de
formato básica do IOS, o sistema checa se o hostname segue o padrão usado neste laboratório
— `CD-SP1-SW001`, `CD-SP1-CSW001`, `CD-SP1-CR001`. Isso é só um **aviso**, nunca um erro: um
hostname como `SWITCH_AUTOMATIZADO` (o do próprio enunciado do desafio) continua sendo um
valor válido para o IOS, só não segue essa convenção específica. O aviso aparece tanto na
prévia dos comandos quanto depois de aplicar, para os dois tipos de dispositivo.

**Rollback reaproveita o fluxo de aplicação normal, não duplica lógica.** Restaurar um backup
não é um caminho de código separado: o sistema lê o `show running-config` salvo, extrai dele
o hostname e as VLANs/subinterfaces, monta um `DesiredState`/`RouterDesiredState` como se o
usuário tivesse digitado aqueles valores, e manda pelo mesmo `aplicar_configuracao`. Isso
significa que o rollback ganha de graça duas proteções que já existiam: um novo backup do
estado atual é feito automaticamente **antes** de restaurar (uma segunda rede de segurança
sobre a primeira), e a validação roda no final confirmando se a restauração bateu. Também
significa que o rollback **não apaga** o que foi configurado depois do backup escolhido —
ele só reaplica o que estava lá; qualquer VLAN/subinterface criada depois vira um alerta de
"fora do padrão" em vez de ser removida silenciosamente, para que uma pessoa revise antes.

**O dispositivo simulado persiste estado em disco entre execuções separadas.** Sem isso, cada
chamada de `cli.py --simular` ou cada requisição do frontend criaria um dispositivo do zero,
e nunca seria possível demonstrar de verdade um "aplicar → aplicar de novo → restaurar" sem
laboratório ligado — o simulado sempre voltaria à fábrica. O estado fica em
`.estado_simulado/` (não versionado), uma pasta por dispositivo simulado (identificado pelo
host informado). Use `--resetar-simulado` para forçar a volta à fábrica quando quiser
recomeçar uma demonstração do zero.

**Log de execuções em JSON Lines, não em banco de dados.** Cada `aplicar`/`validar`/
`restaurar` grava uma linha em `logs/execucoes.jsonl` — formato simples o bastante para ler
com o próprio olho, dar `git diff` nele, ou processar com qualquer ferramenta, sem precisar
de um banco. O frontend expõe isso num painel "Logs de execução"; a CLI, com `--listar-logs`.

---

## Testando contra o laboratório real (do seu PC, para o GNS3)

A topologia e os IPs abaixo são os do laboratório real documentado em
[`lab/README.md`](lab/README.md): `CD-SP1-CR001` alcançável direto do seu host em
`192.168.113.10` (via VMnet8), e `CD-SP1-CSW001`/`SW001`/`SW002` em
`192.168.50.6`/`.7`/`.8`, alcançáveis via rota estática apontando para o CR001 (detalhes de
rede em [`docs/laboratorio.md`](docs/laboratorio.md)).

1. **Confirme o alcance de rede primeiro, fora do Python:**
   ```bash
   ping 192.168.113.10   # CR001 — direto, mesma sub-rede da VMnet8
   ping 192.168.50.6     # CSW001 — via rota estática
   ping 192.168.50.7     # SW001
   ping 192.168.50.8     # SW002
   ```
   Se algum desses falhar, resolva a rede antes de tocar no script — nenhuma automação
   contorna um `ping` que não responde.

2. **Rode a CLI contra cada equipamento, sem `--simular`:**
   ```bash
   python cli.py --host 192.168.50.6 --usuario admin --senha <sua_senha> --enable <sua_senha> --hostname CD-SP1-CSW001
   python cli.py --host 192.168.50.7 --usuario admin --senha <sua_senha> --enable <sua_senha> --hostname CD-SP1-SW001
   python cli.py --host 192.168.50.8 --usuario admin --senha <sua_senha> --enable <sua_senha> --hostname CD-SP1-SW002
   python cli.py --dispositivo router --host 192.168.113.10 --usuario admin --senha <sua_senha> --enable <sua_senha> --hostname CD-SP1-CR001
   ```
   Cada execução grava um backup em `backups/` e uma linha em `logs/execucoes.jsonl` — já são
   evidências por si só.

3. **Ou use o frontend** (`python app.py`): desmarque "Usar dispositivo simulado", preencha o
   IP/usuário/senha do equipamento, escolha o tipo (Switch/Roteador) e clique em Aplicar. Os
   painéis de Execução, Validação, Saída e Logs atualizam em tempo real.

4. **Para gravar a evidência (vídeo ou capturas):**
   - Uma janela com o console do equipamento aberto no GNS3, mostrando `show vlan brief` /
     `show running-config` antes e depois.
   - Outra janela com o navegador no frontend, ou o terminal rodando a CLI.
   - Crie uma divergência real: entre no console de um switch e adicione manualmente uma
     VLAN fora do padrão (`vlan 77` / `name TESTE`). Rode
     `python cli.py --host ... --somente-validar` — o alerta "fora do padrão" aparece com um
     cenário real, não simulado.
   - Rode `python cli.py --host ... --restaurar <arquivo_do_backup>` para mostrar o rollback
     revertendo uma mudança.

5. **Não precisa do laboratório ligado para gravar a demonstração do rollback.** Como o
   dispositivo simulado agora persiste estado entre execuções, dá para gravar todo o fluxo
   "aplicar → aplicar de novo → restaurar → validar" com `--simular`, sem abrir o GNS3 — útil
   se a evidência for montada em uma máquina diferente de onde está o laboratório. Use
   `--resetar-simulado` antes de começar, para garantir um estado limpo no início da
   gravação.

---

## Estrutura do repositório

```
.
├── app.py                        # frontend Flask
├── cli.py                        # mesma automação por linha de comando
├── requirements.txt
├── src/
│   ├── models.py                 # switch: estado desejado, validação, normalização
│   ├── router_models.py          # roteador: estado desejado (subinterfaces 802.1Q)
│   ├── device.py                 # drivers: Netmiko (real) + simulados (com persistência)
│   ├── validator.py              # switch: parsing do IOS, comparação e alertas
│   ├── router_validator.py       # roteador: parsing de subinterfaces, comparação e alertas
│   ├── convencao.py              # aviso de convenção de nomenclatura do hostname
│   ├── rollback.py               # restaura um backup pelo mesmo fluxo de aplicação
│   ├── logs.py                   # log de execuções (JSON Lines)
│   ├── backup.py                 # backup em arquivo local (comum aos dois)
│   ├── runner.py                 # orquestração do fluxo — switch
│   └── router_runner.py          # orquestração do fluxo — roteador
├── templates/index.html          # um formulário para cada tipo, alternável
├── static/{style.css, app.js}
├── tests/{test_automacao.py, test_router.py, test_rollback_logs.py}
├── backups/                      # arquivos .cfg gerados
├── logs/execucoes.jsonl          # trilha de auditoria das execuções
├── docs/
│   ├── plano-vpn-ipsec.md        # Parte 2
│   └── laboratorio.md            # preparo genérico de SSH (Packet Tracer / GNS3)
├── lab/
│   ├── README.md                 # topologia REAL, endereçamento, cadeia de serviços
│   ├── topologia.png
│   └── configs/                  # startup-config real de cada equipamento (sanitizada)
├── examples/
│   ├── inventario_vpn.yaml
│   ├── fortigate_vpn.cfg
│   └── paloalto_vpn.xml
├── scripts/testar_tunel.py       # teste de conectividade do túnel
└── evidencias/                   # capturas de tela
```

---

## Laboratório

A topologia final, com as configs **reais** de cada equipamento (roteador, os três
switches, os servidores DHCP/NTP e os clientes), está documentada em
[`lab/README.md`](lab/README.md) — inclui o diagrama, a tabela de endereçamento, a cadeia
de serviços (por que o `ip helper-address` é necessário) e uma nota sobre por que os
hashes de senha foram redigidos antes de publicar.

Uma investigação extensa de conectividade de gerência — seis causas identificadas e
corrigidas, incluindo uma troca de imagem IOU no meio do caminho — está documentada em
[`lab/troubleshooting.md`](lab/troubleshooting.md). **A automação foi executada com
sucesso contra os quatro dispositivos reais** (três switches e o roteador), não mais em
modo simulado — cada execução conectou por SSH real, aplicou a configuração, salvou na
NVRAM e validou o resultado.

O passo a passo genérico de preparo de SSH (Packet Tracer ou GNS3/EVE-NG com IOSvL2) está
em [`docs/laboratorio.md`](docs/laboratorio.md).

---

## Parte 2 — VPN IPSec FortiGate ↔ Palo Alto

O plano completo está em [`docs/plano-vpn-ipsec.md`](docs/plano-vpn-ipsec.md) e cobre
parâmetros (incluindo a rede de túnel `169.255.1.0/30`), ferramentas e APIs de cada
fabricante, passos da automação, os desafios específicos de um ambiente heterogêneo e a
estratégia de validação e alertas em três camadas.

Acompanham o plano: o inventário em YAML que serve de fonte de verdade única, as
configurações de referência dos dois firewalls e o script de teste de conectividade
`scripts/testar_tunel.py`.

---

## Evidências

As capturas de tela do frontend, da CLI do switch com as VLANs criadas e da saída da
validação estão em [`evidencias/`](evidencias/). O checklist do que deve ser capturado
está em `evidencias/README.md`.
