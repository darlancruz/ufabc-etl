CREATE TYPE enum_campus AS ENUM ('SA', 'SBC');
CREATE TYPE enum_tipo_aula AS ENUM ('teoria', 'pratica');
CREATE TYPE enum_dia_semana AS ENUM ('seg', 'ter', 'qua', 'qui', 'sex', 'sab');
CREATE TYPE enum_periodicidade AS ENUM ('semanal', 'q1', 'q2');


CREATE TABLE disciplina (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo VARCHAR(20) NOT NULL UNIQUE,
    nome VARCHAR(255) NOT NULL,
    carga_horaria INTEGER NOT NULL,
    creditos INTEGER NOT NULL,
    bibliografia_basica TEXT,
    bibliografia_complementar TEXT,
    horas_teoria INTEGER NOT NULL DEFAULT 0,
    horas_pratica INTEGER NOT NULL DEFAULT 0,
    horas_extensao INTEGER NOT NULL DEFAULT 0,
    horas_individuais INTEGER NOT NULL DEFAULT 0
);


CREATE TABLE curso (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome VARCHAR(255) NOT NULL
);


CREATE TABLE quadrimestre (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo VARCHAR(10) NOT NULL UNIQUE,
    ano INTEGER NOT NULL,
    numero INTEGER NOT NULL,
    is_atual BOOLEAN NOT NULL DEFAULT FALSE
    
    CONSTRAINT chk_numero_quadrimestre CHECK (numero BETWEEN 1 AND 3),
    CONSTRAINT uq_ano_quadrimestre UNIQUE (ano, numero)
);


CREATE TABLE docente (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome VARCHAR(255) NOT NULL,
    nome_normalizado VARCHAR(255) NOT NULL
);


CREATE TABLE turma (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo VARCHAR(20) NOT NULL,
    campus enum_campus NOT NULL,
    turno CHAR(1) NOT NULL,
    vagas INTEGER NOT NULL DEFAULT 0,
    reserva INTEGER NOT NULL DEFAULT 0,
    ingles BOOLEAN NOT NULL DEFAULT FALSE,
    espanhol BOOLEAN NOT NULL DEFAULT FALSE,
    disciplina_id BIGINT NOT NULL,
    curso_id BIGINT NOT NULL,
    quadrimestre_id BIGINT NOT NULL,

    CONSTRAINT fk_disciplina_turma 
        FOREIGN KEY (disciplina_id) REFERENCES disciplina(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_curso_turma 
        FOREIGN KEY (curso_id) REFERENCES curso(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_quadrimestre_turma 
        FOREIGN KEY (quadrimestre_id) REFERENCES quadrimestre(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT uq_turma_disciplina_quadrimestre_turno_campus UNIQUE (codigo, disciplina_id, quadrimestre_id, turno, campus)
);

CREATE TABLE horario_aula (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tipo enum_tipo_aula NOT NULL,
    dia_semana enum_dia_semana NOT NULL,
    periodicidade enum_periodicidade NOT NULL,
    horario_inicio TIME NOT NULL,
    horario_termino TIME NOT NULL,
    turma_id BIGINT NOT NULL,
    docente_id BIGINT, 


    CONSTRAINT fk_turma_horario 
        FOREIGN KEY (turma_id) REFERENCES turma(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_docente_horario 
        FOREIGN KEY (docente_id) REFERENCES docente(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT chk_horario_valido CHECK (horario_termino > horario_inicio)
);

CREATE TABLE disciplina_recomendacao (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    disciplina_id BIGINT NOT NULL,
    disciplina_recomendada_id BIGINT NOT NULL,

    CONSTRAINT fk_recomendacao_disciplina_pai 
        FOREIGN KEY (disciplina_id) REFERENCES disciplina(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_recomendacao_disciplina_filho 
        FOREIGN KEY (disciplina_recomendada_id) REFERENCES disciplina(id) ON DELETE CASCADE ON UPDATE CASCADE,

    CONSTRAINT uq_disciplina_recomendacao UNIQUE (disciplina_id, disciplina_recomendada_id),

    CONSTRAINT chk_disciplinas_diferentes CHECK (disciplina_id <> disciplina_recomendada_id)
);