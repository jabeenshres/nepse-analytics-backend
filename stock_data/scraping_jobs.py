"""
Reusable scraper jobs shared by the one-off and daily management commands.

Each job returns a ``JobResult`` instead of raising, so the orchestrator can retry,
verify against the database, and report a summary. Selenium is imported lazily so
this module can be imported (and unit tested) without a browser.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Set

logger = logging.getLogger(__name__)

SCRAPER_DATE_FORMAT = '%m/%d/%Y'


@dataclass
class JobResult:
    name: str
    status: str  # ok | no_data | error | skipped
    rows: int = 0
    detail: str = ''
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ('ok', 'skipped')


# ----------------------------------------------------------------------
# Jobs
# ----------------------------------------------------------------------

def run_indices(target_date, index_ids: Optional[Sequence[int]] = None) -> JobResult:
    """Scrape NEPSE indices for one date and save them."""
    from .nepse_indices_scraper import NepseIndicesScraper, save_indices_to_db

    started = time.time()
    totals = {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 0}

    scraper = NepseIndicesScraper()
    results = scraper.scrape_all_indices(
        index_ids=list(index_ids) if index_ids else None,
        target_date=target_date.isoformat(),
    )

    for records in results.values():
        if not records:
            continue
        stats = save_indices_to_db(records, skip_existing=True)
        for key in totals:
            totals[key] += stats.get(key, 0)

    rows = totals['created'] + totals['updated'] + totals['skipped']
    return JobResult(
        name='indices',
        status='ok' if rows else 'no_data',
        rows=rows,
        detail=f"indices={len(results)} {totals}",
        duration=round(time.time() - started, 2),
    )


def run_today_price(date_from, date_to, headless: bool = True) -> JobResult:
    """Scrape Today's Price for an inclusive date range and save it."""
    from .constants import NEPAL_STOCK_BASE_URL
    from .models import Stock, StockData
    from .utils import NepalStockScraper

    started = time.time()
    scraper = NepalStockScraper(headless=headless)
    try:
        scraper.load_page(NEPAL_STOCK_BASE_URL)
        stats = scraper.loop_through_date_range(
            Stock, StockData, date_from, date_to, save_to_db=True
        )
    finally:
        scraper.close()

    rows = stats.get('rows_parsed', 0)
    return JobResult(
        name='today-price',
        status='ok' if rows else 'no_data',
        rows=rows,
        detail=(
            f"processed={stats.get('dates_processed', 0)} "
            f"failed={stats.get('dates_failed', 0)} "
            f"created={stats.get('rows_created', 0)} "
            f"skipped={stats.get('rows_skipped', 0)}"
        ),
        duration=round(time.time() - started, 2),
    )


def run_floorsheet(
    source: str = 'nepalstock',
    symbols: Optional[Iterable[str]] = None,
    date_from=None,
    date_to=None,
    headless: bool = True,
) -> JobResult:
    """Scrape floorsheet data. nepalstock = whole market; merolagani = per symbol."""
    started = time.time()

    if source == 'nepalstock':
        from .nepalstock_floorsheet_scraper import NepalstockFloorsheetScraper

        scraper = NepalstockFloorsheetScraper(headless=headless)
        try:
            transactions, metadata = scraper.scrape_from_url(save_to_db=True)
        finally:
            scraper.close()

        rows = len(transactions)
        return JobResult(
            name='floorsheet',
            status='ok' if rows else 'no_data',
            rows=rows,
            detail=f"source=nepalstock symbols={len(metadata.get('symbols_found', []))}",
            duration=round(time.time() - started, 2),
        )

    from .floorsheet_scraper import MerolaganiFloorsheetScraper

    symbols = [symbol.upper() for symbol in (symbols or []) if symbol]
    if not symbols:
        raise ValueError('merolagani source requires at least one symbol')
    if not date_from or not date_to:
        raise ValueError('merolagani source requires date_from and date_to')

    scraper = MerolaganiFloorsheetScraper(headless=headless)
    try:
        results = scraper.scrape_multiple_symbols(
            symbols=symbols,
            date_from=date_from.strftime(SCRAPER_DATE_FORMAT),
            date_to=date_to.strftime(SCRAPER_DATE_FORMAT),
            scrape_all_pages=True,
            skip_existing_dates=True,
            save_to_db=True,
        )
    finally:
        scraper.close()

    rows = results['total_transactions']
    return JobResult(
        name='floorsheet',
        status='ok' if rows else 'no_data',
        rows=rows,
        detail=(
            f"source=merolagani "
            f"{results['successful']}/{results['total_symbols']} symbols"
        ),
        duration=round(time.time() - started, 2),
    )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def verify_date(target_date) -> dict:
    """Count rows in each dataset for the date, straight from the database."""
    from .models import FloorsheetData, NepseIndex, StockData

    return {
        'indices': NepseIndex.objects.filter(date=target_date).count(),
        'stock_data': StockData.objects.filter(date=target_date).count(),
        'floorsheet': FloorsheetData.objects.filter(transaction_date=target_date).count(),
    }


def is_satisfied(task: str, counts: dict, min_stock_rows: int = 100) -> bool:
    """Whether the database already proves the task produced data for the date."""
    if task == 'indices':
        return counts.get('indices', 0) > 0
    if task == 'today-price':
        return counts.get('stock_data', 0) >= min_stock_rows
    if task == 'floorsheet':
        return counts.get('floorsheet', 0) > 0
    return False


def parse_holidays(raw: Optional[str]) -> Set:
    """Parse a comma-separated YYYY-MM-DD list into date objects."""
    holidays = set()
    for part in (raw or '').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            holidays.add(datetime.strptime(part, '%Y-%m-%d').date())
        except ValueError:
            logger.warning(f"Ignoring invalid NEPSE_HOLIDAYS entry: {part!r}")
    return holidays


def run_with_retries(
    name: str,
    job,
    attempts: int = 3,
    delays: Sequence[int] = (30, 120, 300),
) -> JobResult:
    """Run ``job`` until it succeeds or attempts are exhausted."""
    last: Optional[JobResult] = None

    for attempt in range(1, attempts + 1):
        try:
            last = job()
        except Exception as exc:  # noqa: BLE001 - report, then retry
            logger.error(f"{name} attempt {attempt} failed: {exc}")
            last = JobResult(name=name, status='error', detail=str(exc))

        if last.ok:
            return last

        if attempt < attempts:
            delay = delays[min(attempt - 1, len(delays) - 1)] if delays else 0
            if delay:
                time.sleep(delay)

    return last or JobResult(name=name, status='error', detail='no attempt ran')
