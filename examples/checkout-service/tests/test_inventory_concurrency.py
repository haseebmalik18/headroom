"""Inventory correctness under concurrent load.

These tests fire many simultaneous reservations at the running service and
check that inventory is conserved: every unit of stock is either still on the
shelf or held by exactly one reservation, and nothing is ever oversold.
"""

import asyncio
import random

import pytest


async def _reserve_many(client, requests):
    return await asyncio.gather(
        *(client.post("/inventory/reserve", json={"sku": sku, "quantity": qty}) for sku, qty in requests)
    )


async def _reserved_units(db, sku):
    return await db.fetchval("SELECT coalesce(sum(quantity), 0) FROM reservations WHERE sku = $1", sku)


@pytest.mark.parametrize("round_", range(3))
async def test_concurrent_reservations_never_oversell(client, db, make_product, round_):
    sku = await make_product(stock=10)

    responses = await _reserve_many(client, [(sku, 1)] * 60)

    statuses = [r.status_code for r in responses]
    assert statuses.count(201) == 10, f"expected exactly 10 successful reservations, got {statuses.count(201)}"
    assert statuses.count(409) == 50
    assert await db.fetchval("SELECT stock FROM products WHERE sku = $1", sku) == 0
    assert await _reserved_units(db, sku) == 10


async def test_concurrent_mixed_quantities_conserve_stock(client, db, make_product):
    initial = 25
    sku = await make_product(stock=initial)
    rng = random.Random(7)
    requests = [(sku, rng.randint(1, 3)) for _ in range(50)]

    responses = await _reserve_many(client, requests)

    granted = sum(qty for (_, qty), r in zip(requests, responses) if r.status_code == 201)
    stock = await db.fetchval("SELECT stock FROM products WHERE sku = $1", sku)
    reserved = await _reserved_units(db, sku)
    assert all(r.status_code in (201, 409) for r in responses)
    assert reserved == granted
    assert stock >= 0
    assert reserved <= initial, f"oversold: {reserved} units reserved from stock of {initial}"
    assert stock + reserved == initial, f"stock {stock} + reserved {reserved} != initial {initial}"


async def test_concurrent_reservations_across_skus_conserve_stock(client, db, make_product):
    initial = 8
    skus = [await make_product(stock=initial) for _ in range(5)]
    requests = [(sku, 1) for sku in skus for _ in range(20)]
    random.Random(11).shuffle(requests)

    responses = await _reserve_many(client, requests)

    assert all(r.status_code in (201, 409) for r in responses)
    for sku in skus:
        stock = await db.fetchval("SELECT stock FROM products WHERE sku = $1", sku)
        reserved = await _reserved_units(db, sku)
        assert reserved == initial, f"{sku}: {reserved} units reserved from stock of {initial}"
        assert stock == 0, f"{sku}: stock should be exhausted, found {stock}"


async def test_responses_report_consistent_remaining_stock(client, make_product):
    sku = await make_product(stock=20)

    responses = await _reserve_many(client, [(sku, 1)] * 20)

    remaining = sorted(r.json()["remaining_stock"] for r in responses if r.status_code == 201)
    assert remaining == list(range(20)), "each reservation should observe a distinct stock level"
