-- Read-only report. Run in Supabase SQL Editor and share the result.
-- Contains schema, permissions, function definitions, and the task catalog.
-- Does not read customer profiles, balances, payments, or proof submissions.
begin transaction read only;

select jsonb_build_object(
  'columns', (
    select coalesce(jsonb_agg(to_jsonb(c) order by c.table_schema, c.table_name, c.ordinal_position), '[]'::jsonb)
    from information_schema.columns c
    where c.table_schema = 'public'
  ),
  'tables', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'schema', n.nspname, 'table', c.relname,
      'rls_enabled', c.relrowsecurity, 'rls_forced', c.relforcerowsecurity,
      'anon_select', has_table_privilege('anon', c.oid, 'SELECT'),
      'anon_insert', has_table_privilege('anon', c.oid, 'INSERT'),
      'anon_update', has_table_privilege('anon', c.oid, 'UPDATE'),
      'anon_delete', has_table_privilege('anon', c.oid, 'DELETE'),
      'authenticated_select', has_table_privilege('authenticated', c.oid, 'SELECT'),
      'authenticated_insert', has_table_privilege('authenticated', c.oid, 'INSERT'),
      'authenticated_update', has_table_privilege('authenticated', c.oid, 'UPDATE'),
      'authenticated_delete', has_table_privilege('authenticated', c.oid, 'DELETE')
    ) order by n.nspname, c.relname), '[]'::jsonb)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname in ('public', 'storage') and c.relkind in ('r', 'p')
  ),
  'policies', (
    select coalesce(jsonb_agg(to_jsonb(p) order by p.schemaname, p.tablename, p.policyname), '[]'::jsonb)
    from pg_policies p where p.schemaname in ('public', 'storage')
  ),
  'column_grants', (
    select coalesce(jsonb_agg(to_jsonb(g) order by g.table_name, g.column_name, g.grantee), '[]'::jsonb)
    from information_schema.column_privileges g
    where g.table_schema = 'public' and g.grantee in ('PUBLIC', 'anon', 'authenticated')
  ),
  'constraints', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'table', c.conrelid::regclass::text, 'name', c.conname,
      'definition', pg_get_constraintdef(c.oid)
    ) order by c.conrelid::regclass::text, c.conname), '[]'::jsonb)
    from pg_constraint c join pg_namespace n on n.oid = c.connamespace
    where n.nspname = 'public'
  ),
  'triggers', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'table', t.tgrelid::regclass::text,
      'enabled', t.tgenabled,
      'definition', pg_get_triggerdef(t.oid),
      'function_definition', pg_get_functiondef(t.tgfoid)
    ) order by t.tgrelid::regclass::text, t.tgname), '[]'::jsonb)
    from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
    join pg_namespace n on n.oid = c.relnamespace
    where not t.tgisinternal
      and (n.nspname = 'public' or (n.nspname = 'auth' and c.relname = 'users'))
  ),
  'functions', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'name', p.oid::regprocedure::text,
      'security_definer', p.prosecdef,
      'configuration', p.proconfig,
      'anon_execute', has_function_privilege('anon', p.oid, 'EXECUTE'),
      'authenticated_execute', has_function_privilege('authenticated', p.oid, 'EXECUTE'),
      'definition', pg_get_functiondef(p.oid)
    ) order by p.oid::regprocedure::text), '[]'::jsonb)
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public' and p.prokind = 'f'
      and (p.proname in ('handle_new_user', 'generate_invitation_code')
        or p.proname ~* '(approv|reject|reward|bonus|claim|balance|transfer|withdraw|deposit|admin|unlock)')
  ),
  'views', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'name', c.oid::regclass::text, 'options', c.reloptions,
      'definition', pg_get_viewdef(c.oid, true)
    ) order by c.relname), '[]'::jsonb)
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relkind in ('v', 'm')
  ),
  'tasks', (
    select coalesce(jsonb_agg(jsonb_build_object(
      'id', t.id, 'title', t.title, 'reward', t.reward, 'status', t.status
    ) order by t.id), '[]'::jsonb) from public."Tasks" t
  )
) as launch_readiness_report;

commit;
