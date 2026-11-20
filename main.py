"""ETL UFABC: catálogo (CSV) + docentes (CSV) + turmas ofertadas (XLSX) -> PostgreSQL.

Exemplos:
    python main.py --dry-run            # só transforma e gera relatórios/CSVs, sem banco
    python main.py --init-db            # cria as tabelas (se faltarem) e carrega tudo
    python main.py --quadrimestre 2026.1 --turmas data/raw/outra_planilha.xlsx
"""

import argparse
import csv
import logging
import re
import sys
from collections import Counter
from pathlib import Path

from etl.config import MULTI_DOCENTE_PADRAO
from etl.extract import ETLError
from etl.pipeline import build

RAW = Path("data/raw")


def escrever_csv(caminho: Path, linhas: list, colunas: list) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=colunas, extrasaction="ignore")
        w.writeheader()
        w.writerows(linhas)


def escrever_relatorios(res, pasta: Path) -> None:
    escrever_csv(
        pasta / "problemas.csv",
        res.problemas,
        ["severidade", "tipo", "chave", "detalhe"],
    )


def escrever_processados(res, pasta: Path) -> None:
    escrever_csv(
        pasta / "disciplinas.csv",
        res.disciplinas,
        [
            "codigo",
            "nome",
            "carga_horaria",
            "creditos",
            "horas_teoria",
            "horas_pratica",
            "horas_extensao",
            "horas_individuais",
            "bibliografia_basica",
            "bibliografia_complementar",
        ],
    )
    escrever_csv(
        pasta / "docentes.csv", res.docentes, ["nome", "nome_normalizado", "origem"]
    )
    escrever_csv(pasta / "cursos.csv", [{"nome": c} for c in res.cursos], ["nome"])
    escrever_csv(
        pasta / "recomendacoes.csv",
        [{"disciplina": a, "recomendada": b} for a, b in res.recomendacoes],
        ["disciplina", "recomendada"],
    )
    turmas = [{k: v for k, v in t.items() if k != "horarios"} for t in res.turmas]
    escrever_csv(
        pasta / "turmas.csv",
        turmas,
        [
            "codigo_completo",
            "codigo",
            "sigla",
            "campus",
            "turno",
            "vagas",
            "reserva",
            "ingles",
            "espanhol",
            "curso",
        ],
    )
    horarios = [
        {"codigo_completo": t["codigo_completo"], **h}
        for t in res.turmas
        for h in t["horarios"]
    ]
    escrever_csv(
        pasta / "horarios.csv",
        horarios,
        [
            "codigo_completo",
            "tipo",
            "dia_semana",
            "periodicidade",
            "horario_inicio",
            "horario_termino",
            "docente_normalizado",
        ],
    )


def resumo(res) -> str:
    c = Counter((p["severidade"], p["tipo"]) for p in res.problemas)
    linhas = [
        f"disciplinas={len(res.disciplinas)} recomendações={len(res.recomendacoes)} "
        f"docentes={len(res.docentes)} cursos={len(res.cursos)} turmas={len(res.turmas)} "
        f"horários={sum(len(t['horarios']) for t in res.turmas)}"
    ]
    linhas += [f"  [{sev}] {tipo}: {n}" for (sev, tipo), n in sorted(c.items())]
    return "\n".join(linhas)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--catalogo",
        required=True,
        help="caminho para o CSV do catálogo de disciplinas",
    )
    ap.add_argument("--docentes", default=str(RAW / "docentes_ufabc.csv"))
    ap.add_argument(
        "--turmas", required=True, help="caminho para o XLSX de turmas ofertadas"
    )
    ap.add_argument(
        "--aba", default=0, help="nome ou índice da aba da planilha (padrão: primeira)"
    )
    ap.add_argument(
        "--quadrimestre",
        required=True,
        help="AAAA.N (padrão: deduzido do nome da planilha)",
    )
    ap.add_argument(
        "--multi-docente", choices=["todos", "primeiro"], default=MULTI_DOCENTE_PADRAO
    )
    ap.add_argument(
        "--nao-marcar-atual",
        action="store_true",
        help="não marcar como quadrimestre atual",
    )
    ap.add_argument(
        "--init-db", action="store_true", help="cria as tabelas se ainda não existirem"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="não grava no banco; gera CSVs em data/processed",
    )
    ap.add_argument("--relatorios", default="reports")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )

    quadrimestre = args.quadrimestre
    if not quadrimestre:
        logging.error("Quadrimestre não especificado: use --quadrimestre AAAA.N")
        return 2

    aba = int(args.aba) if str(args.aba).isdigit() else args.aba
    try:
        res = build(args.catalogo, args.docentes, args.turmas, aba, args.multi_docente)
    except (ETLError, FileNotFoundError) as e:
        logging.error("%s", e)
        return 2

    escrever_relatorios(res, Path(args.relatorios))
    logging.info("Transformação concluída:\n%s", resumo(res))
    logging.info("Detalhes em %s", Path(args.relatorios) / "problemas.csv")

    if args.dry_run:
        escrever_processados(res, Path("data/processed"))
        logging.info(
            "Dry-run: CSVs gerados em data/processed; nada foi gravado no banco."
        )
        return 0

    from database.connection import SqlAlchemyDb, get_engine, init_schema
    from etl.load import carregar

    engine = get_engine()
    if args.init_db and init_schema(engine):
        logging.info("Tabelas criadas.")
    # Uma única transação: se algo falhar, nada é gravado pela metade.
    with engine.begin() as conn:
        stats = carregar(
            SqlAlchemyDb(conn),
            res,
            quadrimestre,
            marcar_atual=not args.nao_marcar_atual,
        )
    logging.info("=== ETL finalizado com sucesso: %s ===", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
