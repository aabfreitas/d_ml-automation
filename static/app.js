"use strict";

const $ = (id) => document.getElementById(id);

const lista = $("vlanLista");
const painelEtapas = $("paineisEtapas");
const painelAlertas = $("paineisAlertas");
const selo = $("seloValidacao");
const consoleSaida = $("saidaConsole");

/* ---------- linhas de VLAN ---------- */

function linhaVlan(id = "", nome = "") {
  const div = document.createElement("div");
  div.className = "vlan-linha";
  div.innerHTML = `
    <input type="number" class="id" min="1" max="4094" placeholder="ID" aria-label="ID da VLAN">
    <input type="text" class="nome" maxlength="32" placeholder="Nome da VLAN" aria-label="Nome da VLAN">
    <button type="button" class="remover" title="Remover VLAN" aria-label="Remover VLAN">&times;</button>`;
  div.querySelector(".id").value = id;
  div.querySelector(".nome").value = nome;
  div.querySelector(".remover").addEventListener("click", () => div.remove());
  return div;
}

function carregarPadrao() {
  lista.innerHTML = "";
  VLANS_PADRAO.forEach((v) => lista.appendChild(linhaVlan(v.id, v.name)));
}

$("btnAddVlan").addEventListener("click", () => lista.appendChild(linhaVlan()));
$("btnRestaurar").addEventListener("click", carregarPadrao);

/* ---------- linhas de subinterface (roteador) ---------- */

const subLista = $("subLista");

function linhaSub(vlanId = "", ip = "", mascara = "255.255.255.0", descricao = "") {
  const div = document.createElement("div");
  div.className = "sub-linha";
  div.innerHTML = `
    <input type="number" class="id" min="1" max="4094" placeholder="VLAN" aria-label="VLAN da subinterface">
    <input type="text" class="ip" placeholder="IP (ex: 192.168.10.1)" aria-label="IP da subinterface">
    <input type="text" class="mascara" placeholder="Máscara" aria-label="Máscara da subinterface">
    <input type="text" class="descricao" placeholder="Descrição (opcional)" aria-label="Descrição da subinterface">
    <button type="button" class="remover" title="Remover subinterface" aria-label="Remover subinterface">&times;</button>`;
  div.querySelector(".id").value = vlanId;
  div.querySelector(".ip").value = ip;
  div.querySelector(".mascara").value = mascara;
  div.querySelector(".descricao").value = descricao;
  div.querySelector(".remover").addEventListener("click", () => div.remove());
  return div;
}

function carregarPadraoSub() {
  subLista.innerHTML = "";
  SUBINTERFACES_PADRAO.forEach((s) => subLista.appendChild(linhaSub(s.vlan_id, s.ip, s.mascara, s.descricao)));
}

$("btnAddSub").addEventListener("click", () => subLista.appendChild(linhaSub()));
$("btnRestaurarSub").addEventListener("click", carregarPadraoSub);

/* ---------- alternância switch / roteador ---------- */

const painelSwitch = $("painelSwitch");
const painelRouter = $("painelRouter");

$("tipoDispositivo").addEventListener("change", (e) => {
  const ehRouter = e.target.value === "router";
  painelSwitch.style.display = ehRouter ? "none" : "";
  painelRouter.style.display = ehRouter ? "" : "none";
  painelEtapas.innerHTML = '<p class="vazio">Nenhuma execução ainda. Confira os dados e escolha uma ação.</p>';
  painelAlertas.innerHTML = '<p class="vazio">A comparação entre o dispositivo e o padrão aparece aqui depois de aplicar ou validar.</p>';
  selo.textContent = "";
  selo.className = "";
  consoleSaida.textContent = "Aguardando execução.";
});

/* ---------- montagem do payload ---------- */

function conexaoAtual() {
  return {
    host: $("host").value.trim(),
    port: Number($("port").value) || 22,
    username: $("username").value.trim(),
    password: $("password").value,
    secret: $("secret").value,
    simulate: $("simulate").checked,
  };
}

function montarPayload() {
  const vlans = [...lista.querySelectorAll(".vlan-linha")]
    .map((l) => ({
      id: l.querySelector(".id").value.trim(),
      name: l.querySelector(".nome").value.trim(),
    }))
    .filter((v) => v.id !== "" || v.name !== "");

  return {
    hostname: $("hostname").value.trim(),
    vlans,
    fazer_backup: $("fazerBackup").checked,
    salvar_nvram: $("salvarNvram").checked,
    conexao: conexaoAtual(),
  };
}

function montarPayloadRouter() {
  const subinterfaces = [...subLista.querySelectorAll(".sub-linha")]
    .map((l) => ({
      vlan_id: l.querySelector(".id").value.trim(),
      ip: l.querySelector(".ip").value.trim(),
      mascara: l.querySelector(".mascara").value.trim(),
      descricao: l.querySelector(".descricao").value.trim(),
    }))
    .filter((s) => s.vlan_id !== "" || s.ip !== "");

  return {
    hostname: $("hostnameRouter").value.trim(),
    interface_fisica: $("interfaceFisica").value.trim(),
    subinterfaces,
    fazer_backup: $("fazerBackupRouter").checked,
    salvar_nvram: $("salvarNvramRouter").checked,
    conexao: conexaoAtual(),
  };
}

/* ---------- renderização ---------- */

function escapar(texto) {
  return String(texto ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function mostrarEtapas(etapas, erro) {
  painelEtapas.innerHTML = "";
  (etapas || []).forEach((e) => {
    const div = document.createElement("div");
    div.className = `etapa ${e.status}`;
    div.innerHTML = `<span class="hora">${escapar(e.horario)}</span>
      <span><strong>${escapar(e.etapa)}</strong> — ${escapar(e.detalhe)}</span>`;
    painelEtapas.appendChild(div);
  });
  if (erro) {
    const div = document.createElement("div");
    div.className = "alerta erro";
    div.style.marginTop = "10px";
    div.textContent = erro;
    painelEtapas.appendChild(div);
  }
  if (!painelEtapas.children.length) {
    painelEtapas.innerHTML = '<p class="vazio">Nenhuma etapa registrada.</p>';
  }
}

function mostrarValidacao(validacao, avisosEntrada) {
  painelAlertas.innerHTML = "";
  selo.textContent = "";
  selo.className = "";

  (avisosEntrada || []).forEach((texto) => {
    const div = document.createElement("div");
    div.className = "alerta aviso";
    div.innerHTML = `<span class="item">entrada</span> — ${escapar(texto)}`;
    painelAlertas.appendChild(div);
  });

  if (!validacao) {
    if (!painelAlertas.children.length) {
      painelAlertas.innerHTML = '<p class="vazio">Sem dados de validação nesta execução.</p>';
    }
    return;
  }

  const estado = !validacao.conforme ? "erro" : validacao.tem_fora_do_padrao ? "aviso" : "ok";
  selo.className = `selo ${estado}`;
  selo.textContent = { ok: "Conforme", aviso: "Fora do padrão", erro: "Divergente" }[estado];

  validacao.alertas.forEach((a) => {
    const div = document.createElement("div");
    div.className = `alerta ${a.severidade}`;
    let html = `<span class="item">${escapar(a.item)}</span> — ${escapar(a.mensagem)}`;
    if (a.esperado || a.encontrado) {
      html += `<div class="diff">esperado: ${escapar(a.esperado)} · encontrado: ${escapar(a.encontrado)}</div>`;
    }
    div.innerHTML = html;
    painelAlertas.appendChild(div);
  });
}

async function carregarBackups() {
  try {
    const dados = await (await fetch("/api/backups")).json();
    const ul = $("listaBackups");
    ul.innerHTML = "";
    $("semBackups").style.display = dados.backups.length ? "none" : "block";
    dados.backups.slice(0, 8).forEach((b) => {
      const li = document.createElement("li");
      li.innerHTML = `<a href="/backups/${encodeURIComponent(b.nome)}">${escapar(b.nome)}</a>
        <span class="meta">${escapar(b.modificado_em)} · ${b.tamanho_bytes} B</span>
        <button type="button" class="restaurar" data-arquivo="${escapar(b.nome)}">Restaurar</button>`;
      ul.appendChild(li);
    });
    ul.querySelectorAll(".restaurar").forEach((btn) =>
      btn.addEventListener("click", () => restaurarBackup(btn.dataset.arquivo, btn))
    );
  } catch (e) {
    /* a lista de backups é acessória; uma falha aqui não interrompe o fluxo */
  }
}

async function restaurarBackup(arquivo, botao) {
  const ehRouter = $("tipoDispositivo").value === "router";
  const confirmado = confirm(
    `Restaurar "${arquivo}"?\n\nIsso vai reenviar essa configuração para o dispositivo ` +
      `${ehRouter ? "roteador" : "switch"} atual (${$("host").value || "(simulado)"}). ` +
      `Um novo backup do estado atual é feito antes, automaticamente.`
  );
  if (!confirmado) return;

  botao.disabled = true;
  botao.textContent = "Restaurando…";
  try {
    const rota = ehRouter ? "/api/restaurar-roteador" : "/api/restaurar";
    const payload = ehRouter
      ? { arquivo, interface_fisica: $("interfaceFisica").value.trim(), conexao: conexaoAtual() }
      : { arquivo, conexao: conexaoAtual() };
    const resp = await fetch(rota, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const dados = await resp.json();

    if (dados.erro && !dados.etapas) {
      painelEtapas.innerHTML = `<div class="alerta erro">${escapar(dados.erro)}</div>`;
      return;
    }
    mostrarEtapas(dados.etapas, dados.erro);
    consoleSaida.textContent = `! restaurado de ${dados.restaurado_de || arquivo}\n\n` + (dados.saida_config || "");
    mostrarValidacao(dados.validacao, dados.avisos_entrada);
    carregarBackups();
    carregarLogs();
  } catch (e) {
    painelEtapas.innerHTML = `<div class="alerta erro">Falha na comunicação com o servidor: ${escapar(e.message)}</div>`;
  } finally {
    botao.disabled = false;
    botao.textContent = "Restaurar";
  }
}

/* ---------- logs de execução ---------- */

async function carregarLogs() {
  try {
    const dados = await (await fetch("/api/logs?limite=30")).json();
    const container = $("tabelaLogs");
    container.innerHTML = "";
    $("semLogs").style.display = dados.execucoes.length ? "none" : "block";
    dados.execucoes.forEach((l) => {
      const div = document.createElement("div");
      div.className = `log-linha ${l.sucesso ? "sucesso" : "falha"}`;
      const contagem = l.alertas
        ? `${l.alertas.ok || 0}ok / ${l.alertas.aviso || 0}aviso / ${l.alertas.erro || 0}erro`
        : "";
      div.innerHTML = `
        <span class="hora">${escapar(l.timestamp || "")}</span>
        <span class="acao">${escapar(l.acao || "")}</span>
        <span class="detalhe" title="${escapar(l.hostname_desejado || "")}">
          [${escapar(l.dispositivo || "")}] ${escapar(l.host || "")} — ${escapar(l.hostname_desejado || "")}
          ${l.erro ? " · " + escapar(l.erro) : l.resumo ? " · " + escapar(l.resumo) : ""}
        </span>
        <span class="contagem">${contagem}</span>`;
      container.appendChild(div);
    });
  } catch (e) {
    /* painel acessório */
  }
}

/* ---------- ações ---------- */

const botoesSwitch = ["btnAplicar", "btnValidar", "btnPrevia"];
const botoesRouter = ["btnAplicarRouter", "btnValidarRouter", "btnPreviaRouter"];
const todosBotoes = [...botoesSwitch, ...botoesRouter];

async function chamar(rota, rotulo, montarPayloadFn, botaoPrincipal) {
  todosBotoes.forEach((b) => ($(b).disabled = true));
  const anterior = $(botaoPrincipal).textContent;
  if (rota.startsWith("/api/aplicar")) $(botaoPrincipal).textContent = "Aplicando…";
  consoleSaida.textContent = `Executando ${rotulo}…`;

  try {
    const resp = await fetch(rota, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(montarPayloadFn()),
    });
    const dados = await resp.json();

    if (dados.erro && !dados.etapas) {
      painelEtapas.innerHTML = `<div class="alerta erro">${escapar(dados.erro)}</div>`;
      consoleSaida.textContent = "A execução foi interrompida.";
      mostrarValidacao(null, dados.avisos_entrada);
      return;
    }

    if (dados.comandos && !dados.etapas) {
      painelEtapas.innerHTML =
        '<p class="vazio">Prévia gerada. Nenhum comando foi enviado ao switch.</p>';
      consoleSaida.textContent = dados.comandos.join("\n");
      mostrarValidacao(null, dados.avisos_entrada);
      return;
    }

    mostrarEtapas(dados.etapas, dados.erro);
    mostrarValidacao(dados.validacao, dados.avisos_entrada);

    const partes = [];
    if (dados.comandos) partes.push("! comandos enviados\n" + dados.comandos.join("\n"));
    if (dados.saida_config) partes.push("\n! resposta do switch\n" + dados.saida_config);
    if (dados.backup) partes.push("\n! backup\n" + dados.backup);
    consoleSaida.textContent = partes.join("\n") || "Nenhuma saída retornada.";

    carregarBackups();
    carregarLogs();
  } catch (e) {
    painelEtapas.innerHTML = `<div class="alerta erro">Falha na comunicação com o servidor: ${escapar(e.message)}</div>`;
  } finally {
    todosBotoes.forEach((b) => ($(b).disabled = false));
    $(botaoPrincipal).textContent = anterior;
  }
}

$("btnAplicar").addEventListener("click", () => chamar("/api/aplicar", "aplicação", montarPayload, "btnAplicar"));
$("btnValidar").addEventListener("click", () => chamar("/api/validar", "validação", montarPayload, "btnValidar"));
$("btnPrevia").addEventListener("click", () => chamar("/api/previa", "prévia", montarPayload, "btnPrevia"));

$("btnAplicarRouter").addEventListener("click", () =>
  chamar("/api/aplicar-roteador", "aplicação", montarPayloadRouter, "btnAplicarRouter")
);
$("btnValidarRouter").addEventListener("click", () =>
  chamar("/api/validar-roteador", "validação", montarPayloadRouter, "btnValidarRouter")
);
$("btnPreviaRouter").addEventListener("click", () =>
  chamar("/api/previa-roteador", "prévia", montarPayloadRouter, "btnPreviaRouter")
);

$("simulate").addEventListener("change", (e) => {
  ["host", "port", "username", "password", "secret"].forEach((id) => {
    $(id).disabled = e.target.checked;
  });
});

carregarPadrao();
carregarPadraoSub();
$("simulate").dispatchEvent(new Event("change"));
carregarBackups();
carregarLogs();
