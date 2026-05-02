from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class KeysetPage:
    items: list
    next_cursor: str | None
    prev_cursor: str | None
    has_next: bool
    has_prev: bool


def paginate_keyset(queryset, *, page_size: int = 50, after: str | None = None, before: str | None = None) -> KeysetPage:
    if after and before:
        before = None

    if before:
        rows = list(
            queryset.filter(id__lt=int(before)).order_by("-id")[: page_size + 1]
        )
        has_prev = len(rows) > page_size
        if has_prev:
            rows = rows[:page_size]
        rows.reverse()
        items = rows
        has_next = True if items else False
    else:
        filtered = queryset
        if after:
            filtered = filtered.filter(id__gt=int(after))
        rows = list(filtered.order_by("id")[: page_size + 1])
        has_next = len(rows) > page_size
        if has_next:
            rows = rows[:page_size]
        items = rows
        has_prev = bool(after)

    next_cursor = str(items[-1].id) if items and has_next else None
    prev_cursor = str(items[0].id) if items and has_prev else None

    return KeysetPage(
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
    )
