"""Decides which scan a GitHub Actions run should do: evening, check, or skip.
Scheduled runs fire at two UTC times per job (daylight saving and standard time);
this keeps the one that lands in the right New York window and skips duplicates."""
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
REPORTS = Path("reports")


def ran_evening(day):
    try:
        return json.loads((REPORTS / "plans_latest.json").read_text()).get("date") == day
    except Exception:
        return False


def ran_check(day):
    return (REPORTS / f"check_{day}.html").exists()


def decide(now, event, manual=""):
    if event == "workflow_dispatch":
        return manual or "evening"
    if now.weekday() >= 5:
        return "skip"
    day = now.date().isoformat()
    mins = now.hour * 60 + now.minute
    if 18 * 60 <= mins < 23 * 60 and not ran_evening(day):
        return "evening"
    if 9 * 60 + 45 <= mins < 13 * 60 and not ran_check(day):
        return "check"
    return "skip"


if __name__ == "__main__":
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    manual = sys.argv[2] if len(sys.argv) > 2 else ""
    now = dt.datetime.now(NY)
    mode = decide(now, event, manual)
    print(f"mode={mode}")
    print(f"New York time {now:%a %H:%M} -> {mode}", file=sys.stderr)
