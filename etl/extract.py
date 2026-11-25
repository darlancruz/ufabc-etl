"""Leitura (extract) dos arquivos de entrada, com validação de colunas."""

import logging

import pandas as pd

from .normalize import canon_header


class ETLError(Exception):
    """Erro de entrada que impede a execução (arquivo ou colunas inválidas)."""


CATALOGO_COLUNAS = [
    "CODIGO",
    "DISCIPLINA",
    "CH TOTAL",
    "CREDITO",
    "BIBLIOGRAFIA BÁSICA",
    "BIBLIOGRAFIA COMPLEMENTAR",
    "HORAS_TEORIA",
    "HORAS_PRATICA",
    "HORAS_EXTENSAO",
    "HORAS_ESTUDO_INDEP",
]
CATALOGO_OPCIONAIS = ["RECOMENDAÇÃO"]

TURMAS_COLUNAS = {
    "curso": "curso",
    "codigo de turma": "codigo_turma",
    "codigo turma": "codigo_turma",
    "turma": "descricao",
    "tpei": "tpei",
    "campus": "campus",
    "turno": "turno",
    "vagas totais": "vagas",
    "vagas": "vagas",
    "vagas ingressantes": "reserva",
    "reserva": "reserva",
    "teoria": "teoria",
    "pratica": "pratica",
    "teoria com sala": "teoria_sala",
    "pratica com sala": "pratica_sala",
    "horario teoria": "teoria_sala",
    "horario pratica": "pratica_sala",
    "ingles": "ingles_col",
    "espanhol": "espanhol_col",
    "docente teoria": "doc_t1",
    "docente teoria 2": "doc_t2",
    "docente teoria 3": "doc_t3",
    "docente pratica": "doc_p1",
    "docente pratica 2": "doc_p2",
    "docente pratica 3": "doc_p3",
}
TURMAS_OBRIGATORIAS = ["curso", "codigo_turma", "campus", "turno", "vagas"]
DOCENTE_COLS_TEORIA = ["doc_t1", "doc_t2", "doc_t3"]
DOCENTE_COLS_PRATICA = ["doc_p1", "doc_p2", "doc_p3"]


def _exigir_colunas(df: pd.DataFrame, obrigatorias, origem: str) -> None:
    faltando = [c for c in obrigatorias if c not in df.columns]
    if faltando:
        raise ETLError(
            f"{origem}: colunas obrigatórias ausentes: {faltando}. "
            f"Colunas encontradas: {list(df.columns)}"
        )


def read_catalogo(caminho: str) -> pd.DataFrame:
    logging.info("Lendo catálogo: %s", caminho)
    df = pd.read_csv(caminho, encoding="utf-8-sig", dtype={"CODIGO": str})
    df.columns = [str(c).strip() for c in df.columns]
    _exigir_colunas(df, CATALOGO_COLUNAS, "Catálogo")
    return df


def read_docentes(caminho: str) -> pd.DataFrame:
    logging.info("Lendo docentes: %s", caminho)
    df = pd.read_csv(caminho, encoding="utf-8-sig")  # utf-8-sig remove o BOM
    df.columns = [str(c).strip() for c in df.columns]
    _exigir_colunas(df, ["Nome"], "Docentes")
    return df


def read_turmas(caminho: str, aba=0) -> pd.DataFrame:
    """Lê a planilha de turmas ofertadas e devolve colunas com nomes internos.

    Tudo é lido como texto para não perder zeros/códigos. Cabeçalhos são
    comparados sem acento/caixa; quando dois cabeçalhos colidem (a planilha tem
    "TURMA" e "turma"), vale o primeiro.
    """
    logging.info("Lendo planilha de turmas: %s", caminho)
    bruto = pd.read_excel(caminho, sheet_name=aba, dtype=str)

    colunas, vistos = {}, set()
    for original in bruto.columns:
        interno = TURMAS_COLUNAS.get(canon_header(original))
        if interno and interno not in vistos:
            colunas[original] = interno
            vistos.add(interno)

    df = bruto[list(colunas)].rename(columns=colunas)
    _exigir_colunas(df, TURMAS_OBRIGATORIAS, "Planilha de turmas")
    for opcional in TURMAS_COLUNAS.values():
        if opcional not in df.columns:
            df[opcional] = pd.NA
    return df.dropna(how="all").reset_index(drop=True)
