import os
import unittest
from unittest.mock import Mock, patch

from supabase_store import SupabaseStore, SupabaseStoreError


ENV = {
    'SUPABASE_URL': 'https://project.supabase.co',
    'SUPABASE_PUBLISHABLE_KEY': 'test-publishable-key',
    'IA_DATABASE_TOKEN': 'server-secret',
    'IA_WORKSPACE_KEY': 'default',
}


class SupabaseStoreTests(unittest.TestCase):
    def test_requires_server_environment(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(SupabaseStoreError):
            SupabaseStore()

    def test_read_uses_server_headers(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [{'data': {'resources': []}}]
        with patch.dict(os.environ, ENV, clear=True), patch('supabase_store.requests.get', return_value=response) as get:
            result = SupabaseStore().read(lambda: {})
        self.assertEqual(result, {'resources': []})
        headers = get.call_args.kwargs['headers']
        self.assertEqual(headers['X-IA-Token'], 'server-secret')
        self.assertEqual(headers['apikey'], 'test-publishable-key')

    def test_write_upserts_workspace(self):
        response = Mock()
        response.raise_for_status.return_value = None
        with patch.dict(os.environ, ENV, clear=True), patch('supabase_store.requests.post', return_value=response) as post:
            SupabaseStore().write({'activity': []})
        self.assertEqual(post.call_args.kwargs['params']['on_conflict'], 'workspace_key')
        self.assertIn('resolution=merge-duplicates', post.call_args.kwargs['headers']['Prefer'])


if __name__ == '__main__':
    unittest.main()
