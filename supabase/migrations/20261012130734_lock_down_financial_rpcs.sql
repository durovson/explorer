-- Keep SECURITY DEFINER financial RPCs inaccessible to public API roles.
-- PostgreSQL grants EXECUTE on newly-created functions to PUBLIC by default,
-- so revoking only anon/authenticated is not sufficient.

revoke execute on function public.assign_referrer_once(bigint, bigint) from public, anon, authenticated;
revoke execute on function public.referral_stats(bigint) from public, anon, authenticated;
revoke execute on function public.confirm_order_payment(uuid, text, numeric, text) from public, anon, authenticated;
revoke execute on function public.expire_due_orders() from public, anon, authenticated;
revoke execute on function public.review_stale_processing_orders() from public, anon, authenticated;
revoke execute on function public.cancel_order(uuid, bigint) from public, anon, authenticated;
revoke execute on function public.claim_order_fulfillment(uuid, integer) from public, anon, authenticated;
revoke execute on function public.complete_order_fulfillment(uuid, bigint, jsonb, text, integer) from public, anon, authenticated;
revoke execute on function public.fail_order_fulfillment(uuid, bigint, text, boolean, jsonb, integer) from public, anon, authenticated;
revoke execute on function public.approve_order_retry(uuid, bigint, text) from public, anon, authenticated;
revoke execute on function public.admin_order_stats() from public, anon, authenticated;

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
