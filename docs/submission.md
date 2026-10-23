# MLH submission

## Title
Circuit Breaker

## Tagline
Real-time UPI fraud protection that trips like a breaker, with an open-weight Gemma 4 investigator that explains every stop in English, Tamil or Hindi.

## What it does
Circuit Breaker watches a live stream of UPI-style rupee payments. Each payment is scored in a few milliseconds by an XGBoost model, using behaviour and payment-graph features such as new payee, device age, velocity, the payee's fan-in, pass-through ratio and forwarding-chain depth. Instead of a binary block, it responds in proportion: allow, nudge, hold with a context question ("Did someone on a call ask you to make this payment?"), or block with a simulated trusted-contact alert.

Every hold or block goes to a Gemma 4 investigator. Gemma looks up the payer's history, the payee's network neighbours and the scorer's risk factors, then returns a verdict, a reason, a note for an analyst, and a calm message for the customer in their language. A screenshot scanner uses Gemma 4's vision to read a payment request or scam SMS and pull out the payee, amount, urgency, pressure cues and scam signals.

A live scoreboard compares Circuit Breaker with two rules engines on the same stream. A red-team panel injects a fraud pattern the model has never seen, shows it slipping through, then retrains in seconds and reports detection before and after on campaigns it did not train on.

On the synthetic held-out stream (59,778 payments, 1,324 fraud), Circuit Breaker intercepts 94.1% of fraud and blocks 9 genuine payments. A simple rules engine intercepts 57.5% and blocks 1,677 genuine payments; a tighter rule set intercepts 56.9% and blocks 571. All data is synthetic.

## How we built it
- Python, FastAPI and uvicorn, with a WebSocket stream.
- A seeded synthetic generator of 200k payments across four fraud typologies: social engineering, mule rings, card/UPI testing and account takeover. A fifth typology, smurfing, is held out for red-teaming.
- networkx for graph features and XGBoost for scoring, with `pred_contribs` giving per-payment factor attributions.
- The Gemma 4 provider chain: local Ollama (`gemma4:e4b`), the Gemini API (`gemma-4-26b-a4b-it`), any OpenAI-compatible endpoint, and a labelled template as the last resort.
- React, TypeScript and Vite, with framer-motion and a canvas force graph. The design is a "switchgear control room" with offline fonts that include Tamil and Devanagari.
- pytest coverage for the generator, scorer, policy, rule sets and the investigator's fallback and provenance logic.

## How Gemma 4 is used
- **Investigator with tools.** Gemma 4 is given three functions (`get_account_history`, `get_graph_neighbours`, `get_risk_factors`) and decides what to check before giving its verdict. If a runtime rejects tool calls, the backend switches to context injection: it runs the same lookups and puts them in the prompt. The mode is recorded and shown on every explanation.
- **Multilingual customer messages.** Gemma writes the customer message in English, Tamil or Hindi. Replies are checked for the right script; if the check fails, a hand-written template is shown and labelled as such.
- **Multimodal screenshot scan.** Image plus text: Gemma 4 reads a payment request or scam message and returns structured risk evidence.
- **Open weights for privacy.** The default provider is a local Gemma 4 E4B through Ollama, so payment data can stay on the bank's own hardware.
- **Verified.** On the Gemini API, a full investigation with all three tool calls takes 6–8 s, including a Tamil message in Tamil script. The screenshot scan correctly read a fake electricity-disconnection scam SMS (payee, ₹4,999, high urgency, impersonation signals) in about 7 s.
- **Honest provenance.** Every explanation is labelled, for example "Gemma 4 E4B · local · function calling" or "Template (model unavailable)".

## Challenges
- Making synthetic fraud realistic enough to be credible. Our first dataset was perfectly separable, so we added overlap: young genuine accounts, genuine night-time and new-device transfers, genuine pass-through "collector" accounts, daytime scams and aged mule accounts.
- Keeping a real-time stream responsive while a local model on CPU can take many seconds. Investigations run in a single background worker with a cache, and the UI shows the elapsed time.
- Providers support tool calling differently. We built an automatic fallback to context injection rather than assuming one API.
- On the Gemini API, Gemma 4 reasoned for about 27 s per call by default. Setting minimal thinking and asking for all three tools in one round brought a full investigation to 6–8 s.

## What's next
- Point-in-time graph features and evaluation on real, consented data with a partner bank.
- Native-speaker review of the Tamil and Hindi copy, and more Indian languages.
- An analyst feedback loop that turns confirmed cases into labelled retraining data, with review gates before deployment.
- Fine-tuning a small Gemma 4 variant on investigation transcripts.

## Built with
python, fastapi, uvicorn, xgboost, networkx, scikit-learn, pandas, numpy, google-genai, ollama, gemma-4, react, typescript, vite, framer-motion, pytest, playwright

## Best Open-Source AI Project
Circuit Breaker is MIT-licensed, and its intelligence is built on open components end to end. The default investigator is the open-weight Gemma 4 E4B running locally through Ollama. The scorer is XGBoost with transparent per-factor attributions, and the graph analysis uses networkx. The same code runs on any OpenAI-compatible open-model server. Because the whole stack can run on the bank's own hardware, no payment data has to leave the institution. The repo includes a seeded data generator, tests and a reproducible scoreboard, so anyone can rerun and check every number.

## Best Use of Gemma 4
Gemma 4 does the work an analyst would do. It calls tools to check account history, payment-graph neighbours and risk factors, reasons over that evidence, and returns a structured verdict with a proportional response. It then speaks to the customer in English, Tamil or Hindi. Its multimodal side reads screenshots of payment requests and scam messages to pull out risk signals. A runtime that cannot do tool calls falls back to context injection, and every output carries a provenance label, so Gemma's contribution is always visible and never faked.

## GitHub repo settings
**About description:** Real-time UPI fraud protection: XGBoost risk scoring, proportional responses, and an open-weight Gemma 4 investigator with tool calling, multilingual messages and screenshot scanning. Synthetic data.

**Topics:** hacktoberfest, gemma, gemma-4, fraud-detection, open-source-ai, fastapi, react, upi
