import pandas as pd
import logging
from database.connection import engine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import logging
import pandas as pd
from database.connection import engine
from sqlalchemy import text

def importar_disciplinas_recomendadas(filepath: str):
    """
    Lê o catálogo CSV, extrai as recomendações de cada disciplina e insere
    os relacionamentos na tabela 'disciplina_recomendacao'.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.info(f"Lendo o catálogo de disciplinas: {filepath}")
    
    df = pd.read_csv(filepath)

    with engine.begin() as conn:
        # 1. Carregar mapas de disciplinas do banco para busca rápida por Código e por Nome (em maiúsculas)
        disciplinas_por_codigo = dict(conn.execute(text("SELECT codigo, id FROM disciplina")).fetchall())
        disciplinas_por_nome = dict(conn.execute(text("SELECT UPPER(nome), id FROM disciplina")).fetchall())

        logging.info("Processando recomendações...")

        inseridos = 0
        ignorados = 0

        for idx, row in df.iterrows():
            codigo_pai = str(row['CODIGO']).strip()
            disciplina_pai_id = disciplinas_por_codigo.get(codigo_pai)

            if not disciplina_pai_id:
                logging.warning(f"Linha {idx}: Disciplina principal com código '{codigo_pai}' não encontrada no banco. Pulando.")
                continue

            recomendacao_raw = row.get('RECOMENDAÇÃO')
            
            # Verificar se a coluna de recomendação é válida e possui conteúdo
            if pd.isna(recomendacao_raw) or not str(recomendacao_raw).strip():
                continue

            recomendacao_str = str(recomendacao_raw).strip()
            if recomendacao_str.upper() in ['NÃO HÁ', 'NAO HA', '-']:
                continue

            # Separar múltiplas recomendações delimitadas por ponto e vírgula (;)
            nomes_recomendados = [rec.strip() for rec in recomendacao_str.split(';') if rec.strip()]

            for nome_rec in nomes_recomendados:
                nome_rec_upper = nome_rec.upper()
                disciplina_filho_id = disciplinas_por_nome.get(nome_rec_upper)

                if not disciplina_filho_id:
                    logging.warning(f"Disciplina recomendada não encontrada no banco: '{nome_rec}' (para a disciplina {codigo_pai}).")
                    continue

                # Validar regra para evitar auto-recomendação (mesmo ID)
                if disciplina_pai_id == disciplina_filho_id:
                    continue

                # Inserir na tabela de relacionamento com tratamento de conflito
                try:
                    resultado = conn.execute(
                        text("""
                            INSERT INTO disciplina_recomendacao (disciplina_id, disciplina_recomendada_id)
                            VALUES (:disc_id, :rec_id)
                            ON CONFLICT ON CONSTRAINT uq_disciplina_recomendacao DO NOTHING;
                        """),
                        {
                            'disc_id': disciplina_pai_id,
                            'rec_id': disciplina_filho_id
                        }
                    )
                    if resultado.rowcount > 0:
                        inseridos += 1
                    else:
                        ignorados += 1
                except Exception as e:
                    logging.error(f"Erro ao inserir recomendação ({disciplina_pai_id} -> {disciplina_filho_id}): {e}")

        logging.info(f"Importação concluída! Recomendações inseridas: {inseridos} | Duplicadas/Ignoradas: {ignorados}")
    

def load_and_clean_catalogo(file_path: str) -> pd.DataFrame:
    column_mapping = {
        'CODIGO': 'codigo',
        'DISCIPLINA': 'nome',
        'CH TOTAL': 'carga_horaria',
        'CREDITO': 'creditos',
        'BIBLIOGRAFIA BÁSICA': 'bibliografia_basica',
        'BIBLIOGRAFIA COMPLEMENTAR': 'bibliografia_complementar',
        'HORAS_TEORIA': 'horas_teoria',
        'HORAS_PRATICA': 'horas_pratica',
        'HORAS_EXTENSAO': 'horas_extensao',
        'HORAS_ESTUDO_INDEP': 'horas_individuais'
    }

    logging.info(f"Lendo arquivo: {file_path}")
    df = pd.read_csv(file_path, sep=",", usecols=list(column_mapping.keys()))
    df = df.rename(columns=column_mapping)
    
    return df


def import_catalogo_to_db(file_path: str) -> None:
    try:
        df = load_and_clean_catalogo(file_path)
        
        logging.info("Inserindo registros na tabela 'disciplina'...")
        #df.to_sql('disciplina', con=engine, if_exists='append', index=False)

        with engine.begin() as conn:
            for _, row in df.iterrows():
                resultado = conn.execute(
                    text("""
                        INSERT INTO disciplina (
                            codigo, nome, carga_horaria, creditos, 
                            bibliografia_basica, bibliografia_complementar, 
                            horas_teoria, horas_pratica, horas_extensao, horas_individuais
                        ) VALUES (
                            :codigo, :nome, :carga_horaria, :creditos, 
                            :bibliografia_basica, :bibliografia_complementar, 
                            :horas_teoria, :horas_pratica, :horas_extensao, :horas_individuais
                        )
                        ON CONFLICT (codigo) DO UPDATE SET
                            nome = EXCLUDED.nome,
                            carga_horaria = EXCLUDED.carga_horaria,
                            creditos = EXCLUDED.creditos,
                            bibliografia_basica = EXCLUDED.bibliografia_basica,
                            bibliografia_complementar = EXCLUDED.bibliografia_complementar,
                            horas_teoria = EXCLUDED.horas_teoria,
                            horas_pratica = EXCLUDED.horas_pratica,
                            horas_extensao = EXCLUDED.horas_extensao,
                            horas_individuais = EXCLUDED.horas_individuais;
                    """),
                    {
                        'codigo': row['codigo'],
                        'nome': row['nome'],
                        'carga_horaria': int(row['carga_horaria']) if pd.notna(row['carga_horaria']) else 0,
                        'creditos': int(row['creditos']) if pd.notna(row['creditos']) else 0,
                        'bibliografia_basica': str(row['bibliografia_basica']) if pd.notna(row['bibliografia_basica']) else None,
                        'bibliografia_complementar': str(row['bibliografia_complementar']) if pd.notna(row['bibliografia_complementar']) else None,
                        'horas_teoria': int(row['horas_teoria']) if pd.notna(row['horas_teoria']) else 0,
                        'horas_pratica': int(row['horas_pratica']) if pd.notna(row['horas_pratica']) else 0,
                        'horas_extensao': int(row['horas_extensao']) if pd.notna(row['horas_extensao']) else 0,
                        'horas_individuais': int(row['horas_individuais']) if pd.notna(row['horas_individuais']) else 0,
                    }
                )
        
        logging.info("Importação de disciplinas concluída com sucesso!")
        
        logging.info("Inserindo disciplinas recomendadas na tabela 'disciplina'...")
        importar_disciplinas_recomendadas(file_path)
        
    except Exception as e:
        logging.error(f"Falha na importação do catálogo: {e}")
        raise e