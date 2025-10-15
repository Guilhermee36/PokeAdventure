-- ========= TABELA 1: PLAYERS =========
-- Armazena os dados principais de cada jogador, usando o ID do Discord como chave.
CREATE TABLE players (
  discord_id BIGINT PRIMARY KEY,
  trainer_name TEXT NOT NULL,
  money INTEGER NOT NULL DEFAULT 0,
  badges INTEGER NOT NULL DEFAULT 0,
  current_region TEXT DEFAULT 'Pallet Town',
  masterballs_owned INTEGER NOT NULL DEFAULT 0
);
COMMENT ON TABLE players IS 'Tabela principal dos jogadores, vinculada ao ID do Discord.';


-- ========= TABELA 2: PLAYER_POKEMON =========
-- Armazena cada Pokémon único que um jogador possui, com seus dados dinâmicos.
CREATE TABLE player_pokemon (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  player_id BIGINT NOT NULL REFERENCES players(discord_id) ON DELETE CASCADE,
  pokemon_api_name TEXT NOT NULL,
  nickname TEXT,
  captured_at_location TEXT,
  is_shiny BOOLEAN NOT NULL DEFAULT false,
  party_position INTEGER,
  current_level INTEGER NOT NULL DEFAULT 5,
  current_xp INTEGER NOT NULL DEFAULT 0,
  current_hp INTEGER NOT NULL,
  CONSTRAINT party_position_check CHECK (party_position IS NULL OR (party_position >= 1 AND party_position <= 6)),
  CONSTRAINT unique_party_position UNIQUE (player_id, party_position)
);
COMMENT ON TABLE player_pokemon IS 'Cada linha é um Pokémon único pertencente a um jogador, com seus status que mudam.';


-- ========= TABELA 3: NPCS =========
-- Armazena todos os NPCs do jogo, sejam eles de batalha ou apenas para diálogo.
CREATE TABLE npcs (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  is_battler BOOLEAN NOT NULL DEFAULT false,
  personality_prompt TEXT,
  dialogue_example TEXT,
  reward_on_interact TEXT
);
COMMENT ON TABLE npcs IS 'Define os personagens não-jogáveis do mundo, de batalha ou não.';


-- ========= TABELA 4: NPC_POKEMON_PARTY =========
-- Tabela para montar o time dos NPCs que são batalhadores.
CREATE TABLE npc_pokemon_party (
  id SERIAL PRIMARY KEY,
  npc_id INTEGER NOT NULL REFERENCES npcs(id) ON DELETE CASCADE,
  pokemon_api_name TEXT NOT NULL,
  level INTEGER NOT NULL
);
COMMENT ON TABLE npc_pokemon_party IS 'Define o time de um NPC batalhador.';


-- ========= TABELA 5: PLAYER_QUESTS =========
-- Armazena o progresso das missões ou da história principal para cada jogador.
CREATE TABLE player_quests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  player_id BIGINT NOT NULL REFERENCES players(discord_id) ON DELETE CASCADE,
  quest_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  story_summary_so_far TEXT,
  CONSTRAINT status_check CHECK (status IN ('active', 'completed', 'failed'))
);
COMMENT ON TABLE player_quests IS 'Rastreia o progresso de missões para cada jogador.';


-- ========= TABELA 6: ITEMS (CATÁLOGO) =========
-- Catálogo de todos os itens existentes no jogo.
CREATE TABLE items (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL, -- Ex: 'ball', 'healing', 'key_item'
  description TEXT,
  effect_tag TEXT -- Tag para o código interpretar a função do item
);
COMMENT ON TABLE items IS 'Catálogo mestre de todos os itens do jogo.';


-- ========= TABELA 7: PLAYER_INVENTORY =========
-- Inventário dos jogadores, ligando um jogador a um item e sua quantidade.
CREATE TABLE player_inventory (
  player_id BIGINT NOT NULL REFERENCES players(discord_id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  quantity INTEGER NOT NULL CHECK (quantity >= 0),
  PRIMARY KEY (player_id, item_id)
);
COMMENT ON TABLE player_inventory IS 'Mostra quantos de cada item um jogador possui.';

-- ========= DADOS INICIAIS PARA A TABELA DE ITENS =========
INSERT INTO items (name, type, description, effect_tag) VALUES
  ('pokeball', 'ball', 'Uma bola usada para capturar Pokémon selvagens.', 'CATCH_RATE:1.0'),
  ('potion', 'healing', 'Restaura 20 HP de um Pokémon.', 'HEAL:20'),
  ('revive', 'healing', 'Reanima um Pokémon desmaiado com metade do HP.', 'REVIVE:0.5'),
  ('antidote', 'healing', 'Cura um Pokémon envenenado.', 'CURE:poison');