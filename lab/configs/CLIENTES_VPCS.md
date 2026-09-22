# CLIENTVL10 e CLIENTVL20 — clientes VPCS

Os dois são hosts VPCS simples (não têm shell completo, só o console do
VPCS), usados para comprovar que o DHCP relay e o roteamento inter-VLAN
funcionam ponta a ponta.

| Cliente | Porta no switch | VLAN | Obteve por DHCP |
|---|---|---|---|
| CLIENTVL10 | SW001 e0/2 | 10 (VLAN_DADOS) | 192.168.10.160 |
| CLIENTVL20 | SW002 e0/2 | 20 (VLAN_VOZ) | 192.168.20.161 |

## Configuração

O template padrão do VPCS (`CLIENTVL10_startup.vpc`, `CLIENTVL20_startup.vpc`)
vem só com o nome do host — o IP é pedido interativamente no console:

```
set pcname CLIENTVL10
ip dhcp
save
```

`ip dhcp` dispara o broadcast DHCP que percorre toda a cadeia documentada em
`DHCP001.cfg` (cliente → switch de acesso → trunk → CSW001 → trunk → CR001
→ `ip helper-address` → servidor DHCP na VLAN 50). O `save` grava o comando
no arquivo de startup do VPCS, para não precisar digitar de novo a cada vez
que o nó reinicia.

## Evidência de que funcionou

As leases concedidas (visíveis em `DHCP001.cfg`, arquivo
`/var/lib/misc/dnsmasq.leases`) confirmam os IPs acima — é a prova mais
direta de que o roteamento inter-VLAN, o trunk entre os três switches e o
`ip helper-address` no roteador estão todos funcionando juntos.
