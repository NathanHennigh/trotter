import asyncio

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Dream, DreamItem, DreamLocation, DreamGoogleIdentity
from app.services import dream_locations as locations
from app.services import google_location_lifecycle as google
from test_dreams import test_db, test_user, client
from test_google_location_lifecycle import Cache, CANDIDATE, NOW


@pytest.fixture
def google_item(test_db, test_user, monkeypatch):
    cache = Cache()
    monkeypatch.setattr(google, "cache_client", lambda: cache)
    monkeypatch.setattr(locations, "utcnow", lambda: NOW)
    test_db.add(Dream(id=1,user_id=test_user.id,title="Original"))
    item=DreamItem(id=1,dream_id=1,user_id=test_user.id,source_url="https://example.invalid/save",place_name="Original user label",city="Madrid",country="Spain",category="cafe",summary="Original notes")
    test_db.add(item)
    test_db.flush()
    row,_=locations.enqueue_location(test_db,item,now=NOW)
    row.provider="google_places"
    row.status="needs_review"
    google.ensure_identity(test_db,row).candidate_place_ids=[CANDIDATE["id"]]
    test_db.commit()
    return item


def test_fresh_details_are_authenticated_no_store_and_never_persisted(test_db,test_user,client,google_item,monkeypatch):
    from app.services import google_dream_place_search as provider
    calls=[]
    async def fetch(identity, *, allow_area=False):
        calls.append(identity)
        return provider.GoogleCandidate(**CANDIDATE)
    monkeypatch.setattr(provider,"fetch_google_place_details",fetch)
    response=client.get("/dream-items/1/location-details", headers={"X-Trotter-Maps":"google"})
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    assert response.json()['location_candidates'][0]['name']==CANDIDATE['name']
    assert response.json()['location_attributions']==CANDIDATE['attributions']
    assert calls==[CANDIDATE['id']]
    test_db.expire_all()
    row=test_db.query(DreamLocation).one()
    assert row.address is None and row.candidates==[]
    assert google_item.place_name=='Original user label'
    listed=client.get('/dream-items')
    assert listed.headers['cache-control']=='private, no-store'
    assert listed.json()[0]['location_candidate_ids']==[CANDIDATE['id']]
    assert listed.json()[0]['location_candidates']==[]
    assert len(calls)==1


def test_background_result_is_immediately_mappable_without_confirmation_endpoint(test_db, test_user, client, google_item):
    row, added = locations.enqueue_location(test_db, google_item, force=True, now=NOW)
    assert added
    test_db.commit()
    async def resolver(*_):
        return {"provider": "google_places", "status": "resolved", "candidates": [CANDIDATE]}
    sessions = sessionmaker(bind=test_db.get_bind(), autoflush=False)
    assert asyncio.run(locations.resolve_location_job(row.id, session_factory=sessions, resolver=resolver, now=NOW)) == "resolved"
    test_db.expire_all()
    response = client.get("/dream-items", headers={"X-Trotter-Maps": "google"})
    assert response.headers["cache-control"] == "private, no-store"
    item = response.json()[0]
    assert item["location_status"] == "resolved"
    assert item["location_user_confirmed"] is False
    assert item["location_place_id"] == CANDIDATE["id"]
    assert (item["latitude"], item["longitude"]) == (40.4, -3.7)
    assert "query_place_id=google-place-a" in item["google_maps_url"]
    assert item["place_name"] == "Original user label" and item["summary"] == "Original notes"
    assert item["location_address"] is None and item["location_candidates"] == []


def test_area_precision_reaches_both_map_list_and_live_details(test_db, test_user, client, google_item, monkeypatch):
    from app.services import google_dream_place_search as provider
    row, _ = locations.enqueue_location(test_db, google_item, force=True, now=NOW)
    test_db.commit()
    async def resolver(*_):
        return {"provider": "google_places", "status": "resolved", "candidates": [{**CANDIDATE, "precision": "area"}]}
    sessions = sessionmaker(bind=test_db.get_bind(), autoflush=False)
    assert asyncio.run(locations.resolve_location_job(row.id, session_factory=sessions, resolver=resolver, now=NOW)) == "resolved"
    test_db.expire_all()
    async def fetch(identity, *, allow_area=False):
        assert allow_area and identity == CANDIDATE["id"]
        return provider.GoogleCandidate(**CANDIDATE, precision="area")
    monkeypatch.setattr(provider, "fetch_google_place_details", fetch)
    headers = {"X-Trotter-Maps": "google"}
    assert client.get('/dream-items', headers=headers).json()[0]["coordinate_precision"] == "area"
    details = client.get('/dream-items/1/location-details', headers=headers)
    assert details.status_code == 200 and details.json()["coordinate_precision"] == "area"


def test_foreign_owner_details_and_confirmation_never_call_provider(test_db,test_user,client,google_item,monkeypatch):
    from app.services import google_dream_place_search as provider
    async def forbidden(_, *, allow_area=False):
        raise AssertionError('No cross-owner lookup')
    monkeypatch.setattr(provider,'fetch_google_place_details',forbidden)
    google_item.user_id=999
    test_db.commit()
    assert client.get('/dream-items/1/location-details', headers={'X-Trotter-Maps':'google'}).status_code==404
    assert client.post('/dream-items/1/location-confirm',json={'candidate_id':CANDIDATE['id']}).status_code==404


def test_confirmation_stores_only_current_selected_id(test_db,test_user,client,google_item,monkeypatch):
    from app.services import google_dream_place_search as provider
    async def fetch(_, *, allow_area=False):
        return provider.GoogleCandidate(**CANDIDATE)
    monkeypatch.setattr(provider,'fetch_google_place_details',fetch)
    response=client.post('/dream-items/1/location-confirm',json={'candidate_id':CANDIDATE['id']})
    assert response.status_code==200 and response.json()['location_user_confirmed']
    test_db.expire_all()
    assert test_db.query(DreamGoogleIdentity).one().confirmed_place_id==CANDIDATE['id']
    assert 'Provider-only' not in repr(test_db.query(DreamLocation).one().history)
    assert test_db.query(DreamItem).one().summary=='Original notes'


def test_category_edit_keeps_google_choice_with_original_query_url(test_db,test_user,client,google_item,monkeypatch):
    from app.services import google_dream_place_search as provider
    google_item.google_maps_url='https://www.google.com/maps/search/?api=1&query=Original+user+label+Madrid+Spain'
    google_item.location.pin_fingerprint=locations.pin_fingerprint(google_item)
    test_db.commit()
    async def fetch(_, *, allow_area=False):
        return provider.GoogleCandidate(**CANDIDATE)
    monkeypatch.setattr(provider,'fetch_google_place_details',fetch)
    assert client.post('/dream-items/1/location-confirm',json={'candidate_id':CANDIDATE['id']}).status_code==200
    response=client.post('/dream-items/1/review',json={'edits':{'category':'restaurant'}})
    assert response.status_code==200 and response.json()['location_user_confirmed']
    test_db.expire_all()
    assert test_db.query(DreamGoogleIdentity).one().confirmed_place_id==CANDIDATE['id']
    assert test_db.query(DreamItem).one().google_maps_url.endswith('Madrid+Spain')


def test_only_google_map_capable_clients_receive_google_coordinates(test_db,test_user,client,google_item,monkeypatch):
    from app.services import google_dream_place_search as provider
    async def fetch(_, *, allow_area=False):
        return provider.GoogleCandidate(**CANDIDATE)
    monkeypatch.setattr(provider,'fetch_google_place_details',fetch)
    assert client.post('/dream-items/1/location-confirm',json={'candidate_id':CANDIDATE['id']}).status_code==200
    legacy=client.get('/dream-items').json()[0]
    assert legacy['latitude'] is legacy['longitude'] is legacy['location_expires_at'] is None
    assert '40.4' not in legacy['google_maps_url']
    modern=client.get('/dream-items',headers={'X-Trotter-Maps':'google'}).json()[0]
    assert (modern['latitude'],modern['longitude'])==(40.4,-3.7)
    assert modern['location_expires_at']
    assert client.get('/dream-items').json()[0]['latitude'] is None


def test_transient_details_failure_is_retryable_http_error_without_cached_payload(test_db,test_user,client,google_item,monkeypatch):
    from app.services import google_dream_place_search as provider
    async def unavailable(_, *, allow_area=False):
        raise provider.RetryableDreamPlaceLookupError('Synthetic provider failure')
    monkeypatch.setattr(provider,'fetch_google_place_details',unavailable)
    response=client.get('/dream-items/1/location-details', headers={'X-Trotter-Maps':'google'})
    assert response.status_code==503 and response.headers['cache-control']=='private, no-store'
    assert 'Synthetic' not in response.text
    test_db.expire_all()
    assert google_item.location.status=='needs_review'
    assert google_item.location.google_identity.candidate_place_ids==[CANDIDATE['id']]


def test_fresh_details_require_google_map_capability_before_provider(test_db,test_user,client,google_item,monkeypatch):
    from app.services import google_dream_place_search as provider
    async def forbidden(_, *, allow_area=False):
        raise AssertionError('No Google details for incompatible map client')
    monkeypatch.setattr(provider,'fetch_google_place_details',forbidden)
    response=client.get('/dream-items/1/location-details')
    assert response.status_code==409
    assert response.headers['cache-control']=='private, no-store'
    assert 'latitude' not in response.json()
    google_item.user_id=999
    test_db.commit()
    assert client.get('/dream-items/1/location-details').status_code==404
