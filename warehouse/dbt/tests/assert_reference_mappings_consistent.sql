-- One mapping per (domain, source_system, source_value), and no chains: a canonical value
-- may not itself be listed as a source value in the same domain.
with m as (select * from {{ ref('reference_mappings') }})
select 'duplicate key' as problem, domain, coalesce(source_system, '') as source_system, source_value
from m group by 1, 2, 3, 4 having count(*) > 1
union all
select 'chain', a.domain, coalesce(a.source_system, ''), a.canonical_value
from m a join m b on b.domain = a.domain and b.source_value = a.canonical_value
