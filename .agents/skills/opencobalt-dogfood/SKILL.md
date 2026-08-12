---
name: opencobalt-dogfood
description: Execute manual CLI dogfooding protocol across the daily loop.
---

# /opencobalt-dogfood

Run isolated end-to-end smoke test of the daily loop:
1. `opencobalt capture "..."`
2. `opencobalt inbox`
3. `opencobalt clarify <id>`
4. `opencobalt today`
5. `opencobalt next`
6. `opencobalt focus <id>`
7. `opencobalt done <id>`
8. `opencobalt review`
9. `opencobalt why <id>`
Verify persistence across restarts.
