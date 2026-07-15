import sys; sys.path.insert(0, 'backend')
from pathlib import Path
from app.ingestion.dataset_bridge.gaia_run import GaiaRunReader
from app.ingestion.pipeline import IngestionPipeline
from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.db.models import Base, Entity
import uuid

engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)

@sa_event.listens_for(engine, 'connect')
def _fk(conn, _):
    conn.execute('PRAGMA foreign_keys=ON')

Base.metadata.create_all(engine)
session = Session(engine)
for eid, etype, svc, crit in [
    ('api-gateway-01', 'gateway', 'api-gateway', 'tier-1'),
    ('payment-db-01',  'database','payment-db',  'tier-1'),
]:
    session.add(Entity(id=eid, name=eid, entity_type=etype, service=svc, criticality=crit, metadata_json={}))
session.commit()

reader = GaiaRunReader()
records = reader.records(Path('data'), limit=5)
print(f"Loaded {len(records)} records")
print("Sample record:", records[0])
print()

pipeline = IngestionPipeline()
for r in records[:5]:
    clean = {k: v for k, v in r.items() if k != '_meta'}
    result = pipeline.ingest(source='gaia.run', raw=clean, request_id=str(uuid.uuid4()), session=session)
    codes = getattr(result, 'reason_codes', None)
    print(f"status={result.status}  codes={codes}")
