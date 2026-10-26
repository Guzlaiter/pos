"""Application context: one place that wires services together."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import AppPaths
from .database import Database
from .services.catalog import CatalogService
from .services.legacy import LegacyImportService
from .services.payments import PaymentMethodService
from .services.sales import SalesService
from .services.settings import SettingsService
from .services.shifts import ShiftService
from .services.stats import StatsService
from .services.users import UserService


@dataclass
class AppContext:
    paths: AppPaths
    db: Database
    settings: SettingsService
    users: UserService
    catalog: CatalogService
    payments: PaymentMethodService
    shifts: ShiftService
    sales: SalesService
    stats: StatsService
    legacy: LegacyImportService
    startup_notes: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, paths: AppPaths, db: Database) -> "AppContext":
        settings = SettingsService(db)
        catalog = CatalogService(db, settings)
        shifts = ShiftService(db)
        return cls(
            paths=paths,
            db=db,
            settings=settings,
            users=UserService(db),
            catalog=catalog,
            payments=PaymentMethodService(db),
            shifts=shifts,
            sales=SalesService(db, catalog, shifts),
            stats=StatsService(db, shifts, catalog),
            legacy=LegacyImportService(db),
        )

    @property
    def currency(self) -> str:
        return self.settings.currency
