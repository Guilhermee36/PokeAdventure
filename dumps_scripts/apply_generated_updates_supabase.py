import os
from pathlib import Path
from datetime import datetime
import re

from supabase import create_client, Client

BASE_DIR = Path(__file__).parent
GENERATED_SQL_PATH = BASE_DIR / "generated_updates.sql"
ERROR_LOG_PATH = BASE_DIR / "update_errors_supabase.log"


def split_statements(sql: str):
    stmts = []
    current = []
    for line in sql.splitlines():
        if not line.strip() and not current:
            continue
        current.append(line)
        if line.strip().endswith(";"):
            stmts.append("\n".join(current).strip())
            current = []
    return stmts


def parse_update(stmt: str):
    collapsed = " ".join(stmt.splitlines())

    old_match = re.search(r"WHERE\s+location_api_name\s*=\s*'([^']+)'", collapsed)
    old_name = old_match.group(1) if old_match else None

    new_match = re.search(r"SET\s+location_api_name\s*=\s*'([^']+)'", collapsed)
    new_name = new_match.group(1) if new_match else None

    def_match = re.search(r"default_area\s*=\s*'([^']+)'", collapsed)
    default_area = def_match.group(1) if def_match else None

    return old_name, new_name, default_area


def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL e/ou SUPABASE_KEY não definidos nas variáveis de ambiente.\n"
            "Exemplo (PowerShell):\n"
            '  $env:SUPABASE_URL = "https://SEU_PROJETO.supabase.co"\n'
            '  $env:SUPABASE_KEY = "SUA_SERVICE_ROLE_OU_ANON_KEY"\n'
        )
    return create_client(url, key)


def main():
    if not GENERATED_SQL_PATH.exists():
        raise RuntimeError(f"{GENERATED_SQL_PATH} não encontrado.")

    sql_text = GENERATED_SQL_PATH.read_text(encoding="utf-8")
    statements = split_statements(sql_text)
    total = len(statements)
    print(f"Encontrados {total} statements em {GENERATED_SQL_PATH.name}")

    supabase = get_supabase_client()

    ok_count = 0
    fail_count = 0

    with ERROR_LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"\n\n=== Execução em {datetime.utcnow().isoformat()}Z ===\n")

        for idx, stmt in enumerate(statements, start=1):
            lines = stmt.splitlines()
            first_line = lines[0] if lines else ""
            print(f"\n[{idx}/{total}] {first_line}")

            old_name, new_name, default_area = parse_update(stmt)

            if not old_name:
                print("   -> pulando: não consegui extrair old_name")
                log.write(
                    f"[{datetime.utcnow().isoformat()}Z] NÃO PARSEADO (sem old_name) no statement {idx}:\n"
                    f"{stmt}\n\n"
                )
                fail_count += 1
                continue

            payload = {}
            if new_name:
                payload["location_api_name"] = new_name
            if default_area:
                payload["default_area"] = default_area

            if not payload:
                print("   -> nada pra atualizar, pulando")
                continue

            try:
                resp = (
                    supabase
                    .table("locations")
                    .update(payload)
                    .eq("location_api_name", old_name)
                    .execute()
                )

                # Se quiser inspecionar, deixa isso descomentado:
                # print("DEBUG resp:", resp)

                data = getattr(resp, "data", None)
                ok_count += 1  # se não deu exceção, consideramos sucesso

                if not data:
                    # aviso, mas NÃO conta como falha
                    print("   -> AVISO: resposta sem dados (isso é normal em updates no Supabase)")
                    log.write(
                        f"[{datetime.utcnow().isoformat()}Z] Update executado (sem data) no statement {idx} "
                        f"(old_name={old_name}, new_name={new_name}, default_area={default_area})\n"
                        f"SQL original:\n{stmt}\n\n"
                    )
                else:
                    print(f"   -> OK (linhas retornadas: {len(data)})")

            except Exception as e:
                fail_count += 1
                print("   -> FALHOU (Exception, ver log)")
                log.write(
                    f"[{datetime.utcnow().isoformat()}Z] Erro no statement {idx}:\n"
                    f"old_name={old_name}, new_name={new_name}, default_area={default_area}\n"
                    f"Erro: {repr(e)}\n"
                    f"SQL original:\n{stmt}\n\n"
                )

    print("\n=== RESUMO ===")
    print(f"Sucesso : {ok_count}")
    print(f"Falhas  : {fail_count}")
    print(f"Log de erros em: {ERROR_LOG_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        fallback_log = BASE_DIR / "update_errors_supabase_crash.log"
        with fallback_log.open("a", encoding="utf-8") as f:
            f.write(
                f"\n\n=== CRASH em {datetime.utcnow().isoformat()}Z ===\n"
                f"{repr(e)}\n"
            )
        print("ERRO FATAL:", repr(e))
        print(f"Detalhes adicionais em: {fallback_log}")
        raise
