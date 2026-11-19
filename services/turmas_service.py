import re
import logging
import pandas as pd
from database.connection import engine
from sqlalchemy import text

DIA_MAP = {
    'segunda': 'seg',
    'terça': 'ter',
    'quarta': 'qua',
    'quinta': 'qui',
    'sexta': 'sex',
    'sábado': 'sab',
    'sabado': 'sab'
}

PERIODICIDADE_MAP = {
    'semanal': 'semanal',
    'quinzenal i': 'q1',
    'quinzenal ii': 'q2',
    'q1': 'q1',
    'q2': 'q2'
}

CAMPUS_MAP = {
    'SA': 'SA',
    'SB': 'SBC',
    'SBC': 'SBC'
}


def parse_horarios(texto_horario):
    """
    Extrai lista de aulas de strings como:
    "quinta das 10:00 às 12:00, sala S-309-1, semanal , terça das 08:00 às 10:00, sala 402-3, quinzenal I"
    """
    if not isinstance(texto_horario, str) or not texto_horario.strip():
        return []

    pattern = re.compile(
        r'(segunda|terça|quarta|quinta|sexta|sábado|sabado)\s+das\s+(\d{2}:\d{2})\s+às\s+(\d{2}:\d{2})(?:,\s*sala\s*[^,]+)?,\s*(semanal|quinzenal\s+i|quinzenal\s+ii|q1|q2)',
        re.IGNORECASE
    )

    aulas = []
    for dia_str, inicio, termino, period_str in pattern.findall(texto_horario):
        dia_enum = DIA_MAP.get(dia_str.lower().strip())
        period_enum = PERIODICIDADE_MAP.get(period_str.lower().strip())

        if dia_enum and period_enum:
            aulas.append({
                'dia_semana': dia_enum,
                'horario_inicio': inicio,
                'horario_termino': termino,
                'periodicidade': period_enum
            })
    return aulas


def import_turmas_horarios_to_db(filepath: str, codigo_quadrimestre: str = "2026.3"):
    """
    Carrega o arquivo CSV de oferta de turmas, cria o quadrimestre se não existir,
    e popula as tabelas 'turma' e 'horario_aula'.
    """
    logging.info(f"Lendo arquivo de turmas: {filepath}")
    df = pd.read_csv(filepath)

    with engine.begin() as conn:
        # Extrair ano e número do quadrimestre do código (ex: "2026.3" -> ano=2026, numero=3)
        try:
            partes = codigo_quadrimestre.split('.')
            ano_val = int(partes[0])
            num_val = int(partes[1])
        except (IndexError, ValueError):
            raise ValueError(f"Formato de código de quadrimestre inválido: '{codigo_quadrimestre}'. Use o formato 'AAAA.N' (ex: 2026.3).")

        # 1. Inserir o quadrimestre caso ele não exista (usando a restrição UNIQUE uq_ano_quadrimestre)
        conn.execute(
            text("""
                INSERT INTO quadrimestre (codigo, ano, numero, is_atual)
                VALUES (:codigo, :ano, :numero, TRUE)
                ON CONFLICT (ano, numero) DO NOTHING;
            """),
            {"codigo": codigo_quadrimestre, "ano": ano_val, "numero": num_val}
        )

        # 2. Buscar o ID do Quadrimestre (agora garantidamente existente)
        res_quadri = conn.execute(
            text("SELECT id FROM quadrimestre WHERE codigo = :cod"),
            {"cod": codigo_quadrimestre}
        ).fetchone()

        quadrimestre_id = res_quadri[0]

        # 3. Caches de IDs (Cursos, Disciplinas e Docentes)
        cursos = dict(conn.execute(text("SELECT UPPER(nome), id FROM curso")).fetchall())
        disciplinas = dict(conn.execute(text("SELECT codigo, id FROM disciplina")).fetchall())
        docentes = dict(conn.execute(text("SELECT UPPER(nome_normalizado), id FROM docente")).fetchall())

        logging.info("Processando turmas e horários de aula...")

        for idx, row in df.iterrows():
            nome_disc = str(row['Disciplina']).strip()
            curso_nome = str(row['Curso']).strip().upper()
            sigla_disc = str(row['Sigla disciplina']).strip()

            curso_id = cursos.get(curso_nome)
            disciplina_id = disciplinas.get(sigla_disc)

            if not curso_id or not disciplina_id:
                logging.warning(f"Linha {idx}: Curso ('{curso_nome}') ou Disciplina ('{sigla_disc}') - {nome_disc} não encontrado no banco. Pulando.")
                continue

            # Tratamento de campos de turma
            ingles = str(row.get('Inglês', '')).strip().lower() in ['sim', 'yes', 'true', '1']
            espanhol = str(row.get('Espanhol', '')).strip().lower() in ['sim', 'yes', 'true', '1']
            vagas = int(row['Vagas']) if pd.notna(row['Vagas']) else 0
            reserva = int(row['Reserva']) if pd.notna(row['Reserva']) else 0
            turno = str(row['Turno']).strip()[0].upper()

            # Insert/Update na tabela 'turma'
            query_turma = text("""
                INSERT INTO turma (codigo, campus, turno, vagas, reserva, ingles, espanhol, disciplina_id, curso_id, quadrimestre_id)
                VALUES (:codigo, :campus, :turno, :vagas, :reserva, :ingles, :espanhol, :disciplina_id, :curso_id, :quadrimestre_id)
                ON CONFLICT ON CONSTRAINT uq_turma_disciplina_quadrimestre_turno_campus
                DO UPDATE SET vagas = EXCLUDED.vagas, reserva = EXCLUDED.reserva
                RETURNING id;
            """)

            campus_raw = str(row['Campus']).strip().upper()
            campus_enum = CAMPUS_MAP.get(campus_raw, campus_raw)

            turma_id = conn.execute(query_turma, {
                'codigo': str(row['Turma']).strip(),
                'campus': campus_enum,
                'turno': turno,
                'vagas': vagas,
                'reserva': reserva,
                'ingles': ingles,
                'espanhol': espanhol,
                'disciplina_id': disciplina_id,
                'curso_id': curso_id,
                'quadrimestre_id': quadrimestre_id
            }).scalar()

            # Inserir Horários de Teoria
            aulas_teoria = parse_horarios(row.get('Horário Teoria'))
            docentes_teoria_ids = [
                docentes.get(str(row[col]).strip().upper())
                for col in ['Docente Teoria', 'Docente Teoria 2', 'Docente Teoria 3']
                if col in row and pd.notna(row[col]) and docentes.get(str(row[col]).strip().upper())
            ]
            docente_teoria_id = docentes_teoria_ids[0] if docentes_teoria_ids else None

            for aula in aulas_teoria:
                conn.execute(text("""
                    INSERT INTO horario_aula (tipo, dia_semana, periodicidade, horario_inicio, horario_termino, turma_id, docente_id)
                    VALUES ('teoria', :dia_semana, :periodicidade, :horario_inicio, :horario_termino, :turma_id, :docente_id)
                """), {**aula, 'turma_id': turma_id, 'docente_id': docente_teoria_id})

            # Inserir Horários de Prática
            aulas_pratica = parse_horarios(row.get('Horário Prática'))
            docentes_pratica_ids = [
                docentes.get(str(row[col]).strip().upper())
                for col in ['Docente Prática', 'Docente Prática 2']
                if col in row and pd.notna(row[col]) and docentes.get(str(row[col]).strip().upper())
            ]
            docente_pratica_id = docentes_pratica_ids[0] if docentes_pratica_ids else None

            for aula in aulas_pratica:
                conn.execute(text("""
                    INSERT INTO horario_aula (tipo, dia_semana, periodicidade, horario_inicio, horario_termino, turma_id, docente_id)
                    VALUES ('pratica', :dia_semana, :periodicidade, :horario_inicio, :horario_termino, :turma_id, :docente_id)
                """), {**aula, 'turma_id': turma_id, 'docente_id': docente_pratica_id})

    logging.info("Turmas e horários carregados com sucesso!")
    