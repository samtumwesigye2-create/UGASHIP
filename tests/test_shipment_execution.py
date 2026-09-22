from fastapi.testclient import TestClient

from app import app
from shipment_execution import SHIPMENTS, EVENTS

client=TestClient(app)

def setup_function():
    SHIPMENTS.clear()
    EVENTS.clear()

def test_happy_path_shipment_state_machine():
    r=client.post('/v1/shipments',json={
        'order_reference':'SO-100',
        'origin':'WH-A',
        'destination':'Customer',
        'package_count':1,
        'total_weight_kg':5,
        'freight_cost':14,
        'order_value':120,
        'currency':'USD',
    })
    assert r.status_code==201
    sid=r.json()['shipment']['id']

    steps=[
        ('book',{'carrier_code':'CARRIER-1','service_code':'GROUND','booking_reference':'BK-1'},'booked'),
        ('manifest',{'manifest_reference':'MF-1'},'manifested'),
        ('dispatch',{'dispatch_reference':'DSP-1'},'dispatched'),
        ('tracking',{'milestone':'in_transit'},'in_transit'),
        ('tracking',{'milestone':'arrived'},'arrived'),
        ('tracking',{'milestone':'delivered'},'delivered'),
        ('pod',{'recipient':'Receiver','proof_reference':'POD-1'},'pod_confirmed'),
    ]
    for endpoint,payload,status in steps:
        rr=client.post(f'/v1/shipments/{sid}/{endpoint}',json=payload)
        assert rr.status_code==200, rr.text
        assert rr.json()['shipment']['status']==status
        if endpoint=='pod':
            assert rr.json()['finance_event']['message_type']=='UGASHIP.POD.CONFIRMED'

    rr=client.post(f'/v1/shipments/{sid}/close')
    assert rr.status_code==200
    assert rr.json()['shipment']['status']=='closed'
    assert rr.json()['finance_event']['message_type']=='UGASHIP.SHIPMENT.CLOSED'
    assert rr.json()['finance_event']['payload']['freight_cost']==14
    assert rr.json()['finance_event']['payload']['order_value']==120

def test_cannot_skip_shipment_states():
    r=client.post('/v1/shipments',json={
        'order_reference':'SO-101','origin':'WH-A','destination':'Customer',
        'package_count':1,'total_weight_kg':1
    })
    sid=r.json()['shipment']['id']
    rr=client.post(f'/v1/shipments/{sid}/dispatch',json={'dispatch_reference':'DSP-X'})
    assert rr.status_code==409

def test_pod_requires_delivered_state():
    r=client.post('/v1/shipments',json={
        'order_reference':'SO-102','origin':'WH-A','destination':'Customer',
        'package_count':1,'total_weight_kg':1
    })
    sid=r.json()['shipment']['id']
    rr=client.post(f'/v1/shipments/{sid}/pod',json={'recipient':'X','proof_reference':'POD-X'})
    assert rr.status_code==409
