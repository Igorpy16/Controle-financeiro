"""Controle financeiro pessoal — API (FastAPI + SQLite).

Também serve o front-end (pasta ./static).
Execute com:  python -m uvicorn main:app --reload
"""

import calendar
import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

BASE = Path(__file__).parent
# DEMO_MODE=1: versão pública de demonstração — somente leitura, sem login, só dados fictícios.
# Usa SEMPRE um banco temporário novo e nunca abre o banco real (FINANCAS_DB é ignorada).
DEMO = os.environ.get("DEMO_MODE") == "1"
if DEMO:
    DB = Path(tempfile.gettempdir()) / "financas_demo.db"
    DB.unlink(missing_ok=True)
else:
    DB = Path(os.environ.get("FINANCAS_DB", BASE / "financas.db"))

CAT_DESPESA = ["Moradia", "Alimentação", "Transporte", "Saúde", "Lazer", "Educação", "Assinaturas", "Outros"]
CAT_RECEITA = ["Salário", "Freelance", "Investimentos", "Outros"]
CONTAS = ["Conta corrente", "Cartão de crédito", "Poupança", "Dinheiro"]
ORCAMENTO_PADRAO = {
    "Moradia": 3000, "Alimentação": 1800, "Transporte": 600, "Saúde": 800,
    "Lazer": 400, "Educação": 300, "Assinaturas": 150, "Outros": 300,
}

app = FastAPI(title="Controle Financeiro — API")


# ----------------------------------------------------------------------------
# Autenticação (senha única, sessão em cookie assinado)
#
#   APP_PASSWORD  senha de acesso. Sem ela o app fica aberto (uso local).
#   REQUIRE_AUTH  =1 recusa iniciar sem APP_PASSWORD (o Dockerfile já define).
#   SECRET_KEY    (opcional) chave para assinar as sessões; padrão = a senha.
# ----------------------------------------------------------------------------
SENHA = "" if DEMO else os.environ.get("APP_PASSWORD", "")
AUTH_ATIVA = bool(SENHA)
REPO_URL = os.environ.get("REPO_URL", "").strip()
if not REPO_URL.startswith("https://"):
    REPO_URL = ""
if DEMO:
    print("MODO DEMONSTRAÇÃO: somente leitura, dados fictícios, sem login.")
elif os.environ.get("REQUIRE_AUTH") == "1" and not AUTH_ATIVA:
    raise RuntimeError("Defina a variável de ambiente APP_PASSWORD (a senha de acesso ao app).")
elif not AUTH_ATIVA:
    print("AVISO: APP_PASSWORD não definida — o app está SEM LOGIN. Use assim só no seu computador.")

LIMITE_DEMO = 300                        # requisições à API por minuto, por IP (só no modo demo)
_acessos: dict[str, list[float]] = {}


def _limite_demo(ip: str) -> bool:
    agora = time.time()
    if len(_acessos) > 2000:
        _acessos.clear()
    recentes = [t for t in _acessos.get(ip, []) if agora - t < 60]
    recentes.append(agora)
    _acessos[ip] = recentes
    return len(recentes) > LIMITE_DEMO

CHAVE = (os.environ.get("SECRET_KEY") or SENHA).encode()
COOKIE = "sessao"
DURACAO_SESSAO = 30 * 24 * 3600          # 30 dias
PUBLICAS = {"/login", "/api/login"}
MAX_FALHAS, JANELA_FALHAS = 5, 15 * 60   # 5 erros de senha a cada 15 min, por IP
_falhas: dict[str, list[float]] = {}


def _assinar(expira: int) -> str:
    return hmac.new(CHAVE, f"sessao:{expira}".encode(), hashlib.sha256).hexdigest()


def criar_token() -> str:
    expira = int(time.time()) + DURACAO_SESSAO
    return f"{expira}.{_assinar(expira)}"


def sessao_valida(token: str | None) -> bool:
    if not token:
        return False
    texto, _, assinatura = token.partition(".")
    if not (texto.isascii() and texto.isdigit()):
        return False
    expira = int(texto)
    return expira > time.time() and hmac.compare_digest(assinatura, _assinar(expira))


@app.middleware("http")
async def protecao(request: Request, call_next):
    caminho = request.url.path
    resposta = None
    if DEMO and caminho.startswith("/api/"):
        if request.method not in ("GET", "HEAD", "OPTIONS") and caminho not in ("/api/login", "/api/logout"):
            resposta = JSONResponse(
                {"detail": "Modo demonstração: somente leitura. Nada pode ser alterado."}, status_code=403
            )
        elif _limite_demo(request.client.host if request.client else "?"):
            resposta = JSONResponse({"detail": "Muitas requisições. Aguarde um instante."}, status_code=429)
    if resposta is None:
        if AUTH_ATIVA and caminho not in PUBLICAS and not sessao_valida(request.cookies.get(COOKIE)):
            if caminho.startswith("/api/"):
                resposta = JSONResponse({"detail": "Não autenticado"}, status_code=401)
            else:
                resposta = RedirectResponse("/login", status_code=303)
        else:
            resposta = await call_next(request)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    resposta.headers["Referrer-Policy"] = "same-origin"
    if caminho.startswith("/api/"):
        resposta.headers["Cache-Control"] = "no-store"
    return resposta


class LoginIn(BaseModel):
    senha: str = Field(max_length=200)


@app.post("/api/login")
def api_login(corpo: LoginIn, request: Request):
    if not AUTH_ATIVA:
        return {"ok": True}
    ip = request.client.host if request.client else "?"
    agora = time.time()
    if len(_falhas) > 1000:
        _falhas.clear()
    recentes = [t for t in _falhas.get(ip, []) if agora - t < JANELA_FALHAS]
    if len(recentes) >= MAX_FALHAS:
        _falhas[ip] = recentes
        raise HTTPException(429, "Muitas tentativas. Aguarde alguns minutos e tente de novo.")
    if not hmac.compare_digest(corpo.senha.encode(), SENHA.encode()):
        recentes.append(agora)
        _falhas[ip] = recentes
        raise HTTPException(401, "Senha incorreta.")
    _falhas.pop(ip, None)
    resposta = JSONResponse({"ok": True})
    resposta.set_cookie(
        COOKIE, criar_token(), max_age=DURACAO_SESSAO,
        httponly=True, samesite="lax", secure=request.url.scheme == "https",
    )
    return resposta


@app.post("/api/logout")
def api_logout():
    resposta = JSONResponse({"ok": True})
    resposta.delete_cookie(COOKIE)
    return resposta


@app.get("/api/sessao")
def api_sessao():
    return {"auth": AUTH_ATIVA, "demo": DEMO, "repo": REPO_URL if DEMO else ""}


@app.get("/login", include_in_schema=False)
def pagina_login(request: Request):
    if not AUTH_ATIVA or sessao_valida(request.cookies.get(COOKIE)):
        return RedirectResponse("/", status_code=303)
    return FileResponse(BASE / "static" / "login.html")


# ----------------------------------------------------------------------------
# Banco de dados
# ----------------------------------------------------------------------------
@contextmanager
def conexao():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def semear_demo(con: sqlite3.Connection) -> None:
    """Cria 6 meses de lançamentos de exemplo (só na primeira execução)."""
    rng = np.random.default_rng(7)
    hoje = date.today()
    linhas = []

    def add(d, descricao, categoria, tipo, valor, conta, pago=None):
        if pago is None:
            pago = d <= hoje
        linhas.append((d.isoformat(), str(descricao), categoria, tipo, round(float(valor), 2), conta, int(pago)))

    for k in range(5, -1, -1):
        ano, mes = hoje.year, hoje.month - k
        while mes <= 0:
            mes += 12
            ano -= 1
        ultimo = calendar.monthrange(ano, mes)[1]
        atual = k == 0

        def dia(n):
            return date(ano, mes, min(n, ultimo))

        cc, cartao = "Conta corrente", "Cartão de crédito"

        # Receitas
        add(dia(5), "Salário", "Salário", "receita", 8500, cc)
        add(dia(1), "Rendimentos", "Investimentos", "receita", rng.uniform(170, 270), "Poupança")
        if rng.random() < 0.45:
            add(dia(int(rng.integers(12, 26))), "Projeto freelance", "Freelance", "receita", rng.uniform(1200, 2600), cc)

        # Moradia
        add(dia(10), "Aluguel", "Moradia", "despesa", 2200, cc)
        add(dia(10), "Condomínio", "Moradia", "despesa", 480, cc)
        add(dia(15), "Energia elétrica", "Moradia", "despesa", rng.uniform(150, 260), cc, pago=False if atual else None)
        add(dia(12), "Internet", "Moradia", "despesa", 120, cc, pago=False if atual else None)

        # Alimentação
        for n in (3, 10, 17, 24):
            add(dia(n + int(rng.integers(0, 3))), "Supermercado", "Alimentação", "despesa", rng.uniform(220, 460), cartao)
        for _ in range(int(rng.integers(3, 6))):
            nome = rng.choice(["Restaurante", "Lanche", "Delivery", "Padaria"])
            add(dia(int(rng.integers(1, 29))), nome, "Alimentação", "despesa", rng.uniform(35, 140), cartao)

        # Transporte
        for _ in range(2):
            add(dia(int(rng.integers(1, 29))), "Combustível", "Transporte", "despesa", rng.uniform(180, 260), cartao)
        for _ in range(3):
            add(dia(int(rng.integers(1, 29))), "Aplicativo de transporte", "Transporte", "despesa", rng.uniform(18, 48), cartao)

        # Saúde
        add(dia(8), "Plano de saúde", "Saúde", "despesa", 520, cc)
        add(dia(6), "Academia", "Saúde", "despesa", 110, cartao)
        for _ in range(int(rng.integers(1, 3))):
            add(dia(int(rng.integers(1, 29))), "Farmácia", "Saúde", "despesa", rng.uniform(40, 150), cartao)

        # Assinaturas, lazer, educação, outros
        add(dia(20), "Streaming de vídeo", "Assinaturas", "despesa", 55, cartao)
        add(dia(20), "Streaming de música", "Assinaturas", "despesa", 22, cartao)
        for _ in range(int(rng.integers(1, 4))):
            nome = rng.choice(["Cinema", "Show", "Passeio", "Bar com amigos"])
            add(dia(int(rng.integers(1, 29))), nome, "Lazer", "despesa", rng.uniform(40, 160), cartao)
        if rng.random() < 0.4:
            add(dia(int(rng.integers(1, 29))), "Curso online", "Educação", "despesa", rng.uniform(150, 400), cartao)
        for _ in range(int(rng.integers(1, 3))):
            add(dia(int(rng.integers(1, 29))), "Compras diversas", "Outros", "despesa", rng.uniform(60, 320), cartao)

    con.executemany(
        "INSERT INTO lancamentos (data, descricao, categoria, tipo, valor, conta, pago) VALUES (?,?,?,?,?,?,?)",
        linhas,
    )


def iniciar_banco() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with conexao() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS lancamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                descricao TEXT NOT NULL,
                categoria TEXT NOT NULL,
                tipo TEXT NOT NULL CHECK (tipo IN ('receita', 'despesa')),
                valor REAL NOT NULL CHECK (valor > 0),
                conta TEXT NOT NULL DEFAULT 'Conta corrente',
                pago INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_lancamentos_data ON lancamentos (data);
            CREATE TABLE IF NOT EXISTS orcamento (
                categoria TEXT PRIMARY KEY,
                limite REAL NOT NULL
            );
            """
        )
        if con.execute("PRAGMA user_version").fetchone()[0] == 0:
            if DEMO or os.environ.get("SEMEAR_DEMO", "1") != "0":   # SEMEAR_DEMO=0 → começa sem dados de exemplo
                semear_demo(con)
            con.executemany(
                "INSERT OR IGNORE INTO orcamento (categoria, limite) VALUES (?, ?)", list(ORCAMENTO_PADRAO.items())
            )
            con.execute("PRAGMA user_version = 1")


iniciar_banco()


# ----------------------------------------------------------------------------
# Filtros compartilhados
# ----------------------------------------------------------------------------
def filtros(
    inicio: str | None = None,
    fim: str | None = None,
    tipo: str | None = None,
    status: str | None = None,
    busca: str | None = None,
    categoria: list[str] | None = Query(None),
    conta: list[str] | None = Query(None),
) -> dict:
    for nome, valor in (("inicio", inicio), ("fim", fim)):
        if valor:
            try:
                date.fromisoformat(valor)
            except ValueError:
                raise HTTPException(422, f"Data inválida em '{nome}': use AAAA-MM-DD")
    if inicio and fim and inicio > fim:
        raise HTTPException(422, "A data inicial é maior que a final")
    return {
        "inicio": inicio, "fim": fim, "tipo": tipo, "status": status,
        "busca": busca, "categoria": categoria, "conta": conta,
    }


def consultar(f: dict, **mudar) -> pd.DataFrame:
    """Lançamentos que atendem aos filtros (mais recentes primeiro)."""
    g = {**f, **mudar}
    where, params = ["1=1"], []
    if g.get("inicio"):
        where.append("data >= ?")
        params.append(g["inicio"])
    if g.get("fim"):
        where.append("data <= ?")
        params.append(g["fim"])
    if g.get("tipo") in ("receita", "despesa"):
        where.append("tipo = ?")
        params.append(g["tipo"])
    if g.get("status") == "pago":
        where.append("pago = 1")
    elif g.get("status") == "pendente":
        where.append("pago = 0")
    if g.get("busca"):
        where.append("descricao LIKE ?")
        params.append(f"%{g['busca']}%")
    for coluna in ("categoria", "conta"):
        valores = g.get(coluna)
        if valores is not None:
            if not valores:
                where.append("0 = 1")
            else:
                where.append(f"{coluna} IN ({','.join('?' * len(valores))})")
                params.extend(valores)
    with conexao() as con:
        return pd.read_sql_query(
            f"SELECT * FROM lancamentos WHERE {' AND '.join(where)} ORDER BY data DESC, id DESC",
            con,
            params=params,
        )


def somar(df: pd.DataFrame, tipo: str) -> float:
    return float(df.loc[df["tipo"] == tipo, "valor"].sum())


def variacao(atual: float, anterior: float):
    return round((atual / anterior - 1) * 100, 1) if anterior > 0 else None


def uniao(padrao: list[str], extras: list[str]) -> list[str]:
    return padrao + sorted(set(extras) - set(padrao))


# ----------------------------------------------------------------------------
# Modelos
# ----------------------------------------------------------------------------
class LancamentoIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    data: date
    descricao: str = Field(min_length=1, max_length=120)
    categoria: str = Field(min_length=1, max_length=60)
    tipo: Literal["receita", "despesa"]
    valor: float = Field(gt=0, lt=1e10)
    conta: str = Field(default="Conta corrente", min_length=1, max_length=60)
    pago: bool = True


class PagoIn(BaseModel):
    pago: bool


def buscar_lancamento(con: sqlite3.Connection, id_: int) -> dict:
    linha = con.execute("SELECT * FROM lancamentos WHERE id = ?", (id_,)).fetchone()
    if linha is None:
        raise HTTPException(404, "Lançamento não encontrado")
    return dict(linha)


# ----------------------------------------------------------------------------
# Endpoints: metadados
# ----------------------------------------------------------------------------
@app.get("/api/meta")
def api_meta():
    with conexao() as con:
        cats_r = [r[0] for r in con.execute("SELECT DISTINCT categoria FROM lancamentos WHERE tipo='receita'")]
        cats_d = [r[0] for r in con.execute("SELECT DISTINCT categoria FROM lancamentos WHERE tipo='despesa'")]
        contas = [r[0] for r in con.execute("SELECT DISTINCT conta FROM lancamentos")]
        data_min, data_max = con.execute("SELECT MIN(data), MAX(data) FROM lancamentos").fetchone()
    cat_r, cat_d = uniao(CAT_RECEITA, cats_r), uniao(CAT_DESPESA, cats_d)
    return {
        "categorias_receita": cat_r,
        "categorias_despesa": cat_d,
        "categorias": uniao(CAT_DESPESA + CAT_RECEITA, cats_r + cats_d),
        "contas": uniao(CONTAS, contas),
        "data_min": data_min,
        "data_max": data_max,
    }


# ----------------------------------------------------------------------------
# Endpoints: resumo do dashboard
# ----------------------------------------------------------------------------
def calcular_orcamento(mes_ref: str) -> dict:
    gastos_df = consultar({}, inicio=f"{mes_ref}-01", fim=f"{mes_ref}-31", tipo="despesa")
    gastos = gastos_df.groupby("categoria")["valor"].sum().to_dict()
    with conexao() as con:
        limites = {r["categoria"]: r["limite"] for r in con.execute("SELECT categoria, limite FROM orcamento")}
    itens = []
    for cat in set(limites) | set(gastos):
        limite, gasto = float(limites.get(cat, 0)), float(gastos.get(cat, 0))
        if limite > 0 or gasto > 0:
            itens.append({"categoria": cat, "limite": limite, "gasto": round(gasto, 2)})
    itens.sort(key=lambda i: (i["gasto"] / i["limite"]) if i["limite"] > 0 else 999, reverse=True)
    return {
        "mes": mes_ref,
        "itens": itens,
        "total_limite": sum(i["limite"] for i in itens),
        "total_gasto": round(sum(i["gasto"] for i in itens), 2),
    }


@app.get("/api/resumo")
def api_resumo(f: dict = Depends(filtros)):
    df = consultar(f)
    receitas, despesas = somar(df, "receita"), somar(df, "despesa")
    saldo = receitas - despesas
    pendentes = df[(df["tipo"] == "despesa") & (df["pago"] == 0)]

    kpis = {
        "receitas": round(receitas, 2),
        "despesas": round(despesas, 2),
        "saldo": round(saldo, 2),
        "taxa_poupanca": round(saldo / receitas * 100, 1) if receitas > 0 else None,
        "a_pagar": round(float(pendentes["valor"].sum()), 2),
        "qtd_a_pagar": int(len(pendentes)),
    }

    # variação vs. período anterior de mesma duração
    var = {"receitas": None, "despesas": None}
    if f["inicio"] and f["fim"]:
        ini, fim = date.fromisoformat(f["inicio"]), date.fromisoformat(f["fim"])
        duracao = (fim - ini).days + 1
        ant_fim = ini - timedelta(days=1)
        ant_ini = ant_fim - timedelta(days=duracao - 1)
        ant = consultar(f, inicio=ant_ini.isoformat(), fim=ant_fim.isoformat())
        var = {
            "receitas": variacao(receitas, somar(ant, "receita")),
            "despesas": variacao(despesas, somar(ant, "despesa")),
        }

    if df.empty:
        return {"vazio": True, "kpis": kpis, "variacao": var}

    # evolução mensal
    d = df.assign(mes=pd.to_datetime(df["data"]).dt.to_period("M"))
    if f["inicio"] and f["fim"]:
        p0, p1 = pd.Period(f["inicio"], "M"), pd.Period(f["fim"], "M")
    else:
        p0, p1 = d["mes"].min(), d["mes"].max()
    meses = pd.period_range(p0, p1, freq="M")
    piv = (
        d.pivot_table(index="mes", columns="tipo", values="valor", aggfunc="sum", fill_value=0)
        .reindex(meses, fill_value=0)
    )
    for t in ("receita", "despesa"):
        if t not in piv.columns:
            piv[t] = 0.0
    saldo_mensal = piv["receita"] - piv["despesa"]

    despesas_df = df[df["tipo"] == "despesa"]
    por_categoria = despesas_df.groupby("categoria")["valor"].sum().sort_values(ascending=False).round(2)
    por_conta = despesas_df.groupby("conta")["valor"].sum().sort_values(ascending=False).round(2)
    top = despesas_df.nlargest(5, "valor")[["data", "descricao", "categoria", "valor"]]

    mes_ref = (f["fim"] or df["data"].max())[:7]

    return {
        "vazio": False,
        "kpis": kpis,
        "variacao": var,
        "mensal": {
            "meses": [str(m) for m in meses],
            "receitas": piv["receita"].round(2).tolist(),
            "despesas": piv["despesa"].round(2).tolist(),
            "saldo": saldo_mensal.round(2).tolist(),
            "acumulado": saldo_mensal.cumsum().round(2).tolist(),
        },
        "por_categoria": {"labels": por_categoria.index.tolist(), "values": por_categoria.tolist()},
        "por_conta": {"labels": por_conta.index.tolist(), "values": por_conta.tolist()},
        "top_despesas": json.loads(top.to_json(orient="records", force_ascii=False)),
        "orcamento": calcular_orcamento(mes_ref),
    }


# ----------------------------------------------------------------------------
# Endpoints: lançamentos (CRUD)
# ----------------------------------------------------------------------------
@app.get("/api/lancamentos")
def api_listar(f: dict = Depends(filtros), pagina: int = 1, tamanho: int = 15):
    df = consultar(f)
    tamanho = max(1, min(tamanho, 200))
    total = len(df)
    paginas = max(1, -(-total // tamanho))
    pagina = max(1, min(pagina, paginas))
    parte = df.iloc[(pagina - 1) * tamanho : pagina * tamanho]
    return {
        "total": total,
        "pagina": pagina,
        "paginas": paginas,
        "linhas": json.loads(parte.to_json(orient="records", force_ascii=False)),
    }


@app.post("/api/lancamentos", status_code=201)
def api_criar(corpo: LancamentoIn):
    with conexao() as con:
        cur = con.execute(
            "INSERT INTO lancamentos (data, descricao, categoria, tipo, valor, conta, pago) VALUES (?,?,?,?,?,?,?)",
            (corpo.data.isoformat(), corpo.descricao, corpo.categoria, corpo.tipo,
             round(corpo.valor, 2), corpo.conta, int(corpo.pago)),
        )
        return buscar_lancamento(con, cur.lastrowid)


@app.put("/api/lancamentos/{id_}")
def api_atualizar(id_: int, corpo: LancamentoIn):
    with conexao() as con:
        buscar_lancamento(con, id_)
        con.execute(
            "UPDATE lancamentos SET data=?, descricao=?, categoria=?, tipo=?, valor=?, conta=?, pago=? WHERE id=?",
            (corpo.data.isoformat(), corpo.descricao, corpo.categoria, corpo.tipo,
             round(corpo.valor, 2), corpo.conta, int(corpo.pago), id_),
        )
        return buscar_lancamento(con, id_)


@app.patch("/api/lancamentos/{id_}/pago")
def api_pago(id_: int, corpo: PagoIn):
    with conexao() as con:
        buscar_lancamento(con, id_)
        con.execute("UPDATE lancamentos SET pago = ? WHERE id = ?", (int(corpo.pago), id_))
        return buscar_lancamento(con, id_)


@app.delete("/api/lancamentos/{id_}")
def api_excluir(id_: int):
    with conexao() as con:
        buscar_lancamento(con, id_)
        con.execute("DELETE FROM lancamentos WHERE id = ?", (id_,))
    return {"ok": True}


@app.delete("/api/lancamentos")
def api_excluir_todos(confirmar: bool = False):
    if not confirmar:
        raise HTTPException(400, "Passe ?confirmar=true para apagar todos os lançamentos")
    with conexao() as con:
        apagados = con.execute("DELETE FROM lancamentos").rowcount
    return {"apagados": apagados}


# ----------------------------------------------------------------------------
# Endpoints: orçamento (metas mensais por categoria de despesa)
# ----------------------------------------------------------------------------
@app.get("/api/orcamento")
def api_orcamento():
    with conexao() as con:
        limites = {r["categoria"]: r["limite"] for r in con.execute("SELECT categoria, limite FROM orcamento")}
    return limites


@app.put("/api/orcamento")
def api_salvar_orcamento(limites: dict[str, float]):
    for cat, limite in limites.items():
        if limite < 0 or limite > 1e10:
            raise HTTPException(422, f"Limite inválido para '{cat}'")
    with conexao() as con:
        for cat, limite in limites.items():
            con.execute(
                "INSERT INTO orcamento (categoria, limite) VALUES (?, ?) "
                "ON CONFLICT(categoria) DO UPDATE SET limite = excluded.limite",
                (cat.strip(), round(limite, 2)),
            )
    return {"ok": True}


# ----------------------------------------------------------------------------
# Exportar / importar CSV
# ----------------------------------------------------------------------------
@app.get("/api/exportar.csv")
def api_exportar(f: dict = Depends(filtros)):
    df = consultar(f)
    saida = pd.DataFrame(
        {
            "Data": df["data"],
            "Descrição": df["descricao"],
            "Categoria": df["categoria"],
            "Tipo": df["tipo"].str.capitalize(),
            "Valor": df["valor"],
            "Conta": df["conta"],
            "Pago": df["pago"].map({1: "Sim", 0: "Não"}),
        }
    )
    # separador ";" e decimal "," para abrir direto no Excel em português
    texto = "﻿" + saida.to_csv(index=False, sep=";", decimal=",")
    return Response(
        texto.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lancamentos.csv"'},
    )


def _norm(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().strip().lower()


def _txt(valor, padrao: str = "") -> str:
    return padrao if pd.isna(valor) else str(valor).strip()


def _parse_data(valor) -> date:
    s = _txt(valor)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return date.fromisoformat(s)
    return pd.to_datetime(s, dayfirst=True).date()


def _parse_valor(valor) -> float:
    s = re.sub(r"[^\d,.\-]", "", _txt(valor))
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    numero = abs(float(s))
    if numero <= 0:
        raise ValueError("valor deve ser maior que zero")
    return round(numero, 2)


def _parse_tipo(valor) -> str:
    n = _norm(_txt(valor))
    if n in {"receita", "entrada", "credito"}:
        return "receita"
    if n in {"despesa", "saida", "debito", "gasto"}:
        return "despesa"
    raise ValueError(f"tipo desconhecido: '{valor}'")


@app.post("/api/importar")
async def api_importar(request: Request):
    bruto = await request.body()
    if len(bruto) > 5_000_000:
        raise HTTPException(413, "Arquivo grande demais (máximo 5 MB)")
    texto = bruto.decode("utf-8-sig", errors="replace")
    try:
        df = pd.read_csv(io.StringIO(texto), sep=None, engine="python", dtype=str)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Não foi possível ler o CSV: {e}")

    df.columns = [_norm(c) for c in df.columns]
    faltando = [c for c in ("data", "descricao", "categoria", "tipo", "valor") if c not in df.columns]
    if faltando:
        raise HTTPException(400, "Colunas ausentes: " + ", ".join(faltando) + ". Esperado: Data, Descrição, Categoria, Tipo, Valor (e opcionais Conta, Pago).")

    linhas, erros = [], []
    for i, r in df.iterrows():
        try:
            descricao, categoria = _txt(r["descricao"])[:120], _txt(r["categoria"])[:60]
            if not descricao or not categoria:
                raise ValueError("descrição ou categoria vazia")
            conta = _txt(r.get("conta"), "Conta corrente")[:60] or "Conta corrente"
            pago = _norm(_txt(r.get("pago"), "sim")) not in {"nao", "0", "false", "n", "pendente"}
            linhas.append((
                _parse_data(r["data"]).isoformat(), descricao, categoria,
                _parse_tipo(r["tipo"]), _parse_valor(r["valor"]), conta, int(pago),
            ))
        except Exception as e:  # noqa: BLE001
            erros.append(f"linha {i + 2}: {e}")

    if linhas:
        with conexao() as con:
            con.executemany(
                "INSERT INTO lancamentos (data, descricao, categoria, tipo, valor, conta, pago) VALUES (?,?,?,?,?,?,?)",
                linhas,
            )
    return {"importados": len(linhas), "ignorados": len(erros), "erros": erros[:5]}


# ----------------------------------------------------------------------------
# Front-end estático
# ----------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(BASE / "static" / "index.html")


app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
