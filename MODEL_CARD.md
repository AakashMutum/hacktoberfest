# Model card: Circuit Breaker risk scorer and investigator

## Components

- **Risk scorer.** An XGBoost binary classifier (220 rounds, depth 6) over 18 features: amount, time of day, account and device age, first-time payee, velocity, and payment-graph features from networkx (payee fan-in and fan-out, pass-through ratio, forwarding-chain depth). Per-payment explanations come from XGBoost `pred_contribs`.
- **Policy.** Fixed thresholds map risk to an action: allow below 0.30, nudge from 0.30, hold from 0.60, block from 0.85.
- **Investigator.** Gemma 4, through local Ollama (`gemma4:e4b`), the Gemini API (`gemma-4-26b-a4b-it`) or an OpenAI-compatible server. It writes a verdict, a reason, an analyst note and a customer message for payments that are held or blocked. It is not trained or fine-tuned by this project.

## Data

All data is synthetic, generated from a fixed seed (42): about 200,000 payments over 30 days, from 12,000 users, 800 merchants and 640 mule or sleeper accounts.

- **Fraud typologies in training:** social engineering, mule rings, card/UPI testing and account takeover. Together they make up about 2.4% of payments.
- **Held out:** smurfing is never in training and is used only for the red-team demo.
- **Split:** the scorer is trained on days 1–21 and evaluated on days 22–30.

No real customer, account or payment data was used at any point.

## Results on the synthetic held-out days

The model intercepts 94.1% of fraud (1,246 of 1,324) and blocks 9 genuine payments out of 58,454; it also holds 17 genuine payments with a question and nudges 40. The AUC on typologies 1–4 is 0.9998. The README has the full comparison with the two rules baselines and the red-team results.

These numbers describe synthetic data whose typologies are cleanly separable. They are not an estimate of performance on real payments.

## Intended use

A demonstration and research prototype. It shows how a fast scorer, proportional responses and an open-weight explainer could work together in real-time UPI fraud protection. It is suitable for hackathons, teaching and experiments on synthetic data.

## Not intended for

- Making decisions about real people's payments or accounts without retraining, validation and review on real, consented data.
- Use as evidence that a specific person committed fraud.
- Credit, identity or any other decision outside fraud screening.

## What it cannot do

- **New patterns.** It generalises poorly to fraud patterns it has not seen: before adapting, it intercepts 20.7% of the held-out smurfing payments.
- **Graph features are not point-in-time.** They come from a snapshot of the whole 30-day period, which leaks some future information.
- **Investigator errors.** The investigator can be wrong, slow or unavailable. Its verdict does not override the scorer's action in this prototype, and template text is shown, with a label, when it cannot answer.
- **Unreviewed translations.** The Tamil and Hindi templates have not yet been reviewed by native speakers.

## Fairness trade-off: blocking fraud vs blocking genuine payments

Every threshold trades missed fraud against genuine customers who are stopped. A blocked genuine payment is not a free safety margin. It can mean rent unpaid, a family transfer delayed, or a customer pushed towards cash. The burden falls hardest on people whose behaviour looks unusual to the model: new account holders, people who are paid irregularly, people who travel, and people who rarely use digital payments.

This prototype handles the trade-off in three ways:

- **Proportional responses.** Only the highest risk is blocked. Medium risk gets a hold with a question, and lower risk a nudge, so a false positive is more often a delay than a refusal.
- **Measuring both sides.** The scoreboard reports genuine payments blocked, held and nudged next to fraud intercepted, for the model and both rule sets.
- **Explanations.** The customer is told in their own language why a payment was stopped.

What it does not do yet: measure error rates across groups of customers. The synthetic data has no demographic attributes, so group fairness cannot be evaluated here. A real deployment would need that analysis, an appeal path, and monitoring of false-positive rates over time.
