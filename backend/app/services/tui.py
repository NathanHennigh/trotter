"""Small terminal reporter for long-running developer tasks."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import sys
from typing import Any


ORANGE = "\033[38;5;208m"
GREEN = "\033[92m"
RED = "\033[91m"
DIM = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[96m"


@dataclass
class GmailImportReporter:
    """Log-safe progress display for Gmail imports."""

    job_id: str
    parser_version: int
    limit: int | None
    batch_size: int
    workers: int
    tiers: list[str]
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_tier: str | None = None
    tier_stats: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    parse_miss_reasons: Counter = field(default_factory=Counter)
    recent_flights: deque[str] = field(default_factory=lambda: deque(maxlen=5))
    slow_parser_calls: list[tuple[float, str, str, str]] = field(default_factory=list)
    initial_scan_announced: bool = False

    def start(self) -> None:
        self._clear_line()
        print(f"\n{BOLD}{'=' * 72}{RESET}")
        print(f"{BOLD}  Trotter Gmail Sync  job={self.job_id[:8]}  parser=v{self.parser_version}{RESET}")
        print(
            f"{DIM}  limit={self.limit or 'none'}  batch={self.batch_size}  "
            f"workers={self.workers}  tiers={', '.join(self.tiers)}{RESET}"
        )
        print(f"{BOLD}{'=' * 72}{RESET}")

    def tier_started(self, tier: str, detail: str | None = None) -> None:
        self.current_tier = tier
        self._clear_line()
        suffix = f"  {DIM}{detail}{RESET}" if detail else ""
        print(f"{BOLD}Phase: {tier}{RESET}{suffix}")

    def initial_scan_complete(self) -> None:
        if self.initial_scan_announced:
            return
        self.initial_scan_announced = True
        self._clear_line()
        print(
            f"{GREEN}Initial email scan completed.{RESET} "
            "Continuing a comprehensive backscan for older or unusual confirmations."
        )

    def count(self, tier: str | None, key: str, amount: int = 1) -> None:
        self.tier_stats[tier or self.current_tier or "unknown"][key] += amount

    def parser_miss(self, tier: str | None, reason: str | None) -> None:
        self.count(tier, "parser_miss")
        self.parse_miss_reasons[reason or "unknown"] += 1

    def evidence(self, tier: str | None, verdict: str) -> None:
        self.count(tier, f"evidence_{verdict or 'unknown'}")

    def parser_timing(self, tier: str | None, *, seconds: float, sender: str, subject: str) -> None:
        self.count(tier, "parser_call")
        self.tier_stats[tier or self.current_tier or "unknown"]["parser_seconds"] += seconds
        self.slow_parser_calls.append((seconds, tier or self.current_tier or "-", sender, subject))
        self.slow_parser_calls.sort(key=lambda row: row[0], reverse=True)
        del self.slow_parser_calls[5:]

    def parsed_flight(self, tier: str | None, *, segments: int, updated: int, skipped: int, sender: str, subject: str) -> None:
        self.count(tier, "parsed_email")
        self.count(tier, "segments_inserted", segments)
        self.count(tier, "segments_updated", updated)
        self.count(tier, "segments_skipped", skipped)
        self.recent_flights.append(f"{self._safe(sender, 34)} | {self._safe(subject, 54)}")
        self._clear_line()
        print(
            f"  {GREEN}+{segments} segment(s){RESET}  "
            f"{DIM}updated={updated} skipped={skipped} tier={tier or self.current_tier or '-'}{RESET}  "
            f"{self._safe(sender, 34)}  |  {self._safe(subject, 54)}"
        )

    def progress(self, *, scanned: int, parsed: int, flights: int, skipped: int) -> None:
        elapsed = int((datetime.now(timezone.utc) - self.started_at).total_seconds())
        tier = self.current_tier or "starting"
        line = (
            f"\r{BOLD}{tier}{RESET}  "
            f"{CYAN}{scanned:,}{RESET} scanned  "
            f"{GREEN}{parsed:,}{RESET} parsed  "
            f"{GREEN}{flights:,}{RESET} new segments  "
            f"{DIM}{skipped:,} skipped  {elapsed}s{RESET}   "
        )
        sys.stdout.write(line[:180])
        sys.stdout.flush()

    def final_summary(self, *, scanned: int, parsed: int, segments: int, updated: int, skipped: int, canceled: int, enriched: int) -> None:
        self._clear_line()
        print(f"\n{BOLD}{'=' * 72}{RESET}")
        print(f"{GREEN}Sync complete{RESET}")
        print(f"  Scanned  {CYAN}{scanned:,}{RESET} emails")
        print(f"  Parsed   {CYAN}{parsed:,}{RESET} flight emails")
        print(f"  Saved    {GREEN}{segments:,}{RESET} segments")
        print(f"  Updated  {CYAN}{updated:,}{RESET} segments")
        print(f"  Skipped  {CYAN}{skipped:,}{RESET} parsed placeholders")
        print(f"  Canceled {CYAN}{canceled:,}{RESET} segments")
        print(f"  Enriched {CYAN}{enriched:,}{RESET} segments")
        print("")
        print(f"{BOLD}Tier stats{RESET}")
        for tier in self.tiers:
            stats = self.tier_stats.get(tier)
            if not stats:
                continue
            print(
                f"  {tier:<28} "
                f"candidates={stats.get('candidate', 0):>5,}  "
                f"meta-pass={stats.get('metadata_pass', 0):>5,}  "
                f"meta-skip={stats.get('metadata_skip', 0):>5,}  "
                f"fetch={stats.get('full_fetch', 0):>5,}  "
                f"evidence={stats.get('evidence_parse', 0):>4,}/{stats.get('evidence_review', 0):>4,}/{stats.get('evidence_skip', 0):>4,}  "
                f"parser={stats.get('parser_call', 0):>4,}/{stats.get('parser_seconds', 0.0):>6.1f}s  "
                f"db-skip={stats.get('db_skip', 0):>5,}  "
                f"prefilter={stats.get('prefilter_skip', 0):>5,}  "
                f"miss={stats.get('parser_miss', 0):>5,}  "
                f"parsed={stats.get('parsed_email', 0):>4,}"
            )
        if self.parse_miss_reasons:
            print(f"{BOLD}Top parser miss reasons{RESET}")
            for reason, count in self.parse_miss_reasons.most_common(5):
                print(f"  {count:>5,}  {self._safe(reason, 64)}")
        if self.recent_flights:
            print(f"{BOLD}Recent parsed flights{RESET}")
            for line in self.recent_flights:
                print(f"  {line}")
        if self.slow_parser_calls:
            print(f"{BOLD}Slowest parser calls{RESET}")
            for seconds, tier, sender, subject in self.slow_parser_calls:
                print(f"  {seconds:>6.2f}s  {self._safe(tier, 24)}  {self._safe(sender, 30)} | {self._safe(subject, 48)}")
        print(f"{BOLD}{'=' * 72}{RESET}\n")

    def as_dict(self) -> dict[str, dict[str, int | float]]:
        return {tier: dict(counter) for tier, counter in self.tier_stats.items()}

    def _clear_line(self) -> None:
        sys.stdout.write("\r" + " " * 180 + "\r")
        sys.stdout.flush()

    def _safe(self, value: Any, limit: int) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ")
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."
