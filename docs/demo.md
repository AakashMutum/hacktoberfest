# 3-minute demo script

Before you start, run `powershell -ExecutionPolicy Bypass -File scripts\run_demo.ps1 -Check` and open http://127.0.0.1:8000. Leave it running for a minute so warm-up and pre-investigation can finish. Check the header badge: it should read `ready` with the provider and model. If it reads `offline · templates`, every explanation will be labelled as a template. Say so; do not present it as model output.

The **Demo tour** button in the header runs this same story step by step with on-screen captions (Space for next, Esc to exit). Use it if you want the app to drive.

If the network or the model is slow on stage, turn on **Safe mode** in the header. Investigations then replay real cached model outputs, labelled "replayed from cache". Rows with nothing cached show the labelled template.

## 0:00 – 0:30 · The problem
"UPI fraud keeps changing shape, and rule engines answer it by blocking genuine customers. Circuit Breaker scores every payment in a few milliseconds and responds in proportion. Everything you see is synthetic data from a fixed seed."

Point at the **live rail**: payments cross the breaker, and the lever trips red on a block.

## 0:30 – 1:15 · One flagged payment
1. Hover over the rail (it freezes) and click a red **Trip** row.
2. Show the **top risk factors**: these are the model's own contributions for this payment.
3. Show the **investigator note** and read out the provenance label, e.g. "Gemma 4 E4B · local · function calling", and the tools it called.
4. The **mule-ring graph** updates. Red nodes forward most of what they receive. Hover over one to see its fan-in and pass-through.

## 1:15 – 1:45 · The customer
1. On the **phone**, show the block screen and the simulated trusted-contact alert.
2. Switch to **தமிழ்**, then **हिन्दी**. Click **Gemma explanation** if the message has not been generated yet; the elapsed time shows while Gemma writes it. Point out the label under the message.
3. Click a yellow **Hold** row and answer the context question on the phone.

## 1:45 – 2:15 · The scoreboard
"Same stream, three systems." Compare fraud intercepted, genuine customers blocked, and rupees saved. Hover over **Rules B** to show its exact rules. "The simple rules save slightly more rupees only by blocking every large payment, and hundreds of genuine customers with them."

## 2:15 – 2:45 · Red team
1. Click **Launch attack**: smurfing, which the model has never seen. Most of it slips through, and the rules catch none.
2. Click **Adapt model**: it retrains in about 2 s. Show detection before and after on campaigns it did not train on, and that AUC on the old typologies did not drop.

## 2:45 – 3:00 · Screenshot and close
Drop a scam SMS screenshot onto **Scan a screenshot** and read out the scam signals Gemma found. Close with: "Open weights, running locally, explaining every stop in the customer's language."
