import random
import time
from typing import Callable, Tuple, Type


def retry_with_backoff(
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    max_attempts: int = 3,
    base_delay: float = 0.2,
) -> Callable:
    """
    指数退避重试装饰器工厂（带参数的装饰器）。

    输入：
        exceptions: 触发重试的异常类型元组，默认 (Exception,)
        max_attempts: 最大重试次数（含首次），默认3
        base_delay: 基础退避时间（秒），默认0.2

    输出：
        decorator: 可用于装饰函数的装饰器。

    关键逻辑：
        - 对指定异常进行指数退避重试，叠加随机抖动。
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    attempt += 1
                    if attempt >= max_attempts:
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    delay += random.uniform(0, base_delay)
                    time.sleep(delay)

        return wrapper

    return decorator