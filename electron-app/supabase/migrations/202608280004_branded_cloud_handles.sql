-- Producer handles remain URL/search friendly while allowing a branded
-- leading plus, for example +nrgy. Display names and aliases stay unrestricted.

alter table public.profiles
  drop constraint if exists profiles_handle_format;

alter table public.profiles
  add constraint profiles_handle_format
  check (
    handle ~ '^\+?[a-z0-9][a-z0-9_-]{2,31}$'
    and char_length(handle) <= 32
  );
