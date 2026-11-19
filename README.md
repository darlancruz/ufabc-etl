# ETL UFABC

Pipeline que lê o **catálogo de disciplinas** (CSV), a lista de **docentes** (CSV) e a planilha de **turmas ofertadas** (XLSX) e carrega tudo em um banco **PostgreSQL**.

- Carga **idempotente**: rodar duas vezes não duplica dados.
- Carga em **uma única transação**: se algo falhar, nada é gravado pela metade.
- Gera `reports/problemas.csv` a cada execução, listando o que foi rejeitado ou merece atenção.
- Modo `--dry-run` para conferir o resultado sem tocar no banco.

## Requisitos

- Python 3.10+
- Docker (opcional, para subir o PostgreSQL local)

## Instalação

```bash
pip install -r requirements.txt
cp .env.example .env        # ajuste as credenciais se necessário
docker compose up -d        # sobe o Postgres e cria as tabelas (database/schema.sql)
```

## Uso

```bash
python main.py --dry-run    # só transforma: gera data/processed/*.csv e reports/problemas.csv
python main.py              # transforma e carrega no banco
python main.py --init-db    # cria as tabelas, se ainda não existirem, e carrega
```

Os arquivos de entrada padrão ficam em `data/raw/`. Para outra planilha ou quadrimestre:

```bash
python main.py --turmas data/raw/outra_planilha.xlsx --quadrimestre 2026.2
```

Sem `--quadrimestre`, ele é deduzido do nome do arquivo (`matriculas_2026_1_...` → `2026.1`).

### Opções

| Opção | Descrição |
|---|---|
| `--catalogo`, `--docentes`, `--turmas` | Caminhos dos arquivos de entrada |
| `--aba` | Nome ou índice da aba da planilha (padrão: primeira) |
| `--quadrimestre AAAA.N` | Quadrimestre da planilha (padrão: deduzido do nome) |
| `--multi-docente todos\|primeiro` | O que fazer quando há mais de um docente por tipo de aula (padrão: `todos`) |
| `--nao-marcar-atual` | Não marca o quadrimestre carregado como o atual |
| `--init-db` | Cria as tabelas se ainda não existirem |
| `--dry-run` | Não grava no banco; gera CSVs em `data/processed/` |
| `--relatorios PASTA` | Pasta do relatório de problemas (padrão: `reports`) |

## Como a planilha vira dados

| Banco | Origem |
|---|---|
| `turma.codigo` | Código de turma sem turno, disciplina e campus: `DA1ESTB019-17SA` → `A1` |
| Disciplina da turma | `ESTB019-17`, extraída do mesmo código (precisa existir no catálogo) |
| `turma.turno` | Coluna TURNO (`M`/`N`), conferida com o prefixo `D`/`N` do código |
| `turma.campus` | Coluna CAMPUS (`SB` → `SBC`) |
| `turma.vagas` / `reserva` | VAGAS TOTAIS / VAGAS INGRESSANTES |
| `turma.ingles` / `espanhol` | Texto "MINISTRADA EM INGLÊS/ESPANHOL" na descrição da turma |
| `horario_aula` | Colunas *teoria/prática COM SALA* (se vazias, as colunas sem sala) |
| `horario_aula.docente_id` | DOCENTE TEORIA 1–3 / DOCENTE PRÁTICA 1–3 |

### Regras de tratamento

- **Vários docentes no mesmo tipo de aula:** por padrão grava uma linha de horário por docente. Com `--multi-docente primeiro`, grava só o primeiro.
- **Docentes que não estão no CSV** são criados a partir da planilha e nunca sobrescrevem um docente vindo do CSV.
- **Placeholders** como `0A DEFINIR DOCENTE` viram "sem docente", e sufixos como `(CEDIDO ...)` são removidos do nome.
- **Turmas cuja disciplina não está no catálogo** são rejeitadas e listadas no relatório.

## Relatório de problemas

A cada execução, `reports/problemas.csv` é reescrito com as colunas `severidade` (`rejeitado` ou `aviso`), `tipo`, `chave` e `detalhe`.

| Tipo | Significado |
|---|---|
| `disciplina_fora_do_catalogo` | Turma rejeitada: a disciplina não existe no catálogo |
| `codigo_turma_invalido` | Turma rejeitada: código fora do padrão esperado |
| `turma_duplicada` | Turma rejeitada: mesma turma, disciplina, turno e campus já lida |
| `docente_sem_horario` | Há docente, mas não há horário; o schema não grava esse docente |
| `multiplos_docentes` | Turma com mais de um docente por tipo de aula |
| `docente_criado_da_planilha` | Docente ausente do CSV, criado a partir da planilha |
| `recomendacao_nao_encontrada` / `recomendacao_ambigua` | Recomendação ignorada |
| `horario_nao_interpretado` | Algum trecho de horário não foi reconhecido |

## Estrutura

```
main.py                 # CLI
etl/
  extract.py            # leitura e validação de colunas
  transform.py          # DataFrames -> registros (sem acesso ao banco)
  load.py               # carga no banco (SQL portável Postgres/SQLite)
  horarios.py           # parser das colunas de horário
  normalize.py          # normalização de nomes e textos
  pipeline.py           # extract + transform
database/
  schema.sql            # schema do PostgreSQL
  connection.py         # conexão (SQLAlchemy)
tests/test_etl.py       # testes unitários e de integração
data/raw/               # arquivos de entrada
```

## Testes

```bash
python -m unittest discover -s tests -v
```

A carga é testada em SQLite com um schema equivalente ao do Postgres (mesmas constraints `UNIQUE`). O SQL de `etl/load.py` é o mesmo nos dois bancos.

## Atualizando um banco existente

Se o banco foi criado com o schema antigo, recrie-o. O schema atual adiciona `UNIQUE` em `curso.nome` e `docente.nome_normalizado`, necessários para a carga idempotente, e corrige a vírgula que faltava na tabela `quadrimestre`.

## Licença

O código é distribuído sob a licença MIT. Veja o arquivo [LICENSE](LICENSE).

Os dados em `data/raw/` pertencem às suas fontes originais e **não** são cobertos por essa licença.
