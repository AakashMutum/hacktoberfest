# Customer message templates: review needed

The Tamil and Hindi customer messages in `backend/policy.py` (`COPY`) were written by hand for this project. They are shown whenever no model is available, or when a model reply is not in the requested script. They should be reviewed by a native speaker of each language before any real-world use, checking:

- tone: calm, plain and respectful, suitable for an older or anxious customer
- banking terms: UPI PIN, payment, cooling-off period and trusted contact as people actually say them
- that rupee amounts and VPAs read naturally inside each sentence
- that the word for "simulated" on the trusted-contact alert is clear to a non-technical reader
