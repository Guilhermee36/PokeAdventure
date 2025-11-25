-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.items (
  id integer NOT NULL DEFAULT nextval('items_id_seq'::regclass),
  name text NOT NULL UNIQUE,
  type text NOT NULL,
  description text,
  effect_tag text,
  required_badges integer NOT NULL DEFAULT 0,
  api_name text,
  CONSTRAINT items_pkey PRIMARY KEY (id)
);
CREATE TABLE public.locations (
  location_api_name text NOT NULL,
  name text NOT NULL,
  name_pt text,
  type text NOT NULL CHECK (type = ANY (ARRAY['city'::text, 'route'::text, 'dungeon'::text])),
  region text NOT NULL,
  has_gym boolean NOT NULL DEFAULT false,
  has_shop boolean NOT NULL DEFAULT false,
  default_area text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT locations_pkey PRIMARY KEY (location_api_name)
);
CREATE TABLE public.npcs (
  id integer NOT NULL DEFAULT nextval('npcs_id_seq'::regclass),
  name character varying NOT NULL,
  is_battler boolean DEFAULT false,
  personality_prompt text,
  dialogue_example text,
  reward_on_interact text,
  role character varying,
  location_api_name character varying,
  image_url text,
  reward_money integer,
  badge_api_name character varying,
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
  game_time_of_day text DEFAULT 'day'::text,
  story_seq integer DEFAULT 0,
  flags ARRAY NOT NULL DEFAULT '{}'::text[],
  wild_battles_since_badge integer NOT NULL DEFAULT 0,
  CONSTRAINT players_pkey PRIMARY KEY (discord_id)
);
CREATE TABLE public.routes (
  location_from text NOT NULL,
  location_to text NOT NULL,
  region text NOT NULL,
  gate jsonb NOT NULL DEFAULT '{}'::jsonb,
  distance smallint,
  notes text,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  is_mainline boolean NOT NULL DEFAULT false,
  step integer,
  CONSTRAINT routes_pkey PRIMARY KEY (location_from, location_to, region),
  CONSTRAINT routes_location_from_fkey FOREIGN KEY (location_from) REFERENCES public.locations(location_api_name),
  CONSTRAINT routes_location_to_fkey FOREIGN KEY (location_to) REFERENCES public.locations(location_api_name)
);