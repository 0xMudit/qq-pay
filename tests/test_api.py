import os
os.environ["API_KEY"]="test-secret-123456"
os.environ["DATABASE_URL"]="sqlite:///:memory:"
from fastapi.testclient import TestClient
import app
H={"x-api-key":os.environ["API_KEY"]}
def test_health():
    with TestClient(app.app) as c:
        assert c.get("/health").status_code==200
def test_payment_idempotency_and_ledger():
    with TestClient(app.app) as c:
        headers={**H,'idempotency-key':'checkout-123'}
        body={'amount':200,'currency':'INR'}
        assert c.post('/payments',json=body,headers={'idempotency-key':'checkout-123'}).status_code==401
        a=c.post('/payments',json=body,headers=headers).json()
        assert c.post('/payments',json=body,headers=headers).json()['id']==a['id']
        assert c.post('/payments',json={**body,'amount':300},headers=headers).status_code==409
        for _ in range(2): assert c.post('/payments/'+a['id']+'/capture',headers=H).json()['status']=='captured'
        entries=c.get('/payments/'+a['id']+'/ledger',headers=H).json()
        assert len(entries)==2 and sum(x['amount'] for x in entries)==0
        assert c.post('/payments/missing/capture',headers=H).status_code==404

import pytest
@pytest.fixture(autouse=True)
def clean_database():
    with TestClient(app.app):
        with app.engine.begin() as db:
            for table in app.SCHEMA.split(';'):
                if 'CREATE TABLE' in table:
                    table_name=table.split('EXISTS ')[1].split(' ')[0]
                    db.execute(app.text('DELETE FROM '+table_name))
    yield

def test_public_demo():
    with TestClient(app.app) as c:
        assert c.get('/').status_code==200
        response=c.post('/demo/run')
        assert response.status_code==200
        assert 'FAILED' not in response.json()['checks']
