# cfo.ai: the business behind Rook

This is the input sheet for the cfo.ai plan. Every assumption is named, given a value, and labelled
with where the value comes from: **measured** from this repository, **benchmark** from published
figures, or **assumption** the team has set and can change. cfo.ai does the modelling; this file
exists so the inputs can be argued with.

Nothing here is presented as a result that has already happened. Rook has no customers yet.

Plan link: _paste the cfo.ai share link here_

---

## 1. What is being sold

Rook is a web application a clinic or company connects to the software it already runs. Staff
report a problem in one dashboard; Rook investigates across every connected system, proposes a fix,
waits for a person to approve anything that reaches someone outside the building, then verifies the
result and shows the proof. It replaces no existing system. It does the chasing between them.

First market: **small and mid-sized clinics**. They have several systems that do not talk to each
other, no IT team, and the coordination lands on a practice manager or receptionist.

## 2. Pricing

Priced per clinic per month, by number of clinicians, because the work scales with clinicians and
clinics resist per-seat pricing for admin tools.

| Tier | Clinicians | Price / month | Assumption type |
|---|---|---|---|
| Small | 1 to 5 | $149 | assumption |
| Standard | 6 to 20 | $299 | assumption |
| Group | 21 to 50 | $699 | assumption |
| Multi-site | 50+ | quoted | assumption |

Blended ARPU assumed at **$280/month**, weighted towards Standard.

### Why that number, for a Standard clinic

| Line | Value | Type |
|---|---|---|
| Coordination hours Rook absorbs per month | 16 h | assumption, built from the two below |
| — absence cover: 1.5 sick days/month at 2 h of rebooking and calling each | 3 h | assumption |
| — chasing referrals, results and prescriptions | 13 h | assumption |
| Fully loaded admin cost per hour | $22 | assumption; set to local rate |
| Labour value per month | **$352** | derived |
| Appointment slots recovered by reaching patients who would not have come | 2/month at $80 | assumption |
| Total measured value per month | **~$512** | derived |
| Price as a share of value | **58%** | derived |

Pricing below measured value on purpose. A tool that claims to save more than it costs, with the
margin visible, is easier to renew than one priced at the ceiling.

## 3. Cost to serve, per customer per month

| Cost | Value | Type |
|---|---|---|
| Model inference | **$0** | **measured**: the shipped planner is deterministic and makes no model calls. The optional `ROOK_PLANNER=llm` adds one planning call per incident; price that from your provider's current rate if you turn it on |
| Observability spans | ~3,100 spans/month | **measured**: 20 to 130 spans per incident (mean 52) across the five playbooks, at an assumed 60 incidents/month |
| Observability spend | $5 | assumption; replace with the neatlogs rate for that volume |
| Hosting and database | $8 | assumption: one small container plus a managed database, shared across tenants |
| Support | $6 | assumption: 0.2 h/month at $30/h |
| Payment processing | 3% of revenue (~$8) | benchmark |
| **Total cost to serve** | **~$27** | derived |
| **Gross margin at $280 ARPU** | **~90%** | derived |

The zero inference cost is the unusual line and it is real: ordering, policy and verification are
deterministic code, not a model. It is worth stating plainly in the plan, because it is why the
margin holds at a low price point.

## 4. Revenue build, year one

| Assumption | Value | Type |
|---|---|---|
| Design partners, months 1 to 3, unpaid | 5 | assumption |
| First paying customer | month 4 | assumption |
| New customers per month from month 4 | 3, 4, 5, 6, 7, 8, then 9/month | assumption |
| Monthly churn | 2% | assumption; benchmark for SMB software is typically 2 to 5% |
| Customers at month 12 | **60** | derived |
| MRR at month 12 | **$16,800** | derived |
| Exit ARR | **$201,600** | derived |

## 5. Acquisition

| Assumption | Value | Type |
|---|---|---|
| Channel | direct outbound to practice managers, plus resale through MSPs already serving clinics | assumption |
| CAC, year one, mostly founder time | $600 | assumption |
| Gross contribution per customer per month | ~$253 | derived |
| **CAC payback** | **~2.4 months** | derived |
| Reference MSP economics, for the resale channel | $100 to $250 per user per month managed services; $25 to $45 per help-desk ticket | benchmark (vendor-published, see Sources) |

The MSP channel matters because of a finding in the research: when MSPs automate, the easy tickets
disappear and the average cost of each remaining human-handled ticket **rises**. Rook attacks the
expensive, multi-system tail, which is the part that is actually hurting them.

## 6. Team and runway

These are the team's own numbers and the ones most worth replacing with real figures in cfo.ai.

| Assumption | Value | Type |
|---|---|---|
| Founders | 2 | fact |
| Founder draw, each | $2,500/month | assumption |
| Tools, hosting, software | $400/month | assumption |
| Fixed burn | **$5,400/month** | derived |
| Starting capital | $30,000 | assumption; set to actual |
| Customers needed to cover fixed burn | **22** | derived: $5,400 / $253 contribution |
| Month that happens | **month 8**, at 25 customers | derived from the ramp in section 4 |
| Lowest cash balance | **$2,320, in month 7** | derived |
| Peak cash consumed | **$27,680 of the $30,000** | derived |

Break-even customer count is the single most useful output to pull from cfo.ai, because it turns a
pricing argument into a sales target: **22 clinics**.

The headroom is the uncomfortable number. The plan survives on $30,000 with **$2,320 to spare at
its worst month**, which is not a margin, it is a rounding error. Two assumptions decide whether
this works: the month the first customer pays, and CAC. If first revenue slips from month 4 to
month 6, the plan needs roughly another $11,000. That is the sensitivity worth running in cfo.ai
before anything else.

The month-by-month build ignores churn so the ramp stays legible. Apply the 2% in cfo.ai; it costs
roughly two customers by month 12.

## 7. What breaks this model

| Risk | Effect | What would show it early |
|---|---|---|
| Real connectors are slower to build than the sandbox adapters | Delays first revenue past month 4 | Time to connect the first design partner's booking system |
| Clinics will not let software contact patients, even with approval | Removes the strongest workflow | Whether design partners enable patient contact or leave it off |
| 16 coordination hours a month turns out to be 5 | Price has to drop to ~$99, margin still holds but payback stretches | Measure hours at design partners before pricing anyone |
| Sold as a feature, not a product | Buyer sends it to their existing vendor | Whether the buyer is the practice manager or the IT supplier |
| Regulatory review of an agent touching patient records | Longer sales cycle in some markets | First procurement conversation |

## 8. Measured facts available to the plan

These come from the repository and are not assumptions.

- The shipped planner makes **no model calls**. Ordering, policy and verification are deterministic.
- **20 to 130 spans per incident**, mean 52, measured across the five playbooks with an in-memory
  OpenTelemetry exporter.
- Work handled per incident, measured: 3 to 24 actions, 7 to 26 independent closure checks.
- One container plus SQLite runs the whole product (`Dockerfile`).
- 120 tests.

## Sources for the benchmark rows

Published figures used as anchors. Most are vendor-published and should be treated as directional.

- Managed services at $100 to $250 per user per month, and $25 to $45 per help-desk ticket:
  [MSP pricing 2026](https://scopable.io/blog/msp-pricing-math-managed-services-2026)
- Cost per human-handled ticket rising after automation:
  [MSP ticket mix after AI](https://bennettfinancials.com/msp-ai-ticket-mix-cost)
- Around half of specialist referrals never completed, which is the problem the clinic workflows
  address: [IHI/NPSF closing the loop](https://www.ihi.org/sites/default/files/IHI_NPSF_Closing_the_Loop_Referral_Management_in_EHR.pdf)
