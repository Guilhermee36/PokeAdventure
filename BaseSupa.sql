-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.items (
  id integer NOT NULL DEFAULT nextval('items_id_seq'::regclass),
  name text NOT NULL UNIQUE,
  type text NOT NULL,
  description text,
  effect_tag text,
  required_badges integer NOT NULL DEFAULT 0,
  CONSTRAINT items_pkey PRIMARY KEY (id)
);
CREATE TABLE public.npc_pokemon_party (
  id integer NOT NULL DEFAULT nextval('npc_pokemon_party_id_seq'::regclass),
  npc_id integer NOT NULL,
  pokemon_api_name text NOT NULL,
  level integer NOT NULL,
  max_hp integer DEFAULT 0,
  attack integer DEFAULT 0,
  defense integer DEFAULT 0,
  special_attack integer DEFAULT 0,
  special_defense integer DEFAULT 0,
  speed integer DEFAULT 0,
  moves jsonb DEFAULT '[null, null, null, null]'::jsonb,
  current_hp integer NOT NULL,
  CONSTRAINT npc_pokemon_party_pkey PRIMARY KEY (id),
  CONSTRAINT npc_pokemon_party_npc_id_fkey FOREIGN KEY (npc_id) REFERENCES public.npcs(id)
);
CREATE TABLE public.npcs (
  id integer NOT NULL DEFAULT nextval('npcs_id_seq'::regclass),
  name text NOT NULL,
  is_battler boolean NOT NULL DEFAULT false,
  personality_prompt text,
  dialogue_example text,
  reward_on_interact text,
  CONSTRAINT npcs_pkey PRIMARY KEY (id)
);
CREATE TABLE public.player_inventory (
  player_id bigint NOT NULL,
  item_id integer NOT NULL,
  quantity integer NOT NULL CHECK (quantity >= 0),
  CONSTRAINT player_inventory_pkey PRIMARY KEY (player_id, item_id),
  CONSTRAINT player_inventory_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(discord_id),
  CONSTRAINT player_inventory_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.items(id)
);
CREATE TABLE public.player_pokemon (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  player_id bigint NOT NULL,
  pokemon_api_name text NOT NULL,
  nickname text,
  captured_at_location text,
  is_shiny boolean NOT NULL DEFAULT false,
  party_position integer CHECK (party_position IS NULL OR party_position >= 1 AND party_position <= 6),
  current_level integer NOT NULL DEFAULT 5,
  current_xp integer NOT NULL DEFAULT 0,
  current_hp integer NOT NULL,
  max_hp integer DEFAULT 0,
  attack integer DEFAULT 0,
  defense integer DEFAULT 0,
  special_attack integer DEFAULT 0,
  special_defense integer DEFAULT 0,
  speed integer DEFAULT 0,
  moves jsonb DEFAULT '[null, null, null, null]'::jsonb,
  happiness integer DEFAULT 70,
  held_item text,
  gender text DEFAULT 'genderless'::text,
  pokemon_pokedex_id integer,
  CONSTRAINT player_pokemon_pkey PRIMARY KEY (id),
  CONSTRAINT player_pokemon_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(discord_id)
);
CREATE TABLE public.player_quests (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  player_id bigint NOT NULL,
  quest_name text NOT NULL,
  status text NOT NULL DEFAULT 'active'::text CHECK (status = ANY (ARRAY['active'::text, 'completed'::text, 'failed'::text])),
  story_summary_so_far text,
  CONSTRAINT player_quests_pkey PRIMARY KEY (id),
  CONSTRAINT player_quests_player_id_fkey FOREIGN KEY (player_id) REFERENCES public.players(discord_id)
);
CREATE TABLE public.players (
  discord_id bigint NOT NULL,
  trainer_name text NOT NULL,
  money integer NOT NULL DEFAULT 0,
  badges integer NOT NULL DEFAULT 0,
  current_region text DEFAULT 'Pallet Town'::text,
  masterballs_owned integer NOT NULL DEFAULT 0,
  current_location_name text DEFAULT 'pallet-town'::text,
  CONSTRAINT players_pkey PRIMARY KEY (discord_id)
);