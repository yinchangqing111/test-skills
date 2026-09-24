#!/usr/bin/env python3
"""Run independent HTTP oracles and optional real Chromium UI checks."""
import argparse
import contextlib
import datetime
import json
from pathlib import Path
import selectors
import shutil
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent


class Evidence:
    def __init__(self, directory):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=False)
        self.results = []

    def check(self, scenario, name, actual, expected, expected_failure=False):
        passed = actual == expected
        result = {'scenario': scenario, 'assertion': name, 'actual': actual,
                  'expected': expected, 'passed': passed,
                  'expected_failure': expected_failure,
                  'accepted': not passed if expected_failure else passed}
        self.results.append(result)
        label = 'DETECTED' if expected_failure and not passed else 'PASS' if passed else 'FAIL'
        if expected_failure and passed:
            label = 'MISSED_DEFECT'
        print(f'{label} {scenario}.{name}: actual={actual!r}, expected={expected!r}', flush=True)

    def save(self, name, data):
        (self.directory / name).write_text(json.dumps(data, indent=2) + '\n')


class Client:
    def __init__(self, url, evidence, scenario):
        self.url, self.evidence, self.scenario = url, evidence, scenario

    def request(self, path, data=None, callback_auth=False):
        headers = {'Content-Type': 'application/json'}
        if callback_auth:
            headers['X-Fixture-Callback'] = 'local-test-only'
        request = urllib.request.Request(self.url + path, headers=headers,
                                         data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, body = response.status, json.load(response)
        except urllib.error.HTTPError as error:
            status, body = error.code, json.load(error)
        # Synthetic response data only. Do not log request headers or credentials.
        with (self.evidence.directory / (self.scenario + '-http.jsonl')).open('a') as log:
            log.write(json.dumps({'method': request.get_method(), 'path': path,
                                  'status': status, 'response': body}) + '\n')
        return status, body

    def state(self):
        status, body = self.request('/api/state')
        if status != 200:
            raise RuntimeError(f'State endpoint returned {status}')
        return body


@contextlib.contextmanager
def service(evidence, scenario, *flags):
    log = (evidence.directory / (scenario + '-server.jsonl')).open('w')
    proc = subprocess.Popen([sys.executable, '-B', str(ROOT / 'src/service.py'), *flags],
                            stdout=subprocess.PIPE, stderr=log, text=True)
    reader = None
    port = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=10):
                raise RuntimeError('Fixture did not become ready within 10 seconds')
        first_line = proc.stdout.readline()
        log.write(first_line)
        log.flush()
        ready = json.loads(first_line)
        port = int(ready['url'].rsplit(':', 1)[1])

        def drain():
            for line in proc.stdout:
                log.write(line)
                log.flush()

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        yield Client(ready['url'], evidence, scenario)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if reader:
            reader.join(timeout=2)
        proc.stdout.close()
        log.close()
        evidence.check(scenario, 'service_exit', proc.returncode, 0)
        if port:
            with socket.socket() as connection:
                listening = connection.connect_ex(('127.0.0.1', port)) == 0
            evidence.check(scenario, 'listener_stopped', listening, False)


def payment_oracles(evidence, scenario, state, defect=False):
    evidence.check(scenario, 'stock_decremented_once', state['inventory'][0]['quantity'], 8, defect)
    evidence.check(scenario, 'one_payment_ledger_entry', len(state['payments']), 1)
    evidence.check(scenario, 'payment_amount_cents', state['payments'][0]['amount_cents'], 1000)
    evidence.check(scenario, 'payment_is_sandbox', state['payments'][0]['mode'], 'sandbox')
    evidence.check(scenario, 'order_paid', state['orders'][0]['status'], 'paid')
    evidence.check(scenario, 'two_callbacks_received', len(state['callbacks']), 2)
    evidence.check(scenario, 'repeat_recognized', state['callbacks'][1]['duplicate'], 1)
    evidence.check(scenario, 'repeat_has_no_effect', state['callbacks'][1]['applied'], 0, defect)
    evidence.check(scenario, 'one_inventory_movement', len(state['inventory_movements']), 1, defect)


def http_flow(evidence, defect=False):
    scenario = 'http-defect' if defect else 'http-normal'
    with service(evidence, scenario, *(['--duplicate-stock-bug'] if defect else [])) as client:
        initial = client.state()
        evidence.check(scenario, 'initial_stock', initial['inventory'][0]['quantity'], 10)
        status, order = client.request('/api/orders', {'quantity': 2, 'request_key': 'acceptance-order'})
        evidence.check(scenario, 'create_http_status', status, 200)
        _, repeat_order = client.request('/api/orders', {'quantity': 2, 'request_key': 'acceptance-order'})
        evidence.check(scenario, 'create_idempotent', repeat_order['id'], order['id'])
        evidence.check(scenario, 'one_order', len(client.state()['orders']), 1)
        pending = client.state()
        status, _ = client.request('/api/callback', {'order_id': order['id'], 'event_id': 'unauthorized'})
        evidence.check(scenario, 'unauthorized_callback_status', status, 401)
        evidence.check(scenario, 'unauthorized_callback_no_effect', client.state(), pending)
        status, payment = client.request('/api/payments', {'order_id': order['id'], 'mode': 'sandbox'})
        evidence.check(scenario, 'payment_http_status', status, 200)
        evidence.check(scenario, 'no_real_charge', payment['real_charge'], False)
        once = client.state()
        evidence.check(scenario, 'first_payment_stock', once['inventory'][0]['quantity'], 8)
        status, callback = client.request('/api/callback', {'order_id': order['id'],
                                           'event_id': payment['event_id']}, callback_auth=True)
        evidence.check(scenario, 'repeat_http_status', status, 200)
        evidence.check(scenario, 'repeat_response_duplicate', callback['duplicate'], True)
        final = client.state()
        evidence.save(scenario + '-state.json', final)
        payment_oracles(evidence, scenario, final, defect)
        status, live = client.request('/api/payments', {'order_id': order['id'], 'mode': 'live'})
        evidence.check(scenario, 'live_payment_rejected', status, 403)
        evidence.check(scenario, 'live_payment_error', live['error'], 'live_payment_disabled')
        evidence.check(scenario, 'live_payment_no_effect', client.state(), final)
        _, health = client.request('/api/health')
        evidence.check(scenario, 'external_provider_absent', health['outbound_payment_integration'], False)


def missing_credentials_flow(evidence):
    scenario = 'http-missing-credentials'
    with service(evidence, scenario, '--payment-credentials', 'missing') as client:
        _, order = client.request('/api/orders', {'quantity': 2, 'request_key': 'missing-credentials'})
        before = client.state()
        status, body = client.request('/api/payments', {'order_id': order['id'], 'mode': 'sandbox'})
        evidence.check(scenario, 'payment_blocked', status, 503)
        evidence.check(scenario, 'explicit_missing_credentials', body['error'], 'sandbox_credentials_missing')
        evidence.check(scenario, 'no_real_charge', body['real_charge'], False)
        evidence.check(scenario, 'no_state_mutation', client.state(), before)
        evidence.check(scenario, 'stock_unchanged', client.state()['inventory'][0]['quantity'], 10)
        evidence.check(scenario, 'no_payment_ledger_entries', len(client.state()['payments']), 0)


def browser_flow(evidence, kind):
    scenario = 'browser-' + kind
    flags = {'normal': [], 'callback-defect': ['--duplicate-stock-bug'],
             'double-submit-defect': ['--double-submit-bug']}[kind]
    session = 'order-fixture-' + uuid.uuid4().hex[:10]

    def browser(*args):
        process = subprocess.run(['agent-browser', '--session', session, *args],
                                 capture_output=True, text=True, timeout=45)
        with (evidence.directory / (scenario + '-browser.log')).open('a') as log:
            log.write(json.dumps({'args': args, 'exit_code': process.returncode}) + '\n')
            log.write(process.stdout + process.stderr + '\n')
        if process.returncode:
            raise RuntimeError(f'Browser command failed: {args}: {process.stderr} {process.stdout}')
        return process.stdout

    with service(evidence, scenario, *flags) as client:
        try:
            browser('open', client.url)
            browser('wait', '--text', 'Studio Mug')
            browser('snapshot', '-i')
            browser('click', '#submit')
            browser('click', '#submit')
            browser('wait', '--text', 'Order created')
            browser('wait', '--load', 'networkidle')
            browser('snapshot', '-i')
            count = len(client.state()['orders'])
            evidence.check(scenario, 'one_order_after_rapid_clicks', count, 1,
                           kind == 'double-submit-defect')
            if kind != 'double-submit-defect':
                browser('click', '#orders tr:first-child button')
                browser('wait', '--text', 'Payment complete')
                browser('snapshot', '-i')
                browser('scrollintoview', '#replay')
                browser('click', '#replay')
                browser('wait', '--text', 'Callback replayed')
                browser('wait', '--load', 'networkidle')
                final = client.state()
                payment_oracles(evidence, scenario, final, kind == 'callback-defect')
                stock_text = browser('get', 'text', '#stock').strip()
                evidence.check(scenario, 'visible_stock_matches_backend', stock_text,
                               str(final['inventory'][0]['quantity']))
                evidence.check(scenario, 'visible_payment_entries', browser('get', 'text', '#payments').strip(), '1')
            browser('snapshot')
            browser('screenshot', '--full', str(evidence.directory / (scenario + '.png')))
            evidence.save(scenario + '-state.json', client.state())
        finally:
            browser('close')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true', help='Also run installed agent-browser; installs nothing')
    parser.add_argument('--output', type=Path, help='New run directory outside src/; default artifacts/run-*')
    args = parser.parse_args()
    if args.browser and not shutil.which('agent-browser'):
        parser.error('agent-browser is not installed; no installation will be attempted')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = (args.output or ROOT / 'artifacts' / ('run-' + stamp + '-' + uuid.uuid4().hex[:6])).resolve()
    if directory == ROOT / 'src' or ROOT / 'src' in directory.parents:
        parser.error('Test artifacts must be outside src/')
    evidence = Evidence(directory)
    error = None
    try:
        http_flow(evidence)
        http_flow(evidence, defect=True)
        missing_credentials_flow(evidence)
        if args.browser:
            for kind in ('normal', 'callback-defect', 'double-submit-defect'):
                browser_flow(evidence, kind)
    except Exception as exception:
        error = f'{type(exception).__name__}: {exception}'
        print('ERROR ' + error, flush=True)
    accepted = error is None and all(item['accepted'] for item in evidence.results)
    summary = {'accepted': accepted, 'checks': len(evidence.results),
               'detected_fault_assertions': sum(item['expected_failure'] and not item['passed']
                                                for item in evidence.results),
               'browser_requested': args.browser, 'error': error, 'results': evidence.results}
    evidence.save('summary.json', summary)
    print(json.dumps({key: value for key, value in summary.items() if key != 'results'}), flush=True)
    print('ARTIFACTS ' + str(directory), flush=True)
    return 0 if accepted else 1


if __name__ == '__main__':
    sys.exit(main())
