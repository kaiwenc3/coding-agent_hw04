"""计算斐波那契数列的前 n 项（从 0、1 开始）。"""

import argparse


def fibonacci(n: int) -> list[int]:
    """返回前 n 项；n 必须是非负整数。"""
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError("n 必须是整数")
    if n < 0:
        raise ValueError("n 不能为负数")

    result = []
    a, b = 0, 1
    for _ in range(n):
        result.append(a)
        a, b = b, a + b
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("n", type=int, nargs="?", default=10, help="项数，默认为 10")
    args = parser.parse_args()
    if args.n < 0:
        parser.error("项数不能为负数")
    print(fibonacci(args.n))


if __name__ == "__main__":
    main()
