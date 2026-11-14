"""Synthetic financial transactions, seeded so the file is reproducible byte for byte.
usage: python3 tools/make_csv.py OUT.csv [rows]      (default 10000 rows)

Columns: Date,Description,Amount,Category. Amounts are built as INTEGER CENTS and written with two decimals, so an
exact answer exists for every sum (the tests recompute it with decimal.Decimal). The file contains, on purpose:
  - quoted descriptions with commas, doubled quotes, and a newline inside the quotes
  - amounts over $1,000 written with a thousands separator, so they must be quoted ("1,250.50")
  - refunds (negative amounts, credit-card style: charges are positive)
  - a handful of bad rows (impossible dates, text amount, three decimals, too few fields, text after a quote, a blank line)
"""
import random, sys

out = sys.argv[1]
rows = int(sys.argv[2]) if len(sys.argv) > 2 else 10000
rng = random.Random(20261112)

# (category, weight, merchants, (low_cents, high_cents)); Subscriptions and Rent are special-cased below
CATEGORIES = [
    ("Groceries", 24, ["Whole Foods Market", "Trader Joe's", "Safeway", "Costco Wholesale, Inc.", "Aldi"], (850, 26000)),
    ("Dining", 18, ["Chipotle", "Blue Bottle Coffee", "Joe's Pizza", "The \"Corner\" Cafe", "Sushi Zen, Downtown"], (600, 14000)),
    ("Transport", 14, ["Shell", "Uber", "Lyft", "City Transit Pass", "Parking Meter 4411"], (300, 9500)),
    ("Shopping", 14, ["Amazon", "Target", "Best Buy", "IKEA", "Etsy"], (900, 60000)),
    ("Subscriptions", 8, ["Netflix", "Spotify", "iCloud", "Gym Membership", "NYT Digital"], None),
    ("Utilities", 6, ["City Power & Light", "Water Dept", "Comcast", "Verizon Wireless"], (3500, 31000)),
    ("Entertainment", 6, ["AMC Theatres", "Steam", "Ticketmaster", "Bowlero"], (800, 18000)),
    ("Health", 5, ["CVS Pharmacy", "Dr. Patel, DDS", "Quest Diagnostics", "Vision Center"], (1500, 90000)),
    ("Travel", 3, ["Delta Air Lines", "Marriott, Downtown", "Airbnb", "Enterprise Rent-A-Car"], (6000, 900000)),
    ("Rent", 2, ["Maple Street Apartments"], (85000, 340000)),
]
SUBSCRIPTION_CENTS = [499, 999, 1299, 1549, 5499]
WEIGHTS = [c[1] for c in CATEGORIES]
MONTH_DAYS = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]  # 2024 is a leap year; 2025 uses 28 for February


def date_for(index):
    # 2024-01-01 .. 2025-12-31 (731 days)
    day = rng.randrange(731)
    year = 2024 if day < 366 else 2025
    if day >= 366:
        day -= 366
    for month in range(12):
        length = MONTH_DAYS[month] if (year == 2024 or month != 1) else 28
        if day < length:
            return "%04d-%02d-%02d" % (year, month + 1, day + 1)
        day -= length
    raise AssertionError("unreachable")


def cents_text(cents):
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return "%s%d.%02d" % (sign, whole, frac)


def quote(text):
    return '"' + text.replace('"', '""') + '"' if any(ch in text for ch in ',"\n') else text


records = []
for i in range(rows):
    name, _weight, merchants, span = rng.choices(CATEGORIES, WEIGHTS)[0]
    merchant = rng.choice(merchants)
    if name == "Subscriptions":
        cents = rng.choice(SUBSCRIPTION_CENTS)
    elif name == "Rent":
        cents = rng.randrange(span[0], span[1]) // 500 * 500  # whole five-dollar rents
    else:
        # skewed towards small purchases: the square of a uniform draw
        u = rng.random()
        cents = span[0] + int((span[1] - span[0]) * u * u)
    if rng.random() < 0.025:  # a refund: negative, a bit smaller than a typical charge
        cents = -max(100, cents // 2)
        merchant = merchant + " (refund)"
    records.append((date_for(i), merchant, cents, name))

records.sort(key=lambda r: r[0])  # a bank export is chronological

lines = ["Date,Description,Amount,Category"]
for date, merchant, cents, name in records:
    amount = cents_text(cents)
    if abs(cents) >= 100000 and rng.random() < 0.5:  # $1,000.00 and up: some exporters add a thousands separator
        whole, frac = amount.split(".")
        sign = "-" if whole.startswith("-") else ""
        whole = "{:,}".format(abs(int(whole)))
        amount = '"%s%s.%s"' % (sign, whole, frac)
    lines.append("%s,%s,%s,%s" % (date, quote(merchant), amount, name))

# awkward records, replacing some existing ones at fixed spots so the row count stays `rows`
if rows >= 1000:
    spots = [rows // 10 * k + 7 for k in range(1, 10)]
    lines[spots[0]] = "2025-02-29,Leap day that is not,12.00,Dining"           # 2025 is not a leap year
    lines[spots[1]] = "2024-02-29,Leap day that is,12.00,Dining"               # 2024 is: this one is valid
    lines[spots[2]] = "2025-03-14,Gas station,N/A,Transport"                   # text amount
    lines[spots[3]] = "2025-03-15,Corner store,4.999,Groceries"                # a fraction of a cent
    lines[spots[4]] = "2025-03-16,Only three fields,19.99"                     # too few fields
    lines[spots[5]] = ""                                                       # a blank line
    lines[spots[6]] = '2025-04-01,"Rest stop\nthen lunch",23.45,Dining'        # a newline inside the quotes: valid
    lines[spots[7]] = "2025-13-01,Month thirteen,9.99,Shopping"                # impossible month
    lines[spots[8]] = '2025-05-05,"Closed early"oops,10.00,Dining'              # text after the closing quote

with open(out, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(lines) + "\n")
print("%d data rows -> %s" % (len(lines) - 1, out))
