"""Thin consumer of provider-owned operations; acquisition remains in the provider."""
from data_providers.web_ops import jobs
from data_providers.web_ops.status import status


def get(path, query):
    if path == '/api/data/status':
        return status()
    if path == '/api/data/plan':
        return jobs.preview(query.get('action', ['all'])[0])
    raise ValueError('Unknown data endpoint')


def post(body):
    return jobs.start(body.get('action'), body.get('request_id'), body.get('digest'))
