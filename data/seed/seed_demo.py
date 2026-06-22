from __future__ import annotations

from data.seed.seed_synthetic_data import main as seed_synthetic_data
from data.seed.seed_users import main as seed_users


def main() -> None:
    seed_users()
    seed_synthetic_data()


if __name__ == "__main__":
    main()
