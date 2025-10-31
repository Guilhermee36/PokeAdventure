# utils/image_generator.py
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap

# VVV CORREÇÃO 1 VVV
# Mudamos de 'from utils.pokeapi_service...' para uma importação relativa '.'
# que significa "da mesma pasta em que eu (image_generator) estou"
from . import pokeapi_service as pokeapi
# ^^^ FIM DA CORREÇÃO 1 ^^^

# --- Constantes de Layout ---
CANVAS_WIDTH = 900
CANVAS_HEIGHT = 600
# ... (o resto das constantes de layout permanece o mesmo) ...
BG_COLOR = (44, 47, 51) 
TEXT_COLOR = (255, 255, 255) 
HP_BAR_BG_COLOR = (100, 100, 100) 
MOVES_BOX_COLOR = (70, 75, 78) 
PARTY_BOX_COLOR = (70, 75, 78) 
SELECTED_PARTY_COLOR = (88, 101, 242) 

# ... (o bloco try/except das fontes permanece o mesmo) ...
try:
    FONT_BOLD = ImageFont.truetype("assets/Roboto-Bold.ttf", 36)
    FONT_REGULAR = ImageFont.truetype("assets/Roboto-Regular.ttf", 20)
    FONT_SMALL = ImageFont.truetype("assets/Roboto-Regular.ttf", 16)
    FONT_LEVEL = ImageFont.truetype("assets.../Roboto-Regular.ttf", 24)
except IOError:
    print("ERRO: Arquivos de fonte (Roboto-Bold.ttf, Roboto-Regular.ttf) não encontrados na pasta 'assets'!")
    print("Usando fontes padrão do sistema. A imagem pode não ficar como o esperado.")
    FONT_BOLD = ImageFont.load_default()
    FONT_REGULAR = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()
    FONT_LEVEL = ImageFont.load_default()


# --- Funções Auxiliares ---

async def _get_sprite(url: str, size: tuple = None) -> Image.Image | None:
    """Baixa um sprite e o converte para um objeto Image do Pillow."""
    
    # VVV CORREÇÃO 2 VVV
    # Precisamos adicionar 'pokeapi.' na frente da função
    img_bytes = await pokeapi.download_image_bytes(url)
    # ^^^ FIM DA CORREÇÃO 2 ^^^

    if not img_bytes:
        return None
    
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    if size:
        img = img.resize(size, Image.LANCZOS)
    return img

# --- Função Principal ---

async def create_team_image(focused_pokemon: dict, full_team_db: list, focused_slot: int) -> BytesIO:
    """
    Cria a imagem da equipe no novo estilo.
    ... (docstring) ...
    """
    
    # 1. Criar o Canvas
    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    # Dados do Pokémon Focado
    f_mon_db = focused_pokemon['db_data']
    f_mon_api = focused_pokemon['api_data']
    f_mon_species = focused_pokemon['species_data']
    
    # ... (código para desenhar sprite, nome, nível, barra de HP, ataques) ...
    # ... (o código aqui não muda) ...
    
    # 2. Desenhar o Pokémon Focado (Grande no Centro)
    sprite_url = f_mon_api['sprites']['other']['official-artwork']['front_default']
    main_sprite = await _get_sprite(sprite_url, (250, 250)) # Ajustei o tamanho
    
    if main_sprite:
        canvas.paste(main_sprite, ((CANVAS_WIDTH - 250) // 2, 70), main_sprite) # Y ajustado

    # 3. Desenhar Nome e Nível
    f_name = f_mon_db['nickname'].capitalize()
    f_level = f_mon_db['current_level']
    draw.text((120, 30), "NOME", font=FONT_REGULAR, fill=TEXT_COLOR, anchor="mt")
    draw.text((120, 60), f_name, font=FONT_BOLD, fill=TEXT_COLOR, anchor="mt")
    draw.text((CANVAS_WIDTH - 120, 30), "NÍVEL", font=FONT_REGULAR, fill=TEXT_COLOR, anchor="mt")
    draw.text((CANVAS_WIDTH - 120, 60), f"Nv. {f_level}", font=FONT_BOLD, fill=TEXT_COLOR, anchor="mt")

    # 4. Desenhar Barra de HP (Condicional)
    f_hp = f_mon_db['current_hp']
    f_max_hp = f_mon_db['max_hp']
    hp_bar_width = 300
    hp_bar_height = 20
    hp_bar_x = (CANVAS_WIDTH - hp_bar_width) // 2
    hp_bar_y = 350
    hp_percent = f_hp / f_max_hp
    hp_color = (0, 200, 0) # Verde
    if hp_percent < 0.5: hp_color = (255, 200, 0) # Amarelo
    if hp_percent < 0.2: hp_color = (255, 80, 80) # Vermelho
    draw.rectangle((hp_bar_x, hp_bar_y, hp_bar_x + hp_bar_width, hp_bar_y + hp_bar_height), fill=HP_BAR_BG_COLOR)
    draw.rectangle((hp_bar_x, hp_bar_y, hp_bar_x + (hp_bar_width * hp_percent), hp_bar_y + hp_bar_height), fill=hp_color)
    hp_text = f"HP: {f_hp}/{f_max_hp}"
    draw.text((CANVAS_WIDTH // 2, hp_bar_y + hp_bar_height + 5), hp_text, font=FONT_SMALL, fill=TEXT_COLOR, anchor="mt")

    # 5. Desenhar Ataques (4 caixas à direita)
    draw.text((CANVAS_WIDTH - 120, 160), "ATAQUES", font=FONT_REGULAR, fill=(135, 206, 250), anchor="mt") # Azul claro
    moves_x_start = CANVAS_WIDTH - 200 # Posição X inicial
    moves_y_start = 200 # Posição Y inicial
    move_box_size = 60
    move_padding = 10
    current_moves = f_mon_db.get('moves', ['-'] * 4) # Assume 4 ataques, usa '-' se não tiver
    for i in range(4):
        row = i // 2
        col = i % 2
        box_x = moves_x_start + col * (move_box_size + move_padding)
        box_y = moves_y_start + row * (move_box_size + move_padding)
        draw.rectangle((box_x, box_y, box_x + move_box_size, box_y + move_box_size), fill=MOVES_BOX_COLOR, outline=(135, 206, 250), width=2)
        move_name = current_moves[i].replace('-', ' ').title() if i < len(current_moves) and current_moves[i] else "-"
        move_font = FONT_SMALL
        if len(move_name) > 10:
             move_font = ImageFont.truetype("assets/Roboto-Regular.ttf", 12) if "assets/Roboto-Regular.ttf" else ImageFont.load_default()
        draw.text((box_x + move_box_size // 2, box_y + move_box_size // 2), move_name, font=move_font, fill=TEXT_COLOR, anchor="mm")
    
    # 6. Desenhar Descrição da Pokédex (Embaixo do sprite principal)
    
    # VVV CORREÇÃO 3 VVV
    # Precisamos adicionar 'pokeapi.' na frente da função
    flavor_text = pokeapi.get_portuguese_flavor_text(f_mon_species)
    # ^^^ FIM DA CORREÇÃO 3 ^^^

    wrapped_lines = textwrap.wrap(flavor_text, width=60) # Ajustei a largura
    desc_y = 390 # Posição Y da descrição
    for line in wrapped_lines[:3]: # Limita a 3 linhas
        draw.text(
            (CANVAS_WIDTH // 2, desc_y),
            line,
            font=FONT_SMALL,
            fill=TEXT_COLOR,
            anchor="mt"
        )
        desc_y += 20 # Move para a próxima linha

    # 7. Desenhar Pokémon Restantes na Parte Inferior (Navegação)
    party_y_start = CANVAS_HEIGHT - 90 # Posição Y para os slots da party
    party_slot_size = 70
    party_padding = 15
    
    total_party_width = len(full_team_db) * party_slot_size + (len(full_team_db) - 1) * party_padding
    party_x_start = (CANVAS_WIDTH - total_party_width) // 2

    for i, p_mon_db in enumerate(full_team_db):
        slot_x = party_x_start + i * (party_slot_size + party_padding)
        
        box_fill = SELECTED_PARTY_COLOR if p_mon_db['party_position'] == focused_slot else PARTY_BOX_COLOR
        draw.rectangle((slot_x, party_y_start, slot_x + party_slot_size, party_y_start + party_slot_size), fill=box_fill)

        # Esta é a linha que você mencionou.
        # Agora 'pokeapi' está definido corretamente pela importação no topo.
        p_mon_api_data = await pokeapi.get_pokemon_data(p_mon_db['pokemon_api_name'])
        
        if p_mon_api_data:
            sprite_url_small = p_mon_api_data['sprites']['front_default']
            small_sprite = await _get_sprite(sprite_url_small, (party_slot_size - 10, party_slot_size - 10))
            if small_sprite:
                sprite_paste_x = slot_x + (party_slot_size - small_sprite.width) // 2
                sprite_paste_y = party_y_start + (party_slot_size - small_sprite.height) // 2
                canvas.paste(small_sprite, (sprite_paste_x, sprite_paste_y), small_sprite)
        
        draw.text(
            (slot_x + party_slot_size // 2, party_y_start + party_slot_size + 5),
            f"Nv.{p_mon_db['current_level']}",
            font=FONT_SMALL,
            fill=TEXT_COLOR,
            anchor="mt"
        )

    # 8. Salvar em Buffer e Retornar
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer