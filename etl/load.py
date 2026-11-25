"""Carga (load) no banco. Idempotente: pode ser executada várias vezes.

O SQL usa parâmetros nomeados (:nome) e `ON CONFLICT (colunas)`, que funcionam
no PostgreSQL e no SQLite. Por isso a carga recebe um objeto `db` mínimo
(veja `Db`), e os testes rodam o mesmo SQL em SQLite.
"""
import logging
from typing import Protocol


class Db(Protocol):
    def execute(self, sql: str, params: dict | None = None) -> list: ...
    def executemany(self, sql: str, rows: list) -> None: ...


SQL_DISCIPLINA = """
INSERT INTO disciplina (codigo, nome, carga_horaria, creditos, bibliografia_basica,
    bibliografia_complementar, horas_teoria, horas_pratica, horas_extensao, horas_individuais)
VALUES (:codigo, :nome, :carga_horaria, :creditos, :bibliografia_basica,
    :bibliografia_complementar, :horas_teoria, :horas_pratica, :horas_extensao, :horas_individuais)
ON CONFLICT (codigo) DO UPDATE SET
    nome = EXCLUDED.nome,
    carga_horaria = EXCLUDED.carga_horaria,
    creditos = EXCLUDED.creditos,
    bibliografia_basica = EXCLUDED.bibliografia_basica,
    bibliografia_complementar = EXCLUDED.bibliografia_complementar,
    horas_teoria = EXCLUDED.horas_teoria,
    horas_pratica = EXCLUDED.horas_pratica,
    horas_extensao = EXCLUDED.horas_extensao,
    horas_individuais = EXCLUDED.horas_individuais
"""

# Disciplina criada a partir da planilha de turmas: dados aproximados, então nunca
# sobrescreve uma disciplina que já exista (o catálogo é a fonte oficial).
SQL_DISCIPLINA_PLANILHA = SQL_DISCIPLINA.split("ON CONFLICT")[0] + "ON CONFLICT (codigo) DO NOTHING\n"

# Docente vindo do CSV é a fonte oficial do nome; o criado pela planilha nunca sobrescreve.
SQL_DOCENTE_CSV = """
INSERT INTO docente (nome, nome_normalizado) VALUES (:nome, :nome_normalizado)
ON CONFLICT (nome_normalizado) DO UPDATE SET nome = EXCLUDED.nome
"""
SQL_DOCENTE_PLANILHA = """
INSERT INTO docente (nome, nome_normalizado) VALUES (:nome, :nome_normalizado)
ON CONFLICT (nome_normalizado) DO NOTHING
"""

SQL_CURSO = "INSERT INTO curso (nome) VALUES (:nome) ON CONFLICT (nome) DO NOTHING"

SQL_RECOMENDACAO = """
INSERT INTO disciplina_recomendacao (disciplina_id, disciplina_recomendada_id)
VALUES (:disciplina_id, :recomendada_id)
ON CONFLICT (disciplina_id, disciplina_recomendada_id) DO NOTHING
"""

SQL_QUADRIMESTRE = """
INSERT INTO quadrimestre (codigo, ano, numero, is_atual) VALUES (:codigo, :ano, :numero, FALSE)
ON CONFLICT (ano, numero) DO NOTHING
"""

SQL_TURMA = """
INSERT INTO turma (codigo, campus, turno, vagas, reserva, ingles, espanhol,
    disciplina_id, curso_id, quadrimestre_id)
VALUES (:codigo, :campus, :turno, :vagas, :reserva, :ingles, :espanhol,
    :disciplina_id, :curso_id, :quadrimestre_id)
ON CONFLICT (codigo, disciplina_id, quadrimestre_id, turno, campus) DO UPDATE SET
    vagas = EXCLUDED.vagas,
    reserva = EXCLUDED.reserva,
    ingles = EXCLUDED.ingles,
    espanhol = EXCLUDED.espanhol,
    curso_id = EXCLUDED.curso_id
RETURNING id
"""

SQL_HORARIO = """
INSERT INTO horario_aula (tipo, dia_semana, periodicidade, horario_inicio,
    horario_termino, turma_id, docente_id)
VALUES (:tipo, :dia_semana, :periodicidade, :horario_inicio,
    :horario_termino, :turma_id, :docente_id)
"""


def _parse_quadrimestre(codigo: str):
    try:
        ano, numero = (int(p) for p in codigo.split("."))
    except ValueError:
        raise ValueError(f"Quadrimestre inválido: {codigo!r}. Use o formato AAAA.N (ex.: 2026.1).")
    if not 1 <= numero <= 3:
        raise ValueError(f"Número de quadrimestre fora de 1..3: {codigo!r}")
    return ano, numero


def carregar(db: Db, res, codigo_quadrimestre: str, marcar_atual: bool = True) -> dict:
    """Grava o resultado do transform. Chame dentro de UMA transação."""
    ano, numero = _parse_quadrimestre(codigo_quadrimestre)
    stats = {}

    # 1. disciplinas
    # catálogo primeiro (fonte oficial); as criadas pela planilha só entram se não existirem
    db.executemany(SQL_DISCIPLINA, [d for d in res.disciplinas if d.get("origem") != "planilha"])
    db.executemany(SQL_DISCIPLINA_PLANILHA, [d for d in res.disciplinas if d.get("origem") == "planilha"])
    stats["disciplinas"] = len(res.disciplinas)
    stats["disciplinas_da_planilha"] = sum(1 for d in res.disciplinas if d.get("origem") == "planilha")

    # 2. docentes (CSV primeiro, depois os criados a partir da planilha)
    db.executemany(SQL_DOCENTE_CSV, [d for d in res.docentes if d["origem"] == "csv"])
    db.executemany(SQL_DOCENTE_PLANILHA, [d for d in res.docentes if d["origem"] != "csv"])
    stats["docentes"] = len(res.docentes)

    # 3. cursos
    db.executemany(SQL_CURSO, [{"nome": c} for c in res.cursos])
    stats["cursos"] = len(res.cursos)

    # 4. recomendações
    disc_id = {c: i for c, i in db.execute("SELECT codigo, id FROM disciplina")}
    db.executemany(
        SQL_RECOMENDACAO,
        [
            {"disciplina_id": disc_id[pai], "recomendada_id": disc_id[filho]}
            for pai, filho in res.recomendacoes
            if pai in disc_id and filho in disc_id
        ],
    )
    stats["recomendacoes"] = len(res.recomendacoes)

    # 5. quadrimestre
    db.execute(SQL_QUADRIMESTRE, {"codigo": codigo_quadrimestre, "ano": ano, "numero": numero})
    quadri_id = db.execute(
        "SELECT id FROM quadrimestre WHERE ano = :ano AND numero = :numero",
        {"ano": ano, "numero": numero},
    )[0][0]
    if marcar_atual:
        db.execute("UPDATE quadrimestre SET is_atual = (id = :id)", {"id": quadri_id})

    # 6. turmas e horários
    curso_id = {n: i for n, i in db.execute("SELECT UPPER(nome), id FROM curso")}
    docente_id = {n: i for n, i in db.execute("SELECT nome_normalizado, id FROM docente")}

    horarios_total = 0
    for turma in res.turmas:
        turma_id = db.execute(
            SQL_TURMA,
            {
                "codigo": turma["codigo"],
                "campus": turma["campus"],
                "turno": turma["turno"],
                "vagas": turma["vagas"],
                "reserva": turma["reserva"],
                "ingles": turma["ingles"],
                "espanhol": turma["espanhol"],
                "disciplina_id": disc_id[turma["sigla"]],
                "curso_id": curso_id[turma["curso"].upper()],
                "quadrimestre_id": quadri_id,
            },
        )[0][0]

        # recarga limpa dos horários da turma => rodar duas vezes não duplica
        db.execute("DELETE FROM horario_aula WHERE turma_id = :id", {"id": turma_id})
        db.executemany(
            SQL_HORARIO,
            [
                {
                    "tipo": h["tipo"],
                    "dia_semana": h["dia_semana"],
                    "periodicidade": h["periodicidade"],
                    "horario_inicio": h["horario_inicio"],
                    "horario_termino": h["horario_termino"],
                    "turma_id": turma_id,
                    "docente_id": docente_id.get(h["docente_normalizado"]),
                }
                for h in turma["horarios"]
            ],
        )
        horarios_total += len(turma["horarios"])

    stats["turmas"] = len(res.turmas)
    stats["horarios"] = horarios_total
    logging.info("Carga concluída: %s", stats)
    return stats
