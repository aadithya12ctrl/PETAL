# Testbed summary

- scenarios: **60** (30 decision, 30 content) across 6 domains
- permitted context: 1173-1323 tokens, mean 1250
- delta ceiling: decision 1.000, content 0.429
- floor utility (what Drop earns by design): decision 0.333, content 0.300

## Distinct answers per domain (guessability check)

| domain | answers under S | answers under S' |
|---|---|---|
| clinic_scheduling | B B C C D | A B B C C |
| hr_leave | B B B C D | A C C D D |
| insurance_claims | A B D D D | A A C C D |
| legal_intake | B B B C D | A C C D D |
| loan_prescreen | A A C C D | B B C D D |
| travel_accessibility | A B C C D | A A B B C |

## Validation

All 60 scenarios pass structural validation.
