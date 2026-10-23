"""Draw a fake scam SMS screenshot for testing the screenshot scan. Entirely fictional."""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "sample-scam-sms.png")


def font(size):
    for name in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


img = Image.new("RGB", (720, 1100), "#f2f2f2")
d = ImageDraw.Draw(img)
d.rectangle([0, 0, 720, 120], fill="#1f3b73")
d.text((30, 40), "VM-ELCTBL", fill="white", font=font(38))
bubble = [30, 170, 690, 760]
d.rounded_rectangle(bubble, radius=28, fill="white", outline="#d0d0d0", width=2)
lines = [
    "Dear Customer, your ELECTRICITY",
    "connection will be DISCONNECTED",
    "tonight at 9:30 PM because your",
    "last month bill was not updated.",
    "",
    "To avoid disconnection pay Rs 4,999",
    "IMMEDIATELY to the officer UPI ID:",
    "  billdesk.helpdesk@okaxis",
    "",
    "Or call 98XXX-12345 now.",
    "Do not ignore. - Electricity Dept",
]
y = 200
for line in lines:
    d.text((60, y), line, fill="#111111", font=font(30))
    y += 48
d.text((60, 790), "Today 7:42 PM", fill="#777777", font=font(24))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.save(OUT)
print(OUT)
