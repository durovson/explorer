-- Marketapp / GRAM / NFT rent migration.
-- Apply after supabase/schema.sql. Existing orders keep provider=FRAGMENT so they
-- can be reconciled with the legacy adapter; all new orders default to MARKETAPP.

alter table public.orders add column if not exists provider text;
update public.orders set provider = 'FRAGMENT' where provider is null;
alter table public.orders alter column provider set default 'MARKETAPP';
alter table public.orders alter column provider set not null;

alter table public.orders add column if not exists gram_amount numeric(36, 9);
alter table public.orders add column if not exists nft_address varchar(128);
alter table public.orders add column if not exists rent_days integer;
alter table public.orders add column if not exists provider_price_gram numeric(36, 9);
alter table public.orders add column if not exists provider_payload jsonb not null default '{}'::jsonb;
alter table public.orders add column if not exists provider_order_id varchar(256);
alter table public.orders add column if not exists provider_response jsonb;
alter table public.orders add column if not exists provider_tx_hash varchar(256);

alter table public.orders drop constraint if exists orders_product_type_check;
alter table public.orders drop constraint if exists orders_check;
alter table public.orders drop constraint if exists orders_provider_check;
alter table public.orders drop constraint if exists orders_product_fields_check;
alter table public.orders drop constraint if exists orders_gram_rent_currency_check;

alter table public.orders
    add constraint orders_product_type_check
    check (product_type in ('STARS', 'PREMIUM', 'GRAM', 'NFT_RENT'));

alter table public.orders
    add constraint orders_provider_check
    check (provider in ('FRAGMENT', 'MARKETAPP'));

alter table public.orders
    add constraint orders_product_fields_check
    check (
        (
            product_type = 'STARS'
            and stars_amount between 50 and 1000000
            and premium_months is null
            and gram_amount is null
            and nft_address is null
            and rent_days is null
            and provider_price_gram is null
        )
        or
        (
            product_type = 'PREMIUM'
            and premium_months in (3, 6, 12)
            and stars_amount is null
            and gram_amount is null
            and nft_address is null
            and rent_days is null
            and provider_price_gram is null
        )
        or
        (
            product_type = 'GRAM'
            and gram_amount > 0
            and stars_amount is null
            and premium_months is null
            and nft_address is null
            and rent_days is null
            and provider_price_gram is null
        )
        or
        (
            product_type = 'NFT_RENT'
            and nft_address is not null
            and length(nft_address) > 10
            and rent_days > 0
            and provider_price_gram > 0
            and stars_amount is null
            and premium_months is null
            and gram_amount is null
        )
    );

alter table public.orders
    add constraint orders_gram_rent_currency_check
    check (product_type not in ('GRAM', 'NFT_RENT') or currency = 'TON');

create index if not exists orders_provider_status_idx
    on public.orders(provider, status, created_at);

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
               error = 'Processing lease expired; provider/blockchain outcome requires review',
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
                jsonb_build_object('reason', 'processing_lease_expired', 'provider', v_order.provider));
        return next v_order;
    end loop;
end;
$$;

create or replace function public.claim_order_fulfillment_v2(
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
        lower(v_order.provider) || ':' || p_order_id::text || ':' || v_attempt_no::text,
        'CLAIMED',
        jsonb_build_object(
            'provider', v_order.provider,
            'recipient', v_order.recipient,
            'product_type', v_order.product_type,
            'stars_amount', v_order.stars_amount,
            'premium_months', v_order.premium_months,
            'gram_amount', v_order.gram_amount,
            'nft_address', v_order.nft_address,
            'rent_days', v_order.rent_days,
            'provider_price_gram', v_order.provider_price_gram,
            'provider_payload', v_order.provider_payload
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
            jsonb_build_object(
                'attempt_id', v_attempt.id,
                'idempotency_key', v_attempt.idempotency_key,
                'provider', v_order.provider
            ));

    return query select to_jsonb(v_order), to_jsonb(v_attempt);
end;
$$;

create or replace function public.complete_order_fulfillment_v2(
    p_order_id uuid,
    p_attempt_id bigint,
    p_response jsonb,
    p_provider_order_id text,
    p_provider_tx_hash text,
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
       set status = 'COMPLETED',
           completed_at = now(),
           provider_order_id = p_provider_order_id,
           provider_response = p_response,
           provider_tx_hash = p_provider_tx_hash,
           fragment_order_id = case
               when provider = 'FRAGMENT' then p_provider_order_id else fragment_order_id end,
           fragment_response = case
               when provider = 'FRAGMENT' then p_response else fragment_response end,
           processing_lease_until = null,
           error = null,
           updated_at = now()
     where id = p_order_id returning * into v_order;

    insert into public.order_status_history(order_id, from_status, to_status, details)
    values (
        p_order_id,
        'PROCESSING',
        'COMPLETED',
        jsonb_build_object(
            'attempt_id', p_attempt_id,
            'provider', v_order.provider,
            'provider_order_id', p_provider_order_id,
            'provider_tx_hash', p_provider_tx_hash
        )
    );

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

revoke execute on function public.claim_order_fulfillment_v2(uuid, integer)
    from anon, authenticated;
revoke execute on function public.complete_order_fulfillment_v2(uuid, bigint, jsonb, text, text, integer)
    from anon, authenticated;
grant execute on function public.claim_order_fulfillment_v2(uuid, integer)
    to service_role;
grant execute on function public.complete_order_fulfillment_v2(uuid, bigint, jsonb, text, text, integer)
    to service_role;
