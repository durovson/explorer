-- Additive ledger for GRNT-style rewards. Existing invoices and paid rewards are immutable.
create table public.shop_referral_profiles (
 user_id bigint primary key references public.users(telegram_id),
 special boolean not null default false, holder_chat_id bigint,
 holder_active boolean not null default false, holder_verified_at timestamptz
);
create table public.shop_referral_credits (
 order_id uuid primary key references public.orders(id), referrer_id bigint not null references public.users(telegram_id),
 currency text not null check(currency in ('TON','USDT')), amount numeric(36,9) not null check(amount>0),
 commission_share numeric not null check(commission_share between 0 and 1), volume numeric(36,9) not null,
 created_at timestamptz not null default now()
);
create index shop_referral_credits_owner_idx on public.shop_referral_credits(referrer_id);
create table public.shop_referral_withdrawals (
 id bigint generated always as identity primary key,user_id bigint not null references public.users(telegram_id),
 currency text not null check(currency in ('TON','USDT')),amount numeric(36,9) not null check(amount>0),
 wallet_address text not null,status text not null default 'creating'
 check(status in ('creating','prepared','submitted','confirmed','bounced','failed')),
 tx_hash text,created_at timestamptz not null default now(),updated_at timestamptz not null default now()
);
create unique index shop_referral_one_active on public.shop_referral_withdrawals(user_id)
 where status in ('creating','prepared','submitted');
alter table public.shop_referral_profiles enable row level security;
alter table public.shop_referral_credits enable row level security;
alter table public.shop_referral_withdrawals enable row level security;
revoke all on public.shop_referral_profiles,public.shop_referral_credits,public.shop_referral_withdrawals from public,anon,authenticated;
grant all on public.shop_referral_profiles,public.shop_referral_credits,public.shop_referral_withdrawals to service_role;
grant usage,select on sequence public.shop_referral_withdrawals_id_seq to service_role;

create function public.shop_referral_stats(p_user_id bigint) returns jsonb
language plpgsql security definer set search_path=public as $$
declare v_volume numeric; v_level text; v_rate numeric; v_profile public.shop_referral_profiles%rowtype;
begin
 select coalesce(sum(volume) filter(where currency='TON'),0) into v_volume from shop_referral_credits where referrer_id=p_user_id;
 select * into v_profile from shop_referral_profiles where user_id=p_user_id;
 v_level:=case when v_profile.special then 'special'
 when v_profile.holder_active and v_profile.holder_verified_at>now()-interval '1 hour' then 'holder'
 when v_volume>=1000 then 'level_3' when v_volume>=500 then 'level_2' else 'level_1' end;
 v_rate:=case v_level when 'special' then .50 when 'holder' then .30 when 'level_3' then .30 when 'level_2' then .20 else .10 end;
 return jsonb_build_object('level',v_level,'reward_rate',v_rate,'ton_volume',v_volume,
 'invited',(select count(*) from users where referrer_id=p_user_id),
 'paid_orders',(select count(*) from shop_referral_credits where referrer_id=p_user_id),
 'balance_ton',coalesce((select sum(amount) from shop_referral_credits where referrer_id=p_user_id and currency='TON'),0)-coalesce((select sum(amount) from shop_referral_withdrawals where user_id=p_user_id and currency='TON' and status not in ('failed','bounced')),0),
 'balance_usdt',coalesce((select sum(amount) from shop_referral_credits where referrer_id=p_user_id and currency='USDT'),0)-coalesce((select sum(amount) from shop_referral_withdrawals where user_id=p_user_id and currency='USDT' and status not in ('failed','bounced')),0),
 'paid_ton',coalesce((select sum(amount) from shop_referral_withdrawals where user_id=p_user_id and currency='TON' and status='confirmed'),0),
 'paid_usdt',coalesce((select sum(amount) from shop_referral_withdrawals where user_id=p_user_id and currency='USDT' and status='confirmed'),0));
end $$;

create function public.shop_credit_completed_referral() returns trigger
language plpgsql security definer set search_path=public as $$
declare v_ref bigint; v_share numeric; v_fee numeric; v_reward numeric;
begin
 if new.status<>'COMPLETED' or old.status='COMPLETED' then return new; end if;
 select referrer_id into v_ref from users where telegram_id=new.user_id;
 if v_ref is null or v_ref=new.user_id then return new; end if;
 insert into shop_referral_profiles(user_id) values(v_ref) on conflict do nothing;
 perform 1 from shop_referral_profiles where user_id=v_ref for update;
 v_share:=(shop_referral_stats(v_ref)->>'reward_rate')::numeric;
 -- Currently the shop issues TON invoices only. Unknown historical bases never earn invented rewards.
 if new.currency<>'TON' or new.provider_cost_ton is null then return new; end if;
 v_fee:=greatest(new.amount-new.provider_cost_ton,0);
 v_reward:=trunc(v_fee*v_share,9);
 if v_reward>0 then
 insert into shop_referral_credits(order_id,referrer_id,currency,amount,commission_share,volume)
 values(new.id,v_ref,new.currency,v_reward,v_share,new.amount) on conflict(order_id) do nothing;
 end if;
 return new;
end $$;
create trigger shop_referral_on_completion after update of status on public.orders
 for each row execute function public.shop_credit_completed_referral();

create function public.shop_request_referral_withdrawal(p_user_id bigint,p_currency text,p_wallet text) returns bigint
language plpgsql security definer set search_path=public as $$
declare v_stats jsonb; v_amount numeric; v_id bigint;
begin
 if p_currency not in ('TON','USDT') or p_wallet!~'^(0|-1):[a-f0-9]{64}$' then raise exception 'Invalid currency or mainnet address'; end if;
 insert into shop_referral_profiles(user_id) values(p_user_id) on conflict do nothing;
 perform 1 from shop_referral_profiles where user_id=p_user_id for update;
 v_stats:=shop_referral_stats(p_user_id);
 v_amount:=(v_stats->>(case when p_currency='TON' then 'balance_ton' else 'balance_usdt' end))::numeric;
 if v_amount<(case when p_currency='TON' then .1 else 1 end) then raise exception 'Minimum withdrawal: 0.1 TON / 1 USDT'; end if;
 insert into shop_referral_withdrawals(user_id,currency,amount,wallet_address) values(p_user_id,p_currency,v_amount,p_wallet) returning id into v_id;
 return v_id;
end $$;
create function public.shop_advance_referral_withdrawal(p_id bigint,p_status text,p_hash text default null) returns void
language plpgsql security definer set search_path=public as $$
declare v_row public.shop_referral_withdrawals%rowtype;
begin
 select * into v_row from shop_referral_withdrawals where id=p_id for update;
 if not found or not ((v_row.status='creating' and p_status in ('prepared','failed'))
 or (v_row.status='prepared' and p_status in ('submitted','failed'))
 or (v_row.status='submitted' and p_status in ('confirmed','bounced'))) then raise exception 'Invalid transition';end if;
 if p_status in ('submitted','confirmed','bounced') and (p_hash is null or p_hash!~'^[a-fA-F0-9]{64}$') then raise exception 'Transaction hash required';end if;
 if p_status in ('confirmed','bounced') and lower(v_row.tx_hash)<>lower(p_hash) then raise exception 'Transaction hash mismatch';end if;
 update shop_referral_withdrawals set status=p_status,tx_hash=coalesce(lower(p_hash),tx_hash),updated_at=now() where id=p_id;
end $$;
revoke all on function public.shop_referral_stats(bigint),public.shop_credit_completed_referral(),public.shop_request_referral_withdrawal(bigint,text,text),public.shop_advance_referral_withdrawal(bigint,text,text) from public,anon,authenticated;
grant execute on function public.shop_referral_stats(bigint),public.shop_request_referral_withdrawal(bigint,text,text),public.shop_advance_referral_withdrawal(bigint,text,text) to service_role;
