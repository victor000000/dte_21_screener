"""Bounded single-flight fanout; cache age starts at completion, not the next poll."""
from concurrent.futures import ThreadPoolExecutor, wait
import threading
import time


class SourcePool:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix='market-source')
        self.lock = threading.RLock()
        self.pending = {}
        self.cache = {}
        self.failures = {}

    @staticmethod
    def run(fn):
        try:
            result = dict(status='responded', data=fn())
        except Exception as exc:
            code = getattr(getattr(exc, 'response', None), 'status_code', getattr(exc, 'code', None))
            result = dict(status='unavailable', detail=getattr(exc, 'safe_detail',
                          f'{type(exc).__name__}' + (f' · HTTP {code}' if code else '')))
        return time.monotonic(), result

    def finish(self, name, item):
        completed, result = item[1].result()
        self.cache[(name, item[0])] = (completed, result)
        if result['status'] != 'responded':
            self.failures[name] = (completed, result)
        else:
            self.failures.pop(name, None)
        if self.pending.get(name) == item:
            del self.pending[name]
        return result

    def collect(self, key, calls, timeout=7):
        chosen = {}
        with self.lock:
            for name, fn in calls.items():
                item = self.pending.get(name)
                if item and item[1].done():
                    self.finish(name, item)
                cached = self.cache.get((name, key))
                failed = self.failures.get(name)
                if failed and time.monotonic()-failed[0] < 60:
                    chosen[name] = dict(failed[1], retry_after_seconds=round(60-(time.monotonic()-failed[0])))
                elif cached and time.monotonic()-cached[0] < 2:
                    chosen[name] = cached[1]
                elif name not in self.pending:
                    self.pending[name] = (key, self.executor.submit(self.run, fn))
            futures = [f for k, f in self.pending.values() if k == key]
        wait(futures, timeout=timeout)
        with self.lock:
            for name in calls:
                if name in chosen:
                    continue
                item = self.pending.get(name)
                if item and item[0] == key and item[1].done():
                    chosen[name] = self.finish(name, item)
                elif name not in self.pending and (name, key) in self.cache:
                    chosen[name] = self.cache[(name, key)][1]
                else:
                    chosen[name] = dict(status='pending', detail='Source still working; other feeds remain usable')
            if len(self.cache) > 100:
                self.cache.clear()
        return chosen
