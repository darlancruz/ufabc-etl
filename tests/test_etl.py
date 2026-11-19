"""Rodar com:  python -m unittest discover -s tests -v

A carga é testada em SQLite com um schema equivalente ao de database/schema.sql
(mesmas constraints UNIQUE); o SQL de etl/load.py é o mesmo usado no PostgreSQL.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etl.horarios import parse_horarios  # noqa: E402
from etl.load import carregar  # noqa: E402
from etl.normalize import clean_docente_name, normalize_name, title_name  # noqa: E402
from etl.pipeline import build  # noqa: E402
from etl.transform import TransformResult, transform_turmas  # noqa: E402

RAW = ROOT / "data" / "raw"
ARQS = (
    RAW / "catalogo_disciplinas_padronizado_2025_2026.csv",
    RAW / "docentes_ufabc.csv",
    RAW / "matriculas_2026_1_turmas_ofertadas.xlsx",
)

DDL_SQLITE = """
CREATE TABLE disciplina (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL UNIQUE,
  nome TEXT NOT NULL, carga_horaria INTEGER NOT NULL, creditos INTEGER NOT NULL,
  bibliografia_basica TEXT, bibliografia_complementar TEXT, horas_teoria INTEGER NOT NULL DEFAULT 0,
  horas_pratica INTEGER NOT NULL DEFAULT 0, horas_extensao INTEGER NOT NULL DEFAULT 0,
  horas_individuais INTEGER NOT NULL DEFAULT 0);
CREATE TABLE curso (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL UNIQUE);
CREATE TABLE quadrimestre (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL UNIQUE,
  ano INTEGER NOT NULL, numero INTEGER NOT NULL, is_atual BOOLEAN NOT NULL DEFAULT FALSE,
  CHECK (numero BETWEEN 1 AND 3), UNIQUE (ano, numero));
CREATE TABLE docente (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL,
  nome_normalizado TEXT NOT NULL UNIQUE);
CREATE TABLE turma (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL,
  campus TEXT NOT NULL CHECK (campus IN ('SA','SBC')), turno TEXT NOT NULL,
  vagas INTEGER NOT NULL DEFAULT 0, reserva INTEGER NOT NULL DEFAULT 0,
  ingles BOOLEAN NOT NULL DEFAULT FALSE, espanhol BOOLEAN NOT NULL DEFAULT FALSE,
  disciplina_id INTEGER NOT NULL REFERENCES disciplina(id) ON DELETE CASCADE,
  curso_id INTEGER NOT NULL REFERENCES curso(id),
  quadrimestre_id INTEGER NOT NULL REFERENCES quadrimestre(id),
  UNIQUE (codigo, disciplina_id, quadrimestre_id, turno, campus));
CREATE TABLE horario_aula (id INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo TEXT NOT NULL CHECK (tipo IN ('teoria','pratica')),
  dia_semana TEXT NOT NULL CHECK (dia_semana IN ('seg','ter','qua','qui','sex','sab')),
  periodicidade TEXT NOT NULL CHECK (periodicidade IN ('semanal','q1','q2')),
  horario_inicio TEXT NOT NULL, horario_termino TEXT NOT NULL,
  turma_id INTEGER NOT NULL REFERENCES turma(id) ON DELETE CASCADE,
  docente_id INTEGER REFERENCES docente(id) ON DELETE SET NULL,
  CHECK (horario_termino > horario_inicio));
CREATE TABLE disciplina_recomendacao (id INTEGER PRIMARY KEY AUTOINCREMENT,
  disciplina_id INTEGER NOT NULL REFERENCES disciplina(id) ON DELETE CASCADE,
  disciplina_recomendada_id INTEGER NOT NULL REFERENCES disciplina(id) ON DELETE CASCADE,
  UNIQUE (disciplina_id, disciplina_recomendada_id),
  CHECK (disciplina_id <> disciplina_recomendada_id));
"""


class SqliteDb:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        cur = self.conn.execute(sql, params or {})
        return cur.fetchall() if cur.description else []

    def executemany(self, sql, rows):
        if rows:
            self.conn.executemany(sql, rows)


def novo_banco():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL_SQLITE)
    return conn


class TestParseHorarios(unittest.TestCase):
    def test_com_sala_e_dois_dias(self):
        aulas, esp = parse_horarios(
            "sexta das 10:00 às 12:00, sala S - 304-1, semanal , quarta das 08:00 às 10:00, sala S-501, semanal "
        )
        self.assertEqual(esp, 2)
        self.assertEqual([(a["dia_semana"], a["horario_inicio"]) for a in aulas], [("sex", "10:00"), ("qua", "08:00")])

    def test_sem_sala(self):
        aulas, _ = parse_horarios("quinta das 10:00 às 12:00, semanal ")
        self.assertEqual(aulas[0]["periodicidade"], "semanal")

    def test_quinzenal_i_e_ii(self):
        aulas, esp = parse_horarios(
            "terça das 08:00 às 10:00, sala 402-3, quinzenal I , terça das 10:00 às 12:00, sala 402-3, quinzenal II"
        )
        self.assertEqual(esp, 2)
        self.assertEqual([a["periodicidade"] for a in aulas], ["q1", "q2"])

    def test_vazio_e_zero(self):
        for v in (None, float("nan"), "", "   ", "0"):
            self.assertEqual(parse_horarios(v), ([], 0))

    def test_horario_invalido_nao_vira_aula(self):
        aulas, esp = parse_horarios("segunda das 12:00 às 10:00, semanal")
        self.assertEqual((len(aulas), esp), (0, 1))


class TestNormalize(unittest.TestCase):
    def test_docente(self):
        self.assertIsNone(clean_docente_name("0A DEFINIR DOCENTE"))
        self.assertIsNone(clean_docente_name(float("nan")))
        self.assertEqual(clean_docente_name("DIEGO ARAUJO AZZI(CEDIDO         )"), "DIEGO ARAUJO AZZI")

    def test_acento_e_caixa(self):
        self.assertEqual(normalize_name("  CINTIA  Lima CRESCÊNCIO "), "cintia lima crescencio")
        self.assertEqual(title_name("MARIA DA SILVA JUNIOR"), "Maria da Silva Junior")


def _linha(**kw):
    base = {"curso": "BACHARELADO EM X", "codigo_turma": "DA1ESTB019-17SA", "descricao": "Foo A1-Matutino (SA)",
            "campus": "SA", "turno": "Matutino", "vagas": "30", "reserva": "0",
            "teoria": pd.NA, "pratica": pd.NA, "teoria_sala": "quinta das 10:00 às 12:00, sala S-1, semanal ",
            "pratica_sala": pd.NA, "doc_t1": "FULANO DA SILVA", "doc_t2": pd.NA, "doc_t3": pd.NA,
            "doc_p1": pd.NA, "doc_p2": pd.NA, "doc_p3": pd.NA}
    base.update(kw)
    return base


def _transformar(linhas, catalogo=("ESTB019-17",), **kw):
    res = TransformResult()
    transform_turmas(pd.DataFrame(linhas), set(catalogo), res, **kw)
    return res


class TestTransformTurmas(unittest.TestCase):
    def test_derivacao_do_codigo(self):
        t = _transformar([_linha()]).turmas[0]
        self.assertEqual((t["codigo"], t["sigla"], t["campus"], t["turno"]), ("A1", "ESTB019-17", "SA", "M"))

    def test_turma_sem_numero_e_campus_sb(self):
        res = _transformar([_linha(codigo_turma="NAESTB019-17SB", campus="SB", turno="Noturno")])
        t = res.turmas[0]
        self.assertEqual((t["codigo"], t["campus"], t["turno"]), ("A", "SBC", "N"))

    def test_disciplina_fora_do_catalogo_e_rejeitada(self):
        res = _transformar([_linha()], catalogo=("OUTRA-99",))
        self.assertEqual(res.turmas, [])
        self.assertEqual(res.problemas[0]["tipo"], "disciplina_fora_do_catalogo")

    def test_codigo_invalido_e_duplicada(self):
        res = _transformar([_linha(codigo_turma="XYZ"), _linha(), _linha()])
        self.assertEqual(len(res.turmas), 1)
        self.assertEqual(sorted(p["tipo"] for p in res.problemas if p["severidade"] == "rejeitado"),
                         ["codigo_turma_invalido", "turma_duplicada"])

    def test_fallback_para_coluna_sem_sala(self):
        res = _transformar([_linha(teoria_sala=pd.NA, teoria="sexta das 08:00 às 10:00, semanal")])
        self.assertEqual(res.turmas[0]["horarios"][0]["dia_semana"], "sex")

    def test_idioma(self):
        res = _transformar([_linha(descricao="ECON A2-Matutino (SB)-TURMA MINISTRADA EM INGLÊS")])
        self.assertTrue(res.turmas[0]["ingles"])

    def test_multi_docente_todos_vs_primeiro(self):
        linha = _linha(doc_t2="BELTRANO SOUZA")
        self.assertEqual(len(_transformar([linha], multi_docente="todos").turmas[0]["horarios"]), 2)
        self.assertEqual(len(_transformar([linha], multi_docente="primeiro").turmas[0]["horarios"]), 1)

    def test_docente_novo_vem_da_planilha(self):
        res = _transformar([_linha()])
        self.assertEqual(res.docentes[0]["origem"], "planilha")
        self.assertEqual(res.docentes[0]["nome"], "Fulano da Silva")


@unittest.skipUnless(all(a.exists() for a in ARQS), "arquivos de data/raw ausentes")
class TestPipelineReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = build(*[str(a) for a in ARQS])

    def test_contagens_transform(self):
        self.assertEqual(len(self.res.disciplinas), 1741)
        self.assertEqual(len(self.res.cursos), 31)
        self.assertEqual(len(self.res.turmas), 983)  # 997 linhas - 14 sem disciplina no catálogo
        self.assertEqual(sum(1 for p in self.res.problemas if p["tipo"] == "disciplina_fora_do_catalogo"), 14)
        self.assertFalse([p for p in self.res.problemas if p["tipo"] == "horario_nao_interpretado"])

    def test_carga_no_banco_e_idempotencia(self):
        conn = novo_banco()
        db = SqliteDb(conn)
        s1 = carregar(db, self.res, "2026.1")
        conn.commit()

        def contagens():
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("disciplina", "docente", "curso", "turma", "horario_aula",
                              "disciplina_recomendacao", "quadrimestre")}

        c1 = contagens()
        self.assertEqual(c1["turma"], 983)
        self.assertEqual(c1["horario_aula"], s1["horarios"])
        self.assertEqual(c1["quadrimestre"], 1)

        carregar(db, self.res, "2026.1")  # 2ª execução não pode duplicar nada
        conn.commit()
        self.assertEqual(c1, contagens())

        com_docente = conn.execute("SELECT COUNT(*) FROM horario_aula WHERE docente_id IS NOT NULL").fetchone()[0]
        self.assertGreater(com_docente / c1["horario_aula"], 0.98)
        self.assertEqual(conn.execute("SELECT is_atual FROM quadrimestre").fetchone()[0], 1)

    def test_novo_quadrimestre_vira_o_atual(self):
        conn = novo_banco()
        db = SqliteDb(conn)
        carregar(db, self.res, "2026.1")
        carregar(db, self.res, "2026.2")
        atuais = conn.execute("SELECT codigo FROM quadrimestre WHERE is_atual").fetchall()
        self.assertEqual(atuais, [("2026.2",)])


if __name__ == "__main__":
    unittest.main()
