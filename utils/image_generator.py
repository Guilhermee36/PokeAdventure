# utils/image_generator.py
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap

# Importação relativa (da mesma pasta 'utils')
from . import pokeapi_service as pokeapi

# --- Constantes de Layout ---
CANVAS_WIDTH = 900
CANVAS_HEIGHT = 600
BG_COLOR = (44, 47, 51) # Fundo escuro
BOX_COLOR = (54, 57, 63) # Cor de caixa
SELECTED_PARTY_COLOR = (88, 101, 242) # Azul Discord
HP_BAR_BG_COLOR = (80, 80, 80)
XP_BAR_COLOR = (0, 150, 255) # Azul para XP
TEXT_COLOR = (255, 255, 255) # Texto branco
TEXT_COLOR_GRAY = (180, 180, 180) # Texto cinza claro

# Dicionário de Cores dos Tipos
TYPE_COLORS = {
    'normal': (168, 168, 120), 'fire': (240, 128, 48), 'water': (104, 144, 240),
    'grass': (120, 200, 80), 'electric': (248, 208, 48), 'ice': (152, 216, 216),
    'fighting': (192, 48, 40), 'poison': (160, 64, 160), 'ground': (224, 192, 104),
    'flying': (168, 144, 240), 'psychic': (248, 88, 136), 'bug': (168, 184, 32),
    'rock': (184, 160, 56), 'ghost': (112, 88, 152), 'dragon': (112, 56, 248),
    'dark': (112, 88, 72), 'steel': (184, 184, 208), 'fairy': (240, 182, 188),
}

# --- Carregamento de Fontes ---
### MUDANÇA: Aumentamos todos os tamanhos de fonte ###
try:
    FONT_NICKNAME = ImageFont.truetype("assets/Roboto-Bold.ttf", 40) # Era 36
    FONT_LEVEL = ImageFont.truetype("assets/Roboto-Regular.ttf", 30) # Era 26
    FONT_TITLE = ImageFont.truetype("assets/Roboto-Bold.ttf", 24) # Era 20
    FONT_BODY = ImageFont.truetype("assets/Roboto-Regular.ttf", 18) # Era 16
    FONT_SMALL = ImageFont.truetype("assets/Roboto-Regular.ttf", 16) # Era 14
    FONT_TYPE = ImageFont.truetype("assets/Roboto-Bold.ttf", 16) # Era 14
    FONT_MOVE = ImageFont.truetype("assets/Roboto-Bold.ttf", 18) # Era 16
except IOError:
    print("ERRO: Fontes Roboto não encontradas! Usando fontes padrão.")
    # Fallback para fontes padrão
    FONT_NICKNAME = ImageFont.load_default()
    FONT_LEVEL = ImageFont.load_default()
    FONT_TITLE = ImageFont.load_default()
    FONT_BODY = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()
    FONT_TYPE = ImageFont.load_default()
    FONT_MOVE = ImageFont.load_default()

# --- Funções Auxiliares ---
# (As funções _get_sprite, _draw_rounded_rectangle, e _draw_progress_bar não mudam)
async def _get_sprite(url: str, size: tuple = None) -> Image.Image | None:
    img_bytes = await pokeapi.download_image_bytes(url)
    if not img_bytes: return None
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    if size: img = img.resize(size, Image.LANCZOS)
    return img

def _draw_rounded_rectangle(draw_obj, xy, corner_radius, fill, outline=None, width=1):
    x1, y1, x2, y2 = xy
    draw_obj.rectangle((x1 + corner_radius, y1, x2 - corner_radius, y2), fill=fill)
    draw_obj.rectangle((x1, y1 + corner_radius, x2, y2 - corner_radius), fill=fill)
    draw_obj.pieslice((x1, y1, x1 + corner_radius * 2, y1 + corner_radius * 2), 180, 270, fill=fill)
    draw_obj.pieslice((x2 - corner_radius * 2, y1, x2, y1 + corner_radius * 2), 270, 360, fill=fill)
    draw_obj.pieslice((x1, y2 - corner_radius * 2, x1 + corner_radius * 2, y2), 90, 180, fill=fill)
    draw_obj.pieslice((x2 - corner_radius * 2, y2 - corner_radius * 2, x2, y2), 0, 90, fill=fill)
    
    if outline:
        draw_obj.line((x1 + corner_radius, y1, x2 - corner_radius, y1), fill=outline, width=width)
        draw_obj.line((x1 + corner_radius, y2, x2 - corner_radius, y2), fill=outline, width=width)
        draw_obj.line((x1, y1 + corner_radius, x1, y2 - corner_radius), fill=outline, width=width)
        draw_obj.line((x2, y1 + corner_radius, x2, y2 - corner_radius), fill=outline, width=width)
        draw_obj.arc((x1, y1, x1 + corner_radius * 2, y1 + corner_radius * 2), 180, 270, fill=outline, width=width)
        draw_obj.arc((x2 - corner_radius * 2, y1, x2, y1 + corner_radius * 2), 270, 360, fill=outline, width=width)
        draw_obj.arc((x1, y2 - corner_radius * 2, x1 + corner_radius * 2, y2), 90, 180, fill=outline, width=width)
        draw_obj.arc((x2 - corner_radius * 2, y2 - corner_radius * 2, x2, y2), 0, 90, fill=outline, width=width)

def _draw_progress_bar(draw, xy, percentage, bg_color, fg_color, text, text_font):
    x1, y1, x2, y2 = xy
    radius = (y2 - y1) // 2
    _draw_rounded_rectangle(draw, xy, radius, bg_color)
    if percentage > 0:
        fill_x = x1 + (x2 - x1) * percentage
        _draw_rounded_rectangle(draw, (x1, y1, fill_x, y2), radius, fg_color)
    draw.text((x1 + (x2 - x1) // 2, y1 + radius), text, font=text_font, fill=TEXT_COLOR, anchor="mm")

# --- Função Principal ---

async def create_team_image(focused_pokemon: dict, full_team_db: list, focused_slot: int) -> BytesIO:
    
    # 1. Canvas
    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    # 2. Dados
    f_mon_db = focused_pokemon['db_data']
    f_mon_api = focused_pokemon['api_data']
    f_mon_species = focused_pokemon['species_data']
    f_types = focused_pokemon['types']
    f_xp_percent = focused_pokemon['xp_percent']
    
    # 3. Coluna Esquerda: Informações
    col_left_x = 40
    col_width = 400
    
    # Sprite (maior)
    sprite_url = f_mon_api['sprites']['other']['official-artwork']['front_default']
    main_sprite = await _get_sprite(sprite_url, (320, 320)) ### MUDANÇA: Sprite 300 -> 320
    if main_sprite:
        canvas.paste(main_sprite, (col_left_x + (col_width - 320) // 2, 20), main_sprite) # Centralizado

    # Nome e Nível (fonte maior)
    f_name = f_mon_db['nickname'].capitalize()
    f_level = f_mon_db['current_level']
    draw.text((col_left_x + col_width // 2, 350), f_name, font=FONT_NICKNAME, fill=TEXT_COLOR, anchor="mt") # Y 330 -> 350
    draw.text((col_left_x + col_width // 2, 400), f"Nv. {f_level}", font=FONT_LEVEL, fill=TEXT_COLOR_GRAY, anchor="mt") # Y 375 -> 400

    # Tipos (fonte maior)
    type_y = 445 # Y 415 -> 445
    type_width = 80 # Era 70
    type_height = 25 # Era 20
    type_padding = 10
    total_types_width = (type_width * len(f_types)) + (type_padding * (len(f_types) - 1))
    type_x_start = col_left_x + (col_width - total_types_width) // 2
    
    for i, type_name in enumerate(f_types):
        type_color = TYPE_COLORS.get(type_name, (100, 100, 100))
        x = type_x_start + i * (type_width + type_padding)
        _draw_rounded_rectangle(draw, (x, type_y, x + type_width, type_y + type_height), 8, type_color) # Raio 5 -> 8
        draw.text((x + type_width // 2, type_y + type_height // 2), type_name.upper(), font=FONT_TYPE, fill=TEXT_COLOR, anchor="mm")

    # Barras de HP e XP
    bar_y_hp = 485 # Y 450 -> 485
    bar_width = col_width - 40
    bar_height = 22 # Era 20
    bar_x = col_left_x + (col_width - bar_width) // 2
    
    f_hp = f_mon_db['current_hp']
    f_max_hp = f_mon_db['max_hp']
    hp_percent = f_hp / f_max_hp
    hp_color = (0, 200, 0); 
    if hp_percent < 0.5: hp_color = (255, 200, 0); 
    if hp_percent < 0.2: hp_color = (255, 80, 80)
    _draw_progress_bar(draw, (bar_x, bar_y_hp, bar_x + bar_width, bar_y_hp + bar_height), hp_percent, HP_BAR_BG_COLOR, hp_color, f"HP: {f_hp}/{f_max_hp}", FONT_SMALL)

    # XP
    bar_y_xp = bar_y_hp + bar_height + 10 # Y 480 -> 517
    xp_text = f"XP: {int(f_xp_percent * 100)}%"
    _draw_progress_bar(draw, (bar_x, bar_y_xp, bar_x + bar_width, bar_y_xp + bar_height), f_xp_percent, HP_BAR_BG_COLOR, XP_BAR_COLOR, xp_text, FONT_SMALL)

    # 4. Coluna Direita: Ataques e Descrição
    col_right_x = CANVAS_WIDTH - col_width - col_left_x # = 460
    
    # Ataques (Caixa menor)
    box_y1_moves = 40
    ### MUDANÇA: Altura da caixa diminuída
    box_height_moves = 180 # Era 200
    _draw_rounded_rectangle(draw, (col_right_x, box_y1_moves, col_right_x + col_width, box_y1_moves + box_height_moves), 10, BOX_COLOR)
    draw.text((col_right_x + col_width // 2, box_y1_moves + 20), "Ataques", font=FONT_TITLE, fill=TEXT_COLOR, anchor="mt")
    
    current_moves = f_mon_db.get('moves', [None] * 4)
    move_y_start = box_y1_moves + 55 # Era 60
    for i, move_name in enumerate(current_moves):
        move_name_display = move_name.replace('-', ' ').title() if move_name else "---"
        draw.text((col_right_x + 30, move_y_start + i * 28), f"• {move_name_display}", font=FONT_MOVE, fill=TEXT_COLOR, anchor="lt") # Espaço 30 -> 28

    # Descrição (Caixa menor)
    ### MUDANÇA: Caixa de descrição reposicionada e altura diminuída
    box_y1_desc = box_y1_moves + box_height_moves + 20 # = 240
    box_height_desc = 210 # Era 230
    _draw_rounded_rectangle(draw, (col_right_x, box_y1_desc, col_right_x + col_width, box_y1_desc + box_height_desc), 10, BOX_COLOR)
    draw.text((col_right_x + col_width // 2, box_y1_desc + 20), "Descrição", font=FONT_TITLE, fill=TEXT_COLOR, anchor="mt")

    flavor_text = pokeapi.get_portuguese_flavor_text(f_mon_species)
    wrapped_lines = textwrap.wrap(flavor_text, width=40) # Largura 45 -> 40
    
    desc_y_start = box_y1_desc + 60 # Era 60
    ### MUDANÇA: Limite de linhas diminuído para 5
    for i, line in enumerate(wrapped_lines[:5]): # Era :6
        draw.text((col_right_x + 25, desc_y_start + i * 25), line, font=FONT_BODY, fill=TEXT_COLOR_GRAY, anchor="lt") # Espaço 25

    # 5. Linha Inferior: Party
    party_y_start = CANVAS_HEIGHT - 80
    party_slot_size = 60
    party_padding = 15
    
    total_party_width = len(full_team_db) * party_slot_size + (len(full_team_db) - 1) * party_padding
    party_x_start = (CANVAS_WIDTH - total_party_width) // 2

    for i, p_mon_db in enumerate(full_team_db):
        slot_x = party_x_start + i * (party_slot_size + party_padding)
        
        box_fill = SELECTED_PARTY_COLOR if p_mon_db['party_position'] == focused_slot else BOX_COLOR
        _draw_rounded_rectangle(draw, (slot_x, party_y_start, slot_x + party_slot_size, party_y_start + party_slot_size), 5, box_fill)

        p_mon_api_data = await pokeapi.get_pokemon_data(p_mon_db['pokemon_api_name'])
        if p_mon_api_data:
            sprite_url_small = p_mon_api_data['sprites']['front_default']
            small_sprite = await _get_sprite(sprite_url_small, (party_slot_size, party_slot_size))
            if small_sprite:
                canvas.paste(small_sprite, (slot_x, party_y_start), small_sprite)
        
        draw.text(
            (slot_x + party_slot_size // 2, party_y_start + party_slot_size + 10),
            f"L.{p_mon_db['current_level']}",
            font=FONT_SMALL,
            fill=TEXT_COLOR_GRAY,
            anchor="mt"
        )

    # 6. Salvar
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer