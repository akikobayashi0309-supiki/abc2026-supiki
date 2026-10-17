from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

# Jobs run on a shared pool after the request returns (Cloud Run keeps CPU allocated).
# Several jobs of a market-comparison batch run side by side.
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="job")


def get_runner() -> Callable[[Callable[[], None]], None]:
    return lambda fn: _pool.submit(fn)
