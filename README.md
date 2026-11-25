# ETL UFABC

Pipeline que lê o **catálogo de disciplinas** (CSV), a lista de **docentes** (CSV) e a planilha de **turmas ofertadas** (XLSX) e carrega tudo em um banco **PostgreSQL**.

- Carga **idempotente**: rodar duas vezes não duplica dados.
- Carga em **uma única transação**: se algo falhar, nada é gravado pela metade.
- Gera `reports/problemas.csv` a cada execução, listando o que foi rejeitado ou merece atenção.
- Modo `--dry-run` para conferir o resultado sem tocar no banco.
- Disciplinas que aparecem na planilha de turmas mas faltam no catálogo são **criadas a partir da planilha** (veja [Disciplinas fora do catálogo](#disciplinas-fora-do-catálogo)).

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

`--catalogo`, `--turmas` e `--quadrimestre` são obrigatórios. `--docentes` é opcional (padrão: `data/raw/docentes_ufabc.csv`).

```bash
python main.py \
  --catalogo data/raw/catalogo_disciplinas.csv \
  --docentes data/raw/docentes_ufabc.csv \
  --turmas data/raw/2027_1.xlsx \
  --quadrimestre 2027.1
```

Acrescente `--init-db` na primeira execução para criar as tabelas, se ainda não existirem. Para conferir o resultado sem gravar nada, acrescente `--dry-run`: ele gera `data/processed/*.csv` e `reports/problemas.csv`.

A planilha de turmas precisa ser `.xlsx`; CSV não é aceito em `--turmas`.

### Rodando de novo ou para um quadrimestre que já existe

A carga é feita por *upsert*, turma a turma:

- **Turma existente** (mesmo `codigo`, disciplina, quadrimestre, turno e campus): atualiza `vagas`, `reserva`, `ingles`, `espanhol` e `curso`. Os horários dela são apagados e recriados, então trocar o docente de um horário na planilha substitui o docente antigo (o cadastro dele continua em `docente`).
- **Turma nova**: é criada. Se mudar o turno ou o campus, vira uma turma nova; a antiga não é alterada.
- **Turma que está no banco mas não está na planilha**: fica como está. O ETL nunca apaga turmas, então uma planilha parcial não zera o quadrimestre.
- **Disciplinas e docentes do CSV**: são atualizados globalmente, valendo para todos os quadrimestres.
- **Quadrimestre atual**: por padrão, o quadrimestre carregado vira o atual e os demais deixam de ser. Para recarregar um quadrimestre antigo sem mudar o atual, use `--nao-marcar-atual`.

### Opções

| Opção | Descrição |
|---|---|
| `--catalogo`, `--turmas` | Caminhos dos arquivos de entrada (obrigatórios) |
| `--docentes` | Caminho do CSV de docentes (padrão: `data/raw/docentes_ufabc.csv`) |
| `--aba` | Nome ou índice da aba da planilha (padrão: primeira) |
| `--quadrimestre AAAA.N` | Quadrimestre da planilha (obrigatório; ex.: `2027.1`) |
| `--multi-docente todos\|primeiro` | O que fazer quando há mais de um docente por tipo de aula (padrão: `todos`) |
| `--nao-marcar-atual` | Não marca o quadrimestre carregado como o atual |
| `--init-db` | Cria as tabelas se ainda não existirem |
| `--dry-run` | Não grava no banco; gera CSVs em `data/processed/` |
| `--nao-criar-disciplinas` | Rejeita turmas de disciplinas fora do catálogo, em vez de criar a disciplina a partir da planilha |
| `--relatorios PASTA` | Pasta do relatório de problemas (padrão: `reports`) |

## Como a planilha vira dados

| Banco | Origem |
|---|---|
| `turma.codigo` | Código de turma sem turno, disciplina e campus: `DA1ESTB019-17SA` → `A1` |
| Disciplina da turma | `ESTB019-17`, extraída do mesmo código (se não existir no catálogo, é criada a partir da planilha) |
| `turma.turno` | Coluna TURNO (`M`/`N`), conferida com o prefixo `D`/`N` do código |
| `turma.campus` | Coluna CAMPUS (`SB` → `SBC`) |
| `turma.vagas` / `reserva` | VAGAS TOTAIS / VAGAS INGRESSANTES |
| `turma.ingles` / `espanhol` | Texto "MINISTRADA EM INGLÊS/ESPANHOL" na descrição da turma |
| `horario_aula` | Colunas *teoria/prática COM SALA* (se vazias, as colunas sem sala) |
| `horario_aula.docente_id` | DOCENTE TEORIA 1–3 / DOCENTE PRÁTICA 1–3 |

### Regras de tratamento

- **Vários docentes no mesmo tipo de aula:** por padrão grava uma linha de horário por docente. Com `--multi-docente primeiro`, grava só o primeiro.
- **Disciplinas fora do catálogo** são criadas a partir da planilha (veja a seção abaixo).
- **Docentes que não estão no CSV** são criados a partir da planilha e nunca sobrescrevem um docente vindo do CSV.
- **Placeholders** como `0A DEFINIR DOCENTE` viram "sem docente", e sufixos como `(CEDIDO ...)` são removidos do nome.
- **Turmas cuja disciplina não está no catálogo e não pode ser criada** (sem `TPEI` válido, ou com `--nao-criar-disciplinas`) são rejeitadas e listadas no relatório.

### Disciplinas fora do catálogo

Quando o código de disciplina de uma turma não existe no catálogo, o ETL cria a disciplina com os dados da própria planilha de turmas:

| Campo | Origem |
|---|---|
| `codigo` | Extraído do código de turma (`ESTB019-17`) |
| `nome` | Coluna `TURMA` sem o sufixo da turma (`BIOESTATÍSTICA A1-Matutino (SA)` → `BIOESTATÍSTICA`) |
| `creditos` | T + P do `TPEI` |
| `carga_horaria` | créditos × 12 |
| `horas_teoria` / `horas_pratica` | T / P |
| `horas_individuais` | I |
| `horas_extensao` | E, quando o `TPEI` tem 4 partes; senão 0 |
| bibliografias | vazias |

O `TPEI` da planilha vem em dois formatos: `T-P-I` (ex.: `2-2-4`) e `T-P-E-I` (ex.: `1-3-4-6`). Com 3 partes, o terceiro número é tratado como estudo individual e a extensão fica 0; isso é uma aproximação, e em alguns casos o terceiro número é, na verdade, extensão.

Regras:

- Os dados são **aproximados**. Disciplinas criadas assim ficam sem bibliografia e sem recomendações.
- **Nunca sobrescrevem** uma disciplina já existente no banco. Quando o catálogo passar a trazer a disciplina, a carga normal a corrige.
- Sem `TPEI` válido (ausente, malformado ou sem créditos) ou sem nome extraível, a turma é rejeitada como `disciplina_fora_do_catalogo`.
- Cada disciplina criada vira um aviso `disciplina_criada_da_planilha` em `reports/problemas.csv`. Vale conferir esses avisos depois de cada carga.
- `--nao-criar-disciplinas` desativa esse comportamento e volta a rejeitar as turmas.

## Relatório de problemas

A cada execução, `reports/problemas.csv` é reescrito com as colunas `severidade` (`rejeitado` ou `aviso`), `tipo`, `chave` e `detalhe`.

| Tipo | Significado |
|---|---|
| `disciplina_fora_do_catalogo` | Turma rejeitada: a disciplina não existe no catálogo e não pôde ser criada a partir da planilha |
| `codigo_turma_invalido` | Turma rejeitada: código fora do padrão esperado |
| `turma_duplicada` | Turma rejeitada: mesma turma, disciplina, turno e campus já lida |
| `docente_sem_horario` | Há docente, mas não há horário; o schema não grava esse docente |
| `multiplos_docentes` | Turma com mais de um docente por tipo de aula |
| `disciplina_criada_da_planilha` | Disciplina ausente do catálogo, criada a partir da planilha (dados aproximados) |
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
