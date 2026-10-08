import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.fleet.horus_sync import HorusBDTSyncer


class ManagementSyncTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_default_preserves_lei_seca_state(self):
        syncer = HorusBDTSyncer(dry_run=True)
        self.assertEqual(syncer.management_id, 49)
        self.assertEqual(syncer.state_file, Path('.bdt_horus_sync_state.json'))

    def test_adm_uses_independent_configured_state(self):
        with patch.dict(os.environ, {'HORUS_SYNC_STATE_FILE': '/tmp/legacy.json'}):
            syncer = HorusBDTSyncer(dry_run=True, management_id=125)
        self.assertEqual(syncer.state_file, Path('/tmp/legacy.management-125.json'))
        self.assertEqual(syncer.management_name, 'SEGOV - ADM')

    def test_explicit_state_file_is_respected(self):
        syncer = HorusBDTSyncer(dry_run=True, management_id=125, state_file='adm.json')
        self.assertEqual(syncer.state_file, Path('adm.json'))

    def test_legacy_cursor_is_only_accepted_for_lei_seca(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder) / 'cursor.json'
            state.write_text(json.dumps({'last_sync_updated_at': '2026-10-01T00:00:00+00:00'}))
            self.assertEqual(HorusBDTSyncer(dry_run=True, state_file=state)._load_cursor()[0].month, 10)
            with self.assertRaisesRegex(RuntimeError, 'outra gestão'):
                HorusBDTSyncer(dry_run=True, management_id=125, state_file=state)._load_cursor()

    def test_saved_cursor_records_management_and_round_trips(self):
        with patch.dict(os.environ, {'VPS_API_URL': 'https://example.test', 'VPS_SYNC_TOKEN': 'test'}):
            with tempfile.TemporaryDirectory() as folder:
                state = Path(folder) / 'adm.json'
                syncer = HorusBDTSyncer(management_id=125, state_file=state)
                dt = datetime(2026, 10, 1, tzinfo=timezone.utc)
                syncer._save_cursor(dt, 'bdt-id')
                self.assertEqual(json.loads(state.read_text())['management_id'], 125)
                self.assertEqual(syncer._load_cursor(), (dt, 'bdt-id'))

    def test_query_uses_selected_management(self):
        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.description = []
        cursor.fetchall.return_value = []
        syncer = HorusBDTSyncer(dry_run=True, management_id=125, limit=5)
        syncer._fetch_bdts(conn, datetime.now(timezone.utc), 'id')
        params = cursor.execute.call_args.args[1]
        self.assertEqual(params[0], 125)
        self.assertEqual(params[-1], 5)

    def make_batch(self, dry_run):
        with patch.dict(os.environ, {'VPS_API_URL': 'https://example.test', 'VPS_SYNC_TOKEN': 'test'}):
            syncer = HorusBDTSyncer(dry_run=dry_run, management_id=125)
        syncer._connect = MagicMock()
        syncer._load_cursor = MagicMock(return_value=(datetime.now(timezone.utc), '0'))
        syncer._fetch_bdts = MagicMock(return_value=[{'id': 'bdt', 'management_id': 125, 'fleet_id': 'fleet', 'user_id': 'driver', 'updated_at': datetime.now(timezone.utc)}])
        syncer._fetch_fleets = MagicMock(return_value=[{'id': 'fleet', 'plate': 'ABC1234', 'special_plate': ''}])
        syncer._fetch_users = MagicMock(return_value=[{'id': 'driver', 'first_name': 'Nome', 'last_name': 'Sobrenome', 'document': ''}])
        syncer._save_cursor = MagicMock()
        syncer._post_data = MagicMock(side_effect=[{'result': 'updated', 'external_id': 'fleet'}, {'processados': 1, 'criados': 0, 'atualizados': 1}, {'processados': 1, 'criados': 1, 'atualizados': 0}])
        return syncer

    def test_dry_run_never_posts_or_advances_cursor(self):
        syncer = self.make_batch(True)
        with patch('builtins.print'):
            syncer.run()
        syncer._post_data.assert_not_called()
        syncer._save_cursor.assert_not_called()
        syncer._connect.return_value.close.assert_called_once()

    def test_adm_sends_dependencies_before_bdts_and_labels_vehicle(self):
        syncer = self.make_batch(False)
        with patch('builtins.print'):
            syncer.run()
        calls = syncer._post_data.call_args_list
        self.assertEqual([call.args[0] for call in calls], ['vehicles', 'drivers', 'bdts'])
        self.assertEqual(calls[0].args[1]['management_name'], 'SEGOV - ADM')
        syncer._save_cursor.assert_called_once()

    def test_partial_acceptance_preserves_cursor(self):
        syncer = self.make_batch(False)
        syncer._post_data.side_effect = [{'result': 'updated', 'external_id': 'fleet'}, {'processados': 1, 'criados': 0, 'atualizados': 0, 'falhas': 1}]
        with patch('builtins.print'), self.assertRaises(RuntimeError):
            syncer.run()
        syncer._save_cursor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
