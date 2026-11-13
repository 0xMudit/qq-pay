"""Run a simulated checkout twice and verify idempotency."""
import os, uuid
import httpx
with httpx.Client(base_url=os.getenv('API_URL','http://localhost:8000'),headers={'x-api-key':os.environ['API_KEY']}) as c:
    key=str(uuid.uuid4())
    def create():
        r=c.post('/payments',headers={'idempotency-key':key},json={'amount':49900,'currency':'INR'})
        r.raise_for_status()
        return r.json()
    first=create()
    assert create()['id']==first['id']
    for _ in range(2):
        r=c.post('/payments/'+first['id']+'/capture');r.raise_for_status()
    r=c.get('/payments/'+first['id']+'/ledger');r.raise_for_status()
    entries=r.json()
    assert len(entries)==2 and sum(x['amount'] for x in entries)==0
    print({'payment':first['id'],'ledger':entries,'duplicate_capture':'safe'})
