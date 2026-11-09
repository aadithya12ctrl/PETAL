# Testbed summary

- scenarios: **60** (30 decision, 30 content) across 6 domains
- permitted context: 1247-1412 tokens, mean 1326
- delta ceiling: decision 1.00, content 0.40
- chance utility (floor for U_drop): decision 0.333, content 0.000

## Distinct answers per domain (guessability check)

| domain | answers under S | answers under S' |
|---|---|---|
| clinic_scheduling | A A C D D | A A B C D |
| hr_leave | B B C C C | A A A B C |
| insurance_claims | A A C D D | A A A B C |
| legal_intake | A A C D D | C C C D D |
| loan_prescreen | A A B D D | A A B C C |
| travel_accessibility | A B B D D | A A C D D |

## Validation

All 60 scenarios pass structural validation.
