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
TEXT_COLOR = (255, 255, 255) # Texto branco
BOX_COLOR = (54, 57, 63) # Cor de caixa (um pouco mais clara que o fundo)
SELECTED_PARTY_COLOR = (88, 101, 242) # Azul
HP_BAR_BG_COLOR = (80, 80, 80)
XP_BAR_COLOR = (0, 150, 255) # Azul para XP

# --- AJUSTE DE FONTES ---
# Aumentamos todos os tamanhos
try:
    FONT_NICKNAME = ImageFont.truetype("assets/Roboto-Bold.ttf", 40)
    FONT_LEVEL = ImageFont.truetype("assets/Roboto-Regular.ttf", 30)
    FONT_TITLE = ImageFont.truetype("assets/Roboto-Bold.ttf", 22)
    FONT_REGULAR = ImageFont.truetype("assets/Roboto-Regular.ttf", 20)
    FONT_SMALL = ImageFont.truetype("assets/Roboto-Regular.ttf", 18)
    FONT_MOVE = ImageFont.truetype("assets/Roboto-Bold.ttf", 16)
except IOError:
    print("ERRO: Fontes Roboto não encontradas! Usando fontes padrão (texto pode ficar desalinhado).")
    FONT_NICKNAME = ImageFont.load_default()
    FONT_LEVEL = ImageFont.load_default()
    FONT_TITLE = ImageFont.load_default()
    FONT_REGULAR = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()
    FONT_MOVE = ImageFont.load_default()


# --- Funções Auxiliares ---
async def _get_sprite(url: str, size: tuple = None) -> Image.Image | None:
    img_bytes = await pokeapi.download_image_bytes(url)
    if not img_bytes: return None
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    if size: img = img.resize(size, Image.LANCZOS)
    return img

def _draw_rounded_rectangle(draw_obj, xy, corner_radius, fill):
    """Desenha um retângulo com cantos arredondados."""
    x1, y1, x2, y2 = xy
    draw_obj.rectangle(
        (x1 + corner_radius, y1, x2 - corner_radius, y2), fill=fill
    )
    draw_obj.rectangle(
        (x1, y1 + corner_radius, x2, y2 - corner_radius), fill=fill
    )
    draw_obj.pieslice(
        (x1, y1, x1 + corner_radius * 2, y1 + corner_radius * 2),
        180, 270, fill=fill
    )
    draw_obj.pieslice(
        (x2 - corner_radius * 2, y1, x2, y1 + corner_radius * 2),
        270, 360, fill=fill
    )
    draw_obj.pieslice(
        (x1, y2 - corner_radius * 2, x1 + corner_radius * 2, y2),
        90, 180, fill=fill
    )
    draw_obj.pieslice(
        (x2 - corner_radius * 2, y2 - corner_radius * 2, x2, y2),
        0, 90, fill=fill
    )

# --- Função Principal ---

async def create_team_image(focused_pokemon: dict, full_team_db: list, focused_slot: int) -> BytesIO:
    
    # 1. Criar o Canvas
    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(canvas)

    # Dados do Pokémon Focado
    f_mon_db = focused_pokemon['db_data']
    f_mon_api = focused_pokemon['api_data']
    f_mon_species = focused_pokemon['species_data']
    f_xp_percent = focused_pokemon['xp_percent']
    f_xp_next = focused_pokemon['xp_for_next_level_raw']
    f_xp_current = focused_pokemon['current_xp_raw']
    
    # 2. Desenhar Nome e Nível (Topo Centralizado)
    f_name = f_mon_db['nickname'].capitalize()
    f_level = f_mon_db['current_level']
    
    draw.text((CANVAS_WIDTH // 2, 30), f_name, font=FONT_NICKNAME, fill=TEXT_COLOR, anchor="mt")
    draw.text((CANVAS_WIDTH // 2, 80), f"Nv. {f_level}", font=FONT_LEVEL, fill=TEXT_COLOR, anchor="mt")
    
    # 3. Desenhar Sprite (Centro)
    sprite_url = f_mon_api['sprites']['other']['official-artwork']['front_default']
    main_sprite = await _get_sprite(sprite_url, (280, 280)) # Tamanho ajustado
    if main_sprite:
        canvas.paste(main_sprite, ((CANVAS_WIDTH - 280) // 2, 110), main_sprite)

    # 4. Desenhar Ataques (Caixa à Esquerda)
    box_x1_moves = 40
    box_y1_moves = 130
    box_x2_moves = 290
    box_y2_moves = 370
    _draw_rounded_rectangle(draw, (box_x1_moves, box_y1_moves, box_x2_moves, box_y2_moves), 10, BOX_COLOR)
    
    draw.text((box_x1_moves + 125, box_y1_moves + 15), "Ataques", font=FONT_TITLE, fill=TEXT_COLOR, anchor="mt")
    
    current_moves = f_mon_db.get('moves', [None] * 4)
    move_y_start = box_y1_moves + 60
    for i, move_name in enumerate(current_moves):
        move_name_display = move_name.replace('-', ' ').title() if move_name else "---"
        draw.text((box_x1_moves + 125, move_y_start + i * 50), move_name_display, font=FONT_MOVE, fill=TEXT_COLOR, anchor="mm")

    # 5. Desenhar Descrição (Caixa à Direita)
    box_x1_desc = CANVAS_WIDTH - 290
    box_y1_desc = 130
    box_x2_desc = CANVAS_WIDTH - 40
    box_y2_desc = 370
    _draw_rounded_rectangle(draw, (box_x1_desc, box_y1_desc, box_x2_desc, box_y2_desc), 10, BOX_COLOR)
    
    draw.text((box_x1_desc + 125, box_y1_desc + 15), "Descrição", font=FONT_TITLE, fill=TEXT_COLOR, anchor="mt")
    
    flavor_text = pokeapi.get_portuguese_flavor_text(f_mon_species)
    wrapped_lines = textwrap.wrap(flavor_text, width=30) # Largura ajustada para a caixa
    
    desc_y_start = box_y1_desc + 60
    for i, line in enumerate(wrapped_lines[:6]): # Limita a 6 linhas
        draw.text((box_x1_desc + 125, desc_y_start + i * 25), line, font=FONT_SMALL, fill=TEXT_COLOR, anchor="mt")

    # 6. Desenhar Barra de HP (Condicional)
    bar_width = 400
    bar_height = 20
    bar_x = (CANVAS_WIDTH - bar_width) // 2
    bar_y_hp = 400 # Posição Y da barra de HP

    f_hp = f_mon_db['current_hp']
    f_max_hp = f_mon_db['max_hp']
    hp_percent = f_hp / f_max_hp
    
    hp_color = (0, 200, 0) # Verde
    if hp_percent < 0.5: hp_color = (255, 200, 0) # Amarelo
    if hp_percent < 0.2: hp_color = (255, 80, 80) # Vermelho

    # Fundo
    _draw_rounded_rectangle(draw, (bar_x, bar_y_hp, bar_x + bar_width, bar_y_hp + bar_height), 10, HP_BAR_BG_COLOR)
    # Preenchimento
    if hp_percent > 0:
        _draw_rounded_rectangle(draw, (bar_x, bar_y_hp, bar_x + (bar_width * hp_percent), bar_y_hp + bar_height), 10, hp_color)
    
    hp_text = f"HP: {f_hp}/{f_max_hp}"
    draw.text((bar_x + bar_width // 2, bar_y_hp + bar_height // 2), hp_text, font=FONT_SMALL, fill=TEXT_COLOR, anchor="mm")

    # 7. Desenhar Barra de XP (!!! NOVO !!!)
    bar_y_xp = bar_y_hp + bar_height + 15 # 15 pixels abaixo da barra de HP
    
    # Fundo
    _draw_rounded_rectangle(draw, (bar_x, bar_y_xp, bar_x + bar_width, bar_y_xp + bar_height), 10, HP_BAR_BG_COLOR)
    # Preenchimento
    if f_xp_percent > 0:
        _draw_rounded_rectangle(draw, (bar_x, bar_y_xp, bar_x + (bar_width * f_xp_percent), bar_y_xp + bar_height), 10, XP_BAR_COLOR)
    
    xp_text = f"XP: {f_xp_current} / {f_xp_next}"
    draw.text((bar_x + bar_width // 2, bar_y_xp + bar_height // 2), xp_text, font=FONT_SMALL, fill=TEXT_COLOR, anchor="mm")

    # 8. Desenhar Pokémon da Party (Inferior)
    party_y_start = CANVAS_HEIGHT - 90
    party_slot_size = 70
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
                sprite_paste_x = slot_x + (party_slot_size - small_sprite.width) // 2
                sprite_paste_y = party_y_start + (party_slot_size - small_sprite.height) // 2
                canvas.paste(small_sprite, (sprite_paste_x, sprite_paste_y), small_sprite)
        
        draw.text(
            (slot_x + party_slot_size // 2, party_y_start + party_slot_size + 10),
            f"Nv.{p_mon_db['current_level']}",
            font=FONT_SMALL,
            fill=TEXT_COLOR,
            anchor="mt"
        )

    # 9. Salvar em Buffer e Retornar
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer