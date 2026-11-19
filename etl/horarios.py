"""Interpretação das colunas de horário da planilha de turmas."""
import re

from .config import DIA_MAP, PERIODICIDADE_MAP

_DIAS = r"segunda|terça|terca|quarta|quinta|sexta|sábado|sabado"

# Ex.: "quinta das 10:00 às 12:00, sala S-209-0, semanal "
#      "sexta das 08:00 às 10:00, quinzenal II"   (sem sala também funciona)
_AULA_RE = re.compile(
    rf"(?P<dia>{_DIAS})\s+das\s+(?P<ini>\d{{1,2}}:\d{{2}})\s+às\s+(?P<fim>\d{{1,2}}:\d{{2}})"
    rf"\s*(?:,\s*sala\s+[^,;]+?)?\s*,\s*"
    rf"(?P<per>semanal|quinzenal\s+II|quinzenal\s+I|q1|q2)\b",
    re.IGNORECASE,
)
_DIA_RE = re.compile(rf"\b(?:{_DIAS})\s+das\b", re.IGNORECASE)


def _hhmm(valor: str) -> str:
    h, m = valor.split(":")
    return f"{int(h):02d}:{m}"


def parse_horarios(texto):
    """Extrai as aulas de um texto de horário.

    Retorna (aulas, esperadas): `aulas` é a lista de dicts com
    dia_semana/horario_inicio/horario_termino/periodicidade e `esperadas` é
    quantas aulas o texto parece conter (nº de "<dia> das"). Se
    len(aulas) < esperadas, algum trecho não foi interpretado.
    """
    if not isinstance(texto, str) or not texto.strip() or texto.strip() == "0":
        return [], 0

    esperadas = len(_DIA_RE.findall(texto))
    aulas = []
    for m in _AULA_RE.finditer(texto):
        inicio, fim = _hhmm(m["ini"]), _hhmm(m["fim"])
        if fim <= inicio:  # violaria chk_horario_valido do banco
            continue
        periodicidade = re.sub(r"\s+", " ", m["per"].lower().strip())
        aulas.append(
            {
                "dia_semana": DIA_MAP[m["dia"].lower()],
                "horario_inicio": inicio,
                "horario_termino": fim,
                "periodicidade": PERIODICIDADE_MAP[periodicidade],
            }
        )
    return aulas, esperadas
