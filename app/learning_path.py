"""Sequential course progression. Only completed lessons unlock the next step.

Pure helpers: the same ordered curriculum is used by server endpoints and UI.
Legacy completed lessons remain viewable even when an earlier gap remains.
"""
from .curriculum import MODULES, LESSONS

ORDER = tuple(lesson["id"] for module in MODULES for lesson in module["lessons"])
INDEX = {lesson_id: position for position, lesson_id in enumerate(ORDER)}


def completed_lessons(done):
    return {lesson_id for kind, lesson_id in done
            if kind == "lesson" and lesson_id in INDEX}


def next_lesson(done):
    finished = completed_lessons(done)
    return next((lesson_id for lesson_id in ORDER if lesson_id not in finished), None)


def unlocked_lessons(done):
    finished = completed_lessons(done)
    current = next_lesson(done)
    return finished | ({current} if current else set())


def is_unlocked(lesson_id, done):
    if lesson_id not in INDEX:
        return False
    return lesson_id in unlocked_lessons(done)


def prerequisite(lesson_id, done):
    """The earliest incomplete prerequisite, or None if accessible."""
    if lesson_id not in INDEX or is_unlocked(lesson_id, done):
        return None
    finished = completed_lessons(done)
    return next((old for old in ORDER[:INDEX[lesson_id]] if old not in finished), None)


def module_state(done):
    available = unlocked_lessons(done)
    finished = completed_lessons(done)
    out = {}
    for module in MODULES:
        lessons = module["lessons"]
        ids = [lesson["id"] for lesson in lessons]
        done_count = sum(lesson_id in finished for lesson_id in ids)
        out[module["id"]] = {
            "unlocked": any(lesson_id in available for lesson_id in ids),
            "completed": bool(ids) and done_count == len(ids),
            "done_count": done_count,
            "total": len(ids)
        }
    return out
