import logging
from services.catalago_service import import_catalogo_to_db
from services.docentes_service import import_docentes_to_db
from services.cursos_service import import_cursos_to_db
from services.turmas_service import import_turmas_horarios_to_db

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def main():
    logging.info("=== Iniciando Pipeline de Carga dos Dados ===")
    
    CATALOGO_FILE = "./data/raw/catalogo_disciplinas_padronizado_2025_2026.csv"
    DOCENTES_FILE = "./data/raw/docentes_ufabc.csv"
    QUAD_FILE = "./data/raw/2026_3.csv"

    try:
        logging.info("--> Executando ETL: Catálogo de Disciplinas")
        import_catalogo_to_db(CATALOGO_FILE)

        logging.info("--> Executando ETL: Docentes")
        import_docentes_to_db(DOCENTES_FILE)

        logging.info("--> Executando ETL: Cursos")
        import_cursos_to_db(QUAD_FILE)

        logging.info("--> Executando ETL: Turmas e Horários de Aula")
        import_turmas_horarios_to_db(QUAD_FILE, codigo_quadrimestre="2026.3")

        logging.info("=== Processo ETL finalizado com sucesso! ===")

    except Exception as e:
        logging.critical(f"Execução interrompida devido a um erro não tratado: {e}")

if __name__ == "__main__":
    main()