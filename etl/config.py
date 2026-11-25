"""Constantes e mapeamentos usados pelo ETL."""

DIA_MAP = {
    "segunda": "seg",
    "terça": "ter",
    "terca": "ter",
    "quarta": "qua",
    "quinta": "qui",
    "sexta": "sex",
    "sábado": "sab",
    "sabado": "sab",
}

PERIODICIDADE_MAP = {
    "semanal": "semanal",
    "quinzenal i": "q1",
    "quinzenal ii": "q2",
    "q1": "q1",
    "q2": "q2",
}

# A planilha usa "SB"; o banco usa "SBC" (enum_campus).
CAMPUS_MAP = {"SA": "SA", "SB": "SBC", "SBC": "SBC"}

# Prefixo do código de turma (D = diurno/matutino, N = noturno) -> CHAR(1) do banco.
TURNO_POR_PREFIXO = {"D": "M", "N": "N"}

# Quando uma turma tem mais de um docente para o mesmo tipo de aula (teoria/prática):
#   "todos"    -> uma linha em horario_aula por docente (co-docência); nada se perde,
#                 mas o mesmo horário aparece repetido com docentes diferentes.
#   "primeiro" -> só o primeiro docente é gravado (comportamento do ETL antigo).
MULTI_DOCENTE_PADRAO = "todos"

# Valores (já normalizados) que significam "sem recomendação".
SEM_RECOMENDACAO = {"nao ha", "-", ""}

# Disciplina criada a partir da planilha (quando ausente do catálogo):
# carga horária = créditos (T + P) x 12 horas.
HORAS_POR_CREDITO = 12
