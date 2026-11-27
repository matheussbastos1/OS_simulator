"""Deterministic logical simulation clock operating strictly in integer milliseconds."""

from typing import Dict


class LogicalClock:
    """Simulated monotonic logical clock (strict integer milliseconds, zero wall-clock usage)."""

    def __init__(self, initial_ms: int = 0) -> None:
        self._now_ms: int = self._validate_non_negative_int(initial_ms, "initial_ms")

    @staticmethod
    def _validate_non_negative_int(value: int, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field_name} deve ser um número inteiro em milissegundos (recebido: {value!r}).")
        if value < 0:
            raise ValueError(f"{field_name} não pode ser negativo (recebido: {value}).")
        return value

    @property
    def now_ms(self) -> int:
        """Current simulated logical time in milliseconds."""
        return self._now_ms

    def advance_by(self, delta_ms: int) -> int:
        """Advance logical clock forward by delta_ms >= 0 and return the new time."""
        delta = self._validate_non_negative_int(delta_ms, "delta_ms")
        self._now_ms += delta
        return self._now_ms

    def advance_to(self, target_ms: int) -> int:
        """Advance logical clock to target_ms >= now_ms and return the new time."""
        target = self._validate_non_negative_int(target_ms, "target_ms")
        if target < self._now_ms:
            raise ValueError(
                f"Salto retroativo inválido no relógio lógico: {target} ms < atual {self._now_ms} ms."
            )
        self._now_ms = target
        return self._now_ms

    def reset(self, initial_ms: int = 0) -> None:
        """Reset logical clock to initial_ms (defaults to 0)."""
        self._now_ms = self._validate_non_negative_int(initial_ms, "initial_ms")

    def to_dict(self) -> Dict[str, int]:
        """Serialize clock state."""
        return {"now_ms": self._now_ms}

    def __repr__(self) -> str:
        return f"<LogicalClock now_ms={self._now_ms}>"
