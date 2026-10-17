import json
import io
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app import server as app


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_path = app.DB_PATH
        app.DB_PATH = str(Path(self.temp.name) / 'test.sqlite3')
        app.initialize(seed=False)

    def tearDown(self):
        app.DB_PATH = self.previous_path
        self.temp.cleanup()

    def card(self, mode='daily', weekdays=None, last='2026-10-12', current=0, target=100, step=1):
        with app.database() as db:
            return db.execute('INSERT INTO cards (title,description,target,current,unit,mode,weekdays,step,color,icon,last_date,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                              ('Goal', 'Description', target, current, 'steps', mode, json.dumps(weekdays or []), step, 'blue', 'sparkles', last, last)).lastrowid

    def value(self, card_id):
        with app.database() as db:
            return dict(db.execute('SELECT * FROM cards WHERE id=?', (card_id,)).fetchone())

    def test_daily_catch_up_is_idempotent_and_capped(self):
        card = self.card(current=2, target=10, step=3)
        app.catch_up(date(2026, 10, 14))
        self.assertEqual(self.value(card)['current'], 8)
        app.catch_up(date(2026, 10, 14))
        self.assertEqual(self.value(card)['current'], 8)
        app.catch_up(date(2026, 10, 20))
        self.assertEqual(self.value(card)['current'], 10)

    def test_tuesday_wednesday_schedule_and_long_catch_up(self):
        card = self.card(mode='weekdays', weekdays=[1, 2])
        app.catch_up(date(2026, 10, 15))
        self.assertEqual(self.value(card)['current'], 2)
        app.catch_up(date(2026, 10, 26))
        self.assertEqual(self.value(card)['current'], 4)
        app.catch_up(date(2026, 10, 27))
        self.assertEqual(self.value(card)['current'], 5)

    def test_manual_cards_do_not_advance(self):
        card = self.card(mode='manual')
        app.catch_up(date(2030, 1, 1))
        self.assertEqual(self.value(card)['current'], 0)

    def test_concurrent_schedule_checks_do_not_duplicate(self):
        card = self.card()
        threads = [threading.Thread(target=app.catch_up, args=(date(2026, 10, 15),)) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(self.value(card)['current'], 3)
        with app.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM activity').fetchone()[0], 1)

    def test_validation_rejects_invalid_goals_and_schedules(self):
        for changes in [{'target': 0}, {'current': 40}, {'step': 0}, {'mode':'weekdays', 'weekdays':[]}, {'weekdays':[7]}, {'target':True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                app.validate({'title':'Test','target':30, **changes})

    def test_seed_cards(self):
        Path(app.DB_PATH).unlink()
        app.initialize()
        with app.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cards').fetchone()[0], 6)
        app.initialize()
        with app.database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM cards').fetchone()[0], 6)

    def test_live_calendar_defaults_and_leap_year(self):
        widgets = app.calendar_cards(datetime(2024, 2, 29, 12))
        self.assertEqual([c['period'] for c in widgets], ['day', 'week', 'month', 'year'])
        self.assertEqual([c['cells'] for c in widgets], [24, 7, 29, 366])
        day, week, month, year = widgets
        self.assertEqual(datetime.fromtimestamp(week['start'] / 1000).weekday(), 0)
        self.assertEqual(datetime.fromtimestamp(month['end'] / 1000), datetime(2024, 3, 1))
        self.assertEqual(datetime.fromtimestamp(year['end'] / 1000), datetime(2025, 1, 1))
        self.assertEqual((datetime(2024, 2, 29, 12).timestamp()*1000-day['start']) / (day['end']-day['start']), .5)
        january = app.calendar_cards(datetime(2025, 1, 1))
        self.assertEqual(january[-1]['cells'], 365)
        self.assertEqual(january[-1]['start'], datetime(2025, 1, 1).timestamp()*1000)
        december = app.calendar_cards(datetime(2026, 12, 31, 23, 59))
        self.assertEqual(datetime.fromtimestamp(december[2]['end']/1000), datetime(2027, 1, 1))

    def test_completed_cards_move_to_archive_and_can_be_reopened(self):
        manual = self.card(mode='manual', current=100)
        automatic = self.card(current=99)
        data = app.dashboard()
        self.assertEqual(data['cards'], [])
        self.assertEqual({c['id'] for c in data['archived']}, {manual, automatic})
        self.assertEqual(len(data['calendar']), 4)
        with app.database() as db:
            db.execute('UPDATE cards SET current=90 WHERE id=?', (manual,))
        app.initialize(seed=False)
        data = app.dashboard()
        self.assertEqual([c['id'] for c in data['cards']], [manual])
        self.assertEqual([c['id'] for c in data['archived']], [automatic])

    def request(self, method, path, body=None):
        # Exercise the real HTTP handler without opening a network socket.
        # This also runs in restricted environments that prohibit listeners.
        payload = json.dumps(body).encode() if body is not None else b''
        raw = f'{method} {path} HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n'.encode() + payload
        output = bytearray()
        socket = SimpleNamespace(makefile=lambda *args: io.BytesIO(raw), sendall=output.extend)
        app.Handler(socket, ('127.0.0.1', 12345), SimpleNamespace())
        headers, content = bytes(output).split(b'\r\n\r\n', 1)
        status = int(headers.split(b' ')[1])
        return status, json.loads(content) if path.startswith('/api') else content

    def test_http_create_adjust_edit_delete_and_persist(self):
        request = self.request
        self.assertEqual(request('GET', '/')[0], 200)
        self.assertEqual(request('GET', '/static/app.js')[0], 200)
        values = {'title':'HTTP goal', 'description':'Test', 'target':3, 'step':2, 'mode':'manual'}
        status, result = request('POST', '/api/cards', values)
        self.assertEqual(status, 201)
        card_id = result['id']
        for _ in range(3):
            self.assertEqual(request('POST', f'/api/cards/{card_id}/adjust', {'direction':1})[0], 200)
        self.assertEqual(self.value(card_id)['current'], 3)
        for _ in range(3):
            request('POST', f'/api/cards/{card_id}/adjust', {'direction':-1})
        self.assertEqual(self.value(card_id)['current'], 0)
        values.update(mode='weekdays', weekdays=[1,2], current=1)
        self.assertEqual(request('PUT', f'/api/cards/{card_id}', values)[0], 200)
        self.assertEqual(request('POST', f'/api/cards/{card_id}/adjust', {'direction':1})[0], 400)
        app.initialize(seed=False)
        self.assertEqual(request('GET', '/api/cards')[1]['cards'][0]['current'], 1)
        self.assertEqual(request('DELETE', f'/api/cards/{card_id}', {})[0], 200)
        self.assertEqual(request('GET', '/api/cards')[1]['cards'], [])
        self.assertEqual(request('DELETE', f'/api/cards/{card_id}', {})[0], 404)
        app.initialize()
        self.assertEqual(request('GET', '/api/cards')[1]['cards'], [])

    def test_date_progress_boundaries_and_leap_day(self):
        self.assertEqual(app.date_progress('2024-02-28', '2024-03-01', date(2024, 2, 27)), (2, 0))
        self.assertEqual(app.date_progress('2024-02-28', '2024-03-01', date(2024, 2, 28)), (2, 0))
        self.assertEqual(app.date_progress('2024-02-28', '2024-03-01', date(2024, 2, 29)), (2, 1))
        self.assertEqual(app.date_progress('2024-02-28', '2024-03-01', date(2024, 3, 1)), (2, 2))
        self.assertEqual(app.date_progress('2024-02-28', '2024-03-01', date(2030, 1, 1)), (2, 2))

    def test_invalid_date_ranges(self):
        for start, end in [(None, None), ('2026-02-30', '2026-03-10'), ('2026-10-20', '2026-10-20'), ('2026-10-21', '2026-10-20'), ('20261001', '2026-10-20'), (123, '2026-10-20')]:
            with self.subTest(start=start, end=end):
                status, result = self.request('POST', '/api/cards', {'title':'Date goal', 'mode':'date', 'start_date':start, 'end_date':end})
                self.assertEqual(status, 400)
                self.assertIn('date', result['error'])

    def test_date_card_create_edit_archive_and_conversion(self):
        today = date.today()
        values = {'title':'Date goal','mode':'date', 'start_date':(today-timedelta(days=5)).isoformat(), 'end_date':(today+timedelta(days=5)).isoformat()}
        status, result = self.request('POST', '/api/cards', values)
        self.assertEqual(status, 201)
        card_id = result['id']
        card = self.request('GET', '/api/cards')[1]['cards'][0]
        self.assertEqual((card['current'], card['target'], card['unit']), (5, 10, 'days'))
        self.assertEqual(self.request('POST', f'/api/cards/{card_id}/adjust', {'direction':1})[0], 400)
        app.initialize(seed=False)
        self.assertEqual(self.value(card_id)['start_date'], values['start_date'])
        app.catch_up(today+timedelta(days=5))
        self.assertEqual(self.value(card_id)['current'], 10)
        app.catch_up(today+timedelta(days=5))
        self.assertEqual(self.value(card_id)['current'], 10)
        # An end date that has passed is archived immediately after saving.
        values['end_date'] = today.isoformat()
        self.assertEqual(self.request('PUT', f'/api/cards/{card_id}', values)[0], 200)
        data = self.request('GET', '/api/cards')[1]
        self.assertEqual(data['cards'], [])
        self.assertEqual(data['archived'][0]['id'], card_id)
        values['end_date'] = (today+timedelta(days=10)).isoformat()
        self.request('PUT', f'/api/cards/{card_id}', values)
        self.assertEqual(len(self.request('GET', '/api/cards')[1]['cards']), 1)
        values.update(mode='manual', target=20, current=3)
        self.request('PUT', f'/api/cards/{card_id}', values)
        card = self.value(card_id)
        self.assertEqual((card['current'], card['target'], card['start_date'], card['end_date']), (3, 20, None, None))

    def test_existing_database_migrates_without_losing_cards(self):
        card_id = self.card(mode='manual', current=7)
        with app.database() as db:
            db.execute('ALTER TABLE cards DROP COLUMN start_date')
            db.execute('ALTER TABLE cards DROP COLUMN end_date')
        app.initialize(seed=False)
        app.initialize(seed=False)
        card = self.value(card_id)
        self.assertEqual(card['current'], 7)
        self.assertIsNone(card['start_date'])
        self.assertIsNone(card['end_date'])


if __name__ == '__main__':
    unittest.main()
