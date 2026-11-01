// Front-end do controle financeiro: consome a API Python (FastAPI) e desenha tudo com JavaScript puro + Plotly.js.

const $ = (id) => document.getElementById(id);
const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const inteiro = new Intl.NumberFormat("pt-BR");
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const COR = { receita: "#16a34a", despesa: "#ea580c", saldo: "#2563eb" };
const PALETA = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16", "#64748b"];
const CONFIG = { responsive: true, displaylogo: false };
const DIMENSOES = { categoria: "categorias", conta: "contas" };   // filtro -> chave em /api/meta

const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const dataBR = (s) => s.split("-").reverse().join("/");
const rotuloMes = (ym) => { const [y, m] = ym.split("-"); return `${MESES[+m - 1]}/${y.slice(2)}`; };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const estado = {
  meta: null,
  tipo: "",
  status: "",
  pagina: 1,
  linhas: new Map(),
  sel: { categoria: new Set(), conta: new Set() },
  editando: null,
};

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
function parametros(extras = {}) {
  const p = new URLSearchParams();
  if ($("inicio").value) p.set("inicio", $("inicio").value);
  if ($("fim").value) p.set("fim", $("fim").value);
  if (estado.tipo) p.set("tipo", estado.tipo);
  if (estado.status) p.set("status", estado.status);
  const busca = $("busca").value.trim();
  if (busca) p.set("busca", busca);

  for (const [dim, chave] of Object.entries(DIMENSOES)) {
    const opcoes = estado.meta[chave];
    const sel = [...estado.sel[dim]];
    if (sel.length === 0) p.append(dim, "__nenhum__");                 // nada marcado = nenhum resultado
    else if (sel.length < opcoes.length) sel.forEach((v) => p.append(dim, v));
    // tudo marcado = sem filtro
  }
  Object.entries(extras).forEach(([k, v]) => p.set(k, v));
  return p;
}

async function mensagemErro(resp) {
  try {
    const d = await resp.json();
    if (typeof d.detail === "string") return d.detail;
    if (Array.isArray(d.detail)) return d.detail.map((e) => `${e.loc.at(-1)}: ${e.msg}`).join("; ");
  } catch (_) { /* sem corpo JSON */ }
  return `Erro ${resp.status}`;
}

async function chamar(url, opcoes = {}) {
  const resp = await fetch(url, opcoes);
  if (resp.status === 401) {                        // sessão expirada ou não autenticado
    location.href = "/login";
    throw new Error("Sessão expirada. Entre novamente.");
  }
  if (!resp.ok) throw new Error(await mensagemErro(resp));
  return resp.json();
}

const consultar = (caminho, extras = {}) => chamar(`${caminho}?${parametros(extras)}`);
const enviarJson = (url, metodo, corpo) =>
  chamar(url, { method: metodo, headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) });

function avisar(texto, erro = false) {
  const t = $("toast");
  t.textContent = texto;
  t.className = erro ? "toast erro-toast" : "toast";
  t.hidden = false;
  clearTimeout(avisar.timer);
  avisar.timer = setTimeout(() => (t.hidden = true), erro ? 6000 : 3500);
}

// ---------------------------------------------------------------------------
// Estilo dos gráficos (acompanha o tema claro/escuro)
// ---------------------------------------------------------------------------
function estilo(titulo) {
  const css = getComputedStyle(document.documentElement);
  const texto = css.getPropertyValue("--texto").trim();
  const grade = css.getPropertyValue("--borda").trim();
  return {
    title: { text: titulo, font: { size: 14, color: texto }, x: 0.02 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: texto },
    separators: ",.",
    margin: { l: 70, r: 20, t: 44, b: 50 },
    xaxis: { gridcolor: grade },
    yaxis: { gridcolor: grade, tickprefix: "R$ ", tickformat: ",.0f" },
    legend: { orientation: "h", y: -0.2 },
  };
}

// ---------------------------------------------------------------------------
// Renderização
// ---------------------------------------------------------------------------
function variacaoTexto(el, v, subirEhBom) {
  if (v === null || v === undefined) { el.textContent = "sem período anterior"; el.className = ""; return; }
  const sobe = v > 0, desce = v < 0;
  el.textContent = `${sobe ? "▲ +" : desce ? "▼ " : ""}${v.toLocaleString("pt-BR")}% vs. período anterior`;
  el.className = v === 0 ? "" : (sobe === subirEhBom ? "bom" : "ruim");
}

function renderKpis(k, v) {
  $("kpi-receitas").textContent = brl.format(k.receitas);
  $("kpi-despesas").textContent = brl.format(k.despesas);
  const saldo = $("kpi-saldo");
  saldo.textContent = brl.format(k.saldo);
  saldo.className = k.saldo >= 0 ? "receita" : "despesa";
  $("sub-saldo").textContent = k.saldo >= 0 ? "receitas acima das despesas" : "despesas acima das receitas";
  $("kpi-poupanca").textContent = k.taxa_poupanca === null ? "—" : `${k.taxa_poupanca.toLocaleString("pt-BR")}%`;
  $("kpi-apagar").textContent = brl.format(k.a_pagar);
  $("sub-apagar").textContent = k.qtd_a_pagar === 0 ? "nada pendente" : `${k.qtd_a_pagar} conta${k.qtd_a_pagar > 1 ? "s" : ""} em aberto`;
  variacaoTexto($("var-receitas"), v.receitas, true);
  variacaoTexto($("var-despesas"), v.despesas, false);
}

function renderGraficos(d) {
  const x = d.mensal.meses.map(rotuloMes);
  Plotly.react(
    "g-mensal",
    [
      { type: "bar", x, y: d.mensal.receitas, name: "Receitas", marker: { color: COR.receita }, hovertemplate: "Receitas: R$ %{y:,.2f}<extra></extra>" },
      { type: "bar", x, y: d.mensal.despesas, name: "Despesas", marker: { color: COR.despesa }, hovertemplate: "Despesas: R$ %{y:,.2f}<extra></extra>" },
      { type: "scatter", mode: "lines+markers", x, y: d.mensal.acumulado, name: "Saldo acumulado", yaxis: "y2",
        line: { color: COR.saldo, width: 2 }, hovertemplate: "Saldo acumulado: R$ %{y:,.2f}<extra></extra>" },
    ],
    {
      ...estilo("Receitas, despesas e saldo acumulado por mês"),
      barmode: "group",
      yaxis2: { overlaying: "y", side: "right", showgrid: false, tickprefix: "R$ ", tickformat: ",.0f" },
      margin: { l: 70, r: 70, t: 44, b: 50 },
    },
    CONFIG
  );

  const rosca = (id, titulo, dados) =>
    Plotly.react(
      id,
      [{ type: "pie", labels: dados.labels, values: dados.values, hole: 0.5, marker: { colors: PALETA },
         hovertemplate: "%{label}<br>R$ %{value:,.2f} (%{percent})<extra></extra>" }],
      { ...estilo(titulo), margin: { l: 20, r: 20, t: 44, b: 20 }, legend: { orientation: "v" } },
      CONFIG
    );
  rosca("g-categorias", "Despesas por categoria", d.por_categoria);
  rosca("g-contas", "Despesas por conta", d.por_conta);
}

function renderOrcamento(o) {
  $("orc-titulo").textContent = `Orçamento de ${rotuloMes(o.mes)}`;
  $("orc-lista").innerHTML = o.itens.length
    ? o.itens.map((i) => {
        const pct = i.limite > 0 ? (i.gasto / i.limite) * 100 : null;
        const cls = pct === null ? "sem" : pct > 100 ? "estourou" : pct >= 80 ? "alerta" : "";
        const largura = pct === null ? 100 : Math.min(pct, 100);
        const rotulo = pct === null ? "sem meta" : `${Math.round(pct)}%`;
        return `<div class="orc-item">
          <div class="orc-linha"><span>${esc(i.categoria)}</span>
            <span>${brl.format(i.gasto)}${i.limite > 0 ? " / " + brl.format(i.limite) : ""} · ${rotulo}</span></div>
          <div class="barra" role="progressbar" aria-label="${esc(i.categoria)}"><div class="${cls}" style="width:${largura}%"></div></div>
        </div>`;
      }).join("")
    : `<p class="suave">Nenhuma meta definida. Clique em “Editar metas”.</p>`;

  const restante = o.total_limite - o.total_gasto;
  $("orc-total").textContent = o.total_limite > 0
    ? `Total: ${brl.format(o.total_gasto)} de ${brl.format(o.total_limite)} (${restante >= 0 ? "restam " + brl.format(restante) : "estourou em " + brl.format(-restante)})`
    : "";
}

function renderTop(lista) {
  $("top-lista").innerHTML = lista.length
    ? lista.map((t) => `<li><span>${esc(t.descricao)}<small>${esc(t.categoria)} · ${dataBR(t.data)}</small></span><strong>${brl.format(t.valor)}</strong></li>`).join("")
    : `<li class="suave">Sem despesas no período.</li>`;
}

async function renderTabela() {
  const t = await consultar("/api/lancamentos", { pagina: estado.pagina, tamanho: 15 });
  estado.pagina = t.pagina;
  estado.linhas = new Map(t.linhas.map((l) => [l.id, l]));

  $("tabela").querySelector("tbody").innerHTML = t.linhas.length
    ? t.linhas.map((r) => `<tr>
        <td>${dataBR(r.data)}</td>
        <td class="descricao">${esc(r.descricao)}</td>
        <td>${esc(r.categoria)}</td>
        <td>${esc(r.conta)}</td>
        <td class="num ${r.tipo}">${r.tipo === "despesa" ? "− " : "+ "}${brl.format(r.valor)}</td>
        <td><button class="badge ${r.pago ? "ok" : "pend"}" data-acao="pago" data-id="${r.id}" title="Alternar situação">
          ${r.pago ? (r.tipo === "receita" ? "Recebido" : "Pago") : (r.tipo === "receita" ? "A receber" : "Pendente")}</button></td>
        <td class="acoes-linha">
          <button data-acao="editar" data-id="${r.id}" title="Editar" aria-label="Editar">✏️</button>
          <button data-acao="excluir" data-id="${r.id}" title="Excluir" aria-label="Excluir">🗑️</button>
        </td></tr>`).join("")
    : `<tr><td colspan="7" class="vazio-linha">Nenhum lançamento encontrado.</td></tr>`;

  $("pagina-info").textContent = `Página ${t.pagina} de ${t.paginas} · ${inteiro.format(t.total)} lançamento${t.total === 1 ? "" : "s"}`;
  $("ant").disabled = t.pagina <= 1;
  $("prox").disabled = t.pagina >= t.paginas;
  $("baixar").href = `/api/exportar.csv?${parametros()}`;
}

let requisicao = 0;
async function atualizar({ resetarPagina = true } = {}) {
  const id = ++requisicao;
  if (resetarPagina) estado.pagina = 1;
  try {
    const d = await consultar("/api/resumo");
    if (id !== requisicao) return;                  // resposta antiga: ignora

    renderKpis(d.kpis, d.variacao);
    $("aviso").hidden = !d.vazio;
    $("aviso").textContent = "Nenhum lançamento para os filtros selecionados.";
    $("painel").style.display = d.vazio ? "none" : "";
    if (!d.vazio) {
      renderGraficos(d);
      renderOrcamento(d.orcamento);
      renderTop(d.top_despesas);
    }
    await renderTabela();
  } catch (e) {
    console.error(e);
    $("aviso").hidden = false;
    $("aviso").textContent = `Não foi possível carregar os dados: ${e.message}. O servidor Python está rodando?`;
  }
}

// ---------------------------------------------------------------------------
// Filtros
// ---------------------------------------------------------------------------
function criarChips(dim) {
  const caixa = $(`chips-${dim}`);
  caixa.innerHTML = "";
  estado.meta[DIMENSOES[dim]].forEach((valor) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (estado.sel[dim].has(valor) ? " ativo" : "");
    b.textContent = valor;
    b.addEventListener("click", () => {
      const sel = estado.sel[dim];
      sel.has(valor) ? sel.delete(valor) : sel.add(valor);
      b.classList.toggle("ativo", sel.has(valor));
      atualizar();
    });
    caixa.appendChild(b);
  });
}

async function carregarMeta() {
  const antiga = estado.meta;
  estado.meta = await chamar("/api/meta");
  for (const [dim, chave] of Object.entries(DIMENSOES)) {
    const conhecidas = new Set(antiga ? antiga[chave] : []);
    estado.meta[chave].forEach((v) => { if (!conhecidas.has(v)) estado.sel[dim].add(v); });  // novas opções entram marcadas
    criarChips(dim);
  }
}

function marcarSegmento(containerId, botao) {
  document.querySelectorAll(`#${containerId} button`).forEach((b) => b.classList.toggle("ativo", b === botao));
}

function aplicarPreset(nome) {
  const h = new Date(), y = h.getFullYear(), m = h.getMonth();
  let ini, fim = new Date(y, m + 1, 0);
  if (nome === "mes") ini = new Date(y, m, 1);
  else if (nome === "3m") ini = new Date(y, m - 2, 1);
  else if (nome === "6m") ini = new Date(y, m - 5, 1);
  else if (nome === "ano") { ini = new Date(y, 0, 1); fim = new Date(y, 11, 31); }
  else if (estado.meta.data_min) {
    ini = new Date(estado.meta.data_min + "T00:00:00");
    const ultimo = new Date(estado.meta.data_max + "T00:00:00");
    if (ultimo > fim) fim = ultimo;
  } else ini = new Date(y, m, 1);
  $("inicio").value = iso(ini);
  $("fim").value = iso(fim);
  document.querySelectorAll("#presets button").forEach((b) => b.classList.toggle("ativo", b.dataset.preset === nome));
}

function limparFiltros() {
  estado.tipo = "";
  estado.status = "";
  marcarSegmento("seg-tipo", document.querySelector('#seg-tipo button[data-valor=""]'));
  marcarSegmento("seg-status", document.querySelector('#seg-status button[data-valor=""]'));
  $("busca").value = "";
  for (const [dim, chave] of Object.entries(DIMENSOES)) {
    estado.sel[dim] = new Set(estado.meta[chave]);
    criarChips(dim);
  }
  aplicarPreset("6m");
  atualizar();
}

// ---------------------------------------------------------------------------
// Formulário de lançamento
// ---------------------------------------------------------------------------
function preencherListas(tipo) {
  const cats = tipo === "receita" ? estado.meta.categorias_receita : estado.meta.categorias_despesa;
  $("lista-cats").innerHTML = cats.map((c) => `<option value="${esc(c)}">`).join("");
  $("lista-contas").innerHTML = estado.meta.contas.map((c) => `<option value="${esc(c)}">`).join("");
}

function abrirFormulario(lanc = null) {
  estado.editando = lanc;
  const f = $("form-lanc").elements;
  $("dlg-titulo").textContent = lanc ? "Editar lançamento" : "Novo lançamento";
  $("dlg-erro").hidden = true;
  f.tipo.value = lanc ? lanc.tipo : "despesa";
  f.descricao.value = lanc ? lanc.descricao : "";
  f.valor.value = lanc ? lanc.valor : "";
  f.data.value = lanc ? lanc.data : iso(new Date());
  f.categoria.value = lanc ? lanc.categoria : "";
  f.conta.value = lanc ? lanc.conta : "Conta corrente";
  f.pago.checked = lanc ? !!lanc.pago : true;
  preencherListas(f.tipo.value);
  $("dlg").showModal();
  f.descricao.focus();
}

async function salvarLancamento(e) {
  e.preventDefault();
  const f = $("form-lanc").elements;
  const corpo = {
    data: f.data.value,
    descricao: f.descricao.value,
    categoria: f.categoria.value,
    tipo: f.tipo.value,
    valor: parseFloat(f.valor.value),
    conta: f.conta.value || "Conta corrente",
    pago: f.pago.checked,
  };
  try {
    if (estado.editando) await enviarJson(`/api/lancamentos/${estado.editando.id}`, "PUT", corpo);
    else await enviarJson("/api/lancamentos", "POST", corpo);
    $("dlg").close();
    const fora = corpo.data < $("inicio").value || corpo.data > $("fim").value;
    avisar(
      (estado.editando ? "Lançamento atualizado." : "Lançamento adicionado.") +
        (fora ? ` A data (${dataBR(corpo.data)}) está fora do período filtrado, então ele não aparece na lista agora.` : "")
    );
    await carregarMeta();                           // pode ter surgido categoria/conta nova
    await atualizar({ resetarPagina: false });
  } catch (err) {
    $("dlg-erro").textContent = err.message;
    $("dlg-erro").hidden = false;
  }
}

async function acaoTabela(e) {
  const botao = e.target.closest("button[data-acao]");
  if (!botao) return;
  const lanc = estado.linhas.get(Number(botao.dataset.id));
  if (!lanc) return;
  try {
    if (botao.dataset.acao === "editar") {
      abrirFormulario(lanc);
    } else if (botao.dataset.acao === "excluir") {
      if (!confirm(`Excluir "${lanc.descricao}" (${brl.format(lanc.valor)})?`)) return;
      await chamar(`/api/lancamentos/${lanc.id}`, { method: "DELETE" });
      avisar("Lançamento excluído.");
      await carregarMeta();
      await atualizar({ resetarPagina: false });
    } else if (botao.dataset.acao === "pago") {
      await enviarJson(`/api/lancamentos/${lanc.id}/pago`, "PATCH", { pago: !lanc.pago });
      await atualizar({ resetarPagina: false });
    }
  } catch (err) {
    avisar(err.message, true);
  }
}

// ---------------------------------------------------------------------------
// Metas de orçamento
// ---------------------------------------------------------------------------
async function abrirMetas() {
  try {
    const limites = await chamar("/api/orcamento");
    $("metas-erro").hidden = true;
    $("metas-campos").innerHTML = estado.meta.categorias_despesa.map((c) => `
      <label class="meta-linha"><span>${esc(c)}</span>
        <input type="number" min="0" step="10" data-cat="${esc(c)}" value="${limites[c] ?? 0}"></label>`).join("");
    $("dlg-metas").showModal();
  } catch (err) {
    avisar(err.message, true);
  }
}

async function salvarMetas(e) {
  e.preventDefault();
  const corpo = {};
  document.querySelectorAll("#metas-campos input").forEach((i) => { corpo[i.dataset.cat] = parseFloat(i.value) || 0; });
  try {
    await enviarJson("/api/orcamento", "PUT", corpo);
    $("dlg-metas").close();
    avisar("Metas salvas.");
    await atualizar({ resetarPagina: false });
  } catch (err) {
    $("metas-erro").textContent = err.message;
    $("metas-erro").hidden = false;
  }
}

// ---------------------------------------------------------------------------
// Importar / apagar
// ---------------------------------------------------------------------------
async function importarCsv(e) {
  const arquivo = e.target.files[0];
  if (!arquivo) return;
  try {
    const r = await chamar("/api/importar", { method: "POST", headers: { "Content-Type": "text/csv" }, body: await arquivo.text() });
    let msg = `${r.importados} lançamento(s) importado(s).`;
    if (r.ignorados) msg += ` ${r.ignorados} ignorado(s): ${r.erros.join("; ")}`;
    avisar(msg, r.importados === 0);
    await carregarMeta();
    if (r.importados) aplicarPreset("tudo");
    await atualizar();
  } catch (err) {
    avisar(err.message, true);
  } finally {
    e.target.value = "";
  }
}

async function apagarTudo() {
  if (!confirm("Apagar TODOS os lançamentos? Esta ação não pode ser desfeita.")) return;
  try {
    const r = await chamar("/api/lancamentos?confirmar=true", { method: "DELETE" });
    avisar(`${r.apagados} lançamento(s) apagado(s).`);
    await carregarMeta();
    await atualizar();
  } catch (err) {
    avisar(err.message, true);
  }
}

// ---------------------------------------------------------------------------
// Início
// ---------------------------------------------------------------------------
async function iniciar() {
  await carregarMeta();
  aplicarPreset("6m");

  $("presets").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    aplicarPreset(b.dataset.preset);
    atualizar();
  });
  ["inicio", "fim"].forEach((id) => $(id).addEventListener("change", () => {
    document.querySelectorAll("#presets button").forEach((b) => b.classList.remove("ativo"));
    atualizar();
  }));

  for (const [contId, campo] of [["seg-tipo", "tipo"], ["seg-status", "status"]]) {
    $(contId).addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      estado[campo] = b.dataset.valor;
      marcarSegmento(contId, b);
      atualizar();
    });
  }

  let espera;
  $("busca").addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(atualizar, 300); });

  $("limpar").addEventListener("click", limparFiltros);
  $("ant").addEventListener("click", () => { estado.pagina--; renderTabela().catch((e) => avisar(e.message, true)); });
  $("prox").addEventListener("click", () => { estado.pagina++; renderTabela().catch((e) => avisar(e.message, true)); });
  $("tabela").addEventListener("click", acaoTabela);

  $("novo").addEventListener("click", () => abrirFormulario());
  $("form-lanc").addEventListener("submit", salvarLancamento);
  $("dlg-cancelar").addEventListener("click", () => $("dlg").close());
  $("form-lanc").addEventListener("change", (e) => { if (e.target.name === "tipo") preencherListas(e.target.value); });

  $("editar-metas").addEventListener("click", abrirMetas);
  $("form-metas").addEventListener("submit", salvarMetas);
  $("metas-cancelar").addEventListener("click", () => $("dlg-metas").close());

  $("arquivo").addEventListener("change", importarCsv);
  $("apagar").addEventListener("click", apagarTudo);

  // Botão "Sair" só aparece quando o servidor exige senha
  try {
    const sessao = await chamar("/api/sessao");
    $("sair").hidden = !sessao.auth;
    if (sessao.demo) {                              // versão pública: somente leitura
      document.body.classList.add("demo");
      $("faixa-demo").hidden = false;
      if (typeof sessao.repo === "string" && sessao.repo.startsWith("https://")) {
        $("link-repo").href = sessao.repo;
        $("link-repo").hidden = false;
      }
    }
  } catch (_) { /* sem sessão */ }
  $("sair").addEventListener("click", async () => {
    try { await fetch("/api/logout", { method: "POST" }); } finally { location.href = "/login"; }
  });

  // Redesenha os gráficos quando o tema do sistema muda
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => atualizar({ resetarPagina: false }));

  await atualizar();
}

iniciar().catch((e) => {
  console.error(e);
  $("aviso").hidden = false;
  $("aviso").textContent = `Não foi possível carregar o app: ${e.message}. O servidor Python está rodando?`;
});
