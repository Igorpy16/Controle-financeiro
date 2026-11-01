# Publicar o Controle Financeiro na internet

O app agora tem **login por senha** e vem com `Dockerfile`, então roda em qualquer hospedagem que aceite Docker.

## Antes de começar: o que você precisa saber

- **Senha:** defina a variável de ambiente `APP_PASSWORD`. Em produção (Docker) o app **recusa iniciar sem ela**. Use uma senha longa e única. Trocar a senha desconecta todas as sessões.
- **Banco de dados:** os lançamentos ficam no arquivo `/data/financas.db`. A hospedagem precisa montar um **disco/volume persistente** em `/data`. Sem isso, **você perde todos os dados a cada novo deploy ou reinício**. Planos gratuitos costumam não ter disco persistente.
- **Um usuário só:** é uma senha única, para uso pessoal. Não há contas separadas por pessoa.
- **HTTPS:** obrigatório, para a senha não trafegar sem proteção. As plataformas abaixo fornecem automaticamente.
- **Começa vazio:** em produção não são criados dados de exemplo.
- **Backup:** de tempos em tempos, use **Período: Tudo** e clique em **Baixar CSV filtrado**. Esse CSV pode ser reimportado pelo botão "Importar CSV".

---

## Caminho A — Plataforma gerenciada (Render, Railway, Fly.io…)

Os nomes de menus e os planos mudam com o tempo; use isto como roteiro e confira a documentação atual da plataforma.

1. Suba o projeto para o **GitHub** (veja o README), de preferência num repositório **privado**.
2. Na plataforma, crie um **novo serviço web** a partir desse repositório e escolha o modo **Docker** (ela vai usar o `Dockerfile`).
3. Crie um **disco/volume persistente** e monte-o no caminho **`/data`**.
4. Em **variáveis de ambiente**, crie `APP_PASSWORD` com a sua senha.
5. Publique (deploy). A plataforma dá um endereço com HTTPS, como `https://seuapp.exemplo.com`.
6. Abra o endereço, entre com a senha e pronto.

Dicas:
- Mantenha **uma única instância** (não escale para várias), porque o SQLite não funciona bem com várias cópias gravando.
- Se a plataforma exigir um *health check*, use o caminho `/login` (responde sem senha).

## Caminho B — Servidor próprio (VPS) com HTTPS automático

Funciona em qualquer VPS com Linux e Docker (Hetzner, DigitalOcean, Contabo, etc.).

1. Aponte o seu domínio para o IP do servidor: crie um registro **A** (por exemplo, `financas.seudominio.com.br` → IP do servidor).
2. No servidor, instale Docker e copie o projeto (`git clone` do seu repositório).
3. Dentro da pasta do projeto, crie o arquivo `.env`:
   ```bash
   cp .env.example .env
   nano .env        # preencha APP_PASSWORD e DOMINIO
   ```
4. Suba tudo:
   ```bash
   docker compose up -d --build
   ```
5. Acesse `https://seu-dominio`. O Caddy obtém e renova o certificado HTTPS sozinho (as portas 80 e 443 precisam estar abertas no firewall).

Atualizar depois de mudar o código:
```bash
git pull
docker compose up -d --build
```

Os dados ficam no volume `dados` do Docker e **sobrevivem** a atualizações.

Backup do banco inteiro:
```bash
docker compose cp app:/data/financas.db ./backup-financas.db
```

---

## Versão de demonstração (para mostrar o projeto ao público)

Se você quer que qualquer pessoa **veja o app funcionando**, sem dar acesso aos seus dados, publique uma **segunda instância** em modo demonstração, separada da sua. Ela:

- é **somente leitura**: qualquer tentativa de criar, editar ou apagar é recusada pelo servidor, e os botões que alteram dados ficam escondidos;
- usa **só dados fictícios**, gerados de novo a cada reinício;
- **não tem login** e **nunca abre o seu banco real**: no modo demo, a variável `FINANCAS_DB` é ignorada e é usado um banco temporário;
- tem um limite de 300 requisições por minuto por IP, para evitar abuso;
- mostra uma faixa avisando que é uma demonstração.

Variáveis da instância de demonstração:

| Variável | Valor |
|---|---|
| `DEMO_MODE` | `1` (é o que liga o modo demonstração) |
| `REPO_URL` | (opcional) endereço do seu repositório, começando com `https://`. Mostra o link "Ver o código no GitHub" na faixa |

Não precisa de `APP_PASSWORD` nem de disco persistente.

**Plataforma gerenciada:** crie um **segundo serviço** a partir do mesmo repositório (modo Docker), sem disco, só com `DEMO_MODE=1` (e `REPO_URL`, se quiser). Planos gratuitos servem para a demo, porque ela não guarda nada. Pode demorar alguns segundos para "acordar" depois de um tempo parada, conforme a plataforma.

**VPS:** rode um segundo contêiner e um segundo endereço no Caddy:
```bash
docker build -t controle-financeiro .
docker run -d --name demo --restart unless-stopped --network <rede-do-compose> \
  -e DEMO_MODE=1 -e REPO_URL=https://github.com/SEU-USUARIO/controle-financeiro controle-financeiro
```
E no `Caddyfile`, um bloco novo apontando para ele:
```
demo.seudominio.com.br {
	reverse_proxy demo:8000
}
```
(Descubra o nome da rede com `docker network ls`; costuma ser `<pasta>_default`.)

**Cuidado:** **nunca** ligue `DEMO_MODE` na instância com os seus dados reais. Ela deixaria de pedir a senha. Use sempre um serviço separado, com outro endereço.

Para ver a demonstração no seu computador:
```bat
set DEMO_MODE=1
python -m uvicorn main:app
```

## Domínio próprio

1. Registre o domínio (o registro.br vende `.com.br`).
2. Na plataforma gerenciada, adicione o domínio em **Custom Domains** e crie no seu DNS o registro que ela indicar (geralmente um `CNAME`). No VPS, use o registro `A` do passo 1.
3. Aguarde a propagação (de minutos a algumas horas).

## Testar a imagem no seu computador (opcional)

Com o Docker instalado:
```bash
docker build -t controle-financeiro .
docker run --rm -p 8000:8000 -e APP_PASSWORD=teste123 -v financas_dados:/data controle-financeiro
```
Abra http://localhost:8000 e entre com `teste123`.

## Variáveis de ambiente

| Variável | Para que serve |
|---|---|
| `APP_PASSWORD` | Senha de acesso. **Obrigatória** em produção |
| `SECRET_KEY` | (Opcional) chave usada para assinar as sessões. Se não definir, usa a senha |
| `FINANCAS_DB` | Caminho do arquivo do banco (no Docker já é `/data/financas.db`) |
| `SEMEAR_DEMO` | `0` = não criar dados de exemplo (já é `0` no Docker) |
| `REQUIRE_AUTH` | `1` = recusar iniciar sem senha (já é `1` no Docker) |
| `PORT` | Porta em que o app escuta (plataformas definem sozinhas; padrão 8000) |
| `DEMO_MODE` | `1` = versão pública de demonstração: somente leitura, dados fictícios, sem login |
| `REPO_URL` | (só na demonstração) link do repositório mostrado na faixa de aviso |

## Segurança: o que já está feito e o que falta

Já incluído: login por senha, sessão em cookie assinado (`HttpOnly`, `SameSite`, `Secure` em HTTPS) válida por 30 dias, bloqueio após 5 senhas erradas em 15 minutos, todas as rotas protegidas e cabeçalhos básicos de segurança.

Fica por sua conta: usar uma senha forte, manter o repositório privado, fazer backups e manter o servidor atualizado (no caso de VPS).
