import threading
import unittest
from apps.trading_web.source_pool import SourcePool


class PoolTests(unittest.TestCase):
    def test_slow_source_does_not_block_healthy_or_duplicate(self):
        pool=SourcePool();gate=threading.Event();calls=[]
        def slow():
            calls.append(1);gate.wait(1);return {'rows':[]}
        try:
            r=pool.collect('key',dict(slow=slow,fast=lambda:{'rows':[1]}),timeout=.02)
            self.assertEqual(r['fast']['status'],'responded')
            self.assertEqual(r['slow']['status'],'pending')
            pool.collect('other',dict(slow=slow),timeout=0)
            self.assertEqual(calls,[1])
        finally:
            gate.set();pool.executor.shutdown(wait=True)

    def test_failure_cooldown_and_sanitization(self):
        pool=SourcePool();calls=[]
        def fail():
            calls.append(1);raise ValueError('secret-bearing-url')
        try:
            r=pool.collect('a',dict(source=fail))
            self.assertNotIn('secret',str(r))
            r=pool.collect('b',dict(source=fail))
            self.assertEqual(len(calls),1)
            self.assertEqual(r['source']['retry_after_seconds'],60)
        finally:
            pool.executor.shutdown(wait=True)

    def test_completed_observation_is_not_reaged_on_later_poll(self):
        from concurrent.futures import Future
        from unittest.mock import patch
        pool=SourcePool();f=Future();f.set_result((10,dict(status='responded',data='old')))
        pool.pending['source']=('key',f)
        try:
            with patch('apps.trading_web.source_pool.time.monotonic',return_value=20):
                result=pool.collect('key',{'source':lambda:'new'})
            self.assertEqual(result['source']['data'],'new')
        finally:
            pool.executor.shutdown(wait=True)
