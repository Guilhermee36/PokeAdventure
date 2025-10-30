# utils/image_generator.py
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap
# Importa o helper que acabamos de adicionar em pokeapi_service
from utils.pokeapi_service import download_image_bytes, get_portuguese_flavor_text 

# --- Constantes de Layout ---
CANVAS_WIDTH = 900
CANVAS_HEIGHT = 600
BG_COLOR = (240, 240, 240) # Um cinza claro de fundo
TEXT_COLOR = (30, 30, 30)
GRAY_COLOR = (100, 100, 100)

# Caminhos das fontes (ELE VAI PROCURAR NA PASTA 'assets' QUE VOCÊ CRIOU)
try:
    FONT_BOLD = ImageFont.truetype("/assets/static/Roboto-Bold.ttf", 36)
    FONT_REGULAR = ImageFont.truetype("/assets/static/Roboto-Regular.ttf", 20)
    FONT_SMALL = ImageFont.truetype("/assets/static/Roboto-Regular.ttf", 16)
except IOError:
    print("ERRO: Arquivos de fonte (Roboto-Bold.ttf, Roboto-Regular.ttf) não encontrados na pasta 'assets'!")
    print("Usando fontes padrão do sistema. A imagem pode ficar feia.")
    FONT_BOLD = ImageFont.load_default()
    FONT_REGULAR = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()

# --- Funções Auxiliares ---

async def _get_sprite(url: str, size: tuple = None) -> Image.Image | None:
    """Baixa um sprite e o converte para um objeto Image do Pillow."""
    img_bytes = await download_image_bytes(url)
    if not img_bytes:
        return None
    
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    if size:
        img = img.resize(size, Image.LANCZOS) # LANCZOS é um algoritmo de resize de alta qualidade
    return img

# --- Função Principal ---

async def create_team_image(focused_pokemon: dict, other_team: list) -> BytesIO:
    """
    Cria a imagem da equipe.
    
    focused_pokemon: { 'db_data': {...}, 'api_data': {...}, 'species_data': {...} }
    other_team: [ { 'db_data': {...}, 'api_data': {...} }, ... ] (lista de até 5 pokémon)
    """
    
    # 1. Criar o Canvas
    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    # 2. Desenhar o Pokémon Focado (Grande no Centro)
    f_mon_db = focused_pokemon['db_data']
    f_mon_api = focused_pokemon['api_data']
    f_mon_species = focused_pokemon['species_data']
    
    # Usamos o "Official Artwork" para o Pokémon principal
    sprite_url = f_mon_api['sprites']['other']['official-artwork']['front_default']
    main_sprite = await _get_sprite(sprite_url, (350, 350))
    
    if main_sprite:
        # Posição do sprite principal (centro-superior)
        canvas.paste(main_sprite, ( (CANVAS_WIDTH - 350) // 2 , 20), main_sprite)

    # 3. Desenhar Informações do Pokémon Focado
    # Nome e Nível
    f_name = f_mon_db['nickname'].capitalize()
    f_level = f_mon_db['current_level']
    draw.text(
        (CANVAS_WIDTH // 2, 380), # Posição
        f"{f_name} - Nv. {f_level}",
        font=FONT_BOLD,
        fill=TEXT_COLOR,
        anchor="mt" # Âncora no "meio-topo" (centraliza o texto)
    )
    
    # Barra de HP
    f_hp = f_mon_db['current_hp']
    f_max_hp = f_mon_db['max_hp']
    hp_bar_width = 300
    hp_percent = f_hp / f_max_hp
    hp_color = (80, 220, 80) # Verde
    if hp_percent < 0.5: hp_color = (255, 200, 0) # Amarelo
    if hp_percent < 0.2: hp_color = (255, 80, 80) # Vermelho
    
    draw.rectangle(
        ((CANVAS_WIDTH - hp_bar_width) // 2, 425, (CANVAS_WIDTH + hp_bar_width) // 2, 435),
        fill=(200, 200, 200) # Fundo da barra
    )
    draw.rectangle(
        ((CANVAS_WIDTH - hp_bar_width) // 2, 425, (CANVAS_WIDTH - hp_bar_width) // 2 + (hp_bar_width * hp_percent), 435),
        fill=hp_color # Cor da vida
    )
    
    # 4. Desenhar Descrição da Pokédex (Embaixo)
    flavor_text = get_portuguese_flavor_text(f_mon_species)
    
    # Quebra o texto para caber na caixa
    wrapped_lines = textwrap.wrap(flavor_text, width=80) 
    
    desc_y = 450 # Posição Y inicial da descrição
    for line in wrapped_lines[:2]: # Limita a 2 linhas
        draw.text(
            (CANVAS_WIDTH // 2, desc_y),
            line,
            font=FONT_REGULAR,
            fill=GRAY_COLOR,
            anchor="mt"
        )
        desc_y += 25 # Move para a próxima linha

    # 5. Desenhar Pokémon Restantes (Posições Sobrando)
    # Vamos colocá-los em uma linha na parte de baixo
    
    other_slots_y = 500 # Posição Y da linha dos outros Pokémon
    slot_width = 150 # Largura de cada "slot" de Pokémon
    total_slots_width = slot_width * len(other_team)
    start_x = (CANVAS_WIDTH - total_slots_width) // 2 + (slot_width // 2)

    for i, other_mon in enumerate(other_team):
        o_mon_db = other_mon['db_data']
        o_mon_api = other_mon['api_data']
        
        o_sprite_url = o_mon_api['sprites']['front_default'] # Sprite pequeno
        o_sprite = await _get_sprite(o_sprite_url, (96, 96))
        
        x_pos = start_x + (i * slot_width)
        
        if o_sprite:
            canvas.paste(o_sprite, (x_pos - 48, other_slots_y), o_sprite) # -48 para centralizar
        
        # Texto do outro Pokémon
        draw.text(
            (x_pos, other_slots_y + 100),
            f"{o_mon_db['nickname'].capitalize()} (Nv. {o_mon_db['current_level']})",
            font=FONT_SMALL,
            fill=TEXT_COLOR,
            anchor="mt"
        )

    # 6. Salvar em Buffer e Retornar
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer