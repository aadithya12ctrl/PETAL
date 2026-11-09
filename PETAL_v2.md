# PETAL v2
### Pioneer-filling with Event-triggered Temporal Abstraction against Latent Leakage in Multi-Agent LLM Relays

**Aadithya — NIE Mysuru**
*Research proposal — working draft v2 (9 Nov 2026). Supersedes v1.*

---

## 0. What changed from v1 (read this first)

v1 had a sound core idea and mostly correct algebra, but several statements were stronger than their proofs, a few were wrong in general, and two citations described the benchmarks inaccurately. v2 does three things:

- **Fixes the errors** (full errata in §9, one line each in the table below).
- **Separates claims into three tiers** so that the bold parts are allowed to be bold:
  - **Theorems** — proved here, under stated conditions.
  - **Postulates** — working laws we *choose* to assume because they make the design tractable. Each has a *licence* (why it is reasonable) and a *kill test* (what observation retires it).
  - **Conjectures** — the risky, interesting claims the experiments exist to test.
- **Adds two new mechanisms** that turn soft claims into hard ones:
  - a **stochastic abstraction ladder** with a *provable* per-hop contraction (§4.3), replacing v1's unproven "deterministic coarsening gives geometric decay";
  - **Contrastive Seed Suppression (CSS)**, a logit-level petal that is literally the token-wise causal effect of S, subtracted (§4.2.3).

| # | v1 statement | Problem | v2 fix |
|---|---|---|---|
| 1 | "All reported leak rates are lower bounds" | False whenever the detector has false positives | Report Rogan–Gladen corrected rates with CIs |
| 2 | Petal independence: "probe must score at chance" | Wrong target: A may already predict S | Probe(filler, A) must not beat Probe(A); equivalence test |
| 3 | "For δ = 0 the petal cannot win" | Only true when κ ≥ 1/q₀ − λ/q_f (true in the toy, not in general) | State the exact condition |
| 4 | Toy loss term uses relative suppression s | Mixes per-instance and relative units; changes the break-even table | Two readings given; decision rule made empirical |
| 5 | "Each ladder step is deterministic, so Eq. (4) applies" (geometric decay) | DPI applies, strict contraction does not | Stochastic ladder with closed-form η |
| 6 | Markov chain S → C_t → M_t → D_{t+1} | Broken by shared memory / scratchpads | Ceiling stated on all inputs to the downstream agent |
| 7 | Galton–Watson "for R ≤ 1 … total ≈ 1/(1−R)" | Diverges at R = 1; degenerate m = g = 1 never dies | R < 1, plus the degenerate linear-chain case |
| 8 | Placement "equalises leak risk across gaps" | Only over gaps that receive budget | Water-filling statement |
| 9 | One µ for both MI decay and leak-probability decay | Different quantities | µ_I and µ_q separated |
| 10 | h* = ln(cD/κq₀) | Negative when cD < κq₀ | h* = max(0, ·) and regime caveat |
| 11 | Slack "in tokens" = slack "in bits" | Units mismatch | Bits-per-token bridge, stated as upper bound |
| 12 | Symbol reuse (Φ, θ, D, L, m, W) | Collisions | New notation table (App. C) |
| 13 | Citation details for AgentLeak / MAGPIE | Some figures mis-described or unverified | Corrected; unverified ones flagged |

---

## Abstract

In multi-agent LLM systems, restricted content **S** often sits dormant in an agent's context or in shared memory and later surfaces through a relay to an agent that should not see it. Output filters miss internal channels, blanket redaction breaks coordination, and privacy instructions are ignored over long interactions. **Petal** treats the relay's spare capacity as a crack that *will* be filled, and fills it first with permitted content.

Petal has three parts:

1. **Context-grown fillers ("petals")** that occupy positions where S would surface — either as text generated from the permitted context, or at the logit level by subtracting the causal effect of S on each token (CSS).
2. **Temporal decay** through a *stochastic* abstraction ladder whose per-hop contraction we can compute in closed form.
3. **Event-triggered collapse**: a CUSUM statistic over probe evidence that, on alarm, concentrates defence on the probed gap and collapses S in every downstream channel.

We give a ceiling on leakage, a slack bound, a decay budget, an alarm threshold and a decision rule for when a petal beats dropping the fact. The central empirical unknown is **disclosure–use separability δ**: whether an agent can still *use* S after losing the ability to *say* it. Our boldest conjecture is that δ is high for decision-type uses of S and low for content-type uses — and that this split, not the defence mechanism, determines which privacy–utility frontier is achievable at all.

Status: one deterministic toy model has been run (§5). No experiment on a real multi-agent system has been run yet.

---

## 1. Introduction

Multi-agent systems pass information through relays: delegation messages, shared scratchpads, memory writes, summaries. A restricted fact can enter legitimately — one agent needs it for one purpose — and then surface downstream.

**The evidence that this matters.**
- AgentLeak (1,000 scenarios, coordinator–worker topology, 5 models) reports inter-agent messages leaking at **68.8%** versus **27.2%** on final outputs, so output-only audits miss **41.7% of violations** [1]. (v1 described this as "41.7% of traces had a clean output but an internal leak" — that is a different quantity; v2 uses the paper's wording.)
- MAGPIE reports that models disclose private information in roughly half or more of multi-turn collaborations even under explicit privacy instructions [2]; its later release (200 tasks) finds substantial leakage even for GPT-5 and Gemini 2.5 Pro [2b].
- *To verify before citing:* v1's interceptor figures (internal leakage 31.5% → 2.4%, task success −4.7 points). These were not found in the abstract-level material checked for v2; confirm against the AgentLeak IEEE Access version [1] before keeping them.

**Core intuition.** Pavement cracks do not stay empty. Whether a harmless pioneer or a damaging weed grows there depends on who arrives first. The gap a leak would pass through will be filled by *something*; we should choose what.

**Where the analogy earns its keep.** In v2 the ecology is not decoration; it is a *design generator*. Each ecological mechanism is translated into a postulate with a kill test:

| Ecology | Petal mechanism | Tier |
|---|---|---|
| Priority effects (first arrival wins) | Filler placed before S surfaces holds the slot | Conjecture C4 |
| Seed-bank mortality | Abstraction ladder decay | Theorem T4 (stochastic ladder) |
| Hydrothermal germination thresholds | Probit dose–response of leakage | Postulate P2 |
| Lockhart wall-growth law | Leak flux limited by the smaller of willingness and access | Postulate P3 |
| Bet-hedging germination | Randomised petal placement vs adaptive probers | Conjecture C6 |

**Contributions (proposed).**
1. A formal setting for **latent** leakage separating a causal leak Λ from an inference floor Φ (§3).
2. A channel ceiling valid with shared memory, a slack bound, and a provable decay rate for a stochastic ladder (§4).
3. Contrastive Seed Suppression: a decoding-time petal defined as the negated causal effect of S (§4.2.3).
4. An empirical decision rule for petal-vs-drop, with the toy algebra as a guide rather than the rule itself (§4.2.4).
5. Event-triggered collapse with a closed-form alarm threshold (§4.4).
6. An evaluation protocol with placebo controls, an optimising attacker, corrected leak rates and explicit kill conditions (see the execution plan).

---

## 2. Related Work

- **Agent privacy benchmarks.** PrivacyLens and ConfAIde test norm awareness in single-turn settings [3, 4]. AgentLeak instruments seven channels and defines leakage against a vault of restricted fields with an allowed disclosure set [1]. MAGPIE builds tasks where private information is central to success [2, 2b]. All rest on contextual integrity [9].
- **Information-theoretic compression.** Information bottleneck [6], privacy funnel [7], strong data-processing inequalities [8], and the bottleneck view of multi-agent relays [5].
- **Local differential privacy.** k-ary randomised response gives a closed-form privacy level and contraction coefficient; the stochastic ladder (§4.3) borrows it per rung [17].
- **Context-aware / contrastive decoding.** Context-aware decoding *amplifies* the effect of context on logits [18]; CSS applies the same contrast with the opposite sign to one restricted span.
- **Ecology.** Lockhart [10], hydrothermal time [11], bet-hedging [12], priority effects [13].
- **Sequential detection and games.** CUSUM [14, 15]; evolutionary games [16].

**Positioning.** Redaction, minimisation and interceptors already exist. The narrow, defensible novelty is: (a) a decoder-side filler (text or logit level), (b) provable hop-wise decay, (c) evidence-triggered collapse, and (d) the regime map (δ) saying when any of this beats dropping the fact.

---

## 3. Problem Formulation

### 3.1 Setting

- A task runs in stages t = 1, …, T. Stage t has local context C_t and emits relay message M_t.
- Stage t+1 reads M_t **and** its own other inputs **E_{t+1}** (shared memory, tool outputs, its own prompt). Its output is O_{t+1}.
- A = permitted information, Y = information the downstream stage needs, S = restricted content.
- **Latency assumption:** S is already in C_t and its location (span) is known to the defender.

> **v1 error (6).** v1 assumed the chain S → C_t → M_t → D_{t+1} is Markov. That is false whenever the downstream agent can also see S through memory or a shared scratchpad — exactly the AgentLeak memory channel. v2 keeps E_{t+1} explicit.

**Definition 1 (Bandwidth and slack).** A relay has bandwidth B if I(M; C) ≤ B. Slack is G = B − I(M; Y).
*Operational bridge.* If ℓ is relay length in tokens and ℓ_min the shortest length that keeps task accuracy, then G ≤ (ℓ − ℓ_min)·h̄ + (residual), where h̄ is the per-token entropy rate of the relay model on this task. Token slack is therefore a **proxy** for bit slack, not the same thing (v1 error 11). We measure h̄ from sampled relays.

**Definition 2 (Gap).** A gap is a generation position where sampled continuations assert S with probability above a threshold τ_g.

### 3.2 What counts as unsafe

| Case | Derivable from A? | Depends on S? | Fix |
|---|---|---|---|
| Permitted | yes | no | none, if policy allows |
| Inference violation | yes | no | output policy only |
| Causal leak | no | yes | channel control, petal, decay |

For each scenario run three arms: **S present**, **S swapped to S′** (same type, same plausibility, different value), **S removed**.

- Inference floor: **Φ_floor = P(assert S | S removed)**
- Causal leak: **Λ = P(assert S | S) − P(assert S | S′)**
- Information form: **I(S; O | A)**

Assertion is detected by entailment against the restricted statement, not verbatim match.

> **v1 error (1).** v1 said all leak rates are lower bounds. That is only true if the detector never fires falsely. With sensitivity Se and specificity Sp measured on human labels, the corrected prevalence is the Rogan–Gladen estimator
>
> **p̂_true = (p̂_obs + Sp − 1) / (Se + Sp − 1)**,
>
> clipped to [0, 1], with a bootstrap CI that resamples both the trace set and the validation set.

### 3.3 Threat model

- **A0 (benign):** no attacker.
- **A1 (scripted):** fixed probes, injections, poisoned inputs.
- **A2 (optimising):** attacker agent with a fixed query budget, sees only defender outputs, re-optimised against each defender configuration, free choice of hop. Includes a *threshold-hugging* variant.

Report the **adaptivity gap** = worst-case leakage − static-attack leakage.

---

## 4. Method and Theory

### 4.1 Layer 1 — channel ceiling

**Theorem T1 (Ceiling with side inputs).** If M_t is generated from C_t alone and O_{t+1} is generated from (M_t, E_{t+1}), then

**I(S; O_{t+1}) ≤ I(S; M_t, E_{t+1}) = I(S; E_{t+1}) + I(S; M_t | E_{t+1}).**

*Proof.* Data-processing on S → (M_t, E_{t+1}) → O_{t+1}, then the chain rule. ∎

- The first term is the **side-channel leak** (memory, scratchpad). No relay-level defence touches it — this is why Petal must also act on memory writes.
- With E_{t+1} = A_{t+1} (only permitted side inputs), the second term is the **causal relay leak**, the quantity Petal targets.
- v1's ceiling I(S; O) ≤ I(S; M) is the special case E_{t+1} independent of S.

**Theorem T2 (Slack bound).** If (S, Y) is a function of C, M depends on C only, and S ⊥ Y, then I(M; S) ≤ B − I(M; Y).
*Proof.* As v1 App. A.1 (correct as written). ∎
When S and Y overlap the bound fails — that is precisely the regime where petals are needed.

**Relay objective.** With a leakage penalty:

min over p(m|c) of **I(M; C) − β I(M; Y) + γ I(M; S)**.

The stationarity condition

p(m|c) ∝ p(m) · exp( −β KL(p(y|c) ‖ p(y|m)) + γ KL(p(s|c) ‖ p(s|m)) )

**is correct** — v1 flagged it as unverified; the sign of the γ term follows the same variational step as the β term with the sign flipped. Two caveats remain:
- The problem is non-convex (privacy-funnel type); alternating updates need not converge.
- The +γ KL term rewards messages whose posterior on S is *far from the truth*. For small alphabets (binary S) a confidently wrong posterior is itself informative ("anti-leak by negation"). We therefore constrain p(s|m) toward the prior p(s|A) rather than merely away from p(s|c).

### 4.2 Layer 2 — gaps and petals

#### 4.2.1 Gap competition (Postulate P1)

At a gap the agent chooses between the restricted completion and legitimate ones:

P(S) = e^{z_S} / (e^{z_S} + W_leg + e^{z_f})

- z_S: trigger pull, W_leg = Σ_j e^{z_j}: pull of legitimate completions, z_f: filler pull.
- **Licence:** any categorical choice has a softmax parameterisation; the claim is only that z_S and z_f vary smoothly with trigger strength and filler design.
- **Kill test:** the fitted dose–response (§4.2.2) is not monotone in trigger strength.
- **v2 addition (v1 omission):** the filler also displaces *legitimate* completions. In the toy, P(legit) falls from 0.119 to 0.0024 as z_f goes 0 → 6. This **distraction cost** must enter utility (it is not λ, which is a length cost).

#### 4.2.2 Dose–response (Postulates P2, P3)

**P2 (germination-style dose–response).** Leak probability follows a probit in trigger strength Ψ and exposure E (hops or tokens S stays in context):

P(leak) = Φ_N( (Ψ − θ_H / E − Ψ_b50) / σ )

with Φ_N the standard normal CDF, θ_H a "hydro-time" constant, Ψ_b50 the median base threshold across agents/prompts.
- *Licence:* thresholds vary across prompts and agents roughly like base water potentials across seeds; longer exposure lowers the effective threshold.
- *Kill test:* poor probit fit (calibration error above logistic and isotonic baselines) or no exposure effect.

**P3 (Lockhart-style flux).** Leak rate ∝ (φ·L_acc / (φ + L_acc)) · (π − y₀)₊, with φ = willingness to assert, L_acc = access to S, π = pull toward S, y₀ = abstention threshold.
- *Licence:* two resistances in series; the smaller conductance dominates.
- *Testable prediction:* intervening on the smaller of {willingness, access} reduces leakage far more than intervening on the larger. Operationalise φ via refusal-training strength or system prompt, L_acc via retrieval rank / position of S in context.
- *Kill test:* reductions are additive rather than bottlenecked.

#### 4.2.3 Petals — two implementations

**(a) Text petal.** f ∼ p_θ(· | C \ S): a completion generated from the permitted context, inserted at the gap.

**(b) Contrastive Seed Suppression (CSS) — new in v2.** At each decoding step of a relay message, compute logits with and without the seed:

- Δ_t(v) = ℓ_t(v | C) − ℓ_t(v | C \ S)  — the token-wise causal effect of S.
- Suppressed logits: ℓ̃_t(v) = ℓ_t(v | C) − α · g_t(v) · [Δ_t(v)]₊

where α ∈ [0, 1] is strength and g_t(v) ∈ {0, 1} is a gate (see below). At α = 1, g = 1, every token S *boosted* is returned to its no-S level; tokens S *suppressed* are left alone.

- **Why it is the right object:** Λ is defined as the causal effect of S on assertions; CSS removes exactly that effect at the token level. It is the sign-flip of context-aware decoding [18].
- **Why the gate matters (and where δ lives):** with g ≡ 1, CSS also removes S's influence on *decisions* ("approve", "reschedule"), which destroys use (δ → 0). The gate restricts suppression to tokens that start or continue an S-entailing span (a small span classifier, or the vocabulary of S's surface forms and paraphrases). How much use survives a gated CSS *is* the empirical δ.
- **Cost:** two forward passes per token → needs open weights run locally; it cannot be done through a chat API.

**Filler independence (v1 error 2 fixed).** Required: f ⊥ S | A. Test:
- Train probe P₁ to predict S from (f, A) and probe P₀ from A alone.
- Pass if AUC(P₁) − AUC(P₀) is within an equivalence margin (e.g. 0.02) by a two-one-sided test (TOST) with a pre-computed power ≥ 0.8.
- v1's "probe at chance" is wrong whenever A carries information about S (it then fails a perfectly good petal), and "not significant" is absence of evidence, not independence.

#### 4.2.4 When does a petal beat dropping the fact?

**Separability.** δ = (U_petal − U_drop) / (U_full − U_drop), from three arms on the same tasks.

**Decision rule (primary, empirical — new in v2).** Measure per task family:
- U_petal, U_restr (utility of the restriction-aware relay that drops overlapping facts),
- leak rates ℓ_petal and ℓ_restr (corrected),
- extra relay length and distraction.

Petal wins iff **U_petal − U_restr > κ (ℓ_petal − ℓ_restr) + λ ΔLength.** No softmax parameters are needed; the toy algebra below only predicts *where* to look.

**Toy algebra (secondary, corrected).** With o overlapping facts, λ length cost, κ leak cost, q₀/q_f leak probability without/with petal:

- *Reading R (v1's):* value lost per overlapping fact = s(1 − δ), with s = 1 − q_f/q₀. Petal wins iff
  **(1 − λ) > s(1 − δ) + κ q_f.**
- *Reading A (absolute):* value lost = (q₀ − q_f)(1 − δ) — only instances whose disclosure was actually blocked lose value. Petal wins iff
  **(1 − λ) > (q₀ − q_f)(1 − δ) + κ q_f.**

In both readings o cancels from the sign (v1 is right about that).

> **v1 error (3).** "For δ = 0 the petal cannot win" is not a theorem. Under reading R, at δ = 0 the petal wins iff **q_f (1/q₀ − κ) > λ**. With the toy's κ = 2 > 1/q₀ ≈ 1.135 it can never hold; with a cheap leak cost (κ < 1/q₀) it can.

> **v1 error (4).** The two readings give different break-evens (recomputed by script, z_S = 2, W = 1, λ = 0.02, κ = 2):

| z_f | q_f | s | δ* (reading R, v1) | δ* (reading A) |
|---|---|---|---|---|
| 2 | 0.468 | 0.468 | 0.907 | 0.895 |
| 3 | 0.260 | 0.705 | 0.346 | 0.258 |
| 4 | 0.117 | 0.867 | 0.140 | 0.024 |
| 5 | 0.047 | 0.947 | 0.064 | wins at any δ |
| 6 | 0.018 | 0.980 | 0.036 | wins at any δ |

Reading A lets the petal win at δ = 0 for strong fillers because the (1 − q₀) instances where S was used *silently* already show some separability at baseline. Which reading is right is itself an empirical question — another reason the primary rule is the measured one.

#### 4.2.5 Conjectures about δ (the bold part)

- **C1 (decision vs content).** δ is high (> 0.6) when S's role is to *choose* among options the downstream agent already knows (decision-type use) and low (< 0.2) when the task output must *contain* S-derived content (content-type use).
- **C2 (decision-only relays).** Relaying the *decision computed with S* but not S itself (e.g. "slot B is unavailable" instead of "the patient has dialysis on Tuesdays") recovers most of U_full for decision-type tasks. This is the mechanism through which petals can beat dropping.
- **C3 (lag separability).** δ rises with the lag between the hop that uses S and the hop where disclosure risk appears.

These are worth being wrong about: if C1 fails, the whole "use without saying" programme is closed and that negative result is itself publishable.

### 4.3 Layer 3 — temporal decay (stochastic ladder)

**Abstraction ladder.** exact value → range → category → generic placeholder → dropped. Rung r has a finite alphabet of size k_r.

> **v1 error (5).** v1 argued "each step is a deterministic coarsening, so Eq. (4) applies". Data processing does apply (information cannot increase), but **strict contraction does not**: for a non-constant deterministic map, the input-independent contraction coefficient is 1. A deterministic ladder gives *step-wise* decay that hits zero at the "dropped" rung, not geometric decay.

**Stochastic rung (new).** At rung r, output the coarsened value with probability p_r; otherwise output one of the other k_r − 1 values of that rung uniformly (k-ary randomised response).

**Theorem T3 (per-rung contraction).** The Dobrushin coefficient of this channel is

**η_r = | p_r − (1 − p_r)/(k_r − 1) |**,

and the KL contraction coefficient satisfies η_KL ≤ η_r. Hence across hops

**I(S; M_t) ≤ ( Π_{r ≤ t} η_r ) · I(S; M_0).**

*Proof.* For a k-ary symmetric channel, the total-variation distance between any two output rows is |p − (1 − p)/(k − 1)|; η_KL ≤ η_TV [8]; composition with the deterministic coarsening cannot increase the coefficient; multiply along the chain. ∎

- Each rung is also ε_r-locally differentially private with ε_r = ln( p_r (k_r − 1) / (1 − p_r) ).
- Example (script-computed): rungs with (k, p) = (20, 0.8), (5, 0.7), (3, 0.6), (2, 0.6) give η = 0.79, 0.63, 0.40, 0.20; four hops multiply to **0.039** — a 96% reduction in the bound on bits about S, before the final "dropped" rung.
- **Scope of the guarantee:** it covers the slot that carries S. It does not cover re-derivation of S from other context (the floor Φ_floor) or side channels E_{t+1} (Theorem T1).

**Decay budget.** Write µ_I = −ln η for information decay and **µ_q** for the empirically fitted decay of *leak probability* q_t = q₁ e^{−µ_q (t−1)} (v1 error 9: these are different quantities; Fano-type bounds link them only loosely).

- Expected number of leak events from hop 1 on: Σ_{t≥1} q₁ e^{−µ_q (t−1)} = q₁ / (1 − e^{−µ_q}).
- This upper-bounds P(any leak) by the union bound (v1 error 10: v1 summed probabilities and called it "total leakage"; it is an expected count).
- Budget: q₁ / (1 − e^{−µ_q}) ≤ ε ⇔ **µ_q ≥ −ln(1 − q₁/ε)**, feasible only if **ε > q₁**.
- This makes v1's "early probe" limitation precise: decay can never protect the *first* exposed hop; no schedule achieves ε below q₁.

**Lag condition.** If salience starts at 1 at hop t_u (use) and must be below τ_s at hop t_d (disclosure risk): µ_q ≥ ln(1/τ_s) / (t_d − t_u).

### 4.4 Layer 4 — event-triggered collapse

Decay rate switches when evidence of probing accumulates:

- µ(t) = µ₀ + (µ_b − µ₀) · 𝟙[W^cs_t ≥ h], with µ_b ≫ µ₀
- W^cs_t = max(0, W^cs_{t−1} + log p₁(x_t)/p₀(x_t)) (CUSUM; p₀ benign, p₁ probing)

On alarm: **concentrate** (full-strength petal / CSS α = 1 at the probed gap), **move fast** (finish before the next probe), **encircle** (collapse S to the "dropped" rung in all downstream channels including memory). The military analogy covers only these three verbs.

**Alarm threshold.** First-order CUSUM asymptotics [14, 15]: mean detection delay ≈ h / D_KL(p₁‖p₀) probes; false alarms roughly every e^h benign queries. With leak cost κ and false-alarm cost c (over the deployment horizon):

J(h) = κ q₁ h / D_KL + c e^{−h} ⇒ **h* = max(0, ln( c D_KL / (κ q₁) ))**

- v1 error 10: without the max, h* is negative when c D_KL < κ q₁ — the correct reading is "always on".
- The h/D_KL delay is a large-h approximation and assumes i.i.d. probes. An adaptive attacker shapes p₁ to reduce D_KL; that is Conjecture C5 below.

**Trigger signals (design choice, to compare).** (a) pre-emission estimate of the gap's own P(S) by sampling or logprobs; (b) CUSUM over incoming queries; (c) judge on outgoing messages. (a) also covers the first probe, at a latency cost paid only on flagged gaps.

**Re-arm rule.** After an alarm, reset W^cs to 0 and keep µ_b for a refractory window of R hops, then decay back to µ₀.

### 4.5 Layer 5 — adversarial conjectures

- **C4 (priority / hysteresis).** Slot occupancy x obeys bistable replicator dynamics ẋ = x(1 − x)(π_f − π_S) with an unstable interior point; a petal placed before S surfaces holds, the same petal placed after does not. *Kill:* order effects explained by recency alone → drop this layer.
- **C5 (stealth–yield trade-off).** Against CUSUM, an attacker's extraction per query rises with D_KL(p₁‖p₀); stealthy attackers are slow. *Kill:* a stealthy attacker extracts as fast as a loud one.
- **C6 (bet-hedging).** Randomised petal placement beats any fixed placement against an adaptive prober, by analogy with optimal germination fractions [12].
- **Placement (corrected, v1 error 8).** With budget B_p, the defender solves min_c max_i v_i P_i(c_i) s.t. Σ c_i ≤ B_p. For P_i decreasing and continuous, the solution is **water-filling**: there is a level ℓ* such that every gap with v_i P_i(0) > ℓ* gets budget until v_i P_i(c_i) = ℓ*, and every other gap gets none. Risk is equalised over the *active* set only.

### 4.6 Layer 6 — multi-hop spread

If S is restated into m downstream slots, each independently with probability g, then R = m g.

- For **R < 1** the restatement process dies out with expected total 1/(1 − R).
- At **R = 1** it still dies out a.s. in the non-degenerate case, but the expected total diverges.
- **Degenerate case (v1 error 7):** a linear chain (m = 1) where every agent restates S (g = 1) has R = 1 and **never** dies out. This is the most common relay shape, which is why decay must be imposed rather than expected.
- Growth (R > 1) requires fan-out m > 1.

---

## 5. Preliminary toy model (unchanged setup, corrected reading)

- n = 100 upstream facts, k = 5 needed, 5 restricted, o of them also needed. Score = facts used − λ·length − κ·leaked, λ = 0.02, κ = 2, z_S = 2, W_leg = 1, so q₀ = 0.881.
- Policies: single big context, task-aware relay, restriction-aware relay, task-aware relay with petal.
- Big context scored worst (−5.81); a query-agnostic relay forwarding 20 random facts also lost (−1.16).
- Break-evens: see the table in §4.2.4 (both readings).
- **What the toy shows:** δ and the petal's suppression strength decide the verdict; the exact numbers depend on arbitrary parameters and are not findings.

---

## 6. Hypotheses and kill conditions (summary)

| ID | Claim | Tier | Kill condition |
|---|---|---|---|
| H0 | Leak detection is valid; Φ_floor measurable | — | Se or Sp < 0.85 on human labels after one revision |
| H1 | Probit dose–response; petal shifts it vs placebo | P2 | Poor fit, or no shift beyond the matched placebo B6 |
| H2 | Empirical decision rule picks petal on decision-type tasks | C1, C2 | δ below break-even on both task types |
| H3 | Leakage → floor as relay budget → minimal sufficient | T2 | Leakage persists well above Φ_floor at minimal budget |
| H4 | Stochastic ladder: measured probe-MI decays at least as fast as Π η_r | T3 | Measured decay slower than the bound (implies a side channel) |
| H5 | Triggered collapse matches always-on decay at lower task cost, optimum near h* | §4.4 | No cost advantage; no interior optimum |
| H6 | Stealth–yield trade-off | C5 | Stealthy attacker as fast as loud one |
| H7 | Order hysteresis | C4 | Recency explains all order effects |
| H8 | CSS gated beats text petal at matched leakage | §4.2.3 | No utility gain at matched leakage |
| H9 | Lockhart bottleneck: cutting the smaller conductance dominates | P3 | Effects additive |

Note H4 is a nice internal check: Theorem T3 is a *bound*. If measured decay is slower than the bound, something other than the ladder is carrying S — a side channel or re-derivation — which is itself a finding.

---

## 7. Limitations and open gaps

1. δ is unmeasured and decides everything downstream.
2. The softmax and Lockhart models are postulates; only fitted curves count as evidence.
3. A petal may leak by its shape ("diagnosis withheld" reveals one exists) — the conditional independence test (§4.2.3) exists for this.
4. Mutual information is not computable for text; probe accuracy gives lower-bound proxies. Theorem T3 bounds the *slot*, not the system.
5. Side channels (memory, tool logs) are outside the relay ceiling (Theorem T1) and need their own petal/decay.
6. Detection is noisy; corrected rates depend on a validation set that must be representative.
7. Inference floor Φ_floor is unavoidable by any relay design and must be subtracted, not blamed on the defence.
8. CSS needs open weights and two forward passes per token.
9. Adaptive attackers can induce false alarms; the false-alarm cost c must include this.
10. Analogies motivate postulates; they are never evidence.

---

## 8. Conclusion

Petal occupies the relay's slack with permitted content, lets restricted content decay along the chain at a rate we can now *prove* for the stochastic ladder, and collapses it when probing evidence accumulates. v2 makes the risky part explicit: the bet is that agents can often use what they cannot say (δ > 0), especially for decisions. The first experiments measure that directly, and every layer above it has a test that can retire it.

---

## 9. Full errata (v1 → v2)

1. **Lower-bound claim.** "All reported leak rates are lower bounds" (§3.2, Table 5) — false with false positives. → Rogan–Gladen correction.
2. **Filler independence test.** "Probe must score at chance" — wrong comparator and an absence-of-evidence test. → Probe(f, A) vs Probe(A), TOST equivalence.
3. **δ = 0 claim.** Holds only when κ ≥ 1/q₀ − λ/q_f. → Exact condition stated.
4. **Toy loss term.** Relative s vs absolute (q₀ − q_f); readings disagree. → Both reported; empirical rule primary.
5. **Ladder contraction.** Deterministic maps have contraction coefficient 1 in general. → Stochastic ladder, Theorem T3.
6. **Markov chain.** Shared memory breaks S → C → M → D. → Theorem T1 with side inputs.
7. **Galton–Watson.** 1/(1 − R) only for R < 1; degenerate m = g = 1 never dies. → Corrected.
8. **Placement equalisation.** Only over the active set. → Water-filling.
9. **One µ for two quantities.** → µ_I and µ_q.
10. **Decay sum and alarm threshold.** Expected count vs probability; hop indexing; negative h*. → Union bound, ε > q₁ feasibility, h* = max(0, ·).
11. **Token slack vs bit slack.** → Entropy-rate bridge.
12. **Relay objective "unverified".** The stationarity condition is correct; added the anti-leak-by-negation caveat.
13. **Notation collisions.** Φ (floor / normal CDF), θ (gap threshold / hydro-time / salience), D (KL / downstream output), L (access / total leakage / length), m (restricted count / fan-out / message), W (legit pull / CUSUM). → App. C.
14. **AgentLeak description.** 41.7% is "violations missed by output-only audits", not "traces with clean output and internal leak"; the paper's large-scale analysis covers C1, C2, C5; channel numbering differs between the paper and the dataset card, so pin the version. Interceptor figures unverified.
15. **MAGPIE description.** v1 says leakage is flagged only on verbatim match; the v1 MAGPIE paper states penalties apply to information *inferable* from the conversation. Check the evaluator code before repeating either claim. Fix the version (v1: 158 tasks [2]; later: 200 tasks [2b]).
16. **Missing utility term.** Filler displaces legitimate completions (distraction). → Added.

---

## Appendix A — Derivations

**A.1 Slack bound.** As in v1 (correct).

**A.2 Petal vs restriction-aware (both readings).**
Restriction-aware: (k − o)(1 − λ).
Petal, reading R: k − o s(1 − δ) − λk − κ o q_f.
Petal, reading A: k − o(q₀ − q_f)(1 − δ) − λk − κ o q_f.
Differences: o[(1 − λ) − s(1 − δ) − κ q_f] and o[(1 − λ) − (q₀ − q_f)(1 − δ) − κ q_f].
Break-evens: δ*_R = 1 − ((1 − λ) − κ q_f)/s; δ*_A = 1 − ((1 − λ) − κ q_f)/(q₀ − q_f).
δ = 0 under R: wins iff q_f(1/q₀ − κ) > λ.

**A.3 Stochastic ladder.** Rows of the k-ary RR channel: p on the true symbol, (1 − p)/(k − 1) elsewhere. TV between rows for x ≠ x′: ½(|p − p′| + |p′ − p| + 0·(k − 2)) where p′ = (1 − p)/(k − 1), = |p − p′|. Dobrushin coefficient = max over pairs = |p − p′|. η_KL ≤ η_TV [8].

**A.4 Decay budget.** Σ_{t≥1} q₁ e^{−µ(t−1)} = q₁/(1 − e^{−µ}) ≤ ε ⇔ e^{−µ} ≤ 1 − q₁/ε ⇔ µ ≥ −ln(1 − q₁/ε), requiring ε > q₁.

**A.5 Alarm threshold.** J′(h) = κq₁/D_KL − c e^{−h} = 0 ⇒ h = ln(cD_KL/(κq₁)); J is convex in h, so the constrained optimum on h ≥ 0 is max(0, ·).

## Appendix B — CSS pseudocode

```
for each token position t in relay message:
    l_full = logits(model, prefix | C)
    l_noS  = logits(model, prefix | C minus span S)
    delta  = l_full - l_noS
    gate   = span_classifier(prefix, candidate_tokens) or token in surface_forms(S)
    l_out  = l_full - alpha * gate * relu(delta)
    sample next token from softmax(l_out / T)
```
KV-cache both contexts; cost ≈ 2× decoding.

## Appendix C — Notation (collision-free)

| Symbol | Meaning |
|---|---|
| S, A, Y | restricted, permitted, needed information |
| C_t, M_t, E_{t+1}, O_{t+1} | context, relay message, side inputs, downstream output |
| B, G, h̄ | bandwidth, slack, per-token entropy rate |
| z_S, z_f, W_leg | trigger pull, filler pull, legitimate pull |
| q₀, q_f, q₁ | leak prob. without petal, with petal, at first exposed hop |
| s | relative suppression 1 − q_f/q₀ |
| δ | disclosure–use separability |
| λ, κ, c | length cost, leak cost, false-alarm cost |
| η_r, µ_I, µ_q | rung contraction, information decay, leak-prob. decay |
| k_r, p_r, ε_r | rung alphabet size, keep prob., LDP level |
| α, g | CSS strength, CSS gate |
| W^cs, h, D_KL | CUSUM statistic, threshold, KL(p₁‖p₀) |
| Λ, Φ_floor | causal leak, inference floor |
| Φ_N | standard normal CDF |
| τ_g, τ_s, θ_H | gap threshold, salience threshold, hydro-time constant |
| φ, L_acc, π, y₀ | willingness, access, pull, abstention threshold |
| m, g, R | fan-out, restatement prob., reproduction number |

## References

[1] F. El Yagoubi, G. Badu-Marfo, R. Al Mallah. AgentLeak: A Benchmark for Internal-Channel Privacy Leakage in Multi-Agent LLM Systems. arXiv:2602.11510 (v3, Jun 2026); IEEE Access, 2026, doi:10.1109/ACCESS.2026.3704541.
[2] G. Juneja, A. Albalak, W. Hua, W. Y. Wang. MAGPIE: A dataset for multi-agent contextual privacy evaluation. arXiv:2506.20737, 2025.
[2b] MAGPIE: A benchmark for multi-agent contextual privacy evaluation (200-task release). arXiv:2510.15186, 2025.
[3] Y. Shao et al. PrivacyLens. arXiv:2409.00138.
[4] N. Mireshghallah et al. Can LLMs keep a secret? arXiv:2310.17884.
[5] Yu et al. When do multi-agent systems help? An information bottleneck perspective. arXiv:2607.16133, 2026.
[6] N. Tishby, F. Pereira, W. Bialek. The information bottleneck method. Allerton, 1999.
[7] A. Makhdoumi, S. Salamatian, N. Fawaz, M. Médard. From the information bottleneck to the privacy funnel. ITW, 2014.
[8] Y. Polyanskiy, Y. Wu. Strong data-processing inequalities for channels and Bayesian networks. 2017.
[9] H. Nissenbaum. Privacy as contextual integrity. Washington Law Review, 2004.
[10] J. A. Lockhart. An analysis of irreversible plant cell elongation. J. Theor. Biol., 1965.
[11] K. J. Bradford. Applications of hydrothermal time to seed germination and dormancy. Weed Science, 2002.
[12] D. Cohen. Optimizing reproduction in a randomly varying environment. J. Theor. Biol., 1966.
[13] T. Fukami. Historical contingency in community assembly. Annu. Rev. Ecol. Evol. Syst., 2015.
[14] E. S. Page. Continuous inspection schemes. Biometrika, 1954.
[15] G. Lorden. Procedures for reacting to a change in distribution. Ann. Math. Stat., 1971.
[16] J. Maynard Smith. Evolution and the Theory of Games. CUP, 1982.
[17] P. Kairouz, S. Oh, P. Viswanath. Extremal mechanisms for local differential privacy. JMLR, 2016.
[18] W. Shi et al. Trusting your evidence: hallucinate less with context-aware decoding. NAACL, 2024.
