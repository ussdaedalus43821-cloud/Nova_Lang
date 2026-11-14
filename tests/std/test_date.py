"""std:date (M14 slice P1, docs/spec/09-library.md [lib.std-date]) against Python's `datetime` and `calendar` as independent oracles.

The natives are called directly over every day from 1900 to 2100 (and the edges of the calendar), then a seeded program is run on the VM, the
tree-walker and the self-hosted engine and its output is compared with the oracle line by line.
"""

import calendar
import datetime as dt
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import novalang  # noqa: E402

N = {name: function.implementation for name, function in novalang.NATIVE_FUNCTIONS["date"].items()}
ENGINES = (("vm", []), ("tree", ["--tree-walk"]), ("bootstrap", ["--bootstrap"]))


class _Interpreter:
    counting = False

    def step(self, position=None):
        pass

    def charge(self, units, position=None):
        pass


def call(name, *args):
    return N[name](list(args), None, _Interpreter())


def text(d):
    return d.strftime("%Y-%m-%d") if d.year >= 1000 else "{:04d}-{:02d}-{:02d}".format(d.year, d.month, d.day)


def oracle_add_months(d, months):
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def refused(test, name, *args):
    with test.assertRaises(novalang.NovaError) as caught:
        call(name, *args)
    return caught.exception.message


class Dates(unittest.TestCase):
    def test_every_day_from_1900_to_2100(self):
        day = dt.date(1900, 1, 1)
        pivot = dt.date(2000, 2, 29)
        while day <= dt.date(2100, 12, 31):
            s = text(day)
            self.assertTrue(call("is_date", s))
            self.assertEqual((call("year", s), call("month", s), call("day", s)), (day.year, day.month, day.day))
            self.assertEqual(call("weekday", s), day.isoweekday(), s)
            self.assertEqual(call("day_of_year", s), day.timetuple().tm_yday, s)
            self.assertEqual(call("last_day_of_month", s), text(dt.date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])), s)
            self.assertEqual(call("diff_days", s, text(pivot)), (day - pivot).days, s)
            for n in (-366, -31, -1, 0, 1, 7, 30, 365, 1461):
                self.assertEqual(call("add_days", s, n), text(day + dt.timedelta(days=n)), (s, n))
            if day.day in (1, 15, 28, 29, 30, 31) or day.month == 2:
                for n in (-25, -13, -1, 0, 1, 2, 11, 12, 13, 36):
                    self.assertEqual(call("add_months", s, n), text(oracle_add_months(day, n)), (s, n))
                for n in (-4, -1, 1, 4, 100):
                    self.assertEqual(call("add_years", s, n), text(oracle_add_months(day, 12 * n)), (s, n))
            day += dt.timedelta(days=1)

    def test_leap_years_and_month_lengths(self):
        for year in range(1, 10000):
            self.assertEqual(call("is_leap", year), calendar.isleap(year), year)
        for year in (1, 1900, 2000, 2023, 2024, 2100, 9999):
            for month in range(1, 13):
                self.assertEqual(call("days_in_month", year, month), calendar.monthrange(year, month)[1], (year, month))

    def test_the_month_end_rule(self):
        for start, months, want in (("2027-01-31", 1, "2027-02-28"), ("2028-01-31", 1, "2028-02-29"), ("2027-03-31", -1, "2027-02-28"),
                                    ("2027-01-31", 3, "2027-04-30"), ("2027-08-31", 6, "2028-02-29"), ("2027-05-30", 12, "2028-05-30")):
            self.assertEqual(call("add_months", start, months), want)
        self.assertEqual(call("add_years", "2028-02-29", 1), "2029-02-28")
        self.assertEqual(call("add_years", "2028-02-29", 4), "2032-02-29")
        self.assertEqual(call("add_months", "2027-01-31", 1.0), "2027-02-28")          # a whole number may be written 1.0

    def test_make_and_compare(self):
        self.assertEqual(call("make", 2027, 1, 31), "2027-01-31")
        self.assertEqual(call("make", 1, 1, 1), "0001-01-01")
        self.assertIn("has no date", refused(self, "make", 2027, 2, 29))
        self.assertIn("needs a whole number", refused(self, "make", 2027.5, 1, 1))
        self.assertEqual([call("compare", "2027-01-01", "2027-01-02"), call("compare", "2027-01-01", "2027-01-01"), call("compare", "2027-03-01", "2027-01-02")], [-1, 0, 1])

    def test_what_is_not_a_date(self):
        for bad in ("2027-02-29", "2027-13-01", "2027-00-10", "2027-1-1", "2027-01-1", " 2027-01-01", "2027-01-01 ", "2027/01/01", "20270101",
                    "٢٠٢٧-٠١-٠١", "0000-01-01", "10000-01-01", "", "2027-01-32", "2027-04-31", "1900-02-29",
                    "2027-01-01T00:00:00+00:00", "2027-01-01\n", "abc"):
            with self.subTest(bad=bad):
                self.assertFalse(call("is_date", bad))
                self.assertIn("is not a date of the calendar", refused(self, "year", bad))
        for good in ("0001-01-01", "9999-12-31", "2028-02-29", "2000-02-29"):
            self.assertTrue(call("is_date", good))
        for value in (5, [], True):
            self.assertIn("needs a string", refused(self, "is_date", value))

    def test_the_edges_of_the_calendar_are_errors_not_wrong_dates(self):
        self.assertIn("outside the years 1 to 9999", refused(self, "add_days", "9999-12-31", 1))
        self.assertIn("outside the years 1 to 9999", refused(self, "add_days", "0001-01-01", -1))
        self.assertIn("outside the years 1 to 9999", refused(self, "add_months", "9999-12-31", 1))
        self.assertIn("outside the years 1 to 9999", refused(self, "add_years", "0001-06-01", -1))
        self.assertIn("out of the calendar", refused(self, "add_days", "2027-01-01", 10 ** 12))
        self.assertIn("needs a whole number", refused(self, "add_days", "2027-01-01", 1.5))
        self.assertIn("needs a whole number", refused(self, "add_days", "2027-01-01", "1"))
        self.assertEqual(call("add_days", "0001-01-01", 3652058), "9999-12-31")


class Timestamps(unittest.TestCase):
    def test_epoch_and_offsets_against_datetime(self):
        rng = random.Random(1970)
        for _ in range(3000):
            seconds = rng.randrange(-62135596800 + 90000, 253402300799 - 90000)
            offset = rng.choice([0, 60, -300, 330, 345, -570, 840, -720, 1, 1439, -1439])
            tz = dt.timezone(dt.timedelta(minutes=offset))
            moment = dt.datetime.fromtimestamp(0, dt.timezone.utc) + dt.timedelta(seconds=seconds)
            local = moment.astimezone(tz)
            sign = "-" if offset < 0 else "+"
            ts = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}{}{:02d}:{:02d}".format(local.year, local.month, local.day, local.hour, local.minute, local.second,
                                                                              sign, abs(offset) // 60, abs(offset) % 60)
            written = "Z" if offset == 0 and rng.random() < 0.5 else "{}{:02d}{:02d}".format(sign, abs(offset) // 60, abs(offset) % 60) if rng.random() < 0.5 else sign + "{:02d}:{:02d}".format(abs(offset) // 60, abs(offset) % 60)
            self.assertEqual(call("from_epoch", seconds, written), ts)
            self.assertEqual(call("to_epoch", ts), seconds)
            self.assertEqual(call("to_utc", ts), "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}+00:00".format(moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second))
            self.assertEqual(call("offset_of", ts), "{}{:02d}:{:02d}".format(sign, abs(offset) // 60, abs(offset) % 60))
            self.assertEqual(call("date_of", ts), ts[:10])
            self.assertEqual(call("with_offset", call("with_offset", ts, "+05:00"), written), ts)
            self.assertTrue(call("is_timestamp", ts))

    def test_differences_additions_and_ordering(self):
        a, b = "2027-03-01T00:00:00+00:00", "2027-02-28T23:00:00-02:00"
        # b is 23:00 at -02:00 on 28 February, which is 01:00 UTC on 1 March: an hour after a
        self.assertEqual(call("diff_seconds", a, b), -3600)
        self.assertEqual(call("diff_seconds", b, a), 3600)
        self.assertEqual(call("add_seconds", "2027-12-31T23:59:59+01:00", 1), "2028-01-01T00:00:00+01:00")
        self.assertEqual(call("add_seconds", "2028-02-28T23:59:59-05:00", 86401), "2028-03-01T00:00:00-05:00")
        self.assertEqual(call("compare", a, b), -1)
        self.assertEqual(call("compare", "2027-01-01T00:00:00+01:00", "2026-12-31T23:00:00+00:00"), 0)      # the same instant
        self.assertEqual(call("diff_seconds", "2027-01-01T00:00:00+01:00", "2026-12-31T23:00:00+00:00"), 0)
        self.assertEqual(call("make_timestamp", 2027, 1, 31, 13, 55, 36, "-0500"), "2027-01-31T13:55:36-05:00")

    def test_what_is_not_a_timestamp(self):
        for bad in ("2027-01-31T13:55:36", "2027-01-31 13:55:36+00:00", "2027-01-31T13:55:36Z", "2027-01-31T24:00:00+00:00", "2027-01-31T13:60:00+00:00",
                    "2027-01-31T13:55:60+00:00", "2027-01-31T13:55:36+24:00", "2027-01-31T13:55:36+01:60", "2027-02-30T13:55:36+00:00",
                    "2027-01-31T13:55:36.5+00:00", "2027-01-31T13:55:36+0000", "", "2027-01-31"):
            with self.subTest(bad=bad):
                self.assertFalse(call("is_timestamp", bad))
        for bad in ("UTC", "+1", "+24:00", "+01:60", "1:00", "", "Z0"):
            with self.subTest(offset=bad):
                refused(self, "with_offset", "2027-01-31T13:55:36+00:00", bad)
        self.assertIn("outside the years 1 to 9999", refused(self, "add_seconds", "9999-12-31T23:59:59+00:00", 1))
        self.assertIn("outside the years 1 to 9999", refused(self, "from_epoch", 300000000000, "Z"))


class Formats(unittest.TestCase):
    def test_the_common_log_forms(self):
        self.assertEqual(call("parse_timestamp", "10/Oct/2026:13:55:36 +0000", "%d/%b/%Y:%H:%M:%S %z"), "2026-10-10T13:55:36+00:00")
        self.assertEqual(call("parse_timestamp", "10/oct/2026:13:55:36 -0700", "%d/%b/%Y:%H:%M:%S %z"), "2026-10-10T13:55:36-07:00")
        self.assertEqual(call("parse_timestamp", "2026-10-10T13:55:36.123456Z", "%Y-%m-%dT%H:%M:%S.%f%z"), "2026-10-10T13:55:36+00:00")
        self.assertEqual(call("parse_timestamp", "2026-10-10 13:55:36 +01:00", "%Y-%m-%d %H:%M:%S %z"), "2026-10-10T13:55:36+01:00")
        self.assertEqual(call("parse_timestamp", "Sat, 10 Oct 2026 13:55:36 +0200", "%a, %d %b %Y %H:%M:%S %z"), "2026-10-10T13:55:36+02:00")
        self.assertEqual(call("parse_timestamp_at", "2026 Oct  9 03:04:05", "%Y %b %e %H:%M:%S", "+01:00"), "2026-10-09T03:04:05+01:00")
        self.assertEqual(call("parse_timestamp_at", "2026 Oct 19 03:04:05", "%Y %b %e %H:%M:%S", "Z"), "2026-10-19T03:04:05+00:00")
        self.assertEqual(call("parse_timestamp", "Saturday October 10 2026 01:02:03 Z", "%A %B %d %Y %H:%M:%S %z"), "2026-10-10T01:02:03+00:00")
        self.assertEqual(call("parse_date", "10 October 2026", "%d %B %Y"), "2026-10-10")
        self.assertEqual(call("parse_date", "2026-10-10 is the day", "%Y-%m-%d is the day"), "2026-10-10")
        self.assertEqual(call("parse_date", "100% of 2026-10-10", "100%% of %Y-%m-%d"), "2026-10-10")

    def test_format_round_trips(self):
        rng = random.Random(7)
        for _ in range(500):
            d = dt.date(1, 1, 1) + dt.timedelta(days=rng.randrange(0, 3652058))
            ts = "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}{}".format(d.year, d.month, d.day, rng.randrange(24), rng.randrange(60), rng.randrange(60), rng.choice(["+00:00", "-05:30", "+09:00", "+14:00"]))
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%d/%b/%Y:%H:%M:%S %z", "%a %A %B %e %Y %H:%M:%S %z"):
                shown = call("format", ts, fmt)
                self.assertEqual(call("parse_timestamp", shown, fmt), ts, (shown, fmt))
            self.assertEqual(call("parse_date", call("format", text(d), "%d %B %Y"), "%d %B %Y"), text(d))
            self.assertEqual(call("format", text(d), "%Y-%m-%d"), text(d))
            self.assertEqual(call("format", text(d), "%a"), calendar.day_abbr[d.weekday()])

    def test_names_are_english_whatever_the_locale(self):
        self.assertEqual(call("format", "2026-10-10", "%A %B %e %a %b"), "Saturday October 10 Sat Oct")
        self.assertEqual(call("format", "2026-03-04", "%e|%d"), " 4|04")
        self.assertEqual(call("format", "2026-10-10T01:02:03+05:30", "%H:%M:%S %z"), "01:02:03 +0530")

    def test_what_a_format_refuses(self):
        for fmt, text_, needle in (("%Y-%m-%d", "2026-10-10x", "more after the format ended"), ("%Y-%m-%d", "2026-1-10", "expected 2 digits for the month"),
                                   ("%Y-%m-%d", "2026-13-10", "not a date of the calendar"), ("%Y-%m-%d", "2026-02-30", "not a date of the calendar"),
                                   ("%d %b %Y", "10 Foo 2026", "expected a month name"), ("%a %d %b %Y", "Mon 10 Oct 2026", "not the weekday"),
                                   ("%Q", "x", "does not know the format code"), ("%", "x", "does not know the format code"), ("%d", "10", "needs the format to read the year")):
            with self.subTest(fmt=fmt, text=text_):
                self.assertIn(needle, refused(self, "parse_date", text_, fmt))
        self.assertIn("needs the format to read the offset", refused(self, "parse_timestamp", "2026-10-10 01:02:03", "%Y-%m-%d %H:%M:%S"))
        self.assertIn("use date.parse_timestamp() instead", refused(self, "parse_timestamp_at", "2026-10-10 01:02:03 +0000", "%Y-%m-%d %H:%M:%S %z", "Z"))
        self.assertIn("read the hour", refused(self, "parse_timestamp", "2026-10-10 +0000", "%Y-%m-%d %z"))
        self.assertIn("cannot write %f", refused(self, "format", "2026-10-10T01:02:03+00:00", "%f"))
        self.assertIn("has %H but the value is a date", refused(self, "format", "2026-10-10", "%H"))
        self.assertIn("needs a string for the format", refused(self, "format", "2026-10-10", 5))
        self.assertIn("not a date of the calendar", refused(self, "parse_date", "2026-02-29", "%Y-%m-%d"))
        self.assertIn("a time of day that does not exist", refused(self, "parse_timestamp", "2026-10-10 25:00:00 +0000", "%Y-%m-%d %H:%M:%S %z"))


class Hostile(unittest.TestCase):
    """No argument, however wrong, ends in anything but a NovaLang error: a Python exception would be a crash."""

    POOL = [None, True, False, 0, 1, -1, 1.5, float("nan"), float("inf"), 10 ** 30, -10 ** 30, 2 ** 63, "", "x", " ", "\0", "2027-01-31", "9999-12-31", "0001-01-01",
            "2027-01-31T13:55:36+00:00", "9999-12-31T23:59:59-23:59", "0001-01-01T00:00:00+23:59", "Z", "+01:00", "%Y", "%", "%d %b", [], {}, [1], "\u0661" * 4]

    def test_every_native_with_junk(self):
        rng = random.Random(99)
        for name, function in sorted(novalang.NATIVE_FUNCTIONS["date"].items()):
            for _ in range(400):
                args = [rng.choice(self.POOL) for _ in range(function.arity)]
                try:
                    call(name, *args)
                except novalang.NovaError:
                    pass
                except Exception as problem:            # noqa: BLE001
                    self.fail("date.{}{!r} raised {}: {}".format(name, args, type(problem).__name__, problem))

    def test_the_largest_and_smallest_timestamps_survive_every_conversion(self):
        for ts in ("9999-12-31T23:59:59-23:59", "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59+00:00", "0001-01-01T00:00:00+00:00"):
            for name, args in (("to_utc", (ts,)), ("to_epoch", (ts,)), ("date_of", (ts,)), ("offset_of", (ts,)), ("with_offset", (ts, "+05:00")),
                               ("add_seconds", (ts, 1)), ("add_seconds", (ts, -1)), ("diff_seconds", (ts, ts)), ("compare", (ts, ts))):
                try:
                    call(name, *args)
                except novalang.NovaError:
                    pass


class Engines(unittest.TestCase):
    """A seeded program of valid calls on the three engines, against the independent oracle."""

    def build(self, count, seed):
        rng = random.Random(seed)
        source, expected = ['import "std:date" as date'], []
        for _ in range(count):
            d = dt.date(1, 1, 1) + dt.timedelta(days=rng.randrange(0, 3652058))
            e = dt.date(1900, 1, 1) + dt.timedelta(days=rng.randrange(0, 73000))
            d = e if rng.random() < 0.8 else d
            n = rng.choice([-400, -31, -1, 0, 1, 28, 30, 31, 365, 1000])
            m = rng.choice([-13, -1, 0, 1, 2, 12, 13, 25])
            choice = rng.randrange(7)
            s, t = text(d), text(e)
            if choice == 0:
                source.append('print(date.add_days("{}", {}))'.format(s, n))
                try:
                    expected.append(text(d + dt.timedelta(days=n)))
                except OverflowError:
                    source.pop()
                    continue
            elif choice == 1:
                try:
                    want = text(oracle_add_months(d, m))
                except (ValueError, OverflowError):
                    continue
                source.append('print(date.add_months("{}", {}))'.format(s, m))
                expected.append(want)
            elif choice == 2:
                source.append('print(date.diff_days("{}", "{}"), date.weekday("{}"), date.day_of_year("{}"))'.format(s, t, s, t))
                expected.append("{} {} {}".format((d - e).days, d.isoweekday(), e.timetuple().tm_yday))
            elif choice == 3:
                source.append('print(date.last_day_of_month("{}"), date.is_leap(date.year("{}")))'.format(s, s))
                expected.append("{} {}".format(text(dt.date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])), str(calendar.isleap(d.year)).lower()))
            elif choice == 4:
                hour, minute, second, off = rng.randrange(24), rng.randrange(60), rng.randrange(60), rng.choice([0, 60, -300, 330])
                sign = "-" if off < 0 else "+"
                ts = "{}T{:02d}:{:02d}:{:02d}{}{:02d}:{:02d}".format(s, hour, minute, second, sign, abs(off) // 60, abs(off) % 60)
                tz = dt.timezone(dt.timedelta(minutes=off))
                epoch = int((dt.datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=tz) - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)).total_seconds())
                source.append('print(date.to_epoch("{}"), date.from_epoch(date.to_epoch("{}"), "{}") == "{}")'.format(ts, ts, ts[-6:], ts))
                expected.append("{} true".format(epoch))
            elif choice == 5:
                source.append('print(date.format("{}", "%A, %d %B %Y"))'.format(s))
                expected.append("{}, {:02d} {} {}".format(calendar.day_name[d.weekday()], d.day, calendar.month_name[d.month], "{:04d}".format(d.year)))
            else:
                source.append('print(date.parse_timestamp(date.format("{}T01:02:03+00:00", "%d/%b/%Y:%H:%M:%S %z"), "%d/%b/%Y:%H:%M:%S %z"))'.format(s))
                expected.append(s + "T01:02:03+00:00")
        return "\n".join(source) + "\n", expected

    def run_on(self, flags, source):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "main.nova")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(source)
            return subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + flags + [path], capture_output=True, text=True, timeout=900,
                                  stdin=subprocess.DEVNULL, env=dict(os.environ, NOVALANG_CACHE="off"))

    def test_the_three_engines_give_the_oracles_answers(self):
        for (name, flags), count in zip(ENGINES, (400, 150, 60)):
            source, expected = self.build(count, 2027)
            done = self.run_on(flags, source)
            self.assertEqual(done.returncode, 0, (name, done.stderr[-400:]))
            self.assertEqual(done.stdout.splitlines(), expected, name)


if __name__ == "__main__":
    unittest.main()
