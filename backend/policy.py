"""Maps risk probability to a proportional response and the customer-facing copy for it."""
from __future__ import annotations

THRESHOLDS = {"nudge": 0.30, "hold": 0.60, "block": 0.85}
HOLD_MINUTES = 30
LANGS = ("en", "ta", "hi")


def decide(prob: float) -> str:
    if prob >= THRESHOLDS["block"]:
        return "block"
    if prob >= THRESHOLDS["hold"]:
        return "hold"
    if prob >= THRESHOLDS["nudge"]:
        return "nudge"
    return "allow"


def risk_band(action: str) -> str:
    return {"allow": "low", "nudge": "elevated", "hold": "medium", "block": "high"}[action]


def needs_investigation(action: str) -> bool:
    return action in ("hold", "block")


COPY = {
    "en": {
        "yes_outcome": "Thank you. This is how most scams work. We have cancelled the payment. Hang up and never share your UPI PIN.",
        "no_outcome": "Thanks for confirming. The payment will go through when the cooling-off period ends.",
        "cancelled": "Payment cancelled. No money has left your account.",
        "continued": "Payment sent. You can raise a dispute within 24 hours if something feels wrong.",
        "title_nudge": "Check this payee",
        "title_hold": "Payment paused",
        "title_block": "Payment stopped",
        "title_allow": "Paid",
        "simulated": "SIMULATED",
        "to": "To",
        "allow": "Payment sent.",
        "nudge": "Check before you pay: {payee} is new to you. Only continue if you know them.",
        "hold": "We have paused this payment of ₹{amount} for {minutes} minutes to keep you safe.",
        "block": "We stopped this payment of ₹{amount}. It matches patterns used in scams.",
        "question": "Did someone on a call or message ask you to make this payment?",
        "yes": "Yes, someone asked me",
        "no": "No, this is my own payment",
        "contact": "Simulated alert sent to your trusted contact",
        "continue": "Continue anyway",
        "cancel": "Cancel payment",
    },
    "ta": {
        "yes_outcome": "நன்றி. பெரும்பாலான மோசடிகள் இப்படித்தான் நடக்கின்றன. பணப்பரிமாற்றத்தை ரத்து செய்தோம். அழைப்பைத் துண்டித்து, உங்கள் UPI PIN-ஐ யாருடனும் பகிர வேண்டாம்.",
        "no_outcome": "உறுதிப்படுத்தியதற்கு நன்றி. காத்திருப்பு நேரம் முடிந்ததும் பணம் அனுப்பப்படும்.",
        "cancelled": "பணப்பரிமாற்றம் ரத்து செய்யப்பட்டது. உங்கள் கணக்கிலிருந்து பணம் எடுக்கப்படவில்லை.",
        "continued": "பணம் அனுப்பப்பட்டது. ஏதேனும் தவறு என்று தோன்றினால் 24 மணி நேரத்திற்குள் புகார் செய்யலாம்.",
        "title_nudge": "பெறுநரைச் சரிபார்க்கவும்",
        "title_hold": "பணப்பரிமாற்றம் நிறுத்தம்",
        "title_block": "பணப்பரிமாற்றம் தடுக்கப்பட்டது",
        "title_allow": "அனுப்பப்பட்டது",
        "simulated": "மாதிரி",
        "to": "பெறுநர்",
        "allow": "பணம் அனுப்பப்பட்டது.",
        "nudge": "பணம் அனுப்பும் முன் சரிபார்க்கவும்: {payee} உங்களுக்குப் புதியவர். தெரிந்தவர் என்றால் மட்டும் தொடரவும்.",
        "hold": "உங்கள் பாதுகாப்பிற்காக ₹{amount} பணப்பரிமாற்றம் {minutes} நிமிடங்கள் நிறுத்தி வைக்கப்பட்டுள்ளது.",
        "block": "₹{amount} பணப்பரிமாற்றத்தை நிறுத்தினோம். இது மோசடிகளில் காணப்படும் முறையுடன் ஒத்துப்போகிறது.",
        "question": "அழைப்பு அல்லது செய்தி மூலம் யாராவது இந்தப் பணத்தை அனுப்பச் சொன்னார்களா?",
        "yes": "ஆம், ஒருவர் கேட்டார்",
        "no": "இல்லை, இது என் சொந்தப் பணப்பரிமாற்றம்",
        "contact": "உங்கள் நம்பகமான தொடர்புக்கு மாதிரி எச்சரிக்கை அனுப்பப்பட்டது",
        "continue": "தொடர்ந்து அனுப்பு",
        "cancel": "பணப்பரிமாற்றத்தை ரத்து செய்",
    },
    "hi": {
        "yes_outcome": "धन्यवाद। ज़्यादातर धोखाधड़ी ऐसे ही होती है। हमने भुगतान रद्द कर दिया है। कॉल काट दें और अपना UPI PIN कभी साझा न करें।",
        "no_outcome": "पुष्टि के लिए धन्यवाद। प्रतीक्षा अवधि खत्म होने पर भुगतान हो जाएगा।",
        "cancelled": "भुगतान रद्द किया गया। आपके खाते से कोई पैसा नहीं गया।",
        "continued": "भुगतान भेज दिया गया। कुछ गलत लगे तो 24 घंटे के भीतर शिकायत करें।",
        "title_nudge": "प्राप्तकर्ता की जाँच करें",
        "title_hold": "भुगतान रोका गया",
        "title_block": "भुगतान अवरुद्ध",
        "title_allow": "भेजा गया",
        "simulated": "सिम्युलेटेड",
        "to": "प्राप्तकर्ता",
        "allow": "भुगतान भेज दिया गया।",
        "nudge": "भुगतान से पहले जाँच लें: {payee} आपके लिए नया है। जानते हों तभी आगे बढ़ें।",
        "hold": "आपकी सुरक्षा के लिए ₹{amount} का भुगतान {minutes} मिनट के लिए रोका गया है।",
        "block": "हमने ₹{amount} का यह भुगतान रोक दिया है। यह धोखाधड़ी के तरीकों से मेल खाता है।",
        "question": "क्या किसी ने कॉल या मैसेज पर आपसे यह भुगतान करने को कहा?",
        "yes": "हाँ, किसी ने कहा",
        "no": "नहीं, यह मेरा अपना भुगतान है",
        "contact": "आपके भरोसेमंद संपर्क को नकली (सिम्युलेटेड) अलर्ट भेजा गया",
        "continue": "फिर भी जारी रखें",
        "cancel": "भुगतान रद्द करें",
    },
}


def customer_message(action: str, lang: str, amount: float, payee: str) -> str:
    lang = lang if lang in LANGS else "en"
    return COPY[lang][action].format(amount=f"{amount:,.0f}", payee=payee, minutes=HOLD_MINUTES)
