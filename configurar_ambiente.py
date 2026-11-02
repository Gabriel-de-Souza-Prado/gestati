"""Configuração local interativa; não imprime nem recebe senha por argumento."""
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

import psycopg

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / ".gestati.local.json"


def main():
    if CONFIG_PATH.exists():
        print("A configuração local já existe e foi preservada.")
        print("Próximo comando: .\\.venv\\Scripts\\python.exe manage.py check --database default")
        return 0

    host = os.environ.get("GESTATI_DB_HOST", "localhost")
    port = os.environ.get("GESTATI_DB_PORT", "5432")
    dbname = os.environ.get("GESTATI_DB_NAME", "gestati")
    user = os.environ.get("GESTATI_DB_USER", "gestati_app")
    print(f"Conexão local: banco {dbname}, usuário {user}, servidor {host}:{port}.")
    password = getpass.getpass(f"Senha do PostgreSQL para {user}: ")
    if not password:
        print("Informe a senha da conta do banco. Nenhum arquivo foi criado.")
        return 1

    try:
        with psycopg.connect(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
            connect_timeout=5,
        ) as connection:
            row = connection.execute("SELECT current_database(), current_user").fetchone()
    except psycopg.Error:
        print("Não foi possível conectar. Confira a senha, o banco, a conta e o serviço PostgreSQL.")
        print("Nenhum arquivo de configuração foi criado.")
        return 1

    content = json.dumps(
        {"secret_key": secrets.token_urlsafe(64), "db_password": password},
        ensure_ascii=False,
        indent=2,
    )
    try:
        # Modo x impede sobrescrever uma configuração criada por outra execução.
        with CONFIG_PATH.open("x", encoding="utf-8") as config_file:
            config_file.write(content + "\n")
    except FileExistsError:
        print("Outra execução já criou a configuração; o arquivo foi preservado.")
        return 1
    except OSError:
        print("Não foi possível salvar a configuração local. Confira a permissão da pasta.")
        return 1

    print(f"Conexão confirmada: {row[0]} / {row[1]}.")
    print("Configuração salva em .gestati.local.json, excluído do Git.")
    print("A senha não foi exibida. Agora execute as migrações do projeto.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nConfiguração interrompida.")
        sys.exit(1)
