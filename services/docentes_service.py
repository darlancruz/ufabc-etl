import unicodedata
import pandas as pd
import logging
from database.connection import engine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def normalizar_texto(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    texto_sem_acento = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return texto_sem_acento.lower().strip()

def load_and_clean_docentes(file_path: str) -> pd.DataFrame:
    column_mapping = {
        "Nome": "nome",
    }

    logging.info(f"Lendo arquivo: {file_path}")
    df = pd.read_csv(file_path, sep=",", usecols=list(column_mapping.keys()))
    df = df.rename(columns=column_mapping)
    
    df["nome_normalizado"] = df["nome"].apply(normalizar_texto)
        
    return df

def import_docentes_to_db(file_path: str) -> None:
    try:
        df = load_and_clean_docentes(file_path)

        logging.info("Inserindo registros na tabela 'docente'...")
        df.to_sql('docente', con=engine, if_exists='append', index=False)
    except Exception as e:
        logging.error(f"Falha na importação do docente: {e}")
        raise e
       
  
    
