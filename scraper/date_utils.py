"""Date parsing and date-range splitting helpers."""

from datetime import datetime, timedelta

from config import MAX_DATE_WINDOW_DAYS


def parse_user_date(value):
    """Parse a user date in DD-MM-YYYY format."""
    return datetime.strptime(value.strip(), "%d-%m-%Y")


def split_date_range(start_date, end_date, max_days=MAX_DATE_WINDOW_DAYS):
    """Split an inclusive date range into consecutive windows of at most max_days."""
    ranges = []
    current_start = start_date

    while current_start <= end_date:
        current_end = min(
            current_start + timedelta(days=max_days - 1),
            end_date,
        )
        ranges.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)

    return ranges
