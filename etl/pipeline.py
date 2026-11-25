"""Orquestra extract + transform (sem tocar no banco)."""
from .config import MULTI_DOCENTE_PADRAO
from .extract import read_catalogo, read_docentes, read_turmas
from .transform import TransformResult, transform_catalogo, transform_docentes, transform_turmas


def build(
    catalogo,
    docentes,
    turmas,
    aba=0,
    multi_docente=MULTI_DOCENTE_PADRAO,
    criar_disciplinas=True,
) -> TransformResult:
    res = TransformResult()
    transform_catalogo(read_catalogo(catalogo), res)
    transform_docentes(read_docentes(docentes), res)
    codigos = {d["codigo"] for d in res.disciplinas}
    transform_turmas(
        read_turmas(turmas, aba), codigos, res, multi_docente, criar_disciplinas
    )
    return res
