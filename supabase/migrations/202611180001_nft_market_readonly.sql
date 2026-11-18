-- Airdrop Hunter 3.0: read-only NFT market observations.
-- Additive migration: existing campaign/reward data is untouched.
create table if not exists public.nft_scan_runs (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    provider text not null,
    status text not null default 'started'
        check (status in ('started', 'completed', 'partial', 'failed')),
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    items_seen integer not null default 0 check (items_seen >= 0),
    error_summary text,
    metadata jsonb not null default '{}'::jsonb
);

create table if not exists public.nft_market_observations (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null references auth.users(id) on delete cascade,
    scan_run_id uuid references public.nft_scan_runs(id) on delete set null,
    provider text not null,
    chain text not null,
    marketplace text not null,
    collection_slug text not null,
    contract_address text,
    token_id text not null,
    currency text not null,
    price numeric(38, 18) not null check (price > 0),
    listing_url text,
    observed_at timestamptz not null default now(),
    raw_data jsonb not null default '{}'::jsonb
);

create index if not exists nft_observations_owner_observed_idx
    on public.nft_market_observations(owner_id, observed_at desc);
create index if not exists nft_observations_asset_idx
    on public.nft_market_observations(chain, lower(collection_slug), token_id, observed_at desc);
create index if not exists nft_scan_runs_owner_started_idx
    on public.nft_scan_runs(owner_id, started_at desc);

alter table public.nft_scan_runs enable row level security;
alter table public.nft_market_observations enable row level security;

drop policy if exists "Users read own NFT scan runs" on public.nft_scan_runs;
create policy "Users read own NFT scan runs"
    on public.nft_scan_runs for select
    using (auth.uid() = owner_id);

drop policy if exists "Users insert own NFT scan runs" on public.nft_scan_runs;
create policy "Users insert own NFT scan runs"
    on public.nft_scan_runs for insert
    with check (auth.uid() = owner_id);

drop policy if exists "Users update own NFT scan runs" on public.nft_scan_runs;
create policy "Users update own NFT scan runs"
    on public.nft_scan_runs for update
    using (auth.uid() = owner_id)
    with check (auth.uid() = owner_id);

drop policy if exists "Users read own NFT observations" on public.nft_market_observations;
create policy "Users read own NFT observations"
    on public.nft_market_observations for select
    using (auth.uid() = owner_id);

drop policy if exists "Users insert own NFT observations" on public.nft_market_observations;
create policy "Users insert own NFT observations"
    on public.nft_market_observations for insert
    with check (auth.uid() = owner_id);

comment on table public.nft_market_observations is
    'Read-only market snapshots. Not an order book and not proof of executable liquidity.';
