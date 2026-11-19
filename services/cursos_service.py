import pandas as pd
import logging
from database.connection import engine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_and_clean_cursos(file_path: str) -> pd.DataFrame:
    logging.info(f"Lendo arquivo: {file_path}")
    df = pd.read_csv(file_path, sep=",")
    curso_df = df[["Curso"]].drop_duplicates()
    curso_df = curso_df.rename(columns= {
            "Curso": "nome",
        })
    return curso_df

def import_cursos_to_db(file_path: str) -> None:
    try:
        df = load_and_clean_cursos(file_path)

        logging.info("Inserindo registros na tabela 'curso'...")
        df.to_sql('curso', con=engine, if_exists='append', index=False)
    except Exception as e:
        logging.error(f"Falha na importação do curso: {e}")
        raise e
       