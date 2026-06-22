"""SQL catalog package."""

from backend.app.catalog.registry import CATALOG, CATALOG_BY_ID, CatalogEntry, CatalogParam, catalog_prompt_entries
from backend.app.catalog.validate import CatalogExecutionPlan, CatalogValidationError, execute_catalog_plan, validate_catalog_selection

__all__ = [
    "CATALOG",
    "CATALOG_BY_ID",
    "CatalogEntry",
    "CatalogExecutionPlan",
    "CatalogParam",
    "CatalogValidationError",
    "catalog_prompt_entries",
    "execute_catalog_plan",
    "validate_catalog_selection",
]
