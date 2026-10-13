create or replace function public.ton_account_key(p_address text)
returns text
language plpgsql
immutable
strict
set search_path = public
as $$
declare
    v text := btrim(p_address);
    v_raw bytea;
    v_wc integer;
begin
    if position(':' in v) > 0 then
        return split_part(v, ':', 1)::integer::text || ':' || lower(split_part(v, ':', 2));
    end if;
    begin
        v_raw := decode(translate(v, '-_', '+/'), 'base64');
    exception when others then
        return null;
    end;
    if length(v_raw) <> 36 then
        return null;
    end if;
    v_wc := get_byte(v_raw, 1);
    if v_wc >= 128 then
        v_wc := v_wc - 256;
    end if;
    return v_wc::text || ':' || encode(substring(v_raw from 3 for 32), 'hex');
end;
$$;

revoke all on function public.ton_account_key(text) from public, anon, authenticated;
grant execute on function public.ton_account_key(text) to service_role;

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
    v_sender_key text;
    v_destination_key text;
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

    v_sender_key := public.ton_account_key(v_observation.sender);
    v_destination_key := public.ton_account_key(v_observation.destination);
    if v_sender_key is not null and v_destination_key is not null and v_sender_key = v_destination_key then
        update public.observed_payments
           set mismatch_reason = 'self_transfer', processed_at = now()
         where id = v_observation.id;
        return query select null::jsonb, false, 'self_transfer'::text;
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
