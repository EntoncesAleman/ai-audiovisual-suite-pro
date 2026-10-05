-- Apply in Supabase SQL Editor before deploying. No client access: backend only.
begin;
create schema if not exists avsuite;
create table if not exists avsuite.studio_records (
    owner text not null,
    kind text not null check (kind in ('workspace', 'media', 'job', 'quota', 'session')),
    id text not null,
    payload jsonb not null,
    revision bigint not null default 1,
    updated double precision not null default extract(epoch from now()),
    primary key (owner, kind, id)
);
create index if not exists studio_records_recent on avsuite.studio_records(owner, kind, updated desc);
alter table avsuite.studio_records enable row level security;
revoke all on avsuite.studio_records from anon, authenticated;
grant usage on schema avsuite to service_role;
grant all on avsuite.studio_records to service_role;

create or replace function avsuite.studio_write(
    p_owner text, p_kind text, p_id text, p_payload jsonb, p_expected bigint default null
) returns jsonb language plpgsql security invoker set search_path = avsuite, pg_temp as $$
declare current_revision bigint; result jsonb;
begin
    -- Also serializes the first insertion, where there is no row to lock yet.
    perform pg_advisory_xact_lock(hashtextextended(p_owner || ':' || p_kind || ':' || p_id, 0));
    select revision into current_revision from avsuite.studio_records
        where owner=p_owner and kind=p_kind and id=p_id for update;
    current_revision := coalesce(current_revision, 0);
    if p_expected is not null and p_expected <> current_revision then
        return jsonb_build_object('conflict', true);
    end if;
    insert into avsuite.studio_records(owner,kind,id,payload,revision,updated)
        values(p_owner,p_kind,p_id,p_payload,current_revision+1,extract(epoch from now()))
        on conflict(owner,kind,id) do update set payload=excluded.payload,
            revision=excluded.revision, updated=excluded.updated;
    select to_jsonb(r) into result from avsuite.studio_records r
        where owner=p_owner and kind=p_kind and id=p_id;
    return result;
end $$;
revoke all on function avsuite.studio_write(text,text,text,jsonb,bigint) from public, anon, authenticated;
grant execute on function avsuite.studio_write(text,text,text,jsonb,bigint) to service_role;
insert into storage.buckets(id,name,public,file_size_limit)
    values('avsuite-media','avsuite-media',false,536870912)
    on conflict(id) do nothing;
notify pgrst, 'reload schema';
commit;
