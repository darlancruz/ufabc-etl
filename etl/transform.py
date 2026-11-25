"""Transformação (transform): converte os DataFrames lidos em registros prontos
para o banco. Nenhuma função aqui acessa o banco, o que permite testar tudo.
"""

import re
from dataclasses import dataclass, field

import pandas as pd

from .config import (
    CAMPUS_MAP,
    HORAS_POR_CREDITO,
    MULTI_DOCENTE_PADRAO,
    SEM_RECOMENDACAO,
    TURNO_POR_PREFIXO,
)
from .extract import DOCENTE_COLS_PRATICA, DOCENTE_COLS_TEORIA
from .horarios import parse_horarios
from .normalize import (
    clean_docente_name,
    collapse_spaces as collapse,
    is_blank,
    normalize_name,
    title_name,
)

# DA1ESTB019-17SA = turno(D) + turma(A1) + disciplina(ESTB019-17) + campus(SA)
# A turma pode vir sem número (DAESTA005-17SA -> turma "A").
CODIGO_TURMA_RE = re.compile(
    r"^(?P<turno>[DN])(?P<turma>[A-Z]\d*)"
    r"(?P<sigla>[A-Z]{2,}\d{3,4}-\d{2})(?P<campus>SA|SBC|SB)$"
)

# "BIOESTATÍSTICA A1-Matutino (SA)" -> nome "BIOESTATÍSTICA".
# Também cobre "ECON A2-Noturno (SB)-TURMA MINISTRADA EM INGLÊS".
NOME_TURMA_RE = re.compile(
    r"^(?P<nome>.+?)\s+[A-Z]\d*\s*-\s*(?:Matutino|Noturno|Diurno|Vespertino)\b.*$",
    re.IGNORECASE,
)
# TPEI da planilha: "2-2-4" (T-P-I, sem extensão) ou "1-3-4-6" (T-P-E-I).
TPEI_RE = re.compile(r"^\s*(\d+)-(\d+)-(\d+)(?:-(\d+))?\s*$")


@dataclass
class TransformResult:
    disciplinas: list = field(default_factory=list)
    recomendacoes: list = field(
        default_factory=list
    )  # (codigo_pai, codigo_recomendado)
    docentes: list = field(default_factory=list)  # {nome, nome_normalizado, origem}
    cursos: list = field(default_factory=list)
    turmas: list = field(default_factory=list)  # cada uma com "horarios"
    problemas: list = field(default_factory=list)  # rejeições e avisos

    def problema(self, severidade, tipo, chave, detalhe):
        self.problemas.append(
            {"severidade": severidade, "tipo": tipo, "chave": chave, "detalhe": detalhe}
        )


def _int(valor, padrao=0) -> int:
    if is_blank(valor):
        return padrao
    return int(float(str(valor).replace(",", ".")))


def _sim(valor) -> bool:
    return normalize_name(_texto(valor) or "") in {"sim", "s", "1", "true"}


def _texto(valor):
    return None if is_blank(valor) else str(valor).strip()


# --------------------------------------------------------------------- catálogo
def transform_catalogo(df: pd.DataFrame, res: TransformResult) -> None:
    por_codigo = {}
    for linha in df.to_dict("records"):
        codigo = str(linha["CODIGO"]).strip()
        if codigo in por_codigo:
            res.problema(
                "aviso",
                "catalogo_codigo_duplicado",
                codigo,
                "código repetido no catálogo; vale a última ocorrência",
            )
        por_codigo[codigo] = {
            "codigo": codigo,
            "nome": str(linha["DISCIPLINA"]).strip(),
            "carga_horaria": _int(linha["CH TOTAL"]),
            "creditos": _int(linha["CREDITO"]),
            "bibliografia_basica": _texto(linha["BIBLIOGRAFIA BÁSICA"]),
            "bibliografia_complementar": _texto(linha["BIBLIOGRAFIA COMPLEMENTAR"]),
            "horas_teoria": _int(linha["HORAS_TEORIA"]),
            "horas_pratica": _int(linha["HORAS_PRATICA"]),
            "horas_extensao": _int(linha["HORAS_EXTENSAO"]),
            "horas_individuais": _int(linha["HORAS_ESTUDO_INDEP"]),
            "_recomendacao": linha.get("RECOMENDAÇÃO"),
        }

    # índice nome normalizado -> códigos (para resolver as recomendações)
    por_nome = {}
    for d in por_codigo.values():
        por_nome.setdefault(normalize_name(d["nome"]), []).append(d["codigo"])

    pares = set()
    for d in por_codigo.values():
        bruto = d.pop("_recomendacao")
        if is_blank(bruto):
            continue
        for nome in (n.strip() for n in str(bruto).split(";")):
            if normalize_name(nome) in SEM_RECOMENDACAO:
                continue
            candidatos = [
                c for c in por_nome.get(normalize_name(nome), []) if c != d["codigo"]
            ]
            if not candidatos:
                res.problema(
                    "aviso",
                    "recomendacao_nao_encontrada",
                    d["codigo"],
                    f"'{nome}' não existe no catálogo",
                )
            elif len(candidatos) > 1:
                res.problema(
                    "aviso",
                    "recomendacao_ambigua",
                    d["codigo"],
                    f"'{nome}' corresponde a {candidatos}; ignorada",
                )
            else:
                pares.add((d["codigo"], candidatos[0]))

    res.disciplinas = list(por_codigo.values())
    res.recomendacoes = sorted(pares)


# ---------------------------------------------------------------------- docentes
def transform_docentes(df: pd.DataFrame, res: TransformResult) -> None:
    vistos = {}
    for nome in df["Nome"].dropna():
        nome = str(nome).strip()
        chave = normalize_name(nome)
        if not chave:
            continue
        if chave in vistos:
            res.problema(
                "aviso",
                "docente_duplicado",
                nome,
                "nome repetido no CSV de docentes; mantida a primeira linha",
            )
            continue
        vistos[chave] = {"nome": nome, "nome_normalizado": chave, "origem": "csv"}
    res.docentes = list(vistos.values())


# ------------------------------------------------------------------------ turmas
def _docentes_da_linha(linha, colunas):
    nomes = []
    for col in colunas:
        nome = clean_docente_name(linha.get(col))
        if nome and normalize_name(nome) not in [normalize_name(n) for n in nomes]:
            nomes.append(nome)
    return nomes


def _horarios_do_tipo(
    linha, tipo, col_sala, col_simples, docentes, estrategia, ctx, res
):
    """Monta os horários de um tipo de aula (teoria/prática) de uma turma."""
    # Prefere a coluna "COM SALA"; se estiver vazia, usa a coluna sem sala.
    texto = linha.get(col_sala)
    if is_blank(texto) or str(texto).strip() == "0":
        texto = linha.get(col_simples)

    aulas, esperadas = parse_horarios(texto)
    if len(aulas) < esperadas:
        res.problema(
            "aviso",
            "horario_nao_interpretado",
            ctx,
            f"{tipo}: {len(aulas)} de {esperadas} aulas interpretadas: {texto!r}",
        )
    if docentes and not aulas:
        res.problema(
            "aviso",
            "docente_sem_horario",
            ctx,
            f"{tipo}: docente(s) {docentes} sem horário; o schema só guarda docente "
            "dentro de horario_aula, então não será gravado",
        )

    escolhidos = docentes[:1] if estrategia == "primeiro" else docentes
    registros = []
    for aula in aulas:
        for docente in escolhidos or [None]:
            registros.append(
                {
                    "tipo": tipo,
                    **aula,
                    "docente_normalizado": normalize_name(docente) if docente else None,
                }
            )
    return registros


def _disciplina_da_planilha(sigla, descricao, tpei):
    """Monta uma disciplina a partir da planilha de turmas.

    Devolve (disciplina, None) ou (None, motivo). Dados aproximados: sem
    bibliografia, sem recomendações e, para TPEI de 3 partes, sem extensão.
    """
    achou = NOME_TURMA_RE.match(collapse(_texto(descricao) or ""))
    if not achou:
        return None, "não foi possível extrair o nome da coluna TURMA"
    nome = achou["nome"].strip()

    partes = TPEI_RE.match(_texto(tpei) or "")
    if not partes:
        return None, f"TPEI ausente ou inválido ({_texto(tpei)!r})"
    if partes[4] is None:  # T-P-I
        t, p, i = (int(partes[n]) for n in (1, 2, 3))
        e = 0
    else:  # T-P-E-I
        t, p, e, i = (int(partes[n]) for n in (1, 2, 3, 4))
    creditos = t + p
    if creditos == 0:
        return None, f"TPEI sem créditos ({tpei!r})"

    return {
        "codigo": sigla,
        "nome": nome,
        "carga_horaria": creditos * HORAS_POR_CREDITO,
        "creditos": creditos,
        "bibliografia_basica": None,
        "bibliografia_complementar": None,
        "horas_teoria": t,
        "horas_pratica": p,
        "horas_extensao": e,
        "horas_individuais": i,
        "origem": "planilha",
    }, None


def transform_turmas(
    df,
    codigos_catalogo,
    res,
    multi_docente=MULTI_DOCENTE_PADRAO,
    criar_disciplinas=True,
):
    codigos = set(codigos_catalogo)  # cópia: disciplinas criadas entram aqui
    conhecidos = {d["nome_normalizado"] for d in res.docentes}
    cursos, novos_docentes, chaves_vistas = [], {}, set()

    for idx, linha in enumerate(
        df.to_dict("records"), start=2
    ):  # 2 = 1ª linha de dados
        codigo_completo = _texto(linha.get("codigo_turma"))
        ctx = codigo_completo or f"linha {idx}"

        casado = CODIGO_TURMA_RE.match(codigo_completo or "")
        if not casado:
            res.problema(
                "rejeitado",
                "codigo_turma_invalido",
                ctx,
                "não segue o padrão <D|N><turma><disciplina>-<ano><campus>",
            )
            continue

        sigla, turma = casado["sigla"], casado["turma"]
        if sigla not in codigos:
            disciplina, motivo = (
                _disciplina_da_planilha(sigla, linha.get("descricao"), linha.get("tpei"))
                if criar_disciplinas
                else (None, "criação a partir da planilha desativada")
            )
            if disciplina is None:
                res.problema(
                    "rejeitado",
                    "disciplina_fora_do_catalogo",
                    ctx,
                    f"disciplina {sigla} não existe no catálogo e não foi criada: {motivo}",
                )
                continue
            codigos.add(sigla)
            res.disciplinas.append(disciplina)
            res.problema(
                "aviso",
                "disciplina_criada_da_planilha",
                sigla,
                f"{disciplina['nome']!r} não consta no catálogo; criada a partir da "
                f"planilha (TPEI {_texto(linha.get('tpei'))}): sem bibliografia e sem recomendações",
            )

        campus_bruto = _texto(linha.get("campus")) or casado["campus"]
        campus = CAMPUS_MAP.get(campus_bruto.upper())
        if not campus:
            res.problema(
                "rejeitado", "campus_invalido", ctx, f"campus {campus_bruto!r}"
            )
            continue

        turno = (
            None
            if is_blank(linha.get("turno"))
            else str(linha["turno"]).strip()[0].upper()
        )
        turno_codigo = TURNO_POR_PREFIXO[casado["turno"]]
        if turno is None:
            turno = turno_codigo
        elif turno != turno_codigo:
            res.problema(
                "aviso",
                "turno_divergente",
                ctx,
                f"coluna TURNO={turno!r} difere do prefixo do código; usado {turno!r}",
            )

        chave = (turma, sigla, turno, campus)
        if chave in chaves_vistas:
            res.problema(
                "rejeitado",
                "turma_duplicada",
                ctx,
                "mesma turma/disciplina/turno/campus já lida; ignorada",
            )
            continue
        chaves_vistas.add(chave)

        curso = (
            str(linha["curso"]).strip().upper()
            if not is_blank(linha.get("curso"))
            else None
        )
        if not curso:
            res.problema("rejeitado", "curso_ausente", ctx, "linha sem curso")
            continue
        if curso not in cursos:
            cursos.append(curso)

        docs_teoria = _docentes_da_linha(linha, DOCENTE_COLS_TEORIA)
        docs_pratica = _docentes_da_linha(linha, DOCENTE_COLS_PRATICA)
        for nome in docs_teoria + docs_pratica:
            chave_doc = normalize_name(nome)
            if chave_doc not in conhecidos and chave_doc not in novos_docentes:
                novos_docentes[chave_doc] = {
                    "nome": title_name(nome),
                    "nome_normalizado": chave_doc,
                    "origem": "planilha",
                }
        if len(docs_teoria) > 1 or len(docs_pratica) > 1:
            res.problema(
                "aviso",
                "multiplos_docentes",
                ctx,
                f"teoria={docs_teoria} prática={docs_pratica}; estratégia '{multi_docente}'",
            )

        horarios = _horarios_do_tipo(
            linha,
            "teoria",
            "teoria_sala",
            "teoria",
            docs_teoria,
            multi_docente,
            ctx,
            res,
        ) + _horarios_do_tipo(
            linha,
            "pratica",
            "pratica_sala",
            "pratica",
            docs_pratica,
            multi_docente,
            ctx,
            res,
        )

        descricao = normalize_name(_texto(linha.get("descricao")) or "")
        res.turmas.append(
            {
                "codigo": turma,
                "codigo_completo": codigo_completo,
                "sigla": sigla,
                "campus": campus,
                "turno": turno,
                "vagas": _int(linha.get("vagas")),
                "reserva": _int(linha.get("reserva")),
                "ingles": "ingles" in descricao or _sim(linha.get("ingles_col")),
                "espanhol": "espanhol" in descricao or _sim(linha.get("espanhol_col")),
                "curso": curso,
                "horarios": horarios,
            }
        )

    res.cursos = cursos
    for doc in novos_docentes.values():
        res.docentes.append(doc)
        res.problema(
            "aviso",
            "docente_criado_da_planilha",
            doc["nome"],
            "não consta no CSV de docentes; criado a partir da planilha",
        )
