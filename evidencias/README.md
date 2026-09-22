# Evidências

Capturas que comprovam o funcionamento, conforme os entregáveis do desafio.

| Arquivo | O que mostrar |
|---|---|
| `01-frontend.png` | A tela inicial com as três VLANs preenchidas e o hostname |
| `02-execucao.png` | O painel de execução após aplicar, com as cinco etapas concluídas |
| `03-validacao.png` | O painel de validação com os itens OK e o aviso da VLAN fora do padrão |
| `04-switch-vlans.png` | Saída de `show vlan brief` no switch, com as VLANs 10, 20 e 50 |
| `05-switch-hostname.png` | Saída de `show running-config \| include hostname` |
| `06-cli.png` | Saída de `python cli.py` no terminal |
| `07-divergencia.png` | Validação apontando erro: remova a VLAN 20 no switch e rode `--somente-validar` |
| `08-backup.txt` | Conteúdo de um arquivo gerado em `backups/` |

## Como reproduzir a evidência de divergência

```bash
# 1. aplicar normalmente
python cli.py --host 192.168.10.2 --usuario admin --senha cisco123

# 2. no switch, remover uma VLAN à mão
#    conf t / no vlan 20 / end

# 3. validar de novo: o script deve acusar a VLAN 20 ausente e sair com código 1
python cli.py --host 192.168.10.2 --usuario admin --senha cisco123 --somente-validar
echo "codigo de retorno: $?"
```
