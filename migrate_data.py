"""
migrate_data.py — Migração de dados SQLite → PostgreSQL (Supabase)
==================================================================
Uso:
    python migrate_data.py

Este script executa automaticamente:
  1. Cria o schema no PostgreSQL (migrate)
  2. Exporta os dados do SQLite antigo (dumpdata --database=sqlite_old)
  3. Importa os dados no PostgreSQL (loaddata)

Pré-requisitos:
  - .env configurado com as credenciais do Supabase
  - psycopg2-binary instalado
  - db.sqlite3 presente na raiz do projeto
  - settings.py com o banco 'sqlite_old' configurado
"""

import subprocess
import sys
import os

# Garante que estamos no diretório do projeto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

DUMP_FILE = os.path.join(BASE_DIR, "data_dump.json")

# Apps/modelos a excluir do dump (são recriados automaticamente pelo migrate)
EXCLUDE = [
    "contenttypes",
    "auth.permission",
    "admin.logentry",
    "sessions.session",
]


def run(cmd: list[str], description: str) -> None:
    """Executa um comando e aborta em caso de erro."""
    print(f"\n{'='*60}")
    print(f"▶ {description}")
    print(f"  $ {' '.join(cmd)}")
    print("=" * 60)
    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"\n✖ ERRO ao executar: {description}")
        sys.exit(result.returncode)
    print(f"✔ {description} — OK")


def main() -> None:
    python = sys.executable  # Usa o mesmo interpretador que está rodando este script

    # ── Passo 1: Criar schema no PostgreSQL ──────────────────
    run(
        [python, "manage.py", "migrate"],
        "Criando schema no PostgreSQL (migrate)",
    )

    # ── Passo 2: Exportar dados do SQLite ────────────────────
    exclude_args = []
    for app in EXCLUDE:
        exclude_args.extend(["-e", app])

    dump_cmd = [
        python, "manage.py", "dumpdata",
        "--database=sqlite_old",
        "--natural-foreign",
        "--natural-primary",
        "--indent", "2",
        *exclude_args,
        "--output", DUMP_FILE,
    ]
    run(dump_cmd, "Exportando dados do SQLite (dumpdata)")

    # Verifica se o arquivo foi criado
    if not os.path.exists(DUMP_FILE):
        print("✖ Arquivo de dump não foi criado. Abortando.")
        sys.exit(1)

    size_kb = os.path.getsize(DUMP_FILE) / 1024
    print(f"  📦 Arquivo gerado: {DUMP_FILE} ({size_kb:.1f} KB)")

    # ── Passo 3: Importar dados no PostgreSQL ────────────────
    run(
        [python, "manage.py", "loaddata", DUMP_FILE],
        "Importando dados no PostgreSQL (loaddata)",
    )

    # ── Limpeza ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("✅ MIGRAÇÃO CONCLUÍDA COM SUCESSO!")
    print("=" * 60)
    print()
    print("Próximos passos:")
    print(f"  1. Verifique os dados: python manage.py shell → from financeiro.models import *")
    print(f"  2. Teste o login: python manage.py runserver")
    print(f"  3. Remova o banco 'sqlite_old' do settings.py")
    print(f"  4. Delete o arquivo de dump: del {DUMP_FILE}")
    print(f"  5. (Opcional) Archive o db.sqlite3 como backup")


if __name__ == "__main__":
    main()
