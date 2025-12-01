import os
from pathlib import Path
from datetime import datetime
import re
import traceback

from supabase import create_client, Client

BASE_DIR = Path(__file__).parent
GENERATED_SQL_PATH = BASE_DIR / "generated_updates.sql"
ERROR_LOG_PATH = BASE_DIR / "update_errors_supabase.log"


def log_line(log_file, text: str):
    """Helper simples pra logar no arquivo e no console ao mesmo tempo."""
    timestamp = datetime.utcnow().isoformat() + "Z"
    line = f"[{timestamp}] {text}"
    print(line)
    log_file.write(line + "\n")


def split_statements(sql: str):
    """
    Divide o arquivo SQL em statements separados, assumindo que cada um termina com ';'.
    """
    stmts = []
    current = []
    for line in sql.splitlines():
        # ignora linhas vazias antes do primeiro statement
        if not line.strip() and not current:
            continue
        current.append(line)
        if line.strip().endswith(";"):
            stmts.append("\n".join(current).strip())
            current = []
    # se sobrou algo sem ';', descarta (ou você poderia optar por logar)
    return stmts


def parse_update(stmt: str):
    """
    Extrai old_name, new_name e default_area de um UPDATE gerado.
    Exemplo de formato esperado:

      UPDATE public.locations
      SET location_api_name = 'novo_nome',
          default_area      = 'alguma-area'
      WHERE location_api_name = 'nome_antigo';

    """
    collapsed = " ".join(stmt.splitlines())

    old_match = re.search(r"WHERE\s+location_api_name\s*=\s*'([^']+)'", collapsed, re.IGNORECASE)
    old_name = old_match.group(1) if old_match else None

    new_match = re.search(r"SET\s+location_api_name\s*=\s*'([^']+)'", collapsed, re.IGNORECASE)
    new_name = new_match.group(1) if new_match else None

    def_match = re.search(r"default_area\s*=\s*'([^']+)'", collapsed, re.IGNORECASE)
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

    # Só para debug visual (não logar a key!)
    print(f"Usando SUPABASE_URL = {url}")

    supabase: Client = create_client(url, key)
    return supabase


def main():
    if not GENERATED_SQL_PATH.exists():
        raise RuntimeError(f"{GENERATED_SQL_PATH} não encontrado em {GENERATED_SQL_PATH.resolve()}.")

    sql_text = GENERATED_SQL_PATH.read_text(encoding="utf-8")
    statements = split_statements(sql_text)
    total = len(statements)
    print(f"Encontrados {total} statements em {GENERATED_SQL_PATH.name}")

    supabase = get_supabase_client()

    ok_count = 0
    fail_count = 0
    skipped_count = 0

    with ERROR_LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"\n\n=== Execução em {datetime.utcnow().isoformat()}Z ===\n")

        # Teste rápido de conexão / RLS antes de iterar tudo
        try:
            test = supabase.table("locations").select("location_api_name").limit(1).execute()
            log_line(log, f"Teste de conexão OK. Exemplo de linha retornada: {getattr(test, 'data', None)}")
        except Exception as e:
            log_line(log, f"ERRO AO TESTAR CONEXÃO COM 'locations': {repr(e)}")
            log_line(log, "Stacktrace:")
            log.write(traceback.format_exc() + "\n")
            print("Não foi possível testar a conexão. Abortando.")
            return

        for idx, stmt in enumerate(statements, start=1):
            print("\n" + "=" * 80)
            print(f"[{idx}/{total}] Statement original:")
            print(stmt)
            print("=" * 80)

            old_name, new_name, default_area = parse_update(stmt)

            if not old_name:
                log_line(log, f"[{idx}] PULANDO: não consegui extrair old_name do statement.")
                log.write(stmt + "\n\n")
                fail_count += 1
                continue

            payload = {}
            if new_name:
                payload["location_api_name"] = new_name
            if default_area:
                payload["default_area"] = default_area

            if not payload:
                log_line(log, f"[{idx}] Nada para atualizar (sem new_name e sem default_area). PULANDO.")
                skipped_count += 1
                continue

            log_line(
                log,
                f"[{idx}] Tentando atualizar: old_name={old_name}, "
                f"new_name={new_name}, default_area={default_area}"
            )

            # ==== PASSO 1: checar se o registro com old_name existe antes do update ====
            try:
                pre_check = (
                    supabase
                    .table("locations")
                    .select("location_api_name, default_area")
                    .eq("location_api_name", old_name)
                    .execute()
                )
                pre_data = getattr(pre_check, "data", None)

                if not pre_data:
                    log_line(
                        log,
                        f"[{idx}] AVISO: Nenhuma linha encontrada com location_api_name='{old_name}' "
                        f"ANTES do update. Pode já ter sido renomeado ou não existir."
                    )
                    # Não consideramos falha de fato, só pulo
                    skipped_count += 1
                    continue
                else:
                    log_line(
                        log,
                        f"[{idx}] Registro encontrado antes do update: {pre_data}"
                    )
            except Exception as e:
                fail_count += 1
                log_line(
                    log,
                    f"[{idx}] ERRO ao fazer SELECT pré-update (pode ser RLS bloqueando SELECT): {repr(e)}"
                )
                log.write("Stacktrace SELECT pré-update:\n")
                log.write(traceback.format_exc() + "\n")
                # Não prossegue para o update se nem o SELECT funciona
                continue

            # ==== PASSO 2: tentar o UPDATE ====
            try:
                resp = (
                    supabase
                    .table("locations")
                    .update(payload)
                    .eq("location_api_name", old_name)
                    .execute()
                )

                data = getattr(resp, "data", None)

                if not data:
                    # Pode ser:
                    # - UPDATE executou mas não retornou dados (dependendo de header Prefer)
                    # - Nenhuma linha foi afetada
                    # - RLS bloqueou o UPDATE silenciosamente (menos comum, geralmente dá erro)
                    log_line(
                        log,
                        f"[{idx}] AVISO: Update executado mas resposta sem dados. "
                        f"Payload enviado: {payload}"
                    )

                    # Checagem pós-update: ver se old_name ainda existe e/ou se new_name apareceu
                    try:
                        check_old = (
                            supabase
                            .table("locations")
                            .select("location_api_name")
                            .eq("location_api_name", old_name)
                            .execute()
                        )
                        check_new = None
                        if new_name:
                            check_new = (
                                supabase
                                .table("locations")
                                .select("location_api_name")
                                .eq("location_api_name", new_name)
                                .execute()
                            )

                        log_line(
                            log,
                            f"[{idx}] Pós-update: old_name existe? {bool(getattr(check_old, 'data', None))}; "
                            f"new_name existe? {bool(getattr(check_new, 'data', None)) if new_name else 'N/A'}"
                        )

                    except Exception as e2:
                        log_line(
                            log,
                            f"[{idx}] ERRO ao checar pós-update (pode ser RLS): {repr(e2)}"
                        )
                        log.write("Stacktrace pós-update:\n")
                        log.write(traceback.format_exc() + "\n")

                    # mesmo assim consideramos um "caso especial", não sucesso pleno:
                    fail_count += 1
                else:
                    # Sucesso "bonito": temos dados de volta
                    log_line(
                        log,
                        f"[{idx}] OK: linhas retornadas após o update: {len(data)} | Primeiro retorno: {data[0]}"
                    )
                    ok_count += 1

            except Exception as e:
                fail_count += 1
                log_line(
                    log,
                    f"[{idx}] FALHA no UPDATE. Erro: {repr(e)}"
                )
                log.write("Stacktrace UPDATE:\n")
                log.write(traceback.format_exc() + "\n")
                log.write(f"SQL original:\n{stmt}\n\n")

    print("\n=== RESUMO FINAL ===")
    print(f"Sucesso        : {ok_count}")
    print(f"Falhas         : {fail_count}")
    print(f"Pulos (skipped): {skipped_count}")
    print(f"Log de erros em: {ERROR_LOG_PATH.resolve()}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        fallback_log = BASE_DIR / "update_errors_supabase_crash.log"
        with fallback_log.open("a", encoding="utf-8") as f:
            f.write(
                f"\n\n=== CRASH em {datetime.utcnow().isoformat()}Z ===\n"
                f"{repr(e)}\n"
                f"{traceback.format_exc()}\n"
            )
        print("ERRO FATAL:", repr(e))
        print(f"Detalhes adicionais em: {fallback_log}")
        raise
