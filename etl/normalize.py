"""Funções de normalização de texto e nomes."""
import re
import unicodedata

import pandas as pd

_PARTICULAS = {"de", "da", "do", "das", "dos", "e", "di", "du"}


def strip_accents(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def collapse_spaces(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def normalize_name(texto) -> str:
    """minúsculas, sem acento e com espaços colapsados (chave de comparação)."""
    return collapse_spaces(strip_accents(str(texto))).lower()


def canon_header(nome_coluna) -> str:
    """Normaliza o cabeçalho de uma coluna para comparação tolerante."""
    return normalize_name(nome_coluna)


def is_blank(valor) -> bool:
    if valor is None:
        return True
    try:
        if pd.isna(valor):
            return True
    except (TypeError, ValueError):
        pass
    return str(valor).strip() == ""


def clean_docente_name(bruto):
    """Limpa o nome de docente vindo da planilha.

    Retorna None para vazio, "0" e placeholders como "0A DEFINIR DOCENTE".
    Remove sufixos entre parênteses, ex.: "FULANO(CEDIDO    )" -> "FULANO".
    """
    if is_blank(bruto):
        return None
    texto = collapse_spaces(re.sub(r"\([^)]*\)", "", str(bruto)))
    if texto in {"", "0", "-"} or "definir" in normalize_name(texto):
        return None
    return texto


def title_name(texto: str) -> str:
    """'MARIA DA SILVA' -> 'Maria da Silva' (para nomes vindos só da planilha)."""
    palavras = texto.lower().split()
    return " ".join(
        p if (i > 0 and p in _PARTICULAS) else p.capitalize()
        for i, p in enumerate(palavras)
    )
