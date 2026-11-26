from math import ceil

from .memory import REGIONS

# KiB floors avoid classifying a few pages on a small stack as a large change.
FLOOR = {"code": 512, "heap": 512, "stack": 128, "anon": 1024, "other": 512, "total": 1536}


def limits(samples, margin, danger):
    if not samples:
        raise ValueError("정상 표본이 없습니다.")
    result = {}
    for key in REGIONS:
        low = min(s[key] for s in samples)
        high = max(s[key] for s in samples)
        limit = high + max(FLOOR[key], high - low, ceil(high * margin))
        result[key] = {
            "min": low,
            "max": high,
            "limit": limit,
            "danger": limit + max(FLOOR[key], ceil(limit * danger)),
        }
    return result


def classify(sample, bounds):
    issues = {}
    for key, value in sample.items():
        limit, danger = bounds[key]["limit"], bounds[key]["danger"]
        if value > limit:
            issues[key] = {
                "level": "danger" if value > danger else "warning",
                "current": value,
                "limit": limit,
                "danger": danger,
                "excess": value - limit,
                "percent": round((value - limit) * 100 / limit, 2),
            }
    return issues
