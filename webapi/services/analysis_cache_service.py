"""Analysis cache service for storing and reusing analyst reports."""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false, reportDeprecated=false, reportUnannotatedClassAttribute=false, reportUnusedImport=false, reportReturnType=false, reportIndexIssue=false

import hashlib
import logging
from contextlib import contextmanager
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from webapi.models.database import AnalystReportCache

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    """Return naive UTC datetime for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AnalysisCacheService:
    """Service for analyst report cache CRUD, TTL checks, and advisory locks."""

    ANALYST_TYPES: tuple[str, ...] = ("market", "sentiment", "news", "fundamentals")
    HIT_TYPES: tuple[str, ...] = ("full", "partial", "miss")
    EVENT_INVALIDATION_MAP = {
        "trading_halt": ("market", "sentiment", "news"),
        "limit_up": ("market", "sentiment"),
        "limit_down": ("market", "sentiment"),
        "earnings_report": ("fundamentals",),
        "major_news": ("news", "sentiment"),
    }

    def __init__(self, db: Session):
        """Initialize cache service with database session."""
        self.db: Session = db
        self._lock_prefix: str = "analyst_cache"

    _hit_counter: Counter[tuple[str, str | None, str | None]] = Counter()

    def _get_lock_id(self, symbol: str, analyst_type: str) -> int:
        """Generate a stable advisory lock id for (symbol, analyst_type)."""
        key = f"{self._lock_prefix}:{symbol}:{analyst_type}"
        hash_bytes = hashlib.sha256(key.encode()).digest()[:8]
        lock_id = int.from_bytes(hash_bytes, byteorder="big", signed=True)
        return abs(lock_id) % (2**63 - 1)

    def acquire_lock(self, symbol: str, analyst_type: str) -> bool:
        """Acquire a non-blocking advisory lock for a cache key."""
        lock_id = self._get_lock_id(symbol, analyst_type)
        try:
            result = self.db.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": lock_id},
            ).scalar()
            return bool(result)
        except Exception:
            logger.exception("Error acquiring cache lock for %s:%s", symbol, analyst_type)
            return False

    def release_lock(self, symbol: str, analyst_type: str) -> bool:
        """Release advisory lock for a cache key."""
        lock_id = self._get_lock_id(symbol, analyst_type)
        try:
            result = self.db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": lock_id},
            ).scalar()
            return bool(result)
        except Exception:
            logger.exception("Error releasing cache lock for %s:%s", symbol, analyst_type)
            return False

    def is_locked(self, symbol: str, analyst_type: str) -> bool:
        """Return whether another session currently appears to hold the lock."""
        acquired = self.acquire_lock(symbol, analyst_type)
        if acquired:
            _ = self.release_lock(symbol, analyst_type)
            return False
        return True

    @contextmanager
    def lock_context(self, symbol: str, analyst_type: str):
        """Yield whether the advisory lock was acquired."""
        acquired = False
        try:
            acquired = self.acquire_lock(symbol, analyst_type)
            yield acquired
        finally:
            if acquired:
                _ = self.release_lock(symbol, analyst_type)

    def _normalize_analysis_date(self, analysis_date: date | None) -> date:
        """Normalize missing analysis date to current UTC date."""
        if analysis_date is None:
            return utcnow().date()
        return analysis_date

    def _get_cache_entry(
        self,
        symbol: str,
        analyst_type: str,
        analysis_date: date,
    ):
        """Get the latest cache entry for a symbol, analyst, and date."""
        return (
            self.db.query(AnalystReportCache)
            .filter(
                AnalystReportCache.symbol == symbol,
                AnalystReportCache.analyst_type == analyst_type,
                AnalystReportCache.analysis_date == analysis_date,
            )
            .order_by(AnalystReportCache.created_at.desc())
            .first()
        )

    def get_cached_report(
        self,
        symbol: str,
        analyst_type: str,
        analysis_date: date | None = None,
    ) -> str | None:
        """Return cached report content when the cache row is still valid."""
        analysis_date = self._normalize_analysis_date(analysis_date)

        try:
            cache_entry = self._get_cache_entry(symbol, analyst_type, analysis_date)
            if cache_entry and bool(cache_entry.is_valid) and not cache_entry.is_expired():
                self.log_cache_hit(symbol, analyst_type, "full")
                logger.info(
                    "Cache HIT: %s:%s:%s",
                    symbol,
                    analyst_type,
                    analysis_date,
                    extra={
                        "symbol": symbol,
                        "analyst_type": analyst_type,
                        "analysis_date": analysis_date.isoformat(),
                        "cache_hit": True,
                        "cache_age_seconds": (utcnow() - cache_entry.created_at).total_seconds(),
                    },
                )
                return str(cache_entry.report_content)

            reason = "expired_or_invalid" if cache_entry else "not_found"
            self.log_cache_hit(symbol, analyst_type, "miss")
            logger.info(
                "Cache MISS: %s:%s:%s",
                symbol,
                analyst_type,
                analysis_date,
                extra={
                    "symbol": symbol,
                    "analyst_type": analyst_type,
                    "analysis_date": analysis_date.isoformat(),
                    "cache_hit": False,
                    "reason": reason,
                },
            )
            return None
        except Exception:
            logger.exception("Error getting cached report for %s:%s", symbol, analyst_type)
            return None

    def set_cached_report(
        self,
        symbol: str,
        analyst_type: str,
        analysis_date: date | None,
        report_content: str,
        ttl_seconds: int | None = None,
        cache_version: int = 1,
        lock_session_id: str | None = None,
    ) -> bool:
        """Upsert a cached analyst report."""
        analysis_date = self._normalize_analysis_date(analysis_date)
        if ttl_seconds is None:
            ttl_seconds = AnalystReportCache.get_ttl_seconds(analyst_type)

        try:
            existing = self._get_cache_entry(symbol, analyst_type, analysis_date)
            now = utcnow()
            expires_at = now + timedelta(seconds=ttl_seconds)

            if existing:
                existing.report_content = report_content
                existing.expires_at = expires_at
                existing.is_valid = True
                existing.cache_version = max(int(existing.cache_version) + 1, cache_version)
                existing.lock_session_id = lock_session_id
                existing.created_at = now
            else:
                cache_entry = AnalystReportCache(
                    symbol=symbol,
                    analyst_type=analyst_type,
                    analysis_date=analysis_date,
                    report_content=report_content,
                    cache_version=cache_version,
                    lock_session_id=lock_session_id,
                    created_at=now,
                    expires_at=expires_at,
                    is_valid=True,
                )
                self.db.add(cache_entry)

            self.db.commit()
            logger.info(
                "Cache SET: %s:%s:%s",
                symbol,
                analyst_type,
                analysis_date,
                extra={
                    "symbol": symbol,
                    "analyst_type": analyst_type,
                    "analysis_date": analysis_date.isoformat(),
                    "ttl_seconds": ttl_seconds,
                    "expires_at": expires_at.isoformat(),
                    "lock_session_id": lock_session_id,
                },
            )
            return True
        except Exception:
            self.db.rollback()
            logger.exception("Error setting cached report for %s:%s", symbol, analyst_type)
            return False

    def invalidate_cache(
        self,
        symbol: str,
        analyst_type: str | None = None,
        analysis_date: date | None = None,
    ) -> int:
        """Soft-invalidate matching cache rows."""
        try:
            query = self.db.query(AnalystReportCache).filter(
                AnalystReportCache.symbol == symbol,
                AnalystReportCache.is_valid.is_(True),
            )

            if analyst_type:
                query = query.filter(AnalystReportCache.analyst_type == analyst_type)
            if analysis_date:
                query = query.filter(AnalystReportCache.analysis_date == analysis_date)

            count = query.update({AnalystReportCache.is_valid: False}, synchronize_session=False)
            self.db.commit()
            logger.info(
                "Cache INVALIDATED: %s:%s:%s",
                symbol,
                analyst_type or "all",
                analysis_date or "all",
                extra={
                    "symbol": symbol,
                    "analyst_type": analyst_type,
                    "analysis_date": analysis_date.isoformat() if analysis_date else None,
                    "invalidated_count": count,
                },
            )
            return count
        except Exception:
            self.db.rollback()
            logger.exception("Error invalidating cache for %s", symbol)
            return 0

    def invalidate_on_event(
        self,
        event_type: str,
        symbol: str,
        analysis_date: date | None = None,
    ) -> int:
        """Invalidate impacted analyst caches for a market event."""
        if event_type not in self.EVENT_INVALIDATION_MAP:
            logger.warning("Unknown cache invalidation event: %s", event_type)
            return 0

        analysts_to_invalidate = self.EVENT_INVALIDATION_MAP[event_type]
        total_invalidated = 0
        for analyst_type in analysts_to_invalidate:
            total_invalidated += self.invalidate_cache(symbol, analyst_type, analysis_date)

        logger.info(
            "Event-driven invalidation: %s -> %s",
            event_type,
            symbol,
            extra={
                "event_type": event_type,
                "symbol": symbol,
                "analysis_date": analysis_date.isoformat() if analysis_date else None,
                "analysts_affected": list(analysts_to_invalidate),
                "total_invalidated": total_invalidated,
            },
        )
        return total_invalidated

    def log_cache_hit(self, symbol: str, analyst_type: str, hit_type: str) -> None:
        """Record structured cache hit/miss telemetry."""
        if hit_type not in self.HIT_TYPES:
            raise ValueError(f"Unsupported hit_type: {hit_type}")

        self._hit_counter[(hit_type, None, None)] += 1
        self._hit_counter[(hit_type, symbol, None)] += 1
        self._hit_counter[(hit_type, None, analyst_type)] += 1
        self._hit_counter[(hit_type, symbol, analyst_type)] += 1

        logger.info(
            "cache_telemetry",
            extra={
                "event": "cache_hit",
                "symbol": symbol,
                "analyst_type": analyst_type,
                "hit_type": hit_type,
                "timestamp": utcnow().isoformat(),
            },
        )

    def get_hit_rate(
        self,
        symbol: str | None = None,
        analyst_type: str | None = None,
        time_range: str = "24h",
    ) -> dict[str, object]:
        """Return observed runtime hit rate from in-process counters."""
        try:
            time_range_hours = int(time_range[:-1]) if time_range.endswith("h") else int(time_range)
        except ValueError:
            time_range_hours = 24

        counters = {
            hit_type: self._hit_counter[(hit_type, symbol, analyst_type)]
            for hit_type in self.HIT_TYPES
        }
        total = sum(counters.values())
        numerator = counters["full"] + counters["partial"]
        hit_rate = numerator / total if total else 0.0
        return {
            "symbol": symbol,
            "analyst_type": analyst_type,
            "time_range_hours": time_range_hours,
            "hit_rate": hit_rate,
            "counters": counters,
        }

    def is_cache_valid(
        self,
        symbol: str,
        analyst_type: str,
        analysis_date: date | None = None,
    ) -> bool:
        """Return whether a valid cache row exists."""
        return self.get_cached_report(symbol, analyst_type, analysis_date) is not None

    def get_cache_status(
        self,
        symbol: str,
        analysis_date: date | None = None,
    ) -> dict[str, object]:
        """Return cache status for all four analysts for a symbol/date."""
        analysis_date = self._normalize_analysis_date(analysis_date)
        analysts: dict[str, object] = {}
        status: dict[str, object] = {
            "symbol": symbol,
            "analysis_date": analysis_date.isoformat(),
            "analysts": analysts,
        }

        for analyst_type in self.ANALYST_TYPES:
            cache_entry = self._get_cache_entry(symbol, analyst_type, analysis_date)
            if cache_entry:
                analysts[analyst_type] = {
                    "cached": True,
                    "valid": bool(cache_entry.is_valid) and not cache_entry.is_expired(),
                    "created_at": cache_entry.created_at.isoformat(),
                    "expires_at": cache_entry.expires_at.isoformat(),
                    "cache_version": int(cache_entry.cache_version),
                    "lock_session_id": cache_entry.lock_session_id,
                }
            else:
                analysts[analyst_type] = {"cached": False, "valid": False}

        return status

    def get_cache_stats(
        self,
        symbol: str | None = None,
        analyst_type: str | None = None,
        time_range_hours: int = 24,
    ) -> dict[str, object]:
        """Return aggregate cache statistics."""
        cutoff_time = utcnow() - timedelta(hours=time_range_hours)
        query = self.db.query(AnalystReportCache).filter(
            AnalystReportCache.created_at >= cutoff_time,
        )
        if symbol:
            query = query.filter(AnalystReportCache.symbol == symbol)
        if analyst_type:
            query = query.filter(AnalystReportCache.analyst_type == analyst_type)

        total_entries = query.count()
        valid_entries = query.filter(AnalystReportCache.is_valid.is_(True)).count()
        expired_entries = query.filter(
            AnalystReportCache.is_valid.is_(True),
            AnalystReportCache.expires_at < utcnow(),
        ).count()

        analyst_breakdown: dict[str, dict[str, int]] = {}
        for at in self.ANALYST_TYPES:
            at_query = query.filter(AnalystReportCache.analyst_type == at)
            analyst_breakdown[at] = {
                "total": at_query.count(),
                "valid": at_query.filter(AnalystReportCache.is_valid.is_(True)).count(),
            }

        hit_rate_stats = self.get_hit_rate(symbol=symbol, analyst_type=analyst_type, time_range=f"{time_range_hours}h")
        analyst_hit_counters = {
            at: {
                hit_type: self._hit_counter[(hit_type, symbol, at)]
                for hit_type in self.HIT_TYPES
            }
            for at in self.ANALYST_TYPES
        }

        return {
            "time_range_hours": time_range_hours,
            "symbol_filter": symbol,
            "analyst_type_filter": analyst_type,
            "total_entries": total_entries,
            "valid_entries": valid_entries,
            "expired_entries": expired_entries,
            "hit_rate_estimate": valid_entries / total_entries if total_entries > 0 else 0.0,
            "runtime_hit_rate": float(hit_rate_stats["hit_rate"]),
            "hit_counters": hit_rate_stats["counters"],
            "analyst_hit_counters": analyst_hit_counters,
            "analyst_breakdown": analyst_breakdown,
        }

    def cleanup_expired_cache(self, batch_size: int = 1000) -> int:
        """Soft-expire stale cache rows."""
        try:
            stale_entries = (
                self.db.query(AnalystReportCache)
                .filter(
                    AnalystReportCache.is_valid.is_(True),
                    AnalystReportCache.expires_at < utcnow(),
                )
                .order_by(AnalystReportCache.expires_at.asc())
                .limit(batch_size)
                .all()
            )
            for entry in stale_entries:
                entry.is_valid = False
            self.db.commit()
            logger.info("Cleaned up %s expired cache entries", len(stale_entries))
            return len(stale_entries)
        except Exception:
            self.db.rollback()
            logger.exception("Error cleaning up expired cache")
            return 0
