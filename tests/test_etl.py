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


class TestDisciplinaDaPlanilha(unittest.TestCase):
    def _nova(self, **kw):
        base = {"descricao": "ESTATÍSTICA NOVA A1-Matutino (SA)", "tpei": "2-2-4"}
        base.update(kw)
        return _transformar([_linha(**base)], catalogo=("OUTRA-99",))

    def test_cria_disciplina_com_tpei_de_3_partes(self):
        res = self._nova()
        self.assertEqual(len(res.turmas), 1)
        d = res.disciplinas[0]
        self.assertEqual(
            (d["codigo"], d["nome"], d["creditos"], d["carga_horaria"], d["origem"]),
            ("ESTB019-17", "ESTATÍSTICA NOVA", 4, 48, "planilha"),
        )
        self.assertEqual(
            (d["horas_teoria"], d["horas_pratica"], d["horas_extensao"], d["horas_individuais"]),
            (2, 2, 0, 4),
        )
        self.assertIn("disciplina_criada_da_planilha", [p["tipo"] for p in res.problemas])

    def test_tpei_de_4_partes_traz_extensao(self):
        d = self._nova(tpei="1-3-4-6").disciplinas[0]
        self.assertEqual(
            (d["creditos"], d["horas_extensao"], d["horas_individuais"]), (4, 4, 6)
        )

    def test_nome_sem_sufixo_de_turma_e_idioma(self):
        res = self._nova(descricao="ECON X A2-Noturno (SB)-TURMA MINISTRADA EM INGLÊS")
        self.assertEqual(res.disciplinas[0]["nome"], "ECON X")

    def test_disciplina_criada_uma_vez_para_varias_turmas(self):
        linhas = [
            _linha(descricao="NOVA A1-Matutino (SA)", tpei="2-0-2"),
            _linha(codigo_turma="NA1ESTB019-17SA", turno="Noturno",
                   descricao="NOVA A1-Noturno (SA)", tpei="2-0-2"),
        ]
        res = _transformar(linhas, catalogo=("OUTRA-99",))
        self.assertEqual((len(res.turmas), len(res.disciplinas)), (2, 1))

    def test_sem_tpei_valido_continua_rejeitada(self):
        for tpei in (None, "abc", "0-0-4"):
            res = self._nova(tpei=tpei)
            self.assertEqual(res.turmas, [], tpei)
            self.assertEqual(res.disciplinas, [], tpei)
            self.assertEqual(res.problemas[0]["tipo"], "disciplina_fora_do_catalogo")

    def test_desativada_rejeita(self):
        res = _transformar([_linha(tpei="2-2-4")], catalogo=("OUTRA-99",), criar_disciplinas=False)
        self.assertEqual((res.turmas, res.disciplinas), ([], []))

    def test_catalogo_tem_prioridade_na_carga(self):
        conn = novo_banco()
        db = SqliteDb(conn)
        res = TransformResult()
        res.disciplinas = [{
            "codigo": "ESTB019-17", "nome": "NOME OFICIAL", "carga_horaria": 48, "creditos": 4,
            "bibliografia_basica": "livro", "bibliografia_complementar": None,
            "horas_teoria": 2, "horas_pratica": 2, "horas_extensao": 0, "horas_individuais": 4,
        }]
        carregar(db, res, "2027.1")
        # planilha tenta criar a mesma disciplina com dados aproximados
        res2 = _transformar([_linha(descricao="NOME APROXIMADO A1-Matutino (SA)", tpei="1-1-0")],
                            catalogo=("OUTRA-99",))
        carregar(db, res2, "2027.1")
        nome, bib = conn.execute("SELECT nome, bibliografia_basica FROM disciplina").fetchone()
        self.assertEqual((nome, bib), ("NOME OFICIAL", "livro"))

    def test_catalogo_posterior_corrige_a_criada_pela_planilha(self):
        conn = novo_banco()
        db = SqliteDb(conn)
        carregar(db, _transformar([_linha(descricao="NOME APROXIMADO A1-Matutino (SA)", tpei="2-2-4")],
                                  catalogo=("OUTRA-99",)), "2027.1")
        res = TransformResult()
        res.disciplinas = [{
            "codigo": "ESTB019-17", "nome": "NOME OFICIAL", "carga_horaria": 48, "creditos": 4,
            "bibliografia_basica": None, "bibliografia_complementar": None,
            "horas_teoria": 2, "horas_pratica": 2, "horas_extensao": 0, "horas_individuais": 4,
        }]
        carregar(db, res, "2027.1")
        self.assertEqual(conn.execute("SELECT nome FROM disciplina").fetchone()[0], "NOME OFICIAL")


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
