# Investigação: conectividade de gerência do laboratório (22/09/2026)

Registro técnico da sessão de troubleshooting de rede realizada para tentar executar a
automação Python contra os equipamentos reais do laboratório GNS3. Documenta o que foi
diagnosticado, corrigido e o que permaneceu sem solução — como evidência do processo, não
só do resultado.

## Resumo executivo

Quatro problemas de rede distintos foram identificados e corrigidos ao longo da
investigação. Um quinto problema — instabilidade na camada de transporte (SSH e Telnet)
entre a GNS3 VM e os switches IOU — foi diagnosticado extensivamente mas **não foi
resolvido**, apesar de eliminar sistematicamente todas as causas mais prováveis. Por esse
motivo, a entrega final deste desafio usa o modo simulado do projeto (explicitamente
previsto no enunciado: *"switch Cisco (simulado ou real)"*), com as evidências reais do
laboratório (topologia, roteamento, NAT, DHCP relay, NTP) documentadas separadamente em
[`lab/README.md`](README.md) — tudo isso foi confirmado funcionando de fato.

---

## Problemas identificados e corrigidos

### 1. Host Windows sem qualquer acesso à rede do laboratório (Npcap ausente)

**Sintoma:** o roteador `CD-SP1-CR001` tinha internet plena (`ping 8.8.8.8` 100% de
sucesso), mas o host Windows não conseguia pingar nem o próprio roteador, mesmo estando
na mesma sub-rede da VMnet8.

**Diagnóstico:** o nó `Cloud1` do GNS3, quando roda no servidor local (Windows) em vez de
dentro da GNS3 VM, depende do **Npcap** para capturar/injetar pacotes na placa de rede
real (VMware Network Adapter VMnet8). Sem esse driver instalado, a "ponte" entre a
topologia e a placa física simplesmente não existe do lado do Windows.

**Correção:** instalação do Npcap (com "WinPcap API-compatible Mode" habilitado) e
reinício da máquina.

### 2. Adaptador de loopback conflitando com a rota de gerência

**Sintoma:** mesmo com a rota estática correta cadastrada (`192.168.50.0/24` via
`192.168.113.10`), o tráfego para os switches (`192.168.50.6/7/8`) não saía pelo caminho
esperado.

**Diagnóstico:** `route print` revelou um **"Microsoft KM-TEST Loopback Adapter"** — um
adaptador de teste do Windows, sem relação com este laboratório — configurado
manualmente com IP estático `192.168.50.100/24`, a mesma sub-rede do laboratório.
Isso criava uma rota concorrente "diretamente conectada" que competia com a rota
estática legítima.

**Correção:** desabilitação do adaptador (`ncpa.cpl` → botão direito → Desabilitar).

### 3. NAT do roteador "mordendo" tráfego de gerência (causa raiz mais sutil)

**Sintoma:** depois de resolver os dois problemas acima, o `ping` do host/VM para os
switches respondia, mas com um comportamento bizarro: toda resposta chegava marcada como
`(DIFFERENT ADDRESS!)`, sempre com o IP de origem `192.168.113.10` (o próprio roteador),
mesmo pingando `192.168.50.6`, `.7`, `.8` ou `.1`.

**Diagnóstico:** a configuração original de NAT no `CR001` fazia overload de **qualquer**
tráfego originado nas redes internas (`192.168.10/20/50.0/24`) saindo pela interface
`GigabitEthernet1/0`, sem considerar o destino:

```
access-list 1 permit 192.168.10.0 0.0.0.255
access-list 1 permit 192.168.20.0 0.0.0.255
access-list 1 permit 192.168.50.0 0.0.0.255
ip nat inside source list 1 interface GigabitEthernet1/0 overload
```

Como o único caminho até os switches (a partir do host/VM) é entrando pela própria
`Gi1/0`, a **resposta** dos switches (origem `192.168.50.x`) saindo de volta por essa
mesma interface batia na regra de NAT — mesmo não sendo tráfego destinado à internet — e
tinha a origem reescrita para `192.168.113.10`.

**Correção:** substituição da ACL simples por uma ACL estendida que nega NAT
explicitamente para qualquer destino dentro das próprias redes do laboratório, e só
permite NAT para o restante (internet):

```
no ip nat inside source list 1 interface GigabitEthernet1/0 overload
no access-list 1

ip access-list extended NAT_SOMENTE_INTERNET
 deny ip any 192.168.10.0 0.0.0.255
 deny ip any 192.168.20.0 0.0.0.255
 deny ip any 192.168.50.0 0.0.0.255
 deny ip any 192.168.113.0 0.0.0.255
 permit ip 192.168.10.0 0.0.0.255 any
 permit ip 192.168.20.0 0.0.0.255 any
 permit ip 192.168.50.0 0.0.0.255 any

ip nat inside source list NAT_SOMENTE_INTERNET interface GigabitEthernet1/0 overload
```

**Resultado confirmado:** depois dessa correção, `ping 192.168.50.6` da VM passou a
responder com a origem correta (`from 192.168.50.6`, sem mais `DIFFERENT ADDRESS`), e o
`ping 8.8.8.8` do roteador continuou funcionando — a internet não foi afetada.

### 4. SSH desabilitado/chave ausente nos switches após reinícios

**Sintoma:** `Connection refused` na porta 22 em todos os três switches.

**Diagnóstico:** `show ip ssh` mostrava `SSH Disabled` e `IOS Keys ... NONE` no SW001.
A causa mais provável: os nós foram reiniciados (stop/start) diversas vezes ao longo do
dia para tentar corrigir outros problemas (túnel da GNS3 VM, convergência de STP), e a
chave RSA — que precisa ser gerada manualmente em cada boot se não persistida
corretamente — não sobreviveu a algum desses ciclos, apesar do `write memory` anterior.

**Correção (aplicada no SW001 e no CSW001):**
```
ip domain name lab.local
crypto key generate rsa general-keys modulus 1024
ip ssh version 2
line vty 0 4
 transport input ssh
 login local
end
write memory
```

---

## Problema não resolvido: reset de conexão na camada de transporte

### Sintoma

Depois de corrigir os quatro problemas acima, a porta 22 (SSH) e a porta 23 (Telnet) dos
switches passaram a aceitar a conexão TCP (`Connection established`), mas a sessão é
derrubada (`Connection reset by peer`) segundos depois, quase sempre antes de qualquer
troca de dados de aplicação se completar. O comportamento é **inconsistente**: a mesma
tentativa, repetida, às vezes progride um pouco mais antes de cair, às vezes falha na
hora.

### O que foi descartado, com evidência

| Hipótese testada | Evidência que descartou |
|---|---|
| Rota/firewall do Windows | `route print` e ARP confirmaram caminho correto; firewall desligado não mudou nada |
| Captura de pacotes (Npcap) | Resolvido (problema nº 1); não explicava a instabilidade que persistiu depois |
| NAT "mordendo" o tráfego | Resolvido (problema nº 3); ping voltou ao normal, mas SSH/Telnet continuaram falhando |
| Sobrecarga de CPU da GNS3 VM | `top` mostrou `load average: 0.06` (praticamente ocioso) no momento de uma falha — descartado |
| Chave RSA ausente/algoritmo de criptografia incompatível | Testado com `ssh -oKexAlgorithms=+diffie-hellman-group1-sha1` forçando algoritmo legado — mesmo assim `Connection reset` |
| Linhas VTY sem Telnet habilitado | `transport input telnet ssh` configurado; conexão TCP aceita normalmente, falha é depois disso |
| Usuário/autenticação | `username admin secret ...` confirmado presente; o reset acontece antes da troca de credenciais |
| `debug ip ssh` no switch | Revelou `SSH0: receive failure - status 0x03` — o switch envia seu banner mas falha ao **receber** o do cliente |
| Traceback do Paramiko | `EOFError` exatamente na primeira escrita do cliente (`packetizer.write_all`) — o socket já não aceita mais dados nesse ponto |
| Offload de checksum TCP (`ethtool -K ... off`) | Desabilitado em `eth0`/`eth1` da GNS3 VM; não mudou o resultado |
| Socket Python puro (sem Netmiko/Paramiko/telnetlib) | `socket.create_connection()` + `recv()`: mesmo `ConnectionResetError` |
| Condição de corrida (ler rápido demais após conectar) | Testado com `time.sleep(1)` antes do primeiro `recv()` — mesmo resultado |
| Cliente `telnet` nativo do Linux via `pexpect` | Também apresentou `Connection closed by foreign host` em uma das tentativas, apesar de ter funcionado em uma tentativa anterior isolada |

### Hipóteses restantes (não confirmadas)

A causa mais provável, dado que **nenhuma camada de software do lado do host/VM**
(Python, Paramiko, telnetlib, nem o binário `telnet` do sistema) se mostrou confiável, é
uma instabilidade na própria pilha TCP/IP da imagem IOU (`i86bi-linux-l2`) sob a
combinação específica de camadas de virtualização deste ambiente (NIC física → VMware
Workstation → GNS3 VM em QEMU → `ubridge` → processo IOU). Imagens IOU de uso doméstico
(fora do canal oficial Cisco) têm histórico conhecido de implementações de rede
simplificadas, com bugs desse tipo sob certas condições de timing ou opções de TCP que
não chegamos a isolar por completo (ex: opções de janela/SACK específicas que o kernel
Linux moderno da GNS3 VM envia por padrão e que essa pilha antiga não trata bem).

### Decisão

Diante do volume de causas eliminadas sem sucesso, e do tempo já investido, a decisão foi
não continuar a depuração em nível de captura de pacote (`tcpdump`/Wireshark seria o
próximo passo natural, mas está além do escopo razoável para este desafio) e seguir com
a entrega em modo simulado — opção explicitamente prevista no enunciado — documentando
esta investigação como evidência do processo de troubleshooting.

---

## O que foi comprovadamente validado no laboratório real

Apesar do transporte de gerência (SSH/Telnet) não ter sido resolvido, o restante da
topologia foi confirmado funcionando de ponta a ponta, com evidência em
[`lab/configs/`](configs/):

- Roteamento inter-VLAN funcionando (subinterfaces 802.1Q no CR001)
- NAT/internet funcionando (`ping 8.8.8.8` 100% do roteador)
- DHCP relay funcionando (leases concedidos aos clientes VLAN 10 e VLAN 20,
  visíveis em `configs/DHCP001.cfg`)
- NTP funcionando (`chronyc clients` mostrando os 4 equipamentos Cisco sincronizando,
  visível em `configs/NTP001.cfg`)
- Trunk e spanning-tree convergindo corretamente entre os três switches

---

## Confirmação do diagnóstico e pivô para roteadores

Depois da investigação acima, um teste decisivo foi feito: um roteador (`R1`), ligado
diretamente ao `Cloud1`, foi configurado com os mesmos passos de sempre (chave RSA, `ip
ssh version 2`, `transport input ssh`) — e o SSH **funcionou de forma estável**, sem
nenhum dos sintomas descritos acima (sem `Connection reset`, sem instabilidade).

Isso confirma o diagnóstico com uma evidência direta: **o ambiente está saudável**
(GNS3 VM, `ubridge`, todas as camadas de virtualização) — o problema é isolado e
específico da implementação de rede da imagem IOU (`i86bi-linux-l2`) usada nos switches,
não algo generalizável ao laboratório inteiro.

### Decisão: substituir os switches por roteadores para os testes de automação

Como o objetivo prático é demonstrar a automação funcionando contra hardware real (não
necessariamente contra um switch especificamente), `CD-SP1-CSW001`, `CD-SP1-SW001` e
`CD-SP1-SW002` foram recriados como **roteadores** na topologia, usando o mesmo padrão
já validado no R1. Cada um recebeu um *bootstrap* mínimo (hostname, chave RSA, SSH) —
ver `lab/configs/CSW001-router-bootstrap.cfg`, `SW001-router-bootstrap.cfg` e
`SW002-router-bootstrap.cfg` — deixando as **subinterfaces de VLAN por conta do próprio
script de automação** (`cli.py --dispositivo router`), em vez de configuradas
manualmente.

Essa escolha tem uma vantagem além de contornar o bug: é uma demonstração mais direta do
que o desafio pede — a automação não só se conecta e valida, mas efetivamente aplica a
configuração de rede (VLANs, agora como subinterfaces 802.1Q) em um dispositivo real, de
ponta a ponta, sem intervenção manual além do bootstrap inicial de acesso.

O módulo de automação de roteador (`src/router_models.py`, `src/router_runner.py`) já
fazia parte do projeto desde antes desta investigação — não foi criado por causa do
bug, apenas passou a ser o caminho principal de validação contra hardware real, em vez
de uma funcionalidade adicional ao lado do switch.

---

## Atualização: causa raiz encontrada com uma imagem IOU diferente

Depois da decisão de pivotar para roteadores, uma nova tentativa foi feita com outra
imagem IOU (`i86bi-linux-l2-ipbasek9-15.1d`, diferente da usada originalmente). O
resultado foi decisivo e **muito mais informativo** que o bug anterior:

- O SSH nativo do Linux negociou normalmente (sem `Connection reset`), mas travou de
  forma limpa e consistente na negociação de algoritmos: `Unable to negotiate ... no
  matching key exchange method found. Their offer: diffie-hellman-group-exchange-sha1,
  diffie-hellman-group14-sha1,diffie-hellman-group1-sha1`.
- Depois de forçar esses algoritmos no cliente (`-oKexAlgorithms=+...`), travou de novo,
  agora na cifra: `no matching cipher found. Their offer: aes128-cbc,3des-cbc,
  aes192-cbc,aes256-cbc`.
- Adicionando também `-oCiphers=+aes128-cbc,...`, a conexão foi **estável em 8 de 8
  tentativas consecutivas**, sem nenhum reset.

### Causa raiz real

Essa imagem tem uma implementação de SSH funcional e normal — só suporta apenas
algoritmos de criptografia antigos (SHA-1 para troca de chave, cifras CBC), removidos
por padrão dos clientes SSH modernos por motivo de segurança. O cliente `ssh` do Linux
ainda tem esses algoritmos disponíveis, só desligados por padrão (religam com uma flag).
Já o **Paramiko 5.0+** (a biblioteca usada pelo Netmiko/Python) **removeu esse código por
completo** — não é uma questão de configuração, a classe que implementa
`diffie-hellman-group1-sha1` simplesmente não existe mais no pacote a partir da versão
5.0.

### Correção

O próprio Netmiko já previa esse cenário: existe um extra oficial, `netmiko[par4]`, que
fixa a dependência em `paramiko>=4.0,<5.0` — a última série que ainda inclui esses
algoritmos, aliás **habilitados por padrão**, sem precisar de nenhuma configuração
adicional no código do projeto. `requirements.txt` foi atualizado:

```
netmiko[par4]>=4.4.0
```

### O que isso significa para o bug original (imagem anterior)

Vale registrar a diferença: o problema investigado nas seções acima (`Connection reset`
logo na troca de banner, antes de qualquer negociação de algoritmo) é **distinto** deste.
Aquele é mais provavelmente um bug real de estabilidade na pilha TCP/SSH da imagem IOU
original usada nos switches — este, causado por uma imagem diferente, era só uma
incompatibilidade de algoritmos entre um SSH antigo (mas funcional) e um cliente Python
moderno demais. As duas imagens IOU tinham, portanto, causas diferentes para o mesmo
sintoma superficial ("não consigo conectar por SSH").

