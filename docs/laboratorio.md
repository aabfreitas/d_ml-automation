# Laboratório

## Topologia

```
   ┌──────────────┐          ┌──────────────────────┐
   │  PC / Host   │──────────│  Switch Cisco        │
   │ 192.168.10.5 │  Fa0/1   │  Vlan1 192.168.10.2  │
   │   /24        │          │  (SSH habilitado)    │
   └──────────────┘          └──────────────────────┘
```

O script roda no host e fala com o switch por SSH na VLAN 1. Qualquer sub-rede serve,
desde que host e switch estejam na mesma e o SSH esteja ativo.

## Packet Tracer

1. Adicionar um **Switch 2960** e um **PC**.
2. Ligar `PC0 Fa0` em `Switch0 Fa0/1` com cabo direto.
3. No PC: IP `192.168.10.5`, máscara `255.255.255.0`.
4. No switch (CLI), preparar o acesso SSH:

```
enable
configure terminal
 hostname Switch
 ip domain-name lab.local
 username admin privilege 15 secret cisco123
 enable secret cisco123
 crypto key generate rsa general-keys modulus 1024
 ip ssh version 2
 interface Vlan1
  ip address 192.168.10.2 255.255.255.0
  no shutdown
 exit
 line vty 0 4
  login local
  transport input ssh
  exec-timeout 0 0
 exit
end
write memory
```

5. Criar a VLAN 99 para que a validação tenha uma divergência real a reportar:

```
configure terminal
 vlan 99
  name VLAN_LEGADO_NAO_DOCUMENTADA
 exit
end
write memory
```

6. Conferir o alcance: `ping 192.168.10.2` a partir do PC.
7. Rodar o script a partir de uma máquina com acesso à rede do laboratório:

```bash
python cli.py --host 192.168.10.2 --usuario admin --senha cisco123 --enable cisco123
```

> O Packet Tracer expõe o SSH apenas dentro da própria simulação. Para acessar de fora,
> use GNS3/EVE-NG, ou rode o modo simulado (`--simular`) e registre as evidências do
> Packet Tracer aplicando a configuração exibida em **Ver comandos**.

## GNS3 / EVE-NG

Mesma preparação, com a imagem **IOSvL2**. A diferença prática é ligar a interface de
gerência do switch a um `cloud`/`NAT` do GNS3, para que o host com o Python alcance
`192.168.10.2` diretamente. A partir daí `python app.py` funciona sem modo simulado.

## Comandos de conferência no switch

```
show vlan brief
show running-config | include hostname
show startup-config | include hostname
show ip ssh
```
