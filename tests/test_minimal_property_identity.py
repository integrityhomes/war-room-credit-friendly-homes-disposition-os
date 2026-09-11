"""Synthetic owner-approved minimal identities in existing canonical storage."""
import json
from types import SimpleNamespace

import pytest

from cfh_disposition.property_current_import import ensure_minimal_owner_identity, prepare_minimal_owner_identity


def test_minimal_identity_create_retry_and_optional_unknowns(tmp_path):
    stored = {}

    class Bucket:
        def list(self, entity, options):
            return [{"name": k.split('/')[1]} for k in stored if k.startswith(entity + '/')]

        def download(self, path):
            return stored[path]

        def upload(self, path, data, file_options):
            assert file_options['upsert'] == 'false'
            assert path not in stored
            stored[path] = data

    client = SimpleNamespace(storage=SimpleNamespace(from_=lambda name: Bucket()))
    proposed = prepare_minimal_owner_identity('42 West Oak Avenue', 'Sampleton', 'IL', source_reference_hash='synthetic', provenance=[{'source': 'OWNER CONFIRMED'}])
    with pytest.raises(PermissionError):
        ensure_minimal_owner_identity(client, proposed, lock_path=tmp_path/'source.json')
    record, created = ensure_minimal_owner_identity(client, proposed, lock_path=tmp_path/'source.json', owner_approved=True)
    assert created and record['availability'] == 'Available'
    assert record['zip'] is record['parcel_number'] is record['monthly_insurance'] is None
    assert 'marketing_observed_since' not in json.dumps(record)
    retry, created = ensure_minimal_owner_identity(client, proposed, lock_path=tmp_path/'source.json', owner_approved=True)
    assert not created and retry == record and len(stored) == 1
    other = {**record, 'id': 'existing-other', 'address': '42 W Oak Ave'}
    stored['properties/existing-other.json'] = json.dumps(other).encode()
    with pytest.raises(ValueError):
        ensure_minimal_owner_identity(client, proposed, lock_path=tmp_path/'source.json', owner_approved=True)
