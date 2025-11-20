import os
import time
import requests
from supabase import create_client, Client

POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"


def get_supabase_client() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ Faltando SUPABASE_URL ou SUPABASE_KEY nas variáveis de ambiente.")
        raise SystemExit(1)

    print("🔗 Conectando ao Supabase...")
    return create_client(url, key)


def check_route_in_pokeapi(location_to: str) -> bool:
    """
    Retorna True se o recurso existir na PokeAPI,
    False se não existir (404) ou se der algum erro tratável.
    """

    # 👉 Ajuste o endpoint conforme o que você quer:
    #   /location/       -> locais (ex: route-1, acuity-lakefront)
    #   /location-area/  -> áreas (ex: kanto-route-1-area)
    url = f"{POKEAPI_BASE_URL}/location/{location_to}"

    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException as e:
        print(f"⚠️ Erro de rede ao consultar {location_to}: {e}")
        return False

    if resp.status_code == 200:
        return True
    elif resp.status_code == 404:
        # Não existe na PokeAPI
        return False
    else:
        print(f"⚠️ {location_to}: resposta inesperada da PokeAPI (status {resp.status_code})")
        return False


def main():
    supabase = get_supabase_client()

    print("🚀 Buscando routes no Supabase...")

    # Pega só location_to (os destinos)
    response = (
        supabase
        .table("routes")
        .select("location_to")
        .order("location_to", desc=False)
        .execute()
    )

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

    # Deduplica os nomes de location_to
    all_locations = [row.get("location_to") for row in data if row.get("location_to")]
    unique_locations = sorted(set(all_locations))

    print(f"✅ Total de registros em routes: {len(data)}")
    print(f"📍 Distintos location_to para checar na PokeAPI: {len(unique_locations)}")
    print()

    not_found = []

    for idx, loc in enumerate(unique_locations, start=1):
        print(f"[{idx}/{len(unique_locations)}] Checando '{loc}' na PokeAPI... ", end="", flush=True)
        exists = check_route_in_pokeapi(loc)

        if exists:
            print("✔️ encontrado")
        else:
            print("❌ NÃO encontrado")
            not_found.append(loc)

        # Pequeno delay pra não spammar a PokeAPI
        time.sleep(0.2)

    print("\n✨ Fim da checagem na PokeAPI.")
    print(f"❌ Total NÃO encontrados: {len(not_found)}\n")

    if not_found:
        print("Lista de location_to não encontrados na PokeAPI:")
        for loc in not_found:
            print(f"• {loc}")
    else:
        print("🎉 Todos os location_to foram encontrados na PokeAPI!")


if __name__ == "__main__":
    main()
