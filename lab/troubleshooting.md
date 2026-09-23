# Investigação: conectividade de gerência do laboratório (22-23/09/2026)

Registro técnico da sessão de troubleshooting de rede realizada para executar a
automação Python contra os equipamentos reais do laboratório GNS3. Documenta cada
problema diagnosticado e corrigido ao longo do processo — como evidência da investigação,
não só do resultado final.

## Resumo executivo

Ao todo, **seis problemas de rede distintos** foram identificados e corrigidos: acesso do
host Windows à rede do laboratório (Npcap ausente), um adaptador de loopback conflitando
com a rota de gerência, o NAT do roteador "mordendo" tráfego de gerência, SSH sem chave
após reinícios, uma incompatibilidade de algoritmos criptográficos entre o Paramiko
moderno e o SSH legado do IOS, e um estado interno inconsistente no mecanismo
`ip default-gateway` de um dos switches. No meio do caminho, a imagem IOU usada
originalmente nos switches se mostrou instável a ponto de nunca ter sido resolvida —
levando à troca por uma imagem diferente (`i86bi-linux-l2-ipbasek9-15.1d`), que revelou
os últimos problemas (algoritmo e gateway) mas, uma vez corrigidos, funcionou de forma
estável e confiável.

**Resultado final: a automação foi executada com sucesso contra os quatro dispositivos
reais da topologia** (`CD-SP1-CSW001`, `CD-SP1-SW001`, `CD-SP1-SW002`, `CD-SP1-CR001`) —
não mais em modo simulado. Veja a seção final, "Sucesso: os quatro dispositivos
funcionando com a automação real", para os resultados completos. As evidências gerais do
laboratório (topologia, roteamento, NAT, DHCP relay, NTP) estão documentadas
separadamente em [`lab/README.md`](README.md).

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

---

## Sucesso: os quatro dispositivos funcionando com a automação real

Depois da correção do algoritmo SSH (`netmiko[par4]`), o `CD-SP1-CSW001` (na imagem nova)
foi reencaixado na topologia padrão (`CR001 → CSW001 → SW001/SW002`), e surgiu **mais um**
problema, desta vez de roteamento — documentado abaixo — antes do sucesso final.

### Problema 5: `ip default-gateway` do switch não alcança nada fora da própria sub-rede

**Sintoma:** depois de recabear o CSW001 de volta à topologia normal, ele respondia a
ping para qualquer IP dentro da sua própria sub-rede de gerência (`192.168.50.0/24`) —
inclusive o próprio gateway (`192.168.50.1`) — mas **qualquer coisa fora dessa sub-rede**
(o `Gi1/0` do CR001 em `192.168.113.10`, ou a internet em `8.8.8.8`) dava 100% de perda,
de forma absoluta e repetida em várias tentativas.

**Diagnóstico, passo a passo:**

1. `debug ip packet detail` filtrado por ACL no CR001 confirmou que o roteador recebia,
   processava (NAT, roteamento via RIB) e **efetivamente enviava** o pacote de volta em
   direção ao switch — do ponto de vista do CR001, tudo funcionava.
2. Contadores de interface (`show interfaces ... | include packets input`) confirmaram
   que os pacotes de fato chegavam em cada salto do caminho (VM → CR001 → CSW001).
3. `debug ip icmp` no CSW001 confirmou que ele **gerava e enviava** a resposta
   (`echo reply sent, src 192.168.50.6, dst 192.168.113.128`).
4. Mas o pacote de resposta nunca reaparecia no `debug ip packet` do CR001, mesmo com
   `no ip cef` (para garantir que o debug enxergasse tudo). Ou seja: o switch *achava*
   que tinha enviado, mas o pacote nunca chegava no roteador.
5. Um padrão ficou claro: **todo teste que funcionava tinha destino dentro da própria
   sub-rede do switch; todo teste que falhava tinha destino fora dela** — inclusive um
   `ping 192.168.113.10` direto do CSW001 (sem envolver internet/NAT), que também falhou.

Isso isolou a causa no mecanismo `ip default-gateway` — o caminho simplificado que um
switch L2 (sem `ip routing`) usa para tráfego de gerência destinado a fora da própria
sub-rede. Duas tentativas de correção:

- **Tornar a VLAN 50 nativa no trunk** (`encapsulation dot1Q 50 native` no roteador,
  `switchport trunk native vlan 50` nos switches) — não resolveu sozinho.
- **"Reaplicar" o comando `ip default-gateway`** já existente (`no ip routing` /
  `ip default-gateway 192.168.50.1`, mesmo valor de antes) — **resolveu**. O comando
  aparecia idêntico no `show running-config` antes e depois, sugerindo que havia um
  estado interno (provavelmente o ponteiro ARP/adjacência associado ao gateway) que
  ficou inconsistente em algum momento — possivelmente um efeito colateral de todo o
  recabeamento e reinícios de nós feitos durante os testes anteriores — e que só se
  resolveu forçando o IOS a recalcular esse estado.

### Resultado final: automação executada com sucesso nos quatro dispositivos reais

Com a correção acima, replicada em `CD-SP1-SW001` e `CD-SP1-SW002`, a automação foi
executada de ponta a ponta contra hardware real — não mais simulado:

| Dispositivo | Resultado | Observação |
|---|---|---|
| `CD-SP1-CSW001` | `Resultado: configuração conforme o padrão` | Detectou e alertou uma VLAN 85 "legado" fora do padrão, sem apagá-la |
| `CD-SP1-SW001` | `Resultado: configuração conforme o padrão` | Detectou e alertou uma VLAN 3 "teste" fora do padrão |
| `CD-SP1-SW002` | `Resultado: configuração conforme o padrão` | — |
| `CD-SP1-CR001` | `Resultado: configuração conforme o padrão` | Um segundo teste, com uma subinterface `.77` extra, confirmou o mesmo alerta de "fora do padrão" no roteador |

Todas as execuções fizeram backup automático antes de aplicar, salvaram na NVRAM, e a
validação pós-aplicação confirmou o estado real do equipamento — o fluxo completo
descrito no desafio, de ponta a ponta, contra hardware Cisco de verdade.

