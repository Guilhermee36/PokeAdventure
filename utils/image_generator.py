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
TEXT_COLOR_GRAY = (190, 190, 190) # Texto cinza mais claro

# --- Carregamento de Fontes ---
### MUDANÇA RADICAL: Fontes muito maiores ###
try:
    FONT_NICKNAME = ImageFont.truetype("assets/Roboto-Bold.ttf", 48) # Era 40
    FONT_LEVEL = ImageFont.truetype("assets/Roboto-Regular.ttf", 34) # Era 30
    FONT_TITLE = ImageFont.truetype("assets/Roboto-Bold.ttf", 28) # Era 24
    FONT_BODY = ImageFont.truetype("assets/Roboto-Regular.ttf", 20) # Era 18
    FONT_SMALL = ImageFont.truetype("assets/Roboto-Regular.ttf", 18) # Era 16
    FONT_MOVE = ImageFont.truetype("assets/Roboto-Bold.ttf", 20) # Era 18
except IOError:
    print("ERRO: Fontes Roboto não encontradas! Usando fontes padrão.")
    FONT_NICKNAME = ImageFont.load_default()
    FONT_LEVEL = ImageFont.load_default()
    FONT_TITLE = ImageFont.load_default()
    FONT_BODY = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()
    FONT_MOVE = ImageFont.load_default()

# --- Funções Auxiliares ---
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
        # Código de outline (não está sendo usado no momento, mas mantido)
        pass 

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
    f_xp_percent = focused_pokemon['xp_percent']
    
    # 3. Coluna Esquerda: Informações
    col_left_x = 40
    col_width = 400
    
    # Sprite
    sprite_url = f_mon_api['sprites']['other']['official-artwork']['front_default']
    main_sprite = await _get_sprite(sprite_url, (320, 320))
    if main_sprite:
        canvas.paste(main_sprite, (col_left_x + (col_width - 320) // 2, 40), main_sprite) # Y 20 -> 40

    # Nome e Nível (fontes maiores e reposicionados)
    f_name = f_mon_db['nickname'].capitalize()
    f_level = f_mon_db['current_level']
    draw.text((col_left_x + col_width // 2, 370), f_name, font=FONT_NICKNAME, fill=TEXT_COLOR, anchor="mt") # Y 350 -> 370
    draw.text((col_left_x + col_width // 2, 425), f"Nv. {f_level}", font=FONT_LEVEL, fill=TEXT_COLOR_GRAY, anchor="mt") # Y 400 -> 425

    ### MUDANÇA: SEÇÃO DE TIPOS REMOVIDA ###

    # Barras de HP e XP (reposicionadas no espaço dos tipos, maiores)
    bar_y_hp = 475 # Y 485 -> 475
    bar_width = col_width - 40
    bar_height = 25 # Era 22
    bar_x = col_left_x + (col_width - bar_width) // 2
    
    f_hp = f_mon_db['current_hp']
    f_max_hp = f_mon_db['max_hp']
    hp_percent = f_hp / f_max_hp
    hp_color = (0, 200, 0); 
    if hp_percent < 0.5: hp_color = (255, 200, 0); 
    if hp_percent < 0.2: hp_color = (255, 80, 80)
    _draw_progress_bar(draw, (bar_x, bar_y_hp, bar_x + bar_width, bar_y_hp + bar_height), hp_percent, HP_BAR_BG_COLOR, hp_color, f"HP: {f_hp}/{f_max_hp}", FONT_SMALL)

    # XP
    bar_y_xp = bar_y_hp + bar_height + 10 # = 510
    xp_text = f"XP: {int(f_xp_percent * 100)}%"
    _draw_progress_bar(draw, (bar_x, bar_y_xp, bar_x + bar_width, bar_y_xp + bar_height), f_xp_percent, HP_BAR_BG_COLOR, XP_BAR_COLOR, xp_text, FONT_SMALL)

    # 4. Coluna Direita: Ataques e Descrição
    col_right_x = CANVAS_WIDTH - col_width - col_left_x # = 460
    
    # Ataques (Caixa menor, fonte maior)
    box_y1_moves = 40
    box_height_moves = 200 # Era 180, aumentando um pouco para a fonte maior
    _draw_rounded_rectangle(draw, (col_right_x, box_y1_moves, col_right_x + col_width, box_y1_moves + box_height_moves), 10, BOX_COLOR)
    draw.text((col_right_x + col_width // 2, box_y1_moves + 25), "Ataques", font=FONT_TITLE, fill=TEXT_COLOR, anchor="mt") # Y 20 -> 25
    
    current_moves = f_mon_db.get('moves', [None] * 4)
    move_y_start = box_y1_moves + 70 # Y 55 -> 70
    for i, move_name in enumerate(current_moves):
        move_name_display = move_name.replace('-', ' ').title() if move_name else "---"
        draw.text((col_right_x + 30, move_y_start + i * 30), f"• {move_name_display}", font=FONT_MOVE, fill=TEXT_COLOR, anchor="lt") # Espaço 28 -> 30

    # Descrição (Caixa menor, fonte maior)
    box_y1_desc = box_y1_moves + box_height_moves + 20 # = 260
    box_height_desc = 210
    _draw_rounded_rectangle(draw, (col_right_x, box_y1_desc, col_right_x + col_width, box_y1_desc + box_height_desc), 10, BOX_COLOR)
    draw.text((col_right_x + col_width // 2, box_y1_desc + 25), "Descrição", font=FONT_TITLE, fill=TEXT_COLOR, anchor="mt") # Y 20 -> 25

    flavor_text = pokeapi.get_portuguese_flavor_text(f_mon_species)
    wrapped_lines = textwrap.wrap(flavor_text, width=38) # Largura 40 -> 38
    
    desc_y_start = box_y1_desc + 70 # Y 60 -> 70
    for i, line in enumerate(wrapped_lines[:5]): 
        draw.text((col_right_x + 25, desc_y_start + i * 28), line, font=FONT_BODY, fill=TEXT_COLOR_GRAY, anchor="lt") # Espaço 25 -> 28

    # 5. Linha Inferior: Party (Fonte maior)
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
            font=FONT_SMALL, # Esta fonte (agora 18pt) está maior
            fill=TEXT_COLOR_GRAY,
            anchor="mt"
        )

    # 6. Salvar
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer