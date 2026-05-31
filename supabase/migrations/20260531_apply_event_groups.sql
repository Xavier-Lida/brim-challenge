-- Feature 4 (expense report generation) bulk-assigns event_group_id to many
-- transactions at once. Without this RPC the backend issued one UPDATE per
-- transaction (thousands of sequential calls), which timed out the gateway at
-- ~60s on batch runs. This applies every assignment in a single statement.
--
-- Run in the Supabase SQL Editor, then reload the PostgREST schema cache.

create or replace function apply_event_groups(assignments jsonb)
returns integer
language plpgsql
as $$
declare
  affected integer;
begin
  update transactions t
     set event_group_id = a.event_group_id
    from jsonb_to_recordset(assignments)
         as a(transaction_id text, event_group_id text)
   where t.id = a.transaction_id;
  get diagnostics affected = row_count;
  return affected;
end;
$$;

-- Allow the API roles to call it.
grant execute on function apply_event_groups(jsonb) to anon, authenticated, service_role;

-- Refresh PostgREST so the RPC is exposed immediately.
notify pgrst, 'reload schema';
