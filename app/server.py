"""One Progress: a dependency-free Python + SQLite web application."""
import argparse
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
DB_PATH = os.environ.get('PROGRESS_DB', str(ROOT.parent / 'progress.sqlite3'))
COLORS = {'blue', 'purple', 'green', 'orange', 'pink', 'teal'}
CARD_INPUT_COLUMNS = 'title,description,target,current,unit,mode,weekdays,step,color,icon,start_date,end_date'


@contextmanager
def database():
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(seed=True):
    with database() as db:
        is_new = not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cards'").fetchone()
        db.execute('''CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
            target INTEGER NOT NULL, current INTEGER NOT NULL, unit TEXT NOT NULL,
            mode TEXT NOT NULL, weekdays TEXT NOT NULL, step INTEGER NOT NULL,
            color TEXT NOT NULL, icon TEXT NOT NULL, last_date TEXT NOT NULL,
            created_at TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY, card_id INTEGER, title TEXT NOT NULL,
            amount INTEGER NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL)''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(cards)')}
        for column in ('start_date', 'end_date'):
            if column not in columns:
                db.execute(f'ALTER TABLE cards ADD COLUMN {column} TEXT')
        if seed and is_new:
            samples = [
                ('Read 12 books', 'A few pages today. A new perspective tomorrow.', 12, 7, 'books', 'manual', [], 1, 'purple', 'book'),
                ('Morning movement', 'Make a little room for a healthier you.', 30, 18, 'sessions', 'weekdays', [1, 3, 5], 1, 'orange', 'activity'),
                ('Learn something new', 'One small lesson, every single day.', 100, 42, 'lessons', 'daily', [], 1, 'blue', 'sparkles'),
                ('The travel fund', 'A little closer to somewhere new.', 2000, 1250, 'dollars', 'manual', [], 50, 'green', 'plane'),
                ('Build my portfolio', 'Create work that feels like me.', 8, 3, 'projects', 'manual', [], 1, 'pink', 'layers'),
                ('A mindful month', 'Pause. Breathe. Come back to the present.', 30, 30, 'days', 'daily', [], 1, 'teal', 'sun'),
            ]
            for title, desc, target, current, unit, mode, days, step, color, icon in samples:
                db.execute('INSERT INTO cards (title,description,target,current,unit,mode,weekdays,step,color,icon,last_date,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (title, desc, target, current, unit, mode, json.dumps(days), step, color, icon, date.today().isoformat(), datetime.now().isoformat()))


def catch_up(today=None):
    """Apply each eligible local calendar date once, atomically across workers."""
    today = today or date.today()
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        for card in db.execute("SELECT * FROM cards WHERE mode != 'manual'").fetchall():
            if card['mode'] == 'date':
                target, current = date_progress(card['start_date'], card['end_date'], today)
                db.execute('UPDATE cards SET target=?,current=?,last_date=? WHERE id=?',
                           (target, current, today.isoformat(), card['id']))
                continue
            last = date.fromisoformat(card['last_date'])
            if last >= today:
                continue
            days = json.loads(card['weekdays'])
            elapsed = (today - last).days
            if card['mode'] == 'daily':
                count = elapsed
            else:
                weeks, remainder = divmod(elapsed, 7)
                count = weeks * len(days) + sum((last + timedelta(days=i)).weekday() in days for i in range(1, remainder + 1))
            amount = min(card['target'] - card['current'], count * card['step'])
            db.execute('UPDATE cards SET current=current+?, last_date=? WHERE id=?', (amount, today.isoformat(), card['id']))
            if amount:
                db.execute('INSERT INTO activity VALUES(NULL,?,?,?,?,?)', (card['id'], card['title'], amount, 'automatic', datetime.now().isoformat()))


def date_progress(start_value, end_value, today=None):
    try:
        start = date.fromisoformat(start_value)
        end = date.fromisoformat(end_value)
        if start.isoformat() != start_value or end.isoformat() != end_value:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('Choose valid start and end dates (YYYY-MM-DD).') from None
    if end <= start:
        raise ValueError('End date must be after the start date.')
    target = (end - start).days
    return target, max(0, min(target, ((today or date.today()) - start).days))


def validate(data):
    def integer(key, low, high, default=None):
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f'{key.capitalize()} must be a whole number between {low} and {high}.')
        return value
    def text_value(key, limit, default=''):
        value = data.get(key, default)
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError(f'{key.capitalize()} must be at most {limit} characters.')
        return value.strip()
    title = text_value('title', 80)
    if not title:
        raise ValueError('Give your progress card a title.')
    mode = data.get('mode', 'manual')
    start_date = end_date = None
    if mode == 'date':
        start_date, end_date = data.get('start_date'), data.get('end_date')
        target, current = date_progress(start_date, end_date)
        unit, step = 'days', 1
    else:
        target = integer('target', 1, 1000000000)
        current = integer('current', 0, target, 0)
        unit = text_value('unit', 24, 'steps') or 'steps'
        step = integer('step', 1, 1000000000, 1)
    days = data.get('weekdays', [])
    if mode not in {'manual', 'daily', 'weekdays', 'date'}:
        raise ValueError('Choose a valid update schedule.')
    if not isinstance(days, list) or any(type(d) is not int or d not in range(7) for d in days):
        raise ValueError('Choose valid weekdays.')
    if mode == 'weekdays' and not days:
        raise ValueError('Choose at least one weekday.')
    color = data.get('color', 'blue')
    if color not in COLORS:
        raise ValueError('Choose a valid color.')
    icon = data.get('icon', 'sparkles')
    if icon not in {'book', 'activity', 'sparkles', 'plane', 'layers', 'sun'}:
        icon = 'sparkles'
    return (title, text_value('description', 240), target, current, unit, mode, json.dumps(sorted(set(days))) if mode == 'weekdays' else '[]', step, color, icon, start_date, end_date)


def calendar_cards(now=None):
    """Live, recurring calendar widgets in the server's local timezone."""
    now = now or datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = midnight.replace(day=1)
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    week_start = midnight - timedelta(days=now.weekday())
    periods = [
        ('day', 'Today', midnight, midnight + timedelta(days=1), 24),
        ('week', 'This week', week_start, week_start + timedelta(days=7), 7),
        ('month', 'This month', month_start, month_end, (month_end - month_start).days),
        ('year', 'This year', midnight.replace(month=1, day=1), midnight.replace(year=now.year + 1, month=1, day=1), (date(now.year + 1, 1, 1) - date(now.year, 1, 1)).days),
    ]
    return [dict(period=period, title=title, start=start.timestamp() * 1000,
                 end=end.timestamp() * 1000, cells=cells)
            for period, title, start, end, cells in periods]


def dashboard():
    catch_up()
    with database() as db:
        cards = [dict(r) for r in db.execute('SELECT * FROM cards ORDER BY id')]
    for card in cards:
        card['weekdays'] = json.loads(card['weekdays'])
    return {
        'cards': [c for c in cards if c['current'] < c['target']],
        'archived': [c for c in cards if c['current'] >= c['target']],
        'calendar': calendar_cards(),
        'server_now': datetime.now().timestamp() * 1000,
        'today': date.today().isoformat(),
    }


class Handler(BaseHTTPRequestHandler):
    def reply(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/cards':
            return self.reply(dashboard())
        files = {'/': ('templates/index.html', 'text/html; charset=utf-8'), '/static/app.js': ('static/app.js', 'text/javascript'), '/static/animation.js': ('static/animation.js', 'text/javascript'), '/static/theme.js': ('static/theme.js', 'text/javascript'), '/static/style.css': ('static/style.css', 'text/css')}
        if path not in files:
            return self.reply({'error': 'Not found'}, 404)
        filename, mime = files[path]
        body = (ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.mutate()

    def do_PUT(self):
        self.mutate()

    def do_DELETE(self):
        self.mutate()

    def mutate(self):
        # Browsers must use a same-origin JSON request for all mutations.
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.reply({'error': 'Cross-site request rejected.'}, 403)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply({'error': 'Expected JSON.'}, 415)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                raise ValueError('Invalid request size.')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Expected an object.')
            parts = urlparse(self.path).path.strip('/').split('/')
            if parts[:2] != ['api', 'cards'] or len(parts) not in (2, 3, 4):
                return self.reply({'error': 'Not found'}, 404)
            catch_up()
            now = datetime.now().isoformat()
            with database() as db:
                if len(parts) == 2 and self.command == 'POST':
                    values = validate(data)
                    cursor = db.execute(f'INSERT INTO cards ({CARD_INPUT_COLUMNS},last_date,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (*values, date.today().isoformat(), now))
                    return self.reply({'id': cursor.lastrowid}, 201)
                if len(parts) < 3 or not parts[2].isdigit():
                    return self.reply({'error': 'Not found'}, 404)
                db.execute('BEGIN IMMEDIATE')
                card = db.execute('SELECT * FROM cards WHERE id=?', (parts[2],)).fetchone()
                if card is None:
                    return self.reply({'error': 'Card not found.'}, 404)
                if len(parts) == 4 and parts[3] == 'adjust' and self.command == 'POST':
                    if card['mode'] != 'manual':
                        raise ValueError('This card updates automatically. Edit its schedule to update manually.')
                    delta = data.get('direction')
                    if type(delta) is not int or delta not in (-1, 1):
                        raise ValueError('Direction must be -1 or 1.')
                    current = max(0, min(card['target'], card['current'] + delta * card['step']))
                    amount = current - card['current']
                    db.execute('UPDATE cards SET current=? WHERE id=?', (current, card['id']))
                    if amount:
                        db.execute('INSERT INTO activity VALUES(NULL,?,?,?,?,?)', (card['id'], card['title'], amount, 'manual', now))
                elif len(parts) == 3 and self.command == 'PUT':
                    values = validate(data)
                    db.execute('UPDATE cards SET title=?,description=?,target=?,current=?,unit=?,mode=?,weekdays=?,step=?,color=?,icon=?,start_date=?,end_date=?,last_date=? WHERE id=?', (*values, date.today().isoformat(), card['id']))
                elif len(parts) == 3 and self.command == 'DELETE':
                    db.execute('DELETE FROM cards WHERE id=?', (card['id'],))
                else:
                    return self.reply({'error': 'Not found'}, 404)
            return self.reply({'ok': True})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.reply({'error': str(exc)}, 400)


def scheduler(stop):
    while not stop.wait(30):
        try:
            catch_up()
        except sqlite3.Error as exc:
            print(f'Schedule retry: {exc}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8000')))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--demo', action='store_true', help='Add example goals to a new database')
    parser.add_argument('--no-demo', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    initialize(seed=args.demo and not args.no_demo)
    catch_up()
    stop = threading.Event()
    threading.Thread(target=scheduler, args=(stop,), daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'One Progress is ready at http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
