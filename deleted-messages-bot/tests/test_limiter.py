from app.limiter import RateLimiter


class Clock:
    """Часы, которые двигает только сон: тест не ждёт по-настоящему."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def limiter(clock: Clock, rate: float = 2.0, burst: float = 2.0) -> RateLimiter:
    return RateLimiter(rate=rate, burst=burst, clock=clock, sleep=clock.sleep)


async def test_запас_расходуется_без_ожидания():
    clock = Clock()
    bucket = limiter(clock)

    await bucket.acquire()
    await bucket.acquire()

    assert clock.slept == []


async def test_дальше_приходится_ждать():
    clock = Clock()
    bucket = limiter(clock)

    for _ in range(3):
        await bucket.acquire()

    # Запас кончился: при двух проверках в секунду третья ждёт полсекунды.
    assert clock.slept == [0.5]
    assert clock.now == 0.5


async def test_пауза_после_429_держит_все_проверки():
    clock = Clock()
    bucket = limiter(clock)

    bucket.pause(10)
    assert bucket.paused_for == 10

    await bucket.acquire()

    assert clock.slept == [10]
    assert bucket.paused_for == 0


async def test_частота_выдерживается_на_длинной_серии():
    clock = Clock()
    bucket = limiter(clock, rate=2.0, burst=1.0)

    for _ in range(21):
        await bucket.acquire()

    # Один токен в запасе плюс двадцать по две в секунду — ровно десять секунд.
    assert clock.now == 10.0


async def test_слишком_маленькая_частота_не_делит_на_ноль():
    clock = Clock()
    bucket = RateLimiter(rate=0, clock=clock, sleep=clock.sleep)

    await bucket.acquire()
    await bucket.acquire()

    assert bucket.rate > 0
    assert clock.now > 0
