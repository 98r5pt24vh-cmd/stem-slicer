-- Trusted producer connections define collaboration access; the profile flag is obsolete.

alter table public.profiles
  drop column if exists open_to_collaborate;
