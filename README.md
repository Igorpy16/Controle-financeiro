# Controle Financeiro (front-end JavaScript + back-end Python)

- **Back-end (Python / FastAPI):** API, regras e agregações com pandas. Os dados ficam salvos em **SQLite** (`financas.db`, criado sozinho na primeira execução).
- **Front-end (HTML + CSS + JavaScript puro):** consome a API e desenha os gráficos com Plotly.js.

## Como executar

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

Abra **http://localhost:8000**. (O Plotly.js vem de um CDN, então é preciso internet para ver os gráficos.)
Documentação automática da API: http://localhost:8000/docs

## Colocar na internet

Veja o guia **[DEPLOY.md](DEPLOY.md)**. Resumo: o projeto tem login por senha (`APP_PASSWORD`),
`Dockerfile` e `docker-compose.yml` (com HTTPS automático). Rodando localmente, como acima, o app
fica **sem login**: use assim só no seu computador. Para testar o login localmente:

```bat
set APP_PASSWORD=minha-senha
python -m uvicorn main:app --reload
```

Para mostrar o projeto ao público sem expor seus dados, existe o **modo demonstração**
(`DEMO_MODE=1`): somente leitura, com dados fictícios e sem login. Detalhes no [DEPLOY.md](DEPLOY.md).

## O que o app faz

- **Lançamentos:** adicionar, editar e excluir receitas e despesas (descrição, valor, data, categoria, conta e se já foi pago/recebido). Clique no selo "Pago/Pendente" para alternar a situação.
- **Painel:** receitas, despesas, saldo, taxa de poupança e contas a pagar, com variação em relação ao período anterior; gráfico mensal (receitas × despesas + saldo acumulado); despesas por categoria e por conta; maiores despesas.
- **Orçamento:** defina um limite mensal por categoria ("Editar metas") e acompanhe o quanto já foi gasto no mês do fim do período filtrado.
- **Filtros:** período (atalhos Mês/3M/6M/Ano/Tudo), tipo, situação, busca por texto, categorias e contas.
- **CSV:** exporta os lançamentos filtrados (abre direto no Excel em português) e importa planilhas.

## Dados de exemplo

Na primeira execução são criados 6 meses de lançamentos fictícios para você ver o painel funcionando.
Para começar do zero, use o botão **"Apagar todos os lançamentos"** na barra lateral (os dados de exemplo não voltam).
Para recomeçar com o exemplo, apague o arquivo `financas.db` com o servidor parado.

## Importar CSV

Colunas obrigatórias: `Data`, `Descrição`, `Categoria`, `Tipo` (Receita ou Despesa), `Valor`.
Opcionais: `Conta` e `Pago` (Sim/Não).

```
Data;Descrição;Categoria;Tipo;Valor;Conta;Pago
05/11/2026;Salário;Salário;Receita;8500,00;Conta corrente;Sim
10/11/2026;Aluguel;Moradia;Despesa;2200,00;Conta corrente;Não
```

Aceita separador `,` ou `;`, datas `AAAA-MM-DD` ou `DD/MM/AAAA` e valores como `1234.56` ou `1.234,56`.

## Backup

Copie o arquivo `financas.db`: ele contém todos os seus lançamentos e metas.

## Endpoints

| Rota | O que faz |
|------|-----------|
| `GET /api/meta` | Categorias, contas e intervalo de datas |
| `GET /api/resumo` | KPIs, gráficos, maiores despesas e orçamento |
| `GET /api/lancamentos` | Lista paginada |
| `POST /api/lancamentos` | Cria um lançamento |
| `PUT /api/lancamentos/{id}` | Edita |
| `PATCH /api/lancamentos/{id}/pago` | Alterna pago/pendente |
| `DELETE /api/lancamentos/{id}` | Exclui |
| `DELETE /api/lancamentos?confirmar=true` | Apaga todos |
| `GET` / `PUT /api/orcamento` | Lê / salva as metas mensais |
| `GET /api/exportar.csv` | Exporta os lançamentos filtrados |
| `POST /api/importar` | Importa CSV (corpo = texto do arquivo) |

Filtros aceitos nas rotas de leitura: `inicio`, `fim` (AAAA-MM-DD), `tipo`, `status` (`pago`/`pendente`), `busca`, `categoria` e `conta` (repetíveis).
