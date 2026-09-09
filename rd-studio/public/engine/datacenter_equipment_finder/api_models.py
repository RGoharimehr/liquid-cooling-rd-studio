from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator, model_validator


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def query_payload(query: dict[str, list[str]], *keys: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key in keys:
        value = first_query_value(query, key)
        if value is not None:
            payload[key] = value
    return payload


class _BaseRequestModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class ComponentsQuery(_BaseRequestModel):
    category: str | None = None
    component_subtype: str | None = None
    brand: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class FindQuery(_BaseRequestModel):
    category: str | None = None
    component_subtype: str | None = None
    brand: str | None = None
    size_mm: float | None = None
    connection_size_mm: float | None = None
    connection_size_inch: float | None = None
    cv: float | None = None
    kv: float | None = None
    capacity_kw: float | None = None
    capacity_tons: float | None = None
    required_pressure_bar: float | None = None
    required_temperature_c: float | None = None
    top_n: int = Field(default=5, ge=1, le=100)

    @field_validator(
        "size_mm",
        "connection_size_mm",
        "connection_size_inch",
        "cv",
        "kv",
        "capacity_kw",
        "capacity_tons",
        "required_pressure_bar",
    )
    @classmethod
    def _non_negative(cls, value: float | None, info: ValidationInfo) -> float | None:
        if value is not None and value < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return value

    @model_validator(mode="after")
    def _cross_validate(self) -> "FindQuery":
        if self.cv is not None and self.kv is not None:
            raise ValueError("Provide either cv or kv, not both")
        if (self.category or "").lower() in {"cdu", "chiller", "filter_dryer"} and (
            self.cv is not None or self.kv is not None
        ):
            raise ValueError(f"Cv/Kv inputs are not applicable for category '{self.category}'")
        return self


class AssistantRequest(_BaseRequestModel):
    query: str
    mode: Literal["local", "remote", "hybrid"] = "hybrid"

    @field_validator("query")
    @classmethod
    def _query_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must be a non-empty string")
        return value


class CompatibilityRequest(_BaseRequestModel):
    part_numbers: list[str]
    max_connection_time: float | None = None
    required_material: str | None = None
    required_connection_standard: str | None = None
    required_coolant: str | None = None
    required_pressure_bar: float | None = None
    required_temperature_c: float | None = None

    @field_validator("part_numbers")
    @classmethod
    def _part_numbers_are_strings(cls, value: list[Any]) -> list[str]:
        if not all(isinstance(part, str) for part in value):
            raise ValueError("part_numbers must be a list of strings")
        return [part.strip() for part in value if part.strip()]

    @field_validator("max_connection_time")
    @classmethod
    def _non_negative_time(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("max_connection_time must be non-negative")
        return value


def validation_message(exc: ValidationError) -> str:
    first_error = exc.errors()[0]
    return str(first_error.get("msg", "invalid request"))


class DutyItem(_BaseRequestModel):
    tag: str | None = None
    category: str | None = None
    component_subtype: str | None = None
    brand: str | None = None
    required_cv: float | None = None
    required_kv: float | None = None
    required_capacity_kw: float | None = None
    minimum_size_mm: float | None = None
    connection_size_mm: float | None = None
    connection_size_inch: float | None = None
    required_pressure_bar: float | None = None
    required_temperature_c: float | None = None


class SelectRequest(_BaseRequestModel):
    items: list[DutyItem]
    top_n: int = Field(default=3, ge=1, le=50)
