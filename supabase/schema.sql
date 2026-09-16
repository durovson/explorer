-- Run once in Supabase SQL Editor. The bot uses only the service-role key server-side.
create extension if not exists pgcrypto;

create table if not exists public.users (
    telegram_id bigint primary key,
    username text,
    first_name text,
    referrer_id bigint references public.users(telegram_id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (referrer_id is null or referrer_id <> telegram_id)
);

create table if not exists public.orders (
    id uuid primary key,
    user_id bigint not null references public.users(telegram_id),
    recipient varchar(33) not null,
    product_type text not null check (product_type in ('STARS', 'PREMIUM')),
    stars_amount integer,
    premium_months integer,
    currency text not null check (currency in ('TON', 'USDT')),
    amount numeric(36, 9) not null check (amount > 0),
    wallet_address varchar(128) not null,
    memo varchar(64) not null unique,
    status text not null check (status in (
        'CREATED', 'WAITING_PAYMENT', 'PAYMENT_CONFIRMED', 'PROCESSING',
        'COMPLETED', 'EXPIRED', 'CANCELLED', 'FAILED', 'MANUAL_REVIEW'
    )),
    expires_at timestamptz not null,
    paid_at timestamptz,
    completed_at timestamptz,
    tx_hash varchar(128),
    tx_lt numeric(30, 0),
    sender_address varchar(128),
    fragment_order_id varchar(256),
    fragment_response jsonb,
    error text,
    processing_lease_until timestamptz,
    bot_chat_id bigint,
    bot_message_id bigint,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (
        (product_type = 'STARS' and stars_amount between 50 and 1000000 and premium_months is null)
        or
        (product_type = 'PREMIUM' and premium_months in (3, 6, 12) and stars_amount is null)
    )
);

create unique index if not exists orders_tx_hash_unique
    on public.orders(tx_hash) where tx_hash is not null;
create index if not exists orders_status_currency_created_idx
    on public.orders(status, currency, created_at);
create index if not exists orders_user_created_idx
    on public.orders(user_id, created_at desc);
create index if not exists orders_expires_idx
    on public.orders(expires_at) where status = 'WAITING_PAYMENT';

create table if not exists public.order_status_history (
    id bigint generated always as identity primary key,
    order_id uuid not null references public.orders(id) on delete cascade,
    from_status text,
    to_status text not null,
    actor_id bigint,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
create index if not exists order_history_order_idx
    on public.order_status_history(order_id, created_at);

create table if not exists public.fulfillment_attempts (
    id bigint generated always as identity primary key,
    order_id uuid not null references public.orders(id) on delete cascade,
    attempt_no integer not null,
    idempotency_key text not null unique,
    status text not null check (status in ('CLAIMED', 'SUBMITTED', 'COMPLETED', 'REJECTED', 'UNKNOWN')),
    request_payload jsonb not null,
    response_payload jsonb,
    http_status integer,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(order_id, attempt_no)
);

-- This is an immutable audit ledger, not a spendable/internal user balance.
create table if not exists public.referral_rewards (
    id bigint generated always as identity primary key,
    order_id uuid not null unique references public.orders(id),
    referrer_id bigint not null references public.users(telegram_id),
    currency text not null check (currency in ('TON', 'USDT')),
    amount numeric(36, 9) not null check (amount > 0),
    status text not null default 'RECORDED' check (status in ('RECORDED', 'PAID')),
    payout_tx_hash varchar(128),
    paid_at timestamptz,
    created_at timestamptz not null default now(),
    check ((status = 'PAID') = (payout_tx_hash is not null and paid_at is not null))
);

create table if not exists public.bot_settings (
    id integer primary key default 1 check (id = 1),
    referral_reward_rate numeric(8, 6) not null default 0 check (referral_reward_rate between 0 and 0.20),
    updated_at timestamptz not null default now()
);
insert into public.bot_settings(id) values (1) on conflict (id) do nothing;

create or replace function public.log_initial_order_status()
returns trigger language plpgsql set search_path = public
as $$
begin
    insert into public.order_status_history(order_id, from_status, to_status)
    values (new.id, null, new.status);
    return new;
end;
$$;
drop trigger if exists orders_initial_status_history on public.orders;
create trigger orders_initial_status_history
after insert on public.orders
for each row execute function public.log_initial_order_status();

alter table public.users enable row level security;
alter table public.orders enable row level security;
alter table public.order_status_history enable row level security;
alter table public.fulfillment_attempts enable row level security;
alter table public.referral_rewards enable row level security;
alter table public.bot_settings enable row level security;

create or replace function public.assign_referrer_once(
    p_referred_id bigint,
    p_referrer_id bigint
) returns boolean
language plpgsql security definer set search_path = public
as $$
begin
    if p_referred_id = p_referrer_id or not exists (
        select 1 from public.users where telegram_id = p_referrer_id
    ) then
        return false;
    end if;
    update public.users
       set referrer_id = p_referrer_id, updated_at = now()
     where telegram_id = p_referred_id and referrer_id is null;
    return found;
end;
$$;

create or replace function public.referral_stats(p_user_id bigint)
returns table(invited bigint, paid_orders bigint, paid_ton numeric, paid_usdt numeric)
language sql stable security definer set search_path = public
as $$
    select
        (select count(*) from public.users where referrer_id = p_user_id),
        (select count(*)
           from public.orders o
           join public.users u on u.telegram_id = o.user_id
          where u.referrer_id = p_user_id and o.status = 'COMPLETED'),
        coalesce((select sum(amount) from public.referral_rewards
                  where referrer_id = p_user_id and currency = 'TON' and status = 'PAID'), 0),
        coalesce((select sum(amount) from public.referral_rewards
                  where referrer_id = p_user_id and currency = 'USDT' and status = 'PAID'), 0);
$$;

create or replace function public.confirm_order_payment(
    p_order_id uuid,
    p_tx_hash text,
    p_tx_lt numeric,
    p_sender text
) returns setof public.orders
language plpgsql security definer set search_path = public
as $$
declare
    v_order public.orders%rowtype;
begin
    select * into v_order from public.orders where id = p_order_id for update;
    if not found or v_order.status <> 'WAITING_PAYMENT' or v_order.expires_at <= now() then
        return;
    end if;
    update public.orders
       set status = 'PAYMENT_CONFIRMED', paid_at = now(), tx_hash = p_tx_hash,
           tx_lt = p_tx_lt, sender_address = p_sender, error = null, updated_at = now()
     where id = p_order_id
     returning * into v_order;
    insert into public.order_status_history(order_id, from_status, to_status, details)
    values (p_order_id, 'WAITING_PAYMENT', 'PAYMENT_CONFIRMED', jsonb_build_object('tx_hash', p_tx_hash));
    return next v_order;
end;
$$;

create or replace function public.expire_due_orders()
returns setof public.orders
language plpgsql security definer set search_path = public
as $$
declare
    v_order public.orders%rowtype;
begin
    for v_order in
        update public.orders
           set status = 'EXPIRED', updated_at = now()
         where status = 'WAITING_PAYMENT' and expires_at <= now()
         returning *
    loop
        insert into public.order_status_history(order_id, from_status, to_status)
        values (v_order.id, 'WAITING_PAYMENT', 'EXPIRED');
        return next v_order;
    end loop;
end;
$$;

create or replace function public.review_stale_processing_orders()
returns setof public.orders
language plpgsql security definer set search_path = public
as $$
declare
    v_order public.orders%rowtype;
begin
    for v_order in
        update public.orders
           set status = 'MANUAL_REVIEW',
               error = 'Processing lease expired; Fragment outcome requires review',
               processing_lease_until = null,
               updated_at = now()
         where status = 'PROCESSING' and processing_lease_until <= now()
         returning *
    loop
        update public.fulfillment_attempts
           set status = 'UNKNOWN',
               error = 'Worker lease expired before a conclusive result',
               updated_at = now()
         where order_id = v_order.id and status in ('CLAIMED', 'SUBMITTED');
        insert into public.order_status_history(order_id, from_status, to_status, details)
        values (v_order.id, 'PROCESSING', 'MANUAL_REVIEW',
                jsonb_build_object('reason', 'processing_lease_expired'));
        return next v_order;
    end loop;
end;
$$;

create or replace function public.cancel_order(p_order_id uuid, p_user_id bigint)
returns setof public.orders
language plpgsql security definer set search_path = public
as $$
declare
    v_order public.orders%rowtype;
begin
    update public.orders
       set status = 'CANCELLED', updated_at = now()
     where id = p_order_id and user_id = p_user_id and status = 'WAITING_PAYMENT'
     returning * into v_order;
    if not found then return; end if;
    insert into public.order_status_history(order_id, from_status, to_status, actor_id)
    values (p_order_id, 'WAITING_PAYMENT', 'CANCELLED', p_user_id);
    return next v_order;
end;
$$;

create or replace function public.claim_order_fulfillment(
    p_order_id uuid,
    p_lease_seconds integer
) returns table(order_data jsonb, attempt_data jsonb)
language plpgsql security definer set search_path = public
as $$
declare
    v_order public.orders%rowtype;
    v_attempt public.fulfillment_attempts%rowtype;
    v_attempt_no integer;
begin
    select * into v_order from public.orders where id = p_order_id for update skip locked;
    if not found or v_order.status <> 'PAYMENT_CONFIRMED' then return; end if;
    select coalesce(max(attempt_no), 0) + 1 into v_attempt_no
      from public.fulfillment_attempts where order_id = p_order_id;
    insert into public.fulfillment_attempts(
        order_id, attempt_no, idempotency_key, status, request_payload
    ) values (
        p_order_id,
        v_attempt_no,
        'fragment:' || p_order_id::text || ':' || v_attempt_no::text,
        'CLAIMED',
        jsonb_build_object(
            'recipient', v_order.recipient,
            'product_type', v_order.product_type,
            'stars_amount', v_order.stars_amount,
            'premium_months', v_order.premium_months
        )
    ) returning * into v_attempt;
    update public.orders
       set status = 'PROCESSING',
           processing_lease_until = now() + make_interval(secs => p_lease_seconds),
           updated_at = now()
     where id = p_order_id
     returning * into v_order;
    insert into public.order_status_history(order_id, from_status, to_status, details)
    values (p_order_id, 'PAYMENT_CONFIRMED', 'PROCESSING',
            jsonb_build_object('attempt_id', v_attempt.id, 'idempotency_key', v_attempt.idempotency_key));
    return query select to_jsonb(v_order), to_jsonb(v_attempt);
end;
$$;

create or replace function public.complete_order_fulfillment(
    p_order_id uuid,
    p_attempt_id bigint,
    p_response jsonb,
    p_fragment_order_id text,
    p_http_status integer
) returns setof public.orders
language plpgsql security definer set search_path = public
as $$
declare
    v_order public.orders%rowtype;
    v_referrer bigint;
    v_rate numeric;
begin
    select * into v_order from public.orders where id = p_order_id for update;
    if not found or v_order.status <> 'PROCESSING' then return; end if;
    update public.fulfillment_attempts
       set status = 'COMPLETED', response_payload = p_response,
           http_status = p_http_status, updated_at = now()
     where id = p_attempt_id and order_id = p_order_id and status = 'SUBMITTED';
    if not found then return; end if;
    update public.orders
       set status = 'COMPLETED', completed_at = now(),
           fragment_order_id = p_fragment_order_id, fragment_response = p_response,
           processing_lease_until = null, error = null, updated_at = now()
     where id = p_order_id returning * into v_order;
    insert into public.order_status_history(order_id, from_status, to_status, details)
    values (p_order_id, 'PROCESSING', 'COMPLETED', jsonb_build_object('attempt_id', p_attempt_id));

    select referrer_id into v_referrer from public.users where telegram_id = v_order.user_id;
    select referral_reward_rate into v_rate from public.bot_settings where id = 1;
    if v_referrer is not null and coalesce(v_rate, 0) > 0 then
        insert into public.referral_rewards(order_id, referrer_id, currency, amount)
        values (v_order.id, v_referrer, v_order.currency, round(v_order.amount * v_rate, 9))
        on conflict (order_id) do nothing;
    end if;
    return next v_order;
end;
$$;

create or replace function public.fail_order_fulfillment(
    p_order_id uuid,
    p_attempt_id bigint,
    p_error text,
    p_ambiguous boolean,
    p_response jsonb,
    p_http_status integer
) returns setof public.orders
language plpgsql security definer set search_path = public
as $$
declare
    v_order public.orders%rowtype;
    v_status text := case when p_ambiguous then 'MANUAL_REVIEW' else 'FAILED' end;
begin
    select * into v_order from public.orders where id = p_order_id for update;
    if not found or v_order.status <> 'PROCESSING' then return; end if;
    update public.fulfillment_attempts
       set status = case when p_ambiguous then 'UNKNOWN' else 'REJECTED' end,
           response_payload = p_response, http_status = p_http_status,
           error = left(p_error, 4000), updated_at = now()
     where id = p_attempt_id and order_id = p_order_id and status = 'SUBMITTED';
    if not found then return; end if;
    update public.orders
       set status = v_status, error = left(p_error, 4000),
           processing_lease_until = null, updated_at = now()
     where id = p_order_id returning * into v_order;
    insert into public.order_status_history(order_id, from_status, to_status, details)
    values (p_order_id, 'PROCESSING', v_status,
            jsonb_build_object('attempt_id', p_attempt_id, 'error', left(p_error, 1000)));
    return next v_order;
end;
$$;

create or replace function public.approve_order_retry(
    p_order_id uuid,
    p_actor_id bigint,
    p_reason text
) returns setof public.orders
language plpgsql security definer set search_path = public
as $$
declare
    v_order public.orders%rowtype;
    v_previous text;
begin
    select status into v_previous from public.orders where id = p_order_id for update;
    if v_previous not in ('FAILED', 'MANUAL_REVIEW') then return; end if;
    update public.orders
       set status = 'PAYMENT_CONFIRMED', error = null, updated_at = now()
     where id = p_order_id returning * into v_order;
    insert into public.order_status_history(order_id, from_status, to_status, actor_id, details)
    values (p_order_id, v_previous, 'PAYMENT_CONFIRMED', p_actor_id,
            jsonb_build_object('manual_verification', p_reason));
    return next v_order;
end;
$$;

create or replace function public.admin_order_stats()
returns table(
    users bigint, orders bigint, waiting bigint, completed bigint,
    manual_review bigint, volume_ton numeric, volume_usdt numeric
)
language sql stable security definer set search_path = public
as $$
    select
        (select count(*) from public.users),
        count(*),
        count(*) filter (where status = 'WAITING_PAYMENT'),
        count(*) filter (where status = 'COMPLETED'),
        count(*) filter (where status = 'MANUAL_REVIEW'),
        coalesce(sum(amount) filter (where status = 'COMPLETED' and currency = 'TON'), 0),
        coalesce(sum(amount) filter (where status = 'COMPLETED' and currency = 'USDT'), 0)
    from public.orders;
$$;

revoke all on public.users, public.orders, public.order_status_history,
    public.fulfillment_attempts, public.referral_rewards, public.bot_settings
    from anon, authenticated;
revoke execute on function public.assign_referrer_once(bigint, bigint) from anon, authenticated;
revoke execute on function public.referral_stats(bigint) from anon, authenticated;
revoke execute on function public.confirm_order_payment(uuid, text, numeric, text) from anon, authenticated;
revoke execute on function public.expire_due_orders() from anon, authenticated;
revoke execute on function public.review_stale_processing_orders() from anon, authenticated;
revoke execute on function public.cancel_order(uuid, bigint) from anon, authenticated;
revoke execute on function public.claim_order_fulfillment(uuid, integer) from anon, authenticated;
revoke execute on function public.complete_order_fulfillment(uuid, bigint, jsonb, text, integer) from anon, authenticated;
revoke execute on function public.fail_order_fulfillment(uuid, bigint, text, boolean, jsonb, integer) from anon, authenticated;
revoke execute on function public.approve_order_retry(uuid, bigint, text) from anon, authenticated;
revoke execute on function public.admin_order_stats() from anon, authenticated;
grant usage on schema public to service_role;
grant select, insert, update, delete on public.users, public.orders,
    public.order_status_history, public.fulfillment_attempts,
    public.referral_rewards, public.bot_settings to service_role;
grant usage, select on sequence public.order_status_history_id_seq,
    public.fulfillment_attempts_id_seq, public.referral_rewards_id_seq to service_role;
grant execute on function public.assign_referrer_once(bigint, bigint) to service_role;
grant execute on function public.referral_stats(bigint) to service_role;
grant execute on function public.confirm_order_payment(uuid, text, numeric, text) to service_role;
grant execute on function public.expire_due_orders() to service_role;
grant execute on function public.review_stale_processing_orders() to service_role;
grant execute on function public.cancel_order(uuid, bigint) to service_role;
grant execute on function public.claim_order_fulfillment(uuid, integer) to service_role;
grant execute on function public.complete_order_fulfillment(uuid, bigint, jsonb, text, integer) to service_role;
grant execute on function public.fail_order_fulfillment(uuid, bigint, text, boolean, jsonb, integer) to service_role;
grant execute on function public.approve_order_retry(uuid, bigint, text) to service_role;
grant execute on function public.admin_order_stats() to service_role;
