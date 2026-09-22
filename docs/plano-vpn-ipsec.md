# Plano de automação — VPN IPSec site-to-site entre FortiGate e Palo Alto

Documento da **Parte 2** do desafio. Descreve como automatizar, de ponta a ponta, a
configuração de um túnel IPSec route-based entre um FortiGate (Site A) e um firewall
Palo Alto (Site B), incluindo validação e alertas.

O túnel é **route-based nas duas pontas**. Essa escolha vem antes de qualquer outra:
o Palo Alto só trabalha com túneis route-based (interface `tunnel.N`), então tentar
casar um policy-based do FortiGate com ele é a origem mais comum de falha na Phase 2
nesse par de fabricantes.

---

## 1. Definição de parâmetros

### 1.1 Topologia

```
        Site A — FortiGate                       Site B — Palo Alto
   ┌──────────────────────────┐             ┌──────────────────────────┐
   │ LAN 10.10.0.0/24         │             │ LAN 10.20.0.0/24         │
   │ WAN port1 203.0.113.10   │             │ WAN eth1/1 198.51.100.20 │
   │ tunnel: VPN_TO_PALO      │◄══ IPSec ══►│ tunnel.10                │
   │ 169.255.1.1/30           │             │ 169.255.1.2/30           │
   └──────────────────────────┘             └──────────────────────────┘
```

| Parâmetro | Site A — FortiGate | Site B — Palo Alto |
|---|---|---|
| IP WAN (peer) | 203.0.113.10 | 198.51.100.20 |
| Interface WAN | `port1` | `ethernet1/1` |
| Rede local | 10.10.0.0/24 | 10.20.0.0/24 |
| Interface de túnel | `VPN_TO_PALO` | `tunnel.10` |
| IP do túnel | 169.255.1.1/30 | 169.255.1.2/30 |
| Zona de segurança | `vpn_zone` | `ZONA-VPN` |
| Virtual Router / VDOM | VDOM `root` | VR `default` |

A rede de túnel **169.255.1.0/30** é o `/30` pedido pelo desafio: dois endereços
utilizáveis, um para cada extremidade. Ela serve como next-hop das rotas estáticas e
como destino dos pings de monitoração do túnel.

### 1.2 Phase 1 (IKE)

| Item | Valor | Por quê |
|---|---|---|
| Versão | IKEv2 | Suportado pelos dois; menos mensagens, rekey mais limpo, NAT-T nativo |
| Modo | — (IKEv2 não usa main/aggressive) | |
| Autenticação | Pre-shared key | O caminho automatizável sem PKI; a PSK vem de um cofre, nunca do código |
| Criptografia | AES-256-CBC | Presente no conjunto padrão dos dois fabricantes |
| Hash / integridade | SHA-256 | |
| Grupo DH | 14 (2048 bits) | Grupo mais alto comum aos dois sem depender de licença/modelo |
| Lifetime | 28800 s (8 h) | Precisa ser idêntico nos dois lados |
| Local/Peer ID | IP address | Evita mismatch de FQDN |
| DPD | on-idle, intervalo 10 s, 3 tentativas | FortiGate: `dpd on-idle`; Palo Alto: *Liveness Check* |
| NAT-T | habilitado | Necessário se qualquer ponta estiver atrás de NAT |

### 1.3 Phase 2 (IPSec / Child SA)

| Item | Valor |
|---|---|
| Protocolo | ESP |
| Criptografia | AES-256-CBC |
| Autenticação | SHA-256 |
| PFS | habilitado, grupo DH 14 |
| Lifetime | 3600 s (1 h) |
| Proxy ID / seletor | local 0.0.0.0/0 — remoto 0.0.0.0/0 |
| Replay protection | habilitado |

**Sobre o seletor `0.0.0.0/0`:** em túnel route-based o tráfego é escolhido pela rota,
não pelo seletor. Usar `0.0.0.0/0` dos dois lados elimina o mismatch de proxy ID —
segunda causa mais comum de Phase 2 que não sobe entre esses fabricantes. Se a política
interna exigir seletores específicos, eles precisam ser espelhados exatamente:
FortiGate local `10.10.0.0/24` / remoto `10.20.0.0/24` e Palo Alto local `10.20.0.0/24`
/ remoto `10.10.0.0/24`.

### 1.4 Roteamento e políticas

- FortiGate: rota estática `10.20.0.0/24` via interface `VPN_TO_PALO`.
- Palo Alto: rota estática `10.10.0.0/24` via `tunnel.10`, next-hop `169.255.1.1`.
- Política de firewall nos dois sentidos (LAN→VPN e VPN→LAN), sem NAT no tráfego do túnel.

---

## 2. Ferramentas e APIs

### FortiGate

| Opção | Uso | Observação |
|---|---|---|
| **API REST `/api/v2/cmdb`** | escolha principal | Objeto por endpoint (`vpn.ipsec/phase1-interface`, `phase2-interface`, `firewall/policy`, `router/static`). Autenticação por token de API. Idempotente por natureza: `PUT` sobrescreve o objeto |
| API `/api/v2/monitor` | validação | `vpn/ipsec` devolve o estado do túnel em JSON |
| Ansible `fortinet.fortios` | alternativa declarativa | Módulos `fortios_vpn_ipsec_phase1_interface` etc. |
| Netmiko / paramiko (CLI) | fallback | Útil em versões antigas sem a API habilitada |
| FortiManager | escala | Faz sentido quando há dezenas de sites; envia via *Install Wizard* |

### Palo Alto

| Opção | Uso | Observação |
|---|---|---|
| **API XML (`/api/?type=config`)** | escolha principal | Configuração por XPath (`action=set`/`edit`) + `type=commit`. É a API mais completa do PAN-OS |
| `pan-os-python` (SDK oficial) | recomendado | Abstrai XPath e commit; classes `IkeGateway`, `IpsecTunnel`, `IpsecCryptoProfile` |
| API REST (`/restapi/v10.x/`) | alternativa | Mais legível, mas cobre menos objetos que a XML |
| Ansible `paloaltonetworks.panos` | alternativa declarativa | |
| Panorama | escala | Templates + device groups; um push atinge todos os firewalls |

**Diferença estrutural que o script precisa respeitar:** o FortiGate aplica cada
mudança na hora; o PAN-OS escreve em *candidate config* e só materializa no `commit`.
O commit é assíncrono e devolve um `job id` que precisa ser consultado até terminar.

### Orquestração sugerida

Python 3.11+, com `requests` (FortiGate), `pan-os-python` (Palo Alto), `pydantic` para
validar os parâmetros antes de sair enviando, `jinja2` para renderizar configurações de
referência e `hvac`/variáveis de ambiente para buscar a PSK. O inventário fica em um
único YAML, para que os dois lados sejam gerados da mesma fonte de verdade.

---

## 3. Passos da automação

### Fase 0 — Preparação (antes de tocar nos equipamentos)

1. Ler `inventario.yaml` e validar o esquema: IPs válidos, `/30` do túnel com dois hosts,
   propostas de Phase 1 e Phase 2 idênticas nos dois lados, redes locais sem sobreposição.
2. Buscar credenciais e a PSK no cofre. Abortar se faltar qualquer segredo.
3. Testar alcançabilidade e autenticação nas duas APIs (`GET` simples em cada uma).
4. Fazer backup da configuração atual dos dois firewalls
   (FortiGate: `/api/v2/monitor/system/config/backup`; Palo Alto: `type=export&category=configuration`).
5. Rodar em `--dry-run`: gerar o payload completo e exibi-lo, sem enviar nada.

### Fase 1 — FortiGate

6. Criar os objetos de endereço: `LAN_SITE_A` (10.10.0.0/24), `LAN_SITE_B` (10.20.0.0/24).
7. `POST vpn.ipsec/phase1-interface`: nome `VPN_TO_PALO`, `type=static`,
   `remote-gw=198.51.100.20`, `interface=port1`, proposta `aes256-sha256`, `dhgrp=14`,
   `ike-version=2`, `psksecret`, `dpd=on-idle`, `nattraversal=enable`.
8. `POST vpn.ipsec/phase2-interface`: proposta `aes256-sha256`, `pfs=enable`, `dhgrp=14`,
   `src-subnet=0.0.0.0/0`, `dst-subnet=0.0.0.0/0`, `keylifeseconds=3600`.
9. `PUT system/interface/VPN_TO_PALO`: `ip=169.255.1.1 255.255.255.255`,
   `remote-ip=169.255.1.2 255.255.255.252`, `allowaccess=ping`.
10. `POST router/static`: `10.20.0.0/24` via `VPN_TO_PALO`.
11. `POST firewall/policy` nos dois sentidos, com `nat=disable`.

### Fase 2 — Palo Alto

12. Criar os objetos de endereço equivalentes.
13. Criar a interface `tunnel.10`, atribuí-la ao VR `default` e à zona `ZONA-VPN`,
    com IP `169.255.1.2/30` e um *management profile* que aceite ping.
14. Criar os perfis `IKE Crypto` e `IPSec Crypto` com exatamente os mesmos valores da Phase 1/2.
15. Criar o `IKE Gateway`: peer `203.0.113.10`, interface `ethernet1/1`, IKEv2, PSK, liveness check.
16. Criar o `IPSec Tunnel` amarrando gateway + perfil IPSec + `tunnel.10`, com proxy ID
    `0.0.0.0/0 ↔ 0.0.0.0/0`.
17. Criar a rota estática `10.10.0.0/24` via `tunnel.10`, next-hop `169.255.1.1`.
18. Criar as regras de segurança nos dois sentidos entre `TRUST` e `ZONA-VPN`.
19. **Commit**, capturar o `job id` e consultar `type=op&cmd=<show><jobs><id>…` até
    concluir. Falhou o commit? Nada do que foi escrito vale — tratar como falha da etapa.

### Fase 3 — Levantar e conferir

20. Disparar o túnel a partir do FortiGate (`execute vpn ipsec tunnel up VPN_TO_PALO`)
    ou gerar tráfego interessante com um ping de `169.255.1.1` para `169.255.1.2`.
21. Executar a validação da seção 5.
22. Gravar o relatório da execução (JSON + log) e, em caso de falha, disparar o alerta.

---

## 4. Considerações específicas de um ambiente heterogêneo

**Vocabulário diferente para a mesma coisa.** "Phase 1" no FortiGate é *IKE Gateway* +
*IKE Crypto Profile* no PAN-OS; "Phase 2" é *IPSec Tunnel* + *IPSec Crypto Profile*.
O script deve trabalhar com um modelo neutro (um dataclass `TunnelSpec`) e ter um
tradutor por fabricante, em vez de duplicar a lógica.

**Modelo transacional incompatível.** FortiGate aplica imediatamente; PAN-OS precisa de
commit. Se a Fase 1 do script funciona e a Fase 2 falha, o FortiGate fica com meia
configuração ativa. Resolver com rollback explícito: guardar os objetos criados em cada
ponta e removê-los na ordem inversa quando qualquer etapa falhar.

**Proxy ID e route-based vs policy-based.** Já tratado acima — é a divergência que mais
gera túnel com Phase 1 UP e Phase 2 DOWN.

**Propostas negociadas diferente.** O FortiGate envia uma lista de propostas; o Palo Alto
usa um perfil com um conjunto fixo. Se a lista do FortiGate incluir algoritmos que o
perfil do Palo Alto não tem, a negociação pode fechar em algo mais fraco que o desejado.
Definir uma proposta única e explícita nos dois lados.

**Lifetimes assimétricos.** Se os tempos diferirem, o túnel sobe e cai no rekey. O
validador precisa comparar os lifetimes numericamente, não só "está UP".

**Unidades e formatos.** O FortiGate usa segundos; o Palo Alto permite escolher a
unidade. O modelo neutro guarda sempre segundos e converte na saída.

**Máscara da interface de túnel.** O FortiGate configura o IP local com `/32` mais um
`remote-ip`; o Palo Alto usa `/30` direto. Mesma topologia, sintaxe diferente.

**Idempotência.** Reexecutar o script não pode duplicar objetos nem derrubar um túnel que
já está funcionando. Antes de criar, consultar; se existir e estiver igual, não faz nada;
se existir e estiver diferente, atualiza e registra o que mudou.

**Assimetria de erros.** O FortiGate devolve HTTP 500 com um `cli_error` textual; o
PAN-OS devolve HTTP 200 com `status="error"` no XML. Tratar código HTTP como suficiente
é um erro clássico: o parser precisa olhar o corpo da resposta nos dois casos.

**Segredos.** A PSK nunca vai para o Git nem para o log. Variável de ambiente ou cofre,
e mascaramento no log (`psk=***`).

**Janela de mudança.** Aplicar uma política de firewall errada derruba produção. Prever
`--dry-run` obrigatório antes do primeiro `--apply` e um modo `--rollback`.

---

## 5. Validação e alertas

A validação roda em três camadas, e cada uma só executa se a anterior passou.

### Camada 1 — Configuração aplicada (o que está escrito)

| Verificação | FortiGate | Palo Alto |
|---|---|---|
| Phase 1 existe e confere | `GET /api/v2/cmdb/vpn.ipsec/phase1-interface/VPN_TO_PALO` | `type=config&action=get` no XPath do IKE gateway |
| Phase 2 existe e confere | `GET .../phase2-interface/VPN_TO_PALO_P2` | XPath do IPSec tunnel |
| IP do túnel | `GET /api/v2/cmdb/system/interface/VPN_TO_PALO` | XPath de `tunnel.10` |
| Rota presente | `GET /api/v2/cmdb/router/static` | XPath do virtual router |
| Política criada | `GET /api/v2/cmdb/firewall/policy` | XPath das security rules |

O script compara campo a campo com a especificação e emite um alerta por divergência,
no mesmo formato da Parte 1: `severidade | item | esperado | encontrado`.

### Camada 2 — Túnel operacional (o que está acontecendo)

- FortiGate: `GET /api/v2/monitor/vpn/ipsec` — conferir `proxyid[].status == "up"`,
  `incoming_bytes` e `outgoing_bytes` crescendo entre duas leituras.
- Palo Alto: `type=op&cmd=<show><vpn><ike-sa></ike-sa></vpn></show>` e
  `<show><vpn><ipsec-sa></ipsec-sa></vpn></show>`.
- Conferência cruzada: os SPIs e o algoritmo negociado precisam bater entre os dois lados.
  É o que revela o caso "Phase 1 UP nos dois, mas negociaram coisas diferentes".

### Camada 3 — Tráfego passando (o que o usuário sente)

- Ping de `169.255.1.1` para `169.255.1.2` (ponta a ponta do `/30`).
- Ping de um host da LAN A para um host da LAN B, saindo pela interface interna.
- Conferir o contador da política de firewall: se está zerado depois do teste, o tráfego
  está saindo por outro caminho — normalmente rota ou NAT mal configurados.

O script auxiliar `scripts/testar_tunel.py` cobre a camada 3.

### Alertas

| Severidade | Quando | Ação |
|---|---|---|
| `erro` | Objeto ausente, parâmetro divergente, commit falhou, Phase 1 ou 2 DOWN | Interrompe, faz rollback e notifica |
| `aviso` | Túnel UP com algoritmo mais fraco que o especificado, contador de política zerado, objeto pré-existente alterado | Segue, mas registra |
| `ok` | Item conforme | Só log |

**Canais:** saída do script com código de retorno diferente de zero (para o pipeline de
CI barrar), arquivo JSON com o relatório completo, webhook para Slack/Teams com o resumo,
e syslog/SNMP trap para o NMS. Em produção, o mesmo validador da Camada 2 vira um job
periódico: se o túnel cair às 3 da manhã, o alerta é o mesmo código.

---

## 6. Arquivos relacionados no repositório

| Arquivo | Conteúdo |
|---|---|
| `examples/fortigate_vpn.cfg` | Configuração de referência do FortiGate (CLI) |
| `examples/paloalto_vpn.xml` | Configuração de referência do Palo Alto (XML/API) |
| `examples/inventario_vpn.yaml` | Fonte de verdade única dos parâmetros |
| `scripts/testar_tunel.py` | Teste de conectividade através do túnel |
