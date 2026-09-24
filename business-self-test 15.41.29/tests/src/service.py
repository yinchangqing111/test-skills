#!/usr/bin/env python3
"""Deliberately local payment fixture. No external payment/network integration."""
import argparse
import json
import signal
import sqlite3
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Rejection(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class Store:
    def __init__(self, path, duplicate_stock_bug, credentials):
        self.path = path
        self.duplicate_stock_bug = duplicate_stock_bug
        self.credentials = credentials
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE inventory (sku TEXT PRIMARY KEY, quantity INTEGER NOT NULL);
                INSERT INTO inventory VALUES ('fixture-mug', 10);
                CREATE TABLE orders (id INTEGER PRIMARY KEY, request_key TEXT UNIQUE,
                    quantity INTEGER NOT NULL, amount_cents INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE payments (id INTEGER PRIMARY KEY, order_id INTEGER UNIQUE,
                    event_id TEXT UNIQUE, amount_cents INTEGER, mode TEXT);
                CREATE TABLE callbacks (id INTEGER PRIMARY KEY, order_id INTEGER,
                    event_id TEXT, duplicate INTEGER, applied INTEGER);
                CREATE TABLE inventory_movements (id INTEGER PRIMARY KEY, order_id INTEGER,
                    event_id TEXT, delta INTEGER);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def state(self):
        with self.connect() as db:
            db.execute('BEGIN')
            return {name: [dict(row) for row in db.execute('SELECT * FROM ' + name)]
                    for name in ('inventory', 'orders', 'payments', 'callbacks',
                                 'inventory_movements')}

    def create(self, data):
        quantity = data.get('quantity')
        key = data.get('request_key')
        if type(quantity) is not int or not 1 <= quantity <= 5:
            raise Rejection(400, 'invalid_quantity')
        if not isinstance(key, str) or not 1 <= len(key) <= 80:
            raise Rejection(400, 'invalid_request_key')
        time.sleep(0.5)  # Gives two real rapid clicks a reproducible in-flight window.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM orders WHERE request_key=?', (key,)).fetchone()
            if existing:
                if existing['quantity'] != quantity:
                    raise Rejection(409, 'idempotency_conflict')
                return dict(existing)
            cursor = db.execute('INSERT INTO orders(request_key, quantity, amount_cents) VALUES (?,?,?)',
                                (key, quantity, 500 * quantity))
            return dict(db.execute('SELECT * FROM orders WHERE id=?', (cursor.lastrowid,)).fetchone())

    def callback(self, data):
        order_id, event_id = data.get('order_id'), data.get('event_id')
        if type(order_id) is not int or not isinstance(event_id, str) or not 1 <= len(event_id) <= 80:
            raise Rejection(400, 'invalid_callback')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if not order:
                raise Rejection(404, 'order_not_found')
            event = db.execute('SELECT * FROM payments WHERE event_id=?', (event_id,)).fetchone()
            if event and event['order_id'] != order_id:
                raise Rejection(409, 'event_order_conflict')
            duplicate = order['status'] == 'paid'
            applied = not duplicate or self.duplicate_stock_bug
            if applied:
                quantity = db.execute('SELECT quantity FROM inventory').fetchone()[0]
                if quantity < order['quantity']:
                    raise Rejection(409, 'insufficient_stock')
                db.execute('UPDATE inventory SET quantity=quantity-?', (order['quantity'],))
                db.execute('INSERT INTO inventory_movements(order_id,event_id,delta) VALUES (?,?,?)',
                           (order_id, event_id, -order['quantity']))
            if not duplicate:
                db.execute('INSERT INTO payments(order_id,event_id,amount_cents,mode) VALUES (?,?,?,?)',
                           (order_id, event_id, order['amount_cents'], 'sandbox'))
                db.execute("UPDATE orders SET status='paid' WHERE id=?", (order_id,))
            db.execute('INSERT INTO callbacks(order_id,event_id,duplicate,applied) VALUES (?,?,?,?)',
                       (order_id, event_id, duplicate, applied))
            return {'order_id': order_id, 'duplicate': duplicate, 'applied': applied,
                    'event_id': event_id, 'real_charge': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duplicate-stock-bug', action='store_true')
    parser.add_argument('--double-submit-bug', action='store_true')
    parser.add_argument('--payment-credentials', choices=['sandbox', 'missing'], default='sandbox')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='order-fixture-') as directory:
        store = Store(Path(directory) / 'fixture.sqlite', args.duplicate_stock_bug,
                      args.payment_credentials)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *values):
                # Never record request bodies, headers, query strings, credentials or PII.
                pass

            def send(self, status, payload, content_type='application/json'):
                content = json.dumps(payload).encode() if content_type == 'application/json' else payload
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(content)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(content)
                print(json.dumps({'method': self.command, 'route': self.path.split('?')[0],
                                  'status': status}), flush=True)

            def do_GET(self):
                if self.path == '/':
                    page = Path(__file__).with_name('page.html').read_text()
                    page = page.replace('__DOUBLE_SUBMIT_BUG__', json.dumps(args.double_submit_bug))
                    self.send(200, page.encode(), 'text/html; charset=utf-8')
                elif self.path == '/api/state':
                    self.send(200, store.state())
                elif self.path == '/api/health':
                    self.send(200, {'mode': 'sandbox_only', 'real_charges': 0,
                                    'outbound_payment_integration': False,
                                    'credentials': args.payment_credentials})
                else:
                    self.send(404, {'error': 'not_found'})

            def do_POST(self):
                try:
                    length = int(self.headers.get('Content-Length', 0))
                    if not 0 < length <= 4096:
                        raise Rejection(400, 'invalid_body_length')
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise Rejection(400, 'invalid_body')
                    if self.path == '/api/orders':
                        result = store.create(data)
                    elif self.path == '/api/payments':
                        if data.get('mode') != 'sandbox':
                            raise Rejection(403, 'live_payment_disabled')
                        if store.credentials == 'missing':
                            raise Rejection(503, 'sandbox_credentials_missing')
                        order_id = data.get('order_id')
                        result = store.callback({'order_id': order_id,
                                                 'event_id': f'sandbox-event-{order_id}'})
                    elif self.path == '/api/callback':
                        if self.headers.get('X-Fixture-Callback') != 'local-test-only':
                            raise Rejection(401, 'callback_not_authorized')
                        result = store.callback(data)
                    else:
                        raise Rejection(404, 'not_found')
                    self.send(200, result)
                except Rejection as error:
                    self.send(error.status, {'error': error.code, 'real_charge': False})
                except (ValueError, TypeError):
                    self.send(400, {'error': 'invalid_json'})

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
        print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}',
                          'mode': 'sandbox_only'}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
