from dataclasses import dataclass

GIB = 1024**3


class CapacityUnavailable(RuntimeError):
    def __init__(self, *, free_bytes: int, required_free_bytes: int) -> None:
        super().__init__(
            "Insufficient filesystem capacity: "
            f"free={free_bytes}, required={required_free_bytes}"
        )
        self.free_bytes = free_bytes
        self.required_free_bytes = required_free_bytes


@dataclass(frozen=True)
class CapacityReservation:
    peak_bytes: int
    reserve_bytes: int
    remaining_bytes: int


@dataclass(frozen=True)
class CapacityGuard:
    total_bytes: int
    free_bytes: int
    outstanding_reservations: int = 0
    reserve_min_bytes: int = 10 * GIB
    reserve_fraction: float = 0.20

    @property
    def reserve_bytes(self) -> int:
        return max(self.reserve_min_bytes, int(self.total_bytes * self.reserve_fraction))

    def reserve(self, *, peak_bytes: int) -> CapacityReservation:
        if peak_bytes < 0 or self.outstanding_reservations < 0:
            raise ValueError("Capacity reservations cannot be negative")
        required = self.reserve_bytes + self.outstanding_reservations + peak_bytes
        if self.free_bytes < required:
            raise CapacityUnavailable(
                free_bytes=self.free_bytes,
                required_free_bytes=required,
            )
        return CapacityReservation(
            peak_bytes=peak_bytes,
            reserve_bytes=self.reserve_bytes,
            remaining_bytes=self.free_bytes - self.outstanding_reservations - peak_bytes,
        )
