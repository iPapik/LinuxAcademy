import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / 'content' / 'curriculum.json'
with SOURCE.open(encoding='utf-8') as fh:
    EXISTING_MODULES = json.load(fh)
# Extension courses are separate from the original generator.
def load_extra(filename):
    with (SOURCE.parent / filename).open(encoding='utf-8') as stream:
        return json.load(stream)
MODULES = (load_extra('foundations.json') + EXISTING_MODULES
           + load_extra('distros.json'))
LESSONS = {l['id']:l for m in MODULES for l in m['lessons']}
TASKS = {t['id']: dict(t, lesson_id=l['id']) for l in LESSONS.values() for t in l.get('tasks',[])}


def public_lesson(lesson):
    """Never send validation scripts or preparatory commands to browsers."""
    obj = dict(lesson)
    obj['tasks'] = [{k:v for k,v in t.items() if k not in ('setup','checks')}
                    for t in lesson.get('tasks',[])]
    obj['quiz'] = [{k:v for k,v in q.items() if k != 'answer'} for q in lesson.get('quiz',[])]
    return obj


def stats():
    return {'modules':len(MODULES), 'lessons':len(LESSONS), 'tasks':len(TASKS),
            'questions':sum(len(l.get('quiz',[])) for l in LESSONS.values())}
