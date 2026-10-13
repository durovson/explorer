create table if not exists public.payment_scanner_cursors (
    scanner text primary key,
    account_address text not null,
    last_lt numeric not null,
    last_hash text,
    updated_at timestamptz not null default now()
);

create table if not exists public.observed_payments (
    id bigint generated always as identity primary key,
    tx_hash text not null unique,
    tx_lt numeric,
    currency text not null default 'TON' check (currency in ('TON','USDT')),
    amount_atomic bigint not null check (amount_atomic > 0),
    destination text not null,
    sender text,
    memo text,
    observed_at timestamptz,
    matched_order_id uuid references public.orders(id),
    mismatch_reason text,
    processed_at timestamptz,
    created_at timestamptz not null default now()
);

create index if not exists observed_payments_unprocessed_idx
    on public.observed_payments (id) where processed_at is null;
create index if not exists observed_payments_memo_idx
    on public.observed_payments (memo) where memo is not null;
create unique index if not exists orders_tx_hash_unique_idx
    on public.orders (tx_hash) where tx_hash is not null;

alter table public.payment_scanner_cursors enable row level security;
alter table public.observed_payments enable row level security;

revoke all on public.payment_scanner_cursors from public, anon, authenticated;
revoke all on public.observed_payments from public, anon, authenticated;
grant select, insert, update, delete on public.payment_scanner_cursors to service_role;
grant select, insert, update, delete on public.observed_payments to service_role;
grant usage, select on sequence public.observed_payments_id_seq to service_role;

create or replace function public.ingest_ton_payment(
    p_tx_hash text,
    p_tx_lt numeric,
    p_amount_atomic bigint,
    p_destination text,
    p_sender text,
    p_memo text,
    p_observed_at timestamptz
)
returns table(order_data jsonb, matched boolean, reason text)
language plpgsql
security definer
set search_path = public
as $$
declare
    v_observation public.observed_payments%rowtype;
    v_order public.orders%rowtype;
    v_previous text;
    v_expected bigint;
begin
    if p_tx_hash is null or btrim(p_tx_hash) = '' or p_amount_atomic is null or p_amount_atomic <= 0 then
        return query select null::jsonb, false, 'invalid_observation'::text;
        return;
    end if;

    insert into public.observed_payments(
        tx_hash, tx_lt, currency, amount_atomic, destination, sender, memo, observed_at
    ) values (
        p_tx_hash, p_tx_lt, 'TON', p_amount_atomic, p_destination, p_sender,
        nullif(p_memo, ''), p_observed_at
    )
    on conflict (tx_hash) do nothing;

    select * into v_observation
      from public.observed_payments
     where tx_hash = p_tx_hash
     for update;

    if v_observation.processed_at is not null then
        if v_observation.matched_order_id is not null then
            select * into v_order from public.orders where id = v_observation.matched_order_id;
            return query select to_jsonb(v_order), true, 'already_matched'::text;
        else
            return query select null::jsonb, false, coalesce(v_observation.mismatch_reason, 'already_processed')::text;
        end if;
        return;
    end if;

    if v_observation.memo is null then
        update public.observed_payments
           set mismatch_reason = 'missing_memo', processed_at = now()
         where id = v_observation.id;
        return query select null::jsonb, false, 'missing_memo'::text;
        return;
    end if;

    select * into v_order
      from public.orders
     where memo = v_observation.memo
     for update;

    if not found then
        update public.observed_payments
           set mismatch_reason = 'unknown_memo', processed_at = now()
         where id = v_observation.id;
        return query select null::jsonb, false, 'unknown_memo'::text;
        return;
    end if;

    if v_order.currency <> 'TON' then
        update public.observed_payments
           set mismatch_reason = 'wrong_currency', processed_at = now()
         where id = v_observation.id;
        return query select to_jsonb(v_order), false, 'wrong_currency'::text;
        return;
    end if;

    if v_order.wallet_address <> v_observation.destination then
        update public.observed_payments
           set mismatch_reason = 'wrong_destination', processed_at = now()
         where id = v_observation.id;
        return query select to_jsonb(v_order), false, 'wrong_destination'::text;
        return;
    end if;

    if v_observation.observed_at is not null
       and v_observation.observed_at < v_order.created_at - interval '30 seconds' then
        update public.observed_payments
           set mismatch_reason = 'payment_predates_order', processed_at = now()
         where id = v_observation.id;
        return query select to_jsonb(v_order), false, 'payment_predates_order'::text;
        return;
    end if;

    if v_observation.observed_at is not null and v_observation.observed_at > v_order.expires_at then
        update public.observed_payments
           set mismatch_reason = 'late_payment', processed_at = now()
         where id = v_observation.id;
        return query select to_jsonb(v_order), false, 'late_payment'::text;
        return;
    end if;

    v_expected := round(v_order.amount * 1000000000)::bigint;
    if v_expected <> v_observation.amount_atomic then
        update public.observed_payments
           set mismatch_reason = 'invalid_amount:expected=' || v_expected::text,
               processed_at = now()
         where id = v_observation.id;
        return query select to_jsonb(v_order), false, 'invalid_amount'::text;
        return;
    end if;

    if v_order.tx_hash = v_observation.tx_hash and v_order.status in ('PAYMENT_CONFIRMED','PROCESSING','COMPLETED','MANUAL_REVIEW','FAILED') then
        update public.observed_payments
           set matched_order_id = v_order.id, mismatch_reason = null,
               processed_at = coalesce(processed_at, now())
         where id = v_observation.id;
        return query select to_jsonb(v_order), true, 'already_confirmed'::text;
        return;
    end if;

    if v_order.status not in ('WAITING_PAYMENT','EXPIRED') then
        update public.observed_payments
           set mismatch_reason = 'order_not_waiting_payment', processed_at = now()
         where id = v_observation.id;
        return query select to_jsonb(v_order), false, 'order_not_waiting_payment'::text;
        return;
    end if;

    if exists(select 1 from public.orders where tx_hash = v_observation.tx_hash and id <> v_order.id) then
        update public.observed_payments
           set mismatch_reason = 'transaction_already_claimed', processed_at = now()
         where id = v_observation.id;
        return query select to_jsonb(v_order), false, 'transaction_already_claimed'::text;
        return;
    end if;

    v_previous := v_order.status;
    update public.orders
       set status = 'PAYMENT_CONFIRMED',
           paid_at = coalesce(v_observation.observed_at, now()),
           tx_hash = v_observation.tx_hash,
           tx_lt = v_observation.tx_lt,
           sender_address = v_observation.sender,
           processing_lease_until = null,
           error = null,
           updated_at = now()
     where id = v_order.id
     returning * into v_order;

    update public.observed_payments
       set matched_order_id = v_order.id,
           mismatch_reason = null,
           processed_at = now()
     where id = v_observation.id;

    insert into public.order_status_history(order_id, from_status, to_status, details)
    values (
        v_order.id,
        v_previous,
        'PAYMENT_CONFIRMED',
        jsonb_build_object(
            'tx_hash', v_observation.tx_hash,
            'tx_lt', v_observation.tx_lt,
            'payment_indexer', 'ton-receiver-v1'
        )
    );

    return query select to_jsonb(v_order), true, 'matched'::text;
end;
$$;

create or replace function public.retry_order_fulfillment(
    p_order_id uuid,
    p_attempt_id bigint,
    p_error text,
    p_response jsonb,
    p_retry_seconds integer default 60
)
returns setof public.orders
language plpgsql
security definer
set search_path = public
as $$
declare
    v_order public.orders%rowtype;
begin
    select * into v_order from public.orders where id = p_order_id for update;
    if not found or v_order.status <> 'PROCESSING' then return; end if;

    update public.fulfillment_attempts
       set status = 'REJECTED',
           response_payload = p_response,
           error = left(p_error, 4000),
           updated_at = now()
     where id = p_attempt_id
       and order_id = p_order_id
       and status = 'SUBMITTED';
    if not found then return; end if;

    update public.orders
       set status = 'PAYMENT_CONFIRMED',
           error = left(p_error, 4000),
           processing_lease_until = now() + make_interval(secs => greatest(15, least(coalesce(p_retry_seconds, 60), 900))),
           updated_at = now()
     where id = p_order_id
     returning * into v_order;

    insert into public.order_status_history(order_id, from_status, to_status, details)
    values (
        p_order_id,
        'PROCESSING',
        'PAYMENT_CONFIRMED',
        jsonb_build_object('attempt_id', p_attempt_id, 'retryable', true, 'error', left(p_error, 1000))
    );

    return next v_order;
end;
$$;

revoke all on function public.ingest_ton_payment(text,numeric,bigint,text,text,text,timestamptz) from public, anon, authenticated;
grant execute on function public.ingest_ton_payment(text,numeric,bigint,text,text,text,timestamptz) to service_role;
revoke all on function public.retry_order_fulfillment(uuid,bigint,text,jsonb,integer) from public, anon, authenticated;
grant execute on function public.retry_order_fulfillment(uuid,bigint,text,jsonb,integer) to service_role;
