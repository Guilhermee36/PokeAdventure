import os
from supabase import create_client, Client


def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_ANON_KEY")

    if not url or not key:
        print("❌ Faltando SUPABASE_URL ou SUPABASE_ANON_KEY nas variáveis de ambiente.")
        raise SystemExit(1)

    print("🔗 Conectando ao Supabase...")
    return create_client(url, key)


def main():
    supabase = get_supabase_client()

    print("🚀 Iniciando listagem de routes (api_name)...")

    # Ajuste o nome da tabela/campos aqui se forem diferentes
    response = (
        supabase
        .table("routes")              # nome da tabela
        .select("id, api_name")       # campos que você quer listar
        .order("id", desc=False)      # ordenar por id crescente
        .execute()
    )

    # Se a lib que você estiver usando expõe 'error'
    error = getattr(response, "error", None)
    data = getattr(response, "data", None)

    if error:
        print("❌ Erro ao buscar routes no Supabase:")
        print(error)
        raise SystemExit(1)

    if data is None:
        print("⚠️ Nenhum dado retornado (data=None). Resposta completa:")
        print(response)
        raise SystemExit(1)

    print(f"✅ Total de routes encontrados: {len(data)}")

    for row in data:
        # Garante que não quebra se faltar algum campo
        route_id = row.get("id")
        api_name = row.get("api_name")
        print(f"• id={route_id} | api_name={api_name}")

    print("✨ Fim da listagem de routes.")


if __name__ == "__main__":
    main()
